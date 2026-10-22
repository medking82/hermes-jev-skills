param([Parameter(Mandatory)][string]$Packet)
$ErrorActionPreference = 'Stop'
$value = Get-Content -LiteralPath $Packet -Raw | ConvertFrom-Json
& "$env:USERPROFILE\.codex\bin\invoke-hidden.ps1" -FilePath $value.executable -ArgumentList @($value.arguments) -WorkingDirectory $value.cwd
