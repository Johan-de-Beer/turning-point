[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$processFile = Join-Path $taskRoot '.runtime/processes.json'
if (-not (Test-Path -LiteralPath $processFile)) { Write-Host 'No Turning Point startup record found.'; exit 0 }
$record = Get-Content -LiteralPath $processFile -Raw | ConvertFrom-Json
if ($record.root -ne $taskRoot) { throw 'Startup record does not belong to this checkout.' }
$skippedProcesses = $false
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
    if (-not $record.$startedProperty) { Write-Warning "Skipping legacy startup record without $role process start time."; $skippedProcesses = $true; continue }
    $actualStart = (Get-Process -Id $taskProcessId -ErrorAction SilentlyContinue).StartTime.ToUniversalTime()
    # PowerShell 7 may decode an ISO JSON timestamp to DateTime, whereas
    # Windows PowerShell keeps a string. Preserve its kind/offset in both.
    $recordedStart = $record.$startedProperty
    $expectedStart = if ($recordedStart -is [DateTime]) { $recordedStart.ToUniversalTime() } else { [DateTimeOffset]::Parse($recordedStart).UtcDateTime }
    if ([Math]::Abs(($actualStart - $expectedStart).TotalSeconds) -gt 1) { Write-Warning "Skipping reused process ID $taskProcessId."; $skippedProcesses = $true; continue }
    $belongs = ($proc.CommandLine -match 'backend\.main:app') -or ($proc.CommandLine -match 'npm\.cmd run dev')
    if ($role -eq 'backend') { $belongs = $belongs -and ([IO.Path]::GetFullPath($proc.ExecutablePath) -eq [IO.Path]::GetFullPath((Join-Path $taskRoot '.venv/Scripts/python.exe'))) }
    if (-not $belongs) { Write-Warning "Skipping reused process ID $taskProcessId."; $skippedProcesses = $true; continue }
    # Child-first stop is kept in native PowerShell; process paths are not shell commands.
    Stop-RecordedChildren -ParentId $taskProcessId
    Stop-Process -Id $taskProcessId -Force -ErrorAction SilentlyContinue
}
if ($skippedProcesses) { Write-Warning 'Retaining the startup record because one or more processes were skipped.' }
else { Remove-Item -LiteralPath $processFile; Write-Host 'Stopped the recorded Turning Point processes; replay data is retained.' }
