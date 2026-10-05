param(
    [ValidatePattern('^[a-zA-Z0-9.-]+$')][string]$SshHost = 'server-1',
    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9.-]{0,60}$')][string]$ReleaseTag = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss'),
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path $PSScriptRoot -Parent
$bundleDir = Join-Path $workspace '.runtime/deploy'
New-Item -ItemType Directory -Force -Path $bundleDir | Out-Null
$bundle = Join-Path $bundleDir "source-$ReleaseTag.tar.gz"
& $Python (Join-Path $PSScriptRoot 'package_deploy.py') $bundle
if ($LASTEXITCODE -ne 0) { throw 'Source bundle failed.' }

# This deliberately fixed destination and unique release directory preserve
# unrelated applications, previous images, and the named SQLite volume.
$remoteBase = '/home/balanceworx/turning-point'
$remoteRelease = "$remoteBase/releases/$ReleaseTag"
& ssh -o BatchMode=yes $SshHost "mkdir -p '$remoteRelease' '$remoteBase/backups'"
if ($LASTEXITCODE -ne 0) { throw 'Remote release directory failed.' }
& scp $bundle "${SshHost}:$remoteBase/source-$ReleaseTag.tar.gz"
if ($LASTEXITCODE -ne 0) { throw 'Upload failed.' }
$remoteCommands = @'
set -eu
chmod 700 '__BASE__/backups'
existing_backend=$(docker ps --filter label=com.docker.compose.project=turning-point --filter label=com.docker.compose.service=backend --format '{{.ID}}')
if [ -n "$existing_backend" ]; then
  docker exec "$existing_backend" python -c 'import os,sqlite3; source=sqlite3.connect(os.environ["DATABASE_PATH"]); target=sqlite3.connect("/data/pre-deploy.sqlite3"); source.backup(target); target.close(); source.close()'
  docker cp "$existing_backend:/data/pre-deploy.sqlite3" '__BASE__/backups/pre-__TAG__.sqlite3'
  chmod 600 '__BASE__/backups/pre-__TAG__.sqlite3'
fi
tar -xzf '__BASE__/source-__TAG__.tar.gz' -C '__RELEASE__'
cd '__RELEASE__'
export RELEASE_TAG='__TAG__'
docker compose -f docker-compose.production.yml config --quiet
docker compose -f docker-compose.production.yml build
docker compose -f docker-compose.production.yml up -d --wait --wait-timeout 120
printf '%s\n' '__TAG__' > '__RELEASE__/release-tag'
ln -sfn '__RELEASE__' '__BASE__/current'
docker compose -f docker-compose.production.yml ps
'@
$remoteCommands = $remoteCommands.Replace('__BASE__', $remoteBase).Replace('__RELEASE__', $remoteRelease).Replace('__TAG__', $ReleaseTag)
# Send a literal shell program over stdin; no interpolation of source text into
# shell arguments or credentials. The tag was validated above.
$remoteCommands.Replace("`r`n", "`n") | & ssh -o BatchMode=yes $SshHost 'tr -d ''\015'' | sh -s'
if ($LASTEXITCODE -ne 0) { throw 'Remote deployment failed. Previous release/data are retained; inspect containers before retrying.' }
Write-Host "Deployed release $ReleaseTag. Frontend upstream: http://192.168.10.58:5177 (Host: football.thedebeer.co.za)."
