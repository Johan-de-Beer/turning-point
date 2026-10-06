#!/usr/bin/env bash
# Run only from the trusted main checkout after hosted checks pass.
set -Eeuo pipefail
umask 077

die() { printf 'Deployment refused: %s\n' "$*" >&2; exit 1; }
[[ $# == 3 ]] || die 'usage: deploy.sh SOURCE_DIR FULL_COMMIT RELEASE_TAG'
source_dir=$(realpath -e -- "$1")
commit=$2
release_tag=$3
[[ $commit =~ ^[0-9a-f]{40}$ ]] || die 'commit must be a full lowercase 40-character Git hash'
[[ $release_tag =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]{0,63}$ ]] || die 'invalid release tag'
script_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
[[ $source_dir == "$script_root" ]] || die 'source must be this script repository checkout'
[[ $(realpath -e -- "$(git -C "$source_dir" rev-parse --show-toplevel)") == "$source_dir" ]] || die 'source is not a Git repository root'
[[ $(git -C "$source_dir" rev-parse HEAD) == "$commit" ]] || die 'checkout does not match requested commit'
git -C "$source_dir" diff --quiet HEAD -- || die 'tracked checkout changes are not deployable'
for executable in python3 tar flock docker curl; do
  command -v "$executable" >/dev/null || die "required command unavailable: $executable"
done

base=/home/balanceworx/turning-point
lock_seconds=600
if [[ ${TP_DEPLOY_TEST_BASE+x} || ${TP_DEPLOY_TEST_LOCK_SECONDS+x} ]]; then
  [[ ${TP_DEPLOY_TEST_MODE:-} == 1 && ${TP_DEPLOY_TEST_BASE:-} ]] || die 'test overrides require explicit test mode and base'
  base=$(python3 - "$TP_DEPLOY_TEST_BASE" <<'PY'
import os, pathlib, sys
path = pathlib.Path(sys.argv[1])
if not path.is_absolute():
    raise SystemExit('Test base must be absolute')
resolved = path.resolve()
try:
    relative = resolved.relative_to('/tmp')
except ValueError:
    raise SystemExit('Test base must stay under /tmp')
if not relative.parts or not relative.parts[0].startswith('turning-point-deploy-test-'):
    raise SystemExit('Test base requires a dedicated turning-point-deploy-test-* temporary directory')
root = pathlib.Path('/tmp') / relative.parts[0]
if not root.is_dir() or root.stat().st_uid != os.getuid():
    raise SystemExit('Test directory must exist and belong to this user')
print(resolved)
PY
  )
  lock_seconds=${TP_DEPLOY_TEST_LOCK_SECONDS:-1}
  [[ $lock_seconds =~ ^[1-5]$ ]] || die 'test lock timeout must be 1..5 seconds'
fi
[[ ! -L $base ]] || die 'deployment base must not be a symlink'
[[ $(realpath -m -- "$base") == "$base" ]] || die 'deployment base contains a symlink'
mkdir -p -- "$base"
[[ $(realpath -e -- "$base") == "$base" ]] || die 'deployment base contains a symlink'
exec 9>"$base/.deploy.lock"
flock -w "$lock_seconds" 9 || { printf 'Deployment lock is busy.\n' >&2; exit 75; }
for directory in releases backups archives; do
  [[ ! -L $base/$directory ]] || die "$directory must not be a symlink"
  mkdir -p -- "$base/$directory"
done
chmod 700 -- "$base/backups"

previous=''
previous_tag=''
if [[ -e $base/current || -L $base/current ]]; then
  [[ -L $base/current ]] || die 'current must be a release symlink'
  previous=$(realpath -e -- "$base/current")
  [[ $(dirname -- "$previous") == "$base/releases" && -f $previous/docker-compose.production.yml ]] || die 'current must resolve to a direct retained release'
  previous_tag=$(cat -- "$previous/release-tag")
  [[ $previous_tag =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]{0,63}$ && $(basename -- "$previous") == "$previous_tag" ]] || die 'previous release tag is invalid'
fi
release=$base/releases/$release_tag
[[ ! -e $release && ! -L $release ]] || die 'release tag already exists; use a fresh tag'

# Explicit project/directory and fixed LAN binding isolate this application.
export APP_BIND_IP=192.168.10.58 APP_PORT=5177
compose() {
  local directory=$1 tag=$2
  shift 2
  RELEASE_TAG="$tag" docker compose --project-name turning-point --project-directory "$directory" -f "$directory/docker-compose.production.yml" "$@"
}
point_current() {
  local directory=$1 switch_dir
  switch_dir=$(mktemp -d "$base/.switch-XXXXXX") || return $?
  ln -s -- "$directory" "$switch_dir/current" || return $?
  mv -Tf -- "$switch_dir/current" "$base/current" || return $?
  rmdir -- "$switch_dir" || printf 'Empty switch directory retained for inspection.\n' >&2
}
check_release() {
  local directory=$1 tag=$2
  compose "$directory" "$tag" exec -T frontend nginx -t || return $?
  curl --fail --silent --show-error --max-time 10 --header 'Host: football.thedebeer.co.za' --header 'Origin: https://football.thedebeer.co.za' \
    --output "$directory/.api-health.json" 'http://192.168.10.58:5177/api/health' || return $?
  python3 - "$directory/.api-health.json" <<'PY' || return $?
import json, sys
if json.load(open(sys.argv[1], encoding='utf-8')).get('status') != 'ok':
    raise SystemExit('API health response is not healthy')
PY
  if [[ -f $directory/frontend/public/release.json ]]; then
    curl --fail --silent --show-error --max-time 10 --header 'Host: football.thedebeer.co.za' \
      --output "$directory/.served-release.json" 'http://192.168.10.58:5177/release.json' || return $?
    python3 - "$directory/frontend/public/release.json" "$directory/.served-release.json" <<'PY' || return $?
import json, sys
expected, served = (json.load(open(p, encoding='utf-8')) for p in sys.argv[1:])
if served != expected:
    raise SystemExit('Served frontend does not match the staged release')
PY
  fi
}

mutation_started=0
on_failure() {
  local status=$1
  trap - ERR INT TERM
  set +e
  if (( mutation_started )); then
    if [[ $previous ]]; then
      printf 'Release failed; restoring retained release %s without changing replay data.\n' "$previous_tag" >&2
      # Covers signals immediately after the atomic forward pointer switch too.
      # Repair the pointer independently from restoring the running services.
      local pointer_ok=1 runtime_ok=0
      if [[ $(realpath -e -- "$base/current" 2>/dev/null || true) != "$previous" ]]; then
        point_current "$previous" || pointer_ok=0
      fi
      # Marker repair can fail independently (for example a full disk). Always
      # attempt restoring the running services with retained images regardless.
      if compose "$previous" "$previous_tag" up -d --no-build --wait --wait-timeout 120 && check_release "$previous" "$previous_tag"; then
        runtime_ok=1
      fi
      if (( runtime_ok && pointer_ok )); then
        printf 'Previous release restored; current marker remains unchanged.\n' >&2
      elif (( runtime_ok )); then
        printf 'Previous runtime restored. Current marker repair failed; manual inspection required.\n' >&2
      else
        printf 'Rollback health failed; manual inspection required. Replay volume and backup remain untouched.\n' >&2
        (( pointer_ok )) || printf 'Current marker repair also failed.\n' >&2
      fi
    else
      printf 'First release failed; no previous release exists. Candidate and replay volume retained for inspection.\n' >&2
    fi
  fi
  exit "$status"
}
trap 'on_failure "$?"' ERR
trap 'on_failure 130' INT
trap 'on_failure 143' TERM

# Packaging/building cannot alter the running containers. No source secrets or
# local replay files enter this filtered archive; failed candidates are retained.
archive=$base/archives/source-$release_tag.tar.gz
[[ ! -e $archive && ! -L $archive ]] || die 'source archive already exists'
python3 "$source_dir/scripts/package_deploy.py" "$archive"
mkdir -- "$release"
# Archive contains only regular filtered source paths. Implicit parent folders
# need readable/traversable modes in non-root images, independent of runner umask.
(umask 022; tar --no-same-owner -xzf "$archive" -C "$release")
printf '%s\n' "$release_tag" > "$release/release-tag"
python3 - "$release/frontend/public/release.json" "$commit" "$release_tag" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps({'commit': sys.argv[2], 'release': sys.argv[3]}) + '\n', encoding='utf-8')
PY
chmod 644 -- "$release/frontend/public/release.json"
compose "$release" "$release_tag" config --quiet
compose "$release" "$release_tag" build

existing_backend=$(docker ps --filter label=com.docker.compose.project=turning-point --filter label=com.docker.compose.service=backend --format '{{.ID}}')
if [[ $existing_backend ]]; then
  [[ $existing_backend =~ ^[0-9a-f]{12,64}$ ]] || die 'expected at most one backend container for this project'
  [[ $previous ]] || die 'running project has no retained current release for rollback'
  backup_name=pre-$release_tag.sqlite3
  docker exec "$existing_backend" python -c 'import os,sqlite3,sys; source=sqlite3.connect(os.environ["DATABASE_PATH"]); target=sqlite3.connect("/data/"+sys.argv[1]); source.backup(target); target.close(); source.close()' "$backup_name"
  docker cp "$existing_backend:/data/$backup_name" "$base/backups/$backup_name"
  chmod 600 -- "$base/backups/$backup_name"
  python3 - "$base/backups/$backup_name" <<'PY'
import pathlib, sqlite3, sys
source = sqlite3.connect(pathlib.Path(sys.argv[1]).resolve().as_uri() + '?mode=ro', uri=True)
try:
    if source.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
        raise SystemExit('Copied SQLite backup failed quick_check')
finally:
    source.close()
PY
  docker exec "$existing_backend" python -c 'import os,sys; os.unlink("/data/"+sys.argv[1])' "$backup_name"
fi
mutation_started=1
compose "$release" "$release_tag" up -d --no-build --wait --wait-timeout 120
check_release "$release" "$release_tag"
printf '%s\n' "$commit" > "$release/deployed-commit"
point_current "$release"
mutation_started=0
trap - ERR INT TERM
printf 'Deployed commit %s as release %s; persistent replay volume retained.\n' "$commit" "$release_tag"
