# Real WSL2 compatibility test; GitHub-hosted disposable Windows VM only.
# No credentials, production services, container images, or PM host access.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'Requires a disposable GitHub-hosted Windows runner.'
}
$wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
if (!(Test-Path -LiteralPath $wsl -PathType Leaf) -or (Get-Command wsl.exe).Source -ne $wsl) {
    throw 'Native WSL executable unavailable or shadowed.'
}
$distribution = 'Ubuntu-24.04'
$user = 'projectos-ci'
$source = '/home/projectos-ci/source'
$fixture = '/home/projectos-ci/my kit fixture'
function Invoke-Wsl {
    param([string[]]$Arguments)
    & $wsl @Arguments
    if ($LASTEXITCODE -ne 0) { throw "WSL operation failed (exit $LASTEXITCODE)." }
}
# Refuse an existing target rather than modifying it. The runner image has
# WSL but need not contain a registered Linux distribution.
$existing = (& $wsl --list --quiet 2>&1 | Out-String).Replace([string][char]0, '')
if ($existing -match '(?im)^\s*Ubuntu-24\.04\s*$') { throw 'Existing target distribution; not modified.' }
Invoke-Wsl -Arguments @('--version')
Invoke-Wsl -Arguments @('--install', '--distribution', $distribution, '--no-launch', '--web-download')
Invoke-Wsl -Arguments @('--list', '--verbose')
# Provision only the fresh test distro. Distribution packages use Ubuntu's
# normal signed repositories; no added repositories or unsigned downloads.
$provision = @'
set -eu
test "$(id -u)" = 0
if id projectos-ci >/dev/null 2>&1; then exit 1; fi
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git python3 python3-venv
useradd --create-home --shell /bin/bash projectos-ci
printf '[user]\ndefault=projectos-ci\n' > /etc/wsl.conf
'@
Invoke-Wsl -Arguments @('--distribution', $distribution, '--user', 'root', '--exec', '/bin/bash', '-c', ($provision -replace "\r", ''))
Invoke-Wsl -Arguments @('--terminate', $distribution)
$linux = (& $wsl --distribution $distribution --exec uname -r | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $linux -notmatch '(?i)microsoft-standard-wsl2') { throw 'WSL2 kernel not verified.' }
$uid = (& $wsl --distribution $distribution --exec id -u | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $uid -notmatch '^[1-9][0-9]*$') { throw 'Unprivileged test user not verified.' }
Write-Output "WSL2_KERNEL=$linux UID_NONROOT=true"
$archive = Join-Path $env:RUNNER_TEMP 'project-os-wsl-test-source.tar'
& git archive --format=tar "--output=$archive" HEAD
if ($LASTEXITCODE -ne 0) { throw 'Cannot archive tracked test source.' }
$archiveWsl = (& $wsl --distribution $distribution --exec wslpath -a -u $archive | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or !$archiveWsl.StartsWith('/')) { throw 'Cannot resolve fixture archive path.' }
Invoke-Wsl -Arguments @('--distribution', $distribution, '--exec', 'mkdir', '-m', '700', $source, $fixture)
Invoke-Wsl -Arguments @('--distribution', $distribution, '--exec', 'tar', '-xf', $archiveWsl, '-C', $source)
Invoke-Wsl -Arguments @('--distribution', $distribution, '--exec', 'python3', '--version')
Invoke-Wsl -Arguments @('--distribution', $distribution, '--exec', 'git', '--version')
# Run the existing real Git/launcher regression suite inside WSL2.
Invoke-Wsl -Arguments @('--distribution', $distribution, '--exec', 'python3', '-m', 'unittest', 'discover', '-s', "$source/tests", '-p', 'test_install.py', '-v')
# Create a synthetic local Git remote via the existing fixture helper.
$fixtureCode = @'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1] + "/tests")
from test_install import install_fixture
install_fixture(Path(sys.argv[2]))
'@
Invoke-Wsl -Arguments @('--distribution', $distribution, '--exec', 'python3', '-c', ($fixtureCode -replace "\r", ''), $source, $fixture)
# Only this disposable user gets the file:// URL rewrite. No GitHub credentials.
$remoteUri = 'file:///home/projectos-ci/my%20kit%20fixture/remote.git'
Invoke-Wsl -Arguments @('--distribution', $distribution, '--exec', 'git', 'config', '--global', "url.$remoteUri.insteadOf", 'https://github.com/codefusion-repo/project-os-v3.git')
$sha = (& $wsl --distribution $distribution --exec git -C "$fixture/kit" rev-parse HEAD | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $sha -notmatch '^[a-f0-9]{40}$') { throw 'Fixture SHA unavailable.' }
$wrapper = Join-Path $PSScriptRoot '../scripts/install.ps1'
# Invoke the actual PowerShell wrapper (not a function replacing wsl.exe).
& $wrapper -ReviewedSha $sha -Distribution $distribution -Checkout "$fixture/kit" -Mode both
$launcher = "/home/$user/.local/bin/project-os-v3"
$help = (& $wsl --distribution $distribution --exec $launcher --help | Out-String)
if ($LASTEXITCODE -ne 0 -or $help -notmatch '--project') { throw 'Installed launcher failed.' }
$before = (& $wsl --distribution $distribution --exec sha256sum $launcher | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify launcher.' }
# Wrong reviewed SHA must fail on actual WSL without replacing the launcher.
$failed = $false
try { & $wrapper -ReviewedSha ('0' * 40) -Distribution $distribution -Checkout "$fixture/kit" -Mode both }
catch {
    if ($_.Exception.Message -notmatch 'WSL installation blocked or failed \(exit ') { throw }
    $failed = $true
}
if (!$failed) { throw 'Wrong reviewed SHA accepted.' }
$after = (& $wsl --distribution $distribution --exec sha256sum $launcher | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $after -ne $before) { throw 'Launcher changed after rejection.' }
$actual = (& $wsl --distribution $distribution --exec git -C "$fixture/kit" rev-parse HEAD | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $actual -ne $sha) { throw 'Fixture HEAD changed.' }
Write-Output 'REAL_WINDOWS_WSL2_INSTALLER_PASS scope=disposable-central-selector synthetic-git'
# The VM is disposed of by GitHub. Do not unregister or shut down other distros.
exit 0
