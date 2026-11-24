# Exercise the real wrapper without launching WSL or installing anything.
$ErrorActionPreference = 'Stop'
$wrapper = Join-Path $PSScriptRoot '../scripts/install.ps1'
$sha = 'a' * 40
$global:BridgeMockExit = 0
$global:BridgeMockCalls = 0
function global:wsl.exe {
    $global:BridgeMockArgs = @($args)
    $global:BridgeMockCalls++
    $global:LASTEXITCODE = $global:BridgeMockExit
}
try {
    & $wrapper -ReviewedSha $sha -Distribution 'Ubuntu-24.04' -Checkout '/home/service/kit'
    $expected = @('--distribution','Ubuntu-24.04','--exec','/bin/bash','/home/service/kit/local-bridge/scripts/install.sh',$sha)
    if (($global:BridgeMockArgs -join '|') -cne ($expected -join '|')) { throw 'Argument forwarding mismatch' }
    $global:BridgeMockExit = 7
    $failed = $false
    try { & $wrapper -ReviewedSha $sha -Distribution 'Ubuntu-24.04' -Checkout '/home/service/kit' } catch {
        if ($_.Exception.Message -notmatch 'exit 7') { throw }
        $failed = $true
    }
    if (-not $failed) { throw 'Nonzero WSL exit was ignored' }
    $failed = $false
    try { & $wrapper -ReviewedSha 'invalid' -Distribution 'Ubuntu-24.04' -Checkout '/home/service/kit' } catch { $failed = $true }
    if (-not $failed -or $global:BridgeMockCalls -ne 2) { throw 'Invalid SHA reached WSL' }
    Write-Output 'POWERSHELL WRAPPER PASS (mocked WSL)'
} finally {
    Remove-Item Function:\wsl.exe
}
