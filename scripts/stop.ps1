[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$processFile = Join-Path $taskRoot '.runtime/processes.json'
if (-not (Test-Path -LiteralPath $processFile)) { Write-Host 'No Turning Point startup record found.'; exit 0 }
$record = Get-Content -LiteralPath $processFile -Raw | ConvertFrom-Json
if ($record.root -ne $taskRoot) { throw 'Startup record does not belong to this checkout.' }
function Stop-RecordedChildren([int]$ParentId) {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentId"
    foreach ($child in $children) {
        Stop-RecordedChildren -ParentId $child.ProcessId
        Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
foreach ($role in @('frontend', 'backend')) {
    $taskProcessId = $record.$role
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$taskProcessId"
    if (-not $proc) { continue }
    $startedProperty = "${role}_started_at"
    if (-not $record.$startedProperty) { Write-Warning "Skipping legacy startup record without $role process start time."; continue }
    $actualStart = (Get-Process -Id $taskProcessId -ErrorAction SilentlyContinue).StartTime.ToUniversalTime()
    $expectedStart = [DateTime]::Parse($record.$startedProperty).ToUniversalTime()
    if ([Math]::Abs(($actualStart - $expectedStart).TotalSeconds) -gt 1) { Write-Warning "Skipping reused process ID $taskProcessId."; continue }
    $belongs = ($proc.CommandLine -match 'backend\.main:app') -or ($proc.CommandLine -match 'npm\.cmd run dev')
    if ($role -eq 'backend') { $belongs = $belongs -and ($proc.ExecutablePath -eq (Join-Path $taskRoot '.venv/Scripts/python.exe')) }
    if (-not $belongs) { Write-Warning "Skipping reused process ID $taskProcessId."; continue }
    # Child-first stop is kept in native PowerShell; process paths are not shell commands.
    Stop-RecordedChildren -ParentId $taskProcessId
    Stop-Process -Id $taskProcessId -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $processFile
Write-Host 'Stopped the recorded Turning Point processes; replay data is retained.'
