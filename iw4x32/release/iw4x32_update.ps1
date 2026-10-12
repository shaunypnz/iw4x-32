# IW4x-32 auto-update + start (Windows; Linux: iw4x32_update.py - same steps). Run by "Play IW4x-32.bat".
#
#  1. picks the game to start - IW4x-32 (default) or vanilla IW4x: a --vanilla / --iw4x32 flag, then IW4X32_MODE,
#     then a start menu (5 s, the last choice is the default), then the choice remembered in mode.txt. The choice
#     made here is remembered; no other code path touches mode.txt.
#  2. mode iw4x32 - reads latest.json of the newest IW4x-32 release (GitHub, shaunypnz/iw4x-32); if it is newer
#     than this kit (README.txt line 1 "IW4x-32 vX.Y"):
#       - IW4x itself older than the release needs: runs the official IW4x launcher with --skip-launch (update only),
#         but ONLY when the newest IW4x is exactly the version this IW4x-32 release is made for - if IW4x is
#         already newer, nothing is updated (an IW4x-32 update for it follows) and you keep playing the current pair
#       - downloads the changed kit files, checks every SHA-256 against latest.json, swaps them in, installs
#         files\iw4x.dll into the game folder (IW4x-32 v2.0 is one DLL: iw4x.exe stays the official IW4x one)
#     repair: if the game folder has the official iw4x.dll again (e.g. the IW4x launcher was used), puts IW4x-32
#     back; a dll that is not the backed-up one but is the one the newest release is made for: it becomes the
#     backup; a dll newer than that: vanilla IW4x starts this time (mode.txt stays as it is); an iw4x.exe left
#     over from an IW4x-32 v1.x install is restored from backup\
#  3. mode vanilla: puts the official iw4x.dll back and runs the official IW4x launcher (downloaded when missing),
#     which updates IW4x and starts the game itself
#  4. mode iw4x32 starts iw4x.exe the way the official IW4x launcher does (steam_appid.txt, SteamAppId), arguments passed on
# Nothing is downloaded or changed when everything is current; without internet the game just starts.
# Skip the update: set IW4X32_NO_UPDATE=1 (or use "Play IW4x-32 (no update).bat"); the menu: IW4X32_NO_MENU=1.
$ErrorActionPreference = 'Stop'
$Repo = 'shaunypnz/iw4x-32'
$Manifest = if ($env:IW4X32_UPDATE_URL) { $env:IW4X32_UPDATE_URL } else { "https://raw.githubusercontent.com/$Repo/main/latest.json" }
$Iw4xLatest = if ($env:IW4X32_IW4X_LATEST_URL) { $env:IW4X32_IW4X_LATEST_URL } else { 'https://api.github.com/repos/iw4x/iw4x-client/releases/latest' }
$LauncherRelease = if ($env:IW4X32_LAUNCHER_RELEASE_URL) { $env:IW4X32_LAUNCHER_RELEASE_URL } else { 'https://api.github.com/repos/iw4x/launcher/releases/latest' }
$V1Exe = '2609c2687dd2ffb3f32c7687ed04f57b38ef6879c14b1c546faf8bfd8f35ea6b'   # iw4x.exe of an IW4x-32 v1.x install
$Kit = Split-Path -Parent $MyInvocation.MyCommand.Path
$Game = if ($env:IW4X32_GAME) { $env:IW4X32_GAME } else { Split-Path -Parent $Kit }
$GameArgs = @(); $ModeFlag = $null
foreach ($a in $args) {
    if ($a -eq '--vanilla') { $ModeFlag = 'vanilla' }
    elseif ($a -eq '--iw4x32') { $ModeFlag = 'iw4x32' }
    else { $GameArgs += $a }
}

function Say($m) { Write-Host "[IW4x-32 update] $m" }
function Sha($p) { if (Test-Path -LiteralPath $p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower() } else { $null } }
function ShaBytes($b) { -join ([Security.Cryptography.SHA256]::Create().ComputeHash($b) | ForEach-Object { $_.ToString('x2') }) }
function Get-Bytes($url, $timeoutSec = 15) {
    $req = [Net.HttpWebRequest]::Create($url)
    $req.UserAgent = 'iw4x32-updater'; $req.Timeout = $timeoutSec * 1000; $req.ReadWriteTimeout = $timeoutSec * 1000
    $req.Headers.Add('Cache-Control', 'no-cache')
    $resp = $req.GetResponse()
    try { $ms = New-Object IO.MemoryStream; $resp.GetResponseStream().CopyTo($ms); return , $ms.ToArray() } finally { $resp.Close() }
}
function VNum($v) { (([regex]::Matches("$v", '\d+') | ForEach-Object { '{0:D6}' -f [int]$_.Value }) -join '.') }
function Installed-Version {
    $f = Join-Path $Kit 'README.txt'
    if (Test-Path -LiteralPath $f) { $m = [regex]::Match((Get-Content -LiteralPath $f -TotalCount 1), 'IW4x-32 (v[\d.]+)'); if ($m.Success) { return $m.Groups[1].Value } }
    return 'v0'
}
function Install-Ours {
    $src = Join-Path $Kit 'files/iw4x.dll'; $tmp = Join-Path $Game 'iw4x.dll.iw4x32-new'
    Copy-Item -LiteralPath $src -Destination $tmp -Force
    Move-Item -LiteralPath $tmp -Destination (Join-Path $Game 'iw4x.dll') -Force
    if ((Sha (Join-Path $Game 'iw4x.dll')) -ne (Sha $src)) { throw 'installing iw4x.dll failed' }
}
function Restore-V1Exe($officialExe) {
    # an IW4x-32 v1.x install put its own iw4x.exe in the game folder; v2.0 runs the official IW4x one
    # ($officialExe = $null: any backup made by an installer is good enough)
    if ((Sha (Join-Path $Game 'iw4x.exe')) -ne $V1Exe) { return }
    $bak = Sha (Join-Path $Kit 'backup/iw4x.exe')
    if (-not $bak -or ($officialExe -and $bak -ne $officialExe)) {
        Say 'an older IW4x-32 replaced your iw4x.exe and there is no backup of it - run the IW4x launcher once to repair'; return
    }
    Say 'an older IW4x-32 replaced iw4x.exe - putting your official one back'
    Copy-Item -LiteralPath (Join-Path $Kit 'backup/iw4x.exe') -Destination (Join-Path $Game 'iw4x.exe') -Force
}
function Repair($m) {
    Restore-V1Exe $(if ($m) { $m.official.'iw4x.exe' })
    $ours = Sha (Join-Path $Kit 'files/iw4x.dll'); $now = Sha (Join-Path $Game 'iw4x.dll'); $bak = Sha (Join-Path $Kit 'backup/iw4x.dll')
    if ($now -eq $ours) { return }
    if ($now -eq $bak -and $bak) { Say 'the official IW4x iw4x.dll is installed again - putting IW4x-32 back'; Install-Ours; return }
    if (-not $bak -or -not $now) { Say 'not installed yet - run "Install IW4x-32.bat" once'; return }
    if ($m -and $now -eq $m.official.'iw4x.dll') {
        Say 'IW4x was updated by the official launcher - putting IW4x-32 back'
        Copy-Item -LiteralPath (Join-Path $Game 'iw4x.dll') -Destination (Join-Path $Kit 'backup/iw4x.dll') -Force
        Install-Ours; return
    }
    Say 'IW4x was updated to a newer version than IW4x-32 supports yet - starting vanilla IW4x this time.'
    return 'vanilla'
}
function Ensure-Launcher {
    # the official IW4x launcher in the game folder, downloaded from its GitHub release when it is not there
    $p = @('iw4x-launcher', 'iw4x-launcher.exe', 'iw4x-launcher-x86.exe') | ForEach-Object { Join-Path $Game $_ } | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($p) { return $p }
    try {
        $rel = [Text.Encoding]::UTF8.GetString((Get-Bytes $LauncherRelease)) | ConvertFrom-Json
        $asset = @($rel.assets | Where-Object { $_.name -like '*-x86_64-windows.zip' }) | Select-Object -First 1
        $data = Get-Bytes $asset.browser_download_url 120
    } catch { Say 'the IW4x launcher is not in the game folder and could not be downloaded'; return $null }
    if (('sha256:' + (ShaBytes $data)) -ne "$($asset.digest)".ToLower()) { Say 'download check failed for the IW4x launcher'; return $null }
    $tmp = Join-Path $Kit ('.launcher-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    try {
        New-Item -ItemType Directory -Force -Path $tmp | Out-Null
        $zip = Join-Path $tmp 'iw4x.zip'
        [IO.File]::WriteAllBytes($zip, $data)
        Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $tmp 'x')
        $got = @(Get-ChildItem -LiteralPath (Join-Path $tmp 'x') -Recurse -File | Where-Object { $_.Name -eq 'iw4x-launcher.exe' }) | Select-Object -First 1
        if (-not $got) { Say 'the IW4x launcher download has no iw4x-launcher.exe in it'; return $null }
        $dst = Join-Path $Game 'iw4x-launcher.exe'
        Move-Item -LiteralPath $got.FullName -Destination $dst -Force
    } finally { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    Say "downloaded the official IW4x launcher $($rel.tag_name)"
    return $dst
}
function Start-Vanilla {
    # official IW4x: put the official iw4x.dll back, then the official launcher updates IW4x and starts the game
    $ours = Sha (Join-Path $Kit 'files/iw4x.dll'); $now = Sha (Join-Path $Game 'iw4x.dll'); $bak = Sha (Join-Path $Kit 'backup/iw4x.dll')
    if ($now -eq $ours -and $bak) {
        Say 'putting the official IW4x iw4x.dll back - the official launcher starts from that'
        Copy-Item -LiteralPath (Join-Path $Kit 'backup/iw4x.dll') -Destination (Join-Path $Game 'iw4x.dll') -Force
    }
    Restore-V1Exe $null
    $launcher = Ensure-Launcher
    if (-not $launcher) { return $false }
    Say 'starting vanilla IW4x (official IW4x launcher) ...'
    if ($env:IW4X32_NO_START -eq '1') { Start-Process -FilePath $launcher -ArgumentList '--skip-launch' -WorkingDirectory $Game -Wait }
    else { Start-Process -FilePath $launcher -WorkingDirectory $Game -Wait }
    return $true
}
function Read-Mode {
    $f = Join-Path $Kit 'mode.txt'
    if (Test-Path -LiteralPath $f) {
        $w = @(Get-Content -LiteralPath $f -ErrorAction SilentlyContinue | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
        if ($w.Count -and ($w[0] -eq 'vanilla' -or $w[0] -eq 'iw4x32')) { return $w[0] }
    }
    return 'iw4x32'
}
function Write-Mode($m) {
    if ($m -eq 'vanilla' -or $m -eq 'iw4x32') {
        try { Set-Content -LiteralPath (Join-Path $Kit 'mode.txt') -Value $m -Encoding ASCII } catch { }
    }
}
function Start-Menu($def) {
    Write-Host 'Start which game?'
    Write-Host '  [1] IW4x-32  - 32-player servers (and normal ones)'
    Write-Host '  [2] Vanilla IW4x - the official IW4x, always the latest version'
    Write-Host -NoNewline "Enter = $def (starts in 5 s): "
    $line = ''
    $end = (Get-Date).AddSeconds(5)
    while ((Get-Date) -lt $end) {
        if (-not [Console]::KeyAvailable) { Start-Sleep -Milliseconds 100; continue }
        $k = [Console]::ReadKey($true)
        if ($k.Key -eq [ConsoleKey]::Enter) { break }
        if ($k.KeyChar) { $line += $k.KeyChar; Write-Host -NoNewline $k.KeyChar }
    }
    Write-Host ''
    if ($line -match '^\s*1') { return 'iw4x32' }
    if ($line -match '^\s*2') { return 'vanilla' }
    return $def
}
function Select-Mode {
    # flag, IW4X32_MODE, menu, remembered mode - in that order; only a mode chosen now goes into mode.txt
    if ($ModeFlag) { Write-Mode $ModeFlag; return $ModeFlag }
    if ($env:IW4X32_MODE -eq 'vanilla' -or $env:IW4X32_MODE -eq 'iw4x32') { Write-Mode $env:IW4X32_MODE; return $env:IW4X32_MODE }
    $def = Read-Mode
    if ($env:IW4X32_NO_MENU -eq '1' -or $env:IW4X32_NO_UPDATE -eq '1' -or [Console]::IsInputRedirected) { return $def }
    $m = Start-Menu $def
    Write-Mode $m
    return $m
}
function Update-Iw4x($m) {
    $want = $m.official
    if ((Sha (Join-Path $Kit 'backup/iw4x.dll')) -eq $want.'iw4x.dll') { return 'ok' }
    try { $latest = ([Text.Encoding]::UTF8.GetString((Get-Bytes $Iw4xLatest)) | ConvertFrom-Json).tag_name }
    catch { Say "cannot check the IW4x version - not updating now"; return 'skip' }
    if ($latest -ne $m.iw4x) { Say "IW4x $latest is out; IW4x-32 for it is not ready yet - keeping your current version"; return 'skip' }
    $launcher = Ensure-Launcher
    if (-not $launcher) { return 'skip' }
    Say "updating IW4x to $($m.iw4x) (official IW4x launcher, update only) ..."
    $p = Start-Process -FilePath $launcher -ArgumentList '--skip-launch' -WorkingDirectory $Game -Wait -PassThru
    if ((Sha (Join-Path $Game 'iw4x.dll')) -ne $want.'iw4x.dll') {
        Say "the IW4x launcher (exit $($p.ExitCode)) did not install IW4x $($m.iw4x) - you are on the official IW4x files now; start again later to retry"
        return 'failed'
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $Kit 'backup') | Out-Null
    Copy-Item -LiteralPath (Join-Path $Game 'iw4x.dll') -Destination (Join-Path $Kit 'backup/iw4x.dll') -Force
    return 'ok'
}
function Update-Kit($m) {
    $todo = @($m.files.PSObject.Properties | Where-Object { (Sha (Join-Path $Kit $_.Name)) -ne $_.Value })
    Say "IW4x-32 $($m.version): downloading $($todo.Count) file(s) ..."
    $stage = Join-Path $Kit ('.update-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    try {
        foreach ($t in $todo) {
            $url = $m.base_url + ((($t.Name -split '/') | ForEach-Object { [Uri]::EscapeDataString($_) }) -join '/')
            $data = Get-Bytes $url 120
            if ((ShaBytes $data) -ne $t.Value) { throw "download check failed for $($t.Name) - nothing was changed" }
            $dst = Join-Path $stage $t.Name
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
            [IO.File]::WriteAllBytes($dst, $data)
        }
        foreach ($t in $todo) {   # all verified: swap in (this script is already loaded; the .bat is a single line)
            $dst = Join-Path $Kit $t.Name
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
            Move-Item -LiteralPath (Join-Path $stage $t.Name) -Destination $dst -Force
        }
    } finally { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
}
function Do-Update {
    if ($env:IW4X32_NO_UPDATE -eq '1') { return }
    $have = Installed-Version
    try { $m = [Text.Encoding]::UTF8.GetString((Get-Bytes $Manifest)) | ConvertFrom-Json }
    catch { Say "no update check - starting IW4x-32 $have"; $m = $null }
    if ($m -and (VNum $m.version) -gt (VNum $have) -and (Get-Process -Name iw4x -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($Game, [StringComparison]::OrdinalIgnoreCase) })) { Say 'the game is running - update next time'; return }
    if ((Repair $m) -eq 'vanilla') { if (Start-Vanilla) { return 'vanilla' }; return }
    if (-not $m -or (VNum $m.version) -le (VNum $have)) { return }
    $r = Update-Iw4x $m
    if ($r -eq 'failed' -or $r -eq 'skip') { return }
    Update-Kit $m
    Install-Ours
    Say "updated to IW4x-32 $($m.version) on IW4x $($m.iw4x)"
}

[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$vanilla = $false
try {
    if ((Select-Mode) -eq 'vanilla') { $vanilla = Start-Vanilla } else { $vanilla = (Do-Update) -eq 'vanilla' }
} catch { Say "ERROR: $($_.Exception.Message) - starting the game anyway" }
if ($vanilla) { exit 0 }        # the official IW4x launcher started the game - do not start it again

# start the game (what the official IW4x launcher does, minus its file check)
if ($env:IW4X32_NO_START -eq '1') { exit 0 }
$exe = Join-Path $Game 'iw4x.exe'
if (-not (Test-Path -LiteralPath $exe)) { Write-Host "iw4x.exe not found in `"$Game`" - is the IW4x-32 folder inside your game folder?"; exit 1 }
$appid = Join-Path $Game 'steam_appid.txt'
if (-not (Test-Path -LiteralPath $appid)) { Set-Content -LiteralPath $appid -Value '10190' -Encoding ASCII }
$env:SteamAppId = '10190'; $env:SteamGameId = '10190'
if ($GameArgs.Count) { Start-Process -FilePath $exe -WorkingDirectory $Game -ArgumentList $GameArgs } else { Start-Process -FilePath $exe -WorkingDirectory $Game }
exit 0
