[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$FilePath,
    [string[]]$ArgumentList = @(),
    [string]$WorkingDirectory = (Get-Location).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'invoke-hidden.ps1 requires PowerShell 7 or newer.'
}
if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) {
    throw 'Working directory does not exist: ' + $WorkingDirectory
}

# Pin both boundaries: a UTF-8 child cannot repair a legacy parent decoder/encoder.
$utf8 = [Text.UTF8Encoding]::new($false, $true)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$command = Get-Command $FilePath -CommandType Application -ErrorAction Stop |
    Select-Object -First 1
$resolvedPath = $command.Source
if ([IO.Path]::GetFileName($resolvedPath) -ieq 'py.exe') {
    throw 'Do not launch py.exe in background automation; pass python.exe so the real interpreter receives CreateNoWindow.'
}

$startInfo = [Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = $resolvedPath
$startInfo.WorkingDirectory = [IO.Path]::GetFullPath($WorkingDirectory)
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$startInfo.StandardOutputEncoding = $utf8
$startInfo.StandardErrorEncoding = $utf8
if ([IO.Path]::GetFileName($resolvedPath) -match '^python(?:\d+(?:\.\d+)*)?\.exe$') {
    $startInfo.Environment['PYTHONUTF8'] = '1'
    $startInfo.Environment['PYTHONIOENCODING'] = 'utf-8:strict'
}
foreach ($argument in $ArgumentList) {
    [void]$startInfo.ArgumentList.Add($argument)
}

$process = [Diagnostics.Process]::new()
$process.StartInfo = $startInfo
if (-not $process.Start()) {
    throw 'Failed to start hidden process: ' + $resolvedPath
}

$stdoutTask = $process.StandardOutput.ReadToEndAsync()
$stderrTask = $process.StandardError.ReadToEndAsync()
$process.WaitForExit()
$stdout = $stdoutTask.GetAwaiter().GetResult()
$stderr = $stderrTask.GetAwaiter().GetResult()
$exitCode = $process.ExitCode
$process.Dispose()

if ($stdout) {
    [Console]::Out.Write($stdout)
}
if ($stderr) {
    [Console]::Error.Write($stderr)
}
exit $exitCode
