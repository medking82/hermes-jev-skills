Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$runtime = @RUNTIME@
$hidden = @HIDDEN@
$python = @PYTHON@
$repo = @REPO@
$homeRoot = @HOME@
$exitCode = 2
$trusted = $false
try {
    $state = Get-Content -LiteralPath (Join-Path $runtime 'state.json') -Raw | ConvertFrom-Json
    foreach ($entry in $state.runner_files.PSObject.Properties) {
        if ($entry.Name -notmatch '^[a-z][a-z0-9_.-]*$') { throw 'Invalid pinned runner path' }
        $hash = (Get-FileHash -LiteralPath (Join-Path $runtime $entry.Name) -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne $entry.Value) { throw 'Pinned runner changed' }
    }
    $trusted = $true
    & $hidden -FilePath $python -ArgumentList @('-B', (Join-Path $runtime 'sync.py'), 'run', '--runtime', $runtime, '--apply') -WorkingDirectory $repo
    $exitCode = $LASTEXITCODE
} catch {
    if (!(Test-Path -LiteralPath (Join-Path $runtime 'launcher-error.json'))) {
        @{status='stopped'; reason='Updater launcher failed'; event_id=[DateTime]::UtcNow.Ticks.ToString(); observed_at=[DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'launcher-error.json') -Encoding utf8
    }
}
if ($trusted) {
    try {
        & $hidden -FilePath $python -ArgumentList @('-B', (Join-Path $runtime 'report.py'), '--home', $homeRoot, '--kind', @KIND@) -WorkingDirectory $repo
        if ($LASTEXITCODE -ne 0 -and $exitCode -eq 0) { $exitCode = 3 }
    } catch {
        @{status='deferred'; reason='reporting-unavailable'; observed_at=[DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'last-report.json') -Encoding utf8
        if ($exitCode -eq 0) { $exitCode = 3 }
    }
}
exit $exitCode
