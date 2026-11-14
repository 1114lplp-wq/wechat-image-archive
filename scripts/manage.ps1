param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('Configure','Start','Stop','Status')][string]$Action,
    [string]$SourceRoot,
    [string]$TargetFolder,
    [string]$RuntimeDir = (Join-Path $env:LOCALAPPDATA 'WeChatImageArchiveSkill'),
    [string]$PythonPath
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
if (-not $PythonPath) {
    $candidates = @((Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'))
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) { $candidates += $pythonCommand.Source }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { $PythonPath = $candidate; break }
        }
    }
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'Python 3.11+ is required. Pass -PythonPath with the full path to python.exe.'
}
& $PythonPath -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
$runtimePath = [IO.Path]::GetFullPath($RuntimeDir)
$arguments = @('-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'archive.py'), $Action.ToLowerInvariant(),
               '--config', (Join-Path $runtimePath 'config.json'))
if ($Action -eq 'Configure') {
    if (-not $SourceRoot -or -not $TargetFolder) { throw 'Configure requires -SourceRoot and -TargetFolder.' }
    $arguments += @('--source-root', $SourceRoot, '--target-folder', $TargetFolder)
}
& $PythonPath @arguments
if ($LASTEXITCODE -ne 0) { throw ('Image archive command failed, exit ' + $LASTEXITCODE) }
