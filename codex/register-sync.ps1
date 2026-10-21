[CmdletBinding()]
param(
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [string]$CodexHome = (Join-Path $env:USERPROFILE '.codex'),
    [string]$Python = (Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$CodexHome = (Resolve-Path -LiteralPath $CodexHome).Path
$Python = (Resolve-Path -LiteralPath $Python).Path
$runtime = Join-Path $CodexHome 'jev-sync'
$hidden = Join-Path $CodexHome 'bin/invoke-hidden.ps1'
$pwshPath = (Get-Command pwsh.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$taskName = 'Codex Jev Update'
foreach ($value in @($Repo, $CodexHome, $Python, $runtime, $hidden, $pwshPath)) {
    if ($value -match '["\r\n]') { throw 'Unsupported launcher path' }
}
if (!(Test-Path -LiteralPath $hidden -PathType Leaf)) { throw 'Workstation hidden runner is required' }
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'Task already exists. Inspect it before explicitly replacing the approved enrollment.'
}
[IO.Directory]::CreateDirectory($runtime) | Out-Null
foreach ($name in @('sync.py', 'upstream.py', 'invoke-hidden.vbs')) {
    $destination = Join-Path $runtime $name
    if (Test-Path -LiteralPath $destination) { throw "Existing updater file must be reviewed: $name" }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $destination
}
$quote = { param([string]$Value) "'" + $Value.Replace("'", "''") + "'" }
$wrapper = @"
Set-StrictMode -Version Latest
`$ErrorActionPreference = 'Stop'
try {
    & $(& $quote $hidden) -FilePath $(& $quote $Python) -ArgumentList @('-B', $(& $quote (Join-Path $runtime 'sync.py')), 'run', '--runtime', $(& $quote $runtime), '--apply') -WorkingDirectory $(& $quote $Repo)
    exit `$LASTEXITCODE
} catch {
    @{status='stopped'; reason='Jev updater launcher failed'; observed_at=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $(& $quote (Join-Path $runtime 'launcher-error.json')) -Encoding utf8
    exit 2
}
"@
[IO.File]::WriteAllText((Join-Path $runtime 'invoke-sync.ps1'), $wrapper, [Text.UTF8Encoding]::new($false))
# Invoke the actual interpreter with no console; only non-secret enrollment metadata is returned.
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = $Python
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$start.Environment['PYTHONUTF8'] = '1'
foreach ($argument in @('-B', (Join-Path $runtime 'sync.py'), 'enroll', '--runtime', $runtime, '--repo', $Repo, '--home', $CodexHome)) { $start.ArgumentList.Add($argument) }
$process = [Diagnostics.Process]::new()
$process.StartInfo = $start
[void]$process.Start()
$stdout = $process.StandardOutput.ReadToEndAsync()
$stderr = $process.StandardError.ReadToEndAsync()
$process.WaitForExit()
$enrollment = $stdout.GetAwaiter().GetResult()
$errorText = $stderr.GetAwaiter().GetResult()
if ($process.ExitCode -ne 0) { throw "Jev enrollment failed: $enrollment $errorText" }
$process.Dispose()
$arguments = '//B //Nologo "' + (Join-Path $runtime 'invoke-hidden.vbs') + '" "' + $pwshPath + '" -NoProfile -NonInteractive -WindowStyle Hidden -File "' + (Join-Path $runtime 'invoke-sync.ps1') + '"'
$action = New-ScheduledTaskAction -Execute (Join-Path $env:WINDIR 'System32/wscript.exe') -Argument $arguments -WorkingDirectory $Repo
$hourly = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 1)
$logon = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($hourly, $logon) -Principal $principal -Settings $settings | Out-Null
Write-Output $enrollment
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
