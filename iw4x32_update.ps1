# IW4x-32 auto-update + start (Windows; Linux: iw4x32_update.py - same steps). Run by "Play IW4x-32.bat".
#
#  1. reads latest.json of the newest IW4x-32 release (GitHub, shaunypnz/iw4x-32)
#  2. if it is newer than this kit (README.txt line 1 "IW4x-32 vX.Y"):
#       - IW4x itself older than the release needs: runs the official IW4x launcher with --skip-launch (update only),
#         but ONLY when the newest IW4x is exactly the version this IW4x-32 release is made for - if IW4x is already
#         newer, nothing is updated (an IW4x-32 update for it follows) and you keep playing the current pair
#       - downloads the changed kit files, checks every SHA-256 against latest.json, swaps them in, installs
#         files\iw4x.exe + files\iw4x.dll into the game folder
#  3. repair: if the game folder has the official files again (e.g. the IW4x launcher was used), puts IW4x-32 back
#  4. starts iw4x.exe the way the official IW4x launcher does (steam_appid.txt, SteamAppId), arguments passed on
# Nothing is downloaded or changed when everything is current; without internet the game just starts.
# Skip the update: set IW4X32_NO_UPDATE=1 (or use "Play IW4x-32 (no update).bat").
$ErrorActionPreference = 'Stop'
$Repo = 'shaunypnz/iw4x-32'
$Manifest = if ($env:IW4X32_UPDATE_URL) { $env:IW4X32_UPDATE_URL } else { "https://raw.githubusercontent.com/$Repo/main/latest.json" }
$Iw4xLatest = if ($env:IW4X32_IW4X_LATEST_URL) { $env:IW4X32_IW4X_LATEST_URL } else { 'https://api.github.com/repos/iw4x/iw4x-client/releases/latest' }
$Kit = Split-Path -Parent $MyInvocation.MyCommand.Path
$Game = if ($env:IW4X32_GAME) { $env:IW4X32_GAME } else { Split-Path -Parent $Kit }
$GameArgs = $args

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
    foreach ($f in 'iw4x.exe', 'iw4x.dll') {
        $src = Join-Path $Kit "files/$f"; $tmp = Join-Path $Game "$f.iw4x32-new"
        Copy-Item -LiteralPath $src -Destination $tmp -Force
        Move-Item -LiteralPath $tmp -Destination (Join-Path $Game $f) -Force
        if ((Sha (Join-Path $Game $f)) -ne (Sha $src)) { throw "installing $f failed" }
    }
}
function Repair {
    $ours = @{}; $now = @{}; $bak = @{}
    foreach ($f in 'iw4x.exe', 'iw4x.dll') { $ours[$f] = Sha (Join-Path $Kit "files/$f"); $now[$f] = Sha (Join-Path $Game $f); $bak[$f] = Sha (Join-Path $Kit "backup/$f") }
    if ($now['iw4x.exe'] -eq $ours['iw4x.exe'] -and $now['iw4x.dll'] -eq $ours['iw4x.dll']) { return }
    if (-not $bak['iw4x.dll'] -or -not $bak['iw4x.exe']) { Say 'not installed yet - run "Install IW4x-32.bat" once'; return }
    if ($now['iw4x.exe'] -eq $bak['iw4x.exe'] -and $now['iw4x.dll'] -eq $bak['iw4x.dll']) {
        Say 'the official IW4x files are installed again - putting IW4x-32 back'; Install-Ours
    }
}
function Update-Iw4x($m) {
    $want = $m.official
    if ((Sha (Join-Path $Kit 'backup/iw4x.dll')) -eq $want.'iw4x.dll') { return 'ok' }
    try { $latest = ([Text.Encoding]::UTF8.GetString((Get-Bytes $Iw4xLatest)) | ConvertFrom-Json).tag_name }
    catch { Say "cannot check the IW4x version - not updating now"; return 'skip' }
    if ($latest -ne $m.iw4x) { Say "IW4x $latest is out; IW4x-32 for it is not ready yet - keeping your current version"; return 'skip' }
    $launcher = @('iw4x-launcher.exe', 'iw4x-launcher-x86.exe') | ForEach-Object { Join-Path $Game $_ } | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $launcher) { Say 'the IW4x launcher was not found in the game folder - update IW4x yourself, then start again'; return 'skip' }
    Say "updating IW4x to $($m.iw4x) (official IW4x launcher, update only) ..."
    $p = Start-Process -FilePath $launcher -ArgumentList '--skip-launch' -WorkingDirectory $Game -Wait -PassThru
    if ((Sha (Join-Path $Game 'iw4x.dll')) -ne $want.'iw4x.dll' -or (Sha (Join-Path $Game 'iw4x.exe')) -ne $want.'iw4x.exe') {
        Say "the IW4x launcher (exit $($p.ExitCode)) did not install IW4x $($m.iw4x) - you are on the official IW4x files now; start again later to retry"
        return 'failed'
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $Kit 'backup') | Out-Null
    foreach ($f in 'iw4x.exe', 'iw4x.dll') { Copy-Item -LiteralPath (Join-Path $Game $f) -Destination (Join-Path $Kit "backup/$f") -Force }
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
    catch { Say "no update check - starting IW4x-32 $have"; Repair; return }
    if ((VNum $m.version) -le (VNum $have)) { Repair; return }
    if (Get-Process -Name iw4x -ErrorAction SilentlyContinue) { Say 'the game is running - update next time'; return }
    $r = Update-Iw4x $m
    if ($r -eq 'failed') { return }
    if ($r -eq 'skip') { Repair; return }
    Update-Kit $m
    Install-Ours
    Say "updated to IW4x-32 $($m.version) on IW4x $($m.iw4x)"
}

[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
try { Do-Update } catch { Say "ERROR: $($_.Exception.Message) - starting the game anyway" }

# start the game (what the official IW4x launcher does, minus its file check)
if ($env:IW4X32_NO_START -eq '1') { exit 0 }
$exe = Join-Path $Game 'iw4x.exe'
if (-not (Test-Path -LiteralPath $exe)) { Write-Host "iw4x.exe not found in `"$Game`" - is the IW4x-32 folder inside your game folder?"; exit 1 }
$appid = Join-Path $Game 'steam_appid.txt'
if (-not (Test-Path -LiteralPath $appid)) { Set-Content -LiteralPath $appid -Value '10190' -Encoding ASCII }
$env:SteamAppId = '10190'; $env:SteamGameId = '10190'
if ($GameArgs.Count) { Start-Process -FilePath $exe -WorkingDirectory $Game -ArgumentList $GameArgs } else { Start-Process -FilePath $exe -WorkingDirectory $Game }
exit 0
