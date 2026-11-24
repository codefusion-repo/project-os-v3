# Explicit WSL wrapper; no Windows system changes, no shell string interpolation.
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{40}$')][string]$ReviewedSha,
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9_.-]+$')][string]$Distribution,
    [Parameter(Mandatory=$true)][ValidatePattern('^/[A-Za-z0-9_./-]+$')][string]$Checkout
)
$ErrorActionPreference = 'Stop'
& wsl.exe --distribution $Distribution --exec /bin/bash "$Checkout/local-bridge/scripts/install.sh" $ReviewedSha
if ($LASTEXITCODE -ne 0) { throw "WSL installation blocked or failed (exit $LASTEXITCODE)." }
