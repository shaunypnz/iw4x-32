# IW4x-32 for Windows - setup, start menu, auto-update, play, host a server, uninstall: all of it is this file.
# IW4x-32.bat (double-click) runs it. Linux: iw4x32.py next to it does the same steps.
#
#   IW4x-32.bat                          first time: sets everything up; then the start menu
#   IW4x-32.bat --play                   IW4x-32 (32-player servers, and normal ones)
#   IW4x-32.bat --vanilla                vanilla IW4x (the official IW4x launcher updates and starts it)
#   IW4x-32.bat --server [port]          32-player dedicated server (port 28960)
#   IW4x-32.bat --vanilla-server [port]  normal 18-player IW4x server
#   IW4x-32.bat --setup [game folder]    do the setup again, e.g. for another game folder
#   IW4x-32.bat --uninstall              put the official IW4x files back, remove the shortcuts
#   --no-update  skip the update check     --dry  only print what would be started
#   anything else goes to the game, e.g.   +connect 1.2.3.4:28960
#
# Setup (the first start does it by itself): finds MW2 (the folder this IW4x-32 folder is in, then every Steam
# library), copies IW4x-32 to <game>\IW4x-32, lets the OFFICIAL IW4x launcher install or update IW4x (IW4x-32
# never downloads IW4x's own files), backs up the official iw4x.dll, installs files\iw4x.dll (iw4x.exe stays the
# official one) and makes the shortcuts.
# Every start: checks GitHub for a new IW4x-32 (5 s, no network = just start) and installs it with every file's
# SHA-256 checked; puts IW4x-32 back when the IW4x launcher's file check replaced it; an IW4x older than this
# IW4x-32 is made for is updated with the official launcher, a newer one only gets a warning (warn, never block).
# Test hooks: IW4X32_GAME, IW4X32_STEAM, IW4X32_UPDATE_URL, IW4X32_IW4X_LATEST_URL, IW4X32_LAUNCHER_RELEASE_URL,
# IW4X32_NO_START=1 (print the command, start nothing), IW4X32_NO_SHORTCUTS=1, IW4X32_YES=1 (uninstall without asking).
$ErrorActionPreference = 'Stop'
$Repo = 'shaunypnz/iw4x-32'
$OFFICIAL_VER = 'r5168'
$OFFICIAL_DLL = 'e0d8adc473f04f2d0988cffec3ecb8128e9faeba1e169c0acb13118d29aff6ea'
$OFFICIAL_EXE = '49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009'
$V1_EXE = '2609c2687dd2ffb3f32c7687ed04f57b38ef6879c14b1c546faf8bfd8f35ea6b'   # iw4x.exe of an IW4x-32 v1.x install
$Manifest = if ($env:IW4X32_UPDATE_URL) { $env:IW4X32_UPDATE_URL } else { "https://github.com/$Repo/releases/latest/download/latest.json" }
$Iw4xLatest = if ($env:IW4X32_IW4X_LATEST_URL) { $env:IW4X32_IW4X_LATEST_URL } else { 'https://api.github.com/repos/iw4x/iw4x-client/releases/latest' }
$LauncherRelease = if ($env:IW4X32_LAUNCHER_RELEASE_URL) { $env:IW4X32_LAUNCHER_RELEASE_URL } else { 'https://api.github.com/repos/iw4x/launcher/releases/latest' }
$MW2 = 'Call of Duty Modern Warfare 2'
$Files = Split-Path -Parent $MyInvocation.MyCommand.Path      # <kit>\files: the program, backup\ and mode.txt
$Kit = Split-Path -Parent $Files                              # the IW4x-32 folder
$Game = $null
# what IW4x-32 v1.x, v2.0 and the v2.1 test builds had in the IW4x-32 folder; everything is IW4x-32.bat + files\ now
$Legacy = @('AI_CREDITS.txt', 'CHANGES.txt', 'SHA256SUMS.txt', 'IW4x-32 Launcher.bat', 'IW4x-32 Setup.bat',
    'Install IW4x-32.bat', 'Play IW4x-32 (IW4x launcher, no file check).bat', 'Play IW4x-32 (no update).bat',
    'Play IW4x-32.bat', 'Start IW4x-32 Server.bat', 'Uninstall IW4x-32.bat', 'install-linux.sh', 'iw4x32_update.ps1',
    'iw4x32_update.py', 'launcher-linux.sh', 'play-linux.sh', 'setup-linux.sh', 'start-server-linux.sh',
    'uninstall-linux.sh', 'server/server_iw4x32.cfg', 'server/server_vanilla.cfg',
    'latest.json', 'files/iw4x.exe')                                         # the last two: v1.x kits
$LegacyDirs = @('source')                                                    # v1.x: the patch manifests

$Mode = $null; $Port = '28960'; $Dry = $false; $NoUpdate = ($env:IW4X32_NO_UPDATE -eq '1'); $Setup = $false
$SetupPath = $null; $GameArgs = @(); $Warned = $false
for ($i = 0; $i -lt $args.Count; $i++) {
    $a = "$($args[$i])"
    if ($a -eq '--play' -or $a -eq '--iw4x32') { $Mode = 'iw4x32' }
    elseif ($a -eq '--vanilla') { $Mode = 'vanilla' }
    elseif ($a -eq '--server') { $Mode = 'server' }
    elseif ($a -eq '--vanilla-server') { $Mode = 'vanilla-server' }
    elseif ($a -eq '--uninstall') { $Mode = 'uninstall' }
    elseif ($a -eq '--setup') {
        $Setup = $true
        if ($i + 1 -lt $args.Count -and "$($args[$i + 1])" -notmatch '^[-+]') { $i++; $SetupPath = "$($args[$i])" }
    }
    elseif ($a -eq '--no-update') { $NoUpdate = $true }
    elseif ($a -eq '--dry' -or $a -eq '--dry-run') { $Dry = $true }
    elseif ($a -eq '--migrate') { }                      # an IW4x-32 v2.0 script forwarded here (iw4x32_update.ps1)
    elseif ($a -match '^\d+$' -and ($Mode -eq 'server' -or $Mode -eq 'vanilla-server')) { $Port = $a }
    else { $GameArgs += $a }
}

function Say($m) { Write-Host "[IW4x-32] $m" }
function Warn($m) { $script:Warned = $true; Write-Host "[IW4x-32] WARNING: $m" -ForegroundColor Yellow }
function P($dir, $name) { Join-Path $dir ($name -replace '[\\/]', [IO.Path]::DirectorySeparatorChar) }
function F($name) { P $script:Files $name }
function G($name) { P $script:Game $name }
function Sha($p) { if ($p -and (Test-Path -LiteralPath $p -PathType Leaf)) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower() } else { $null } }
function ShaBytes($b) { -join ([Security.Cryptography.SHA256]::Create().ComputeHash($b) | ForEach-Object { $_.ToString('x2') }) }
function Get-Bytes($url, $timeoutSec = 5) {   # 5 s: a version check must never hold up a game start
    $req = [Net.HttpWebRequest]::Create($url)
    $req.UserAgent = 'iw4x32-updater'; $req.Timeout = $timeoutSec * 1000; $req.ReadWriteTimeout = $timeoutSec * 1000
    $req.Headers.Add('Cache-Control', 'no-cache')
    $resp = $req.GetResponse()
    try { $ms = New-Object IO.MemoryStream; $resp.GetResponseStream().CopyTo($ms); return , $ms.ToArray() } finally { $resp.Close() }
}
function Get-Json($url, $timeoutSec = 5) { [Text.Encoding]::UTF8.GetString((Get-Bytes $url $timeoutSec)) | ConvertFrom-Json }
function VNum($v) { (([regex]::Matches("$v", '\d+') | ForEach-Object { '{0:D6}' -f [int]$_.Value }) -join '.') }
function Interactive { -not [Console]::IsInputRedirected }
function Wait-Close { if (Interactive) { Read-Host 'Press Enter to close' | Out-Null } }
function Is-Game($d) {
    if (-not $d -or -not (Test-Path -LiteralPath $d -PathType Container)) { return $false }
    foreach ($e in 'iw4mp.exe', 'iw4x.exe', 'iw2mp.exe') { if (Test-Path -LiteralPath (Join-Path $d $e)) { return $true } }
    return $false
}
function Installed-Version {
    $f = P $Kit 'README.txt'
    if (Test-Path -LiteralPath $f) { $m = [regex]::Match((Get-Content -LiteralPath $f -TotalCount 1), 'IW4x-32 (v[\d.]+)'); if ($m.Success) { return $m.Groups[1].Value } }
    return 'v0'
}
function Game-Running {
    @(Get-Process -Name iw4x -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($Game, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0
}
function Backup-Dll {
    New-Item -ItemType Directory -Force -Path (F 'backup') | Out-Null
    Copy-Item -LiteralPath (G 'iw4x.dll') -Destination (F 'backup/iw4x.dll') -Force
}
function Install-Ours {
    $src = F 'iw4x.dll'; $tmp = G 'iw4x.dll.iw4x32-new'
    Copy-Item -LiteralPath $src -Destination $tmp -Force
    Move-Item -LiteralPath $tmp -Destination (G 'iw4x.dll') -Force
    if ((Sha (G 'iw4x.dll')) -ne (Sha $src)) { throw 'installing iw4x.dll failed (antivirus?)' }
}
function Restore-V1Exe($officialExe) {
    # an IW4x-32 v1.x install put its own iw4x.exe in the game folder; v2 runs the official IW4x one
    # ($officialExe = $null: any backup made by an installer is good enough)
    if ((Sha (G 'iw4x.exe')) -ne $V1_EXE) { return }
    $bak = Sha (F 'backup/iw4x.exe')
    if (-not $bak -or ($officialExe -and $bak -ne $officialExe)) {
        Say 'an older IW4x-32 replaced your iw4x.exe and there is no backup of it - the official IW4x launcher repairs it'
        Install-Official | Out-Null; return
    }
    Say 'an older IW4x-32 replaced iw4x.exe - putting your official one back'
    Copy-Item -LiteralPath (F 'backup/iw4x.exe') -Destination (G 'iw4x.exe') -Force
}
function Warn-NewerIw4x($want, $latest) {
    # IW4x-32 is a version behind: say it plainly and start anyway (owner's rule: warn, never block)
    if ($want -and $latest -and (VNum $latest) -gt (VNum $want)) {
        Warn "IW4x $latest is out, this IW4x-32 is made for $want - an IW4x-32 update normally follows within a day"
    }
}

# ---- the official IW4x launcher: it installs and updates IW4x itself -------------------------------------------
function Ensure-Launcher {
    $p = @('iw4x-launcher', 'iw4x-launcher.exe', 'iw4x-launcher-x86.exe') | ForEach-Object { G $_ } | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($p) { return $p }
    try {
        $rel = Get-Json $LauncherRelease
        $asset = @($rel.assets | Where-Object { $_.name -like '*-x86_64-windows.zip' }) | Select-Object -First 1
        $data = Get-Bytes $asset.browser_download_url 120
    } catch { Say 'the official IW4x launcher is not in the game folder and could not be downloaded - no internet?'; return $null }
    if (('sha256:' + (ShaBytes $data)) -ne "$($asset.digest)".ToLower()) { Say 'download check failed for the IW4x launcher'; return $null }
    $tmp = P $Files ('.launcher-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    try {
        New-Item -ItemType Directory -Force -Path $tmp | Out-Null
        $zip = P $tmp 'iw4x.zip'
        [IO.File]::WriteAllBytes($zip, $data)
        Expand-Archive -LiteralPath $zip -DestinationPath (P $tmp 'x')
        $got = @(Get-ChildItem -LiteralPath (P $tmp 'x') -Recurse -File | Where-Object { $_.Name -eq 'iw4x-launcher.exe' }) | Select-Object -First 1
        if (-not $got) { Say 'the IW4x launcher download has no iw4x-launcher.exe in it'; return $null }
        $dst = G 'iw4x-launcher.exe'
        Move-Item -LiteralPath $got.FullName -Destination $dst -Force
    } finally { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    Say "downloaded the official IW4x launcher $($rel.tag_name)"
    return $dst
}
function Run-Launcher($launcherArgs) {
    $launcher = Ensure-Launcher
    if (-not $launcher) { return $null }
    if ($launcherArgs) { return Start-Process -FilePath $launcher -ArgumentList $launcherArgs -WorkingDirectory $Game -Wait -PassThru }
    return Start-Process -FilePath $launcher -WorkingDirectory $Game -Wait -PassThru
}
function Install-Official {
    Say 'the official IW4x launcher installs / updates IW4x (this can take a few minutes the first time) ...'
    return [bool](Run-Launcher '--skip-launch')
}
function Iw4x-Latest {
    # the newest official IW4x release name (rNNNN), $null when it cannot be checked
    try { return (Get-Json $Iw4xLatest).tag_name } catch { return $null }
}
function Restore-Official {
    # put the official IW4x iw4x.dll back - what vanilla IW4x and a vanilla server start from
    if ((Sha (G 'iw4x.dll')) -eq (Sha (F 'iw4x.dll')) -and (Sha (F 'backup/iw4x.dll'))) {
        Say 'putting the official IW4x iw4x.dll back'
        Copy-Item -LiteralPath (F 'backup/iw4x.dll') -Destination (G 'iw4x.dll') -Force
    }
    Restore-V1Exe $null
}

# ---- updates and repairs ---------------------------------------------------------------------------------------
function Repair($m, $latest) {
    # the IW4x launcher (or a repair) put the official iw4x.dll back: re-install IW4x-32. An IW4x that is neither
    # the backed-up one nor the one this release is made for: older -> the official launcher updates it, newer ->
    # warn and start IW4x-32 on it (it becomes the backup).
    $want = if ($m) { $m.official } else { $null }
    Restore-V1Exe $(if ($want) { $want.'iw4x.exe' } else { $OFFICIAL_EXE })
    $ours = Sha (F 'iw4x.dll'); $now = Sha (G 'iw4x.dll')
    if ($now -eq $ours) { return }
    if (-not $now) { Say 'iw4x.dll is missing - the official IW4x launcher repairs IW4x'; Install-Official | Out-Null; $now = Sha (G 'iw4x.dll') }
    if (-not $now) { throw 'IW4x is not installed in the game folder' }
    $bak = Sha (F 'backup/iw4x.dll')
    $wantDll = if ($want) { $want.'iw4x.dll' } else { $OFFICIAL_DLL }
    if ($bak -and $now -eq $bak) { Say 'the official IW4x iw4x.dll is back (IW4x launcher?) - putting IW4x-32 back'; Install-Ours; return }
    if ($now -eq $wantDll -or $now -eq $OFFICIAL_DLL) { Say 'IW4x was updated - putting IW4x-32 back'; Backup-Dll; Install-Ours; return }
    $wantVer = if ($m) { $m.iw4x } else { $OFFICIAL_VER }
    if ($latest -and (VNum $latest) -le (VNum $wantVer) -and (Update-Iw4x $wantDll $wantVer $latest) -eq 'ok') {
        Say 'your IW4x was older than IW4x-32 is made for - updated'; Install-Ours; return
    }
    Warn "your IW4x is not $wantVer, the version IW4x-32 is made for - starting IW4x-32 on it anyway; it is your backup now (vanilla goes back to it)"
    Backup-Dll; Install-Ours
}
function Update-Iw4x($wantDll, $wantVer, $latest) {
    if ((Sha (F 'backup/iw4x.dll')) -eq $wantDll) { return 'ok' }
    if (-not $latest) { Say 'cannot check the IW4x version - not updating it now'; return 'skip' }
    if ($latest -ne $wantVer) { Say "IW4x $latest is out; IW4x-32 for it is not ready yet - keeping your current IW4x"; return 'skip' }
    Say "updating IW4x to $wantVer (official IW4x launcher, update only) ..."
    $p = Run-Launcher '--skip-launch'
    if (-not $p) { return 'skip' }
    if ((Sha (G 'iw4x.dll')) -ne $wantDll) {
        Say "the IW4x launcher (exit $($p.ExitCode)) did not install IW4x $wantVer - you are on the official IW4x files now; start again later to retry"
        return 'failed'
    }
    Backup-Dll
    return 'ok'
}
function Update-Kit($m) {
    # every file of the release whose SHA-256 differs: download all, check all, then swap them in
    $skip = @($m.legacy)
    $todo = @($m.files.PSObject.Properties | Where-Object { $skip -notcontains $_.Name -and (Sha (P $Kit $_.Name)) -ne $_.Value })
    Say "IW4x-32 $($m.version): downloading $($todo.Count) file(s) ..."
    $stage = P $Files ('.update-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    try {
        foreach ($t in $todo) {
            $url = $m.base_url + ((($t.Name -split '/') | ForEach-Object { [Uri]::EscapeDataString($_) }) -join '/')
            $data = Get-Bytes $url 120
            if ((ShaBytes $data) -ne $t.Value) { throw "download check failed for $($t.Name) - nothing was changed" }
            $dst = P $stage $t.Name
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
            [IO.File]::WriteAllBytes($dst, $data)
        }
        foreach ($t in $todo) {   # all verified: swap in (this script is already loaded; the .bat is one line)
            $dst = P $Kit $t.Name
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
            Move-Item -LiteralPath (P $stage $t.Name) -Destination $dst -Force
        }
    } finally { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
}
function Do-Update {
    $have = Installed-Version
    $m = $null
    if (-not $NoUpdate) {
        try { $m = Get-Json $Manifest } catch { Say "no update check (no internet?) - starting IW4x-32 $have" }
    }
    $latest = if ($NoUpdate) { $null } else { Iw4x-Latest }
    Warn-NewerIw4x $(if ($m) { $m.iw4x } else { $OFFICIAL_VER }) $latest
    if ($m -and (VNum $m.version) -gt (VNum $have) -and (Game-Running)) { Say 'the game is running - updating next time'; $m = $null }
    Repair $m $latest
    if (-not $m -or (VNum $m.version) -le (VNum $have)) { return }
    $r = Update-Iw4x $m.official.'iw4x.dll' $m.iw4x $latest
    if ($r -ne 'ok') { return }
    Update-Kit $m
    Install-Ours
    Migrate-Legacy | Out-Null
    Say "updated to IW4x-32 $($m.version) (IW4x $($m.iw4x))"
}

# ---- setup -----------------------------------------------------------------------------------------------------
function Steam-Libraries {
    $roots = @()
    if ($env:IW4X32_STEAM) { $roots = @($env:IW4X32_STEAM) }
    else {
        foreach ($k in 'HKCU:\Software\Valve\Steam', 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam', 'HKLM:\SOFTWARE\Valve\Steam') {
            try { $p = Get-ItemProperty -Path $k -ErrorAction Stop; foreach ($v in @($p.SteamPath, $p.InstallPath)) { if ($v) { $roots += ($v -replace '/', '\') } } } catch { }
        }
        $roots += @("${env:ProgramFiles(x86)}\Steam", "$env:ProgramFiles\Steam")
    }
    $libs = @()
    foreach ($r in $roots) {
        if (-not $r -or -not (Test-Path -LiteralPath $r)) { continue }
        $libs += $r
        $vdf = P $r 'steamapps/libraryfolders.vdf'
        if (Test-Path -LiteralPath $vdf) {
            foreach ($x in [regex]::Matches((Get-Content -LiteralPath $vdf -Raw), '"(?:path|\d+)"\s+"([^"]+)"')) { $libs += ($x.Groups[1].Value -replace '\\\\', '\') }
        }
    }
    return @($libs | Select-Object -Unique)
}
function Pick-Game {
    $found = @()
    foreach ($lib in Steam-Libraries) {
        $common = P $lib 'steamapps/common'
        if (-not (Test-Path -LiteralPath $common)) { continue }
        foreach ($d in @(Get-ChildItem -LiteralPath $common -Directory -Filter "$MW2*" -ErrorAction SilentlyContinue)) {
            if ((Is-Game $d.FullName) -and $found -notcontains $d.FullName) { $found += $d.FullName }
        }
    }
    if ($found.Count -eq 1) { Say "found Modern Warfare 2: $($found[0])"; return $found[0] }
    if ($found.Count -gt 1) {
        Write-Host 'Modern Warfare 2 is installed in more than one place:'
        for ($n = 0; $n -lt $found.Count; $n++) { Write-Host "  [$($n + 1)] $($found[$n])" }
        $a = if (Interactive) { Read-Host 'Which one? (Enter = 1)' } else { '' }
        if (-not $a) { $a = '1' }
        if ($a -match '^\d+$' -and [int]$a -ge 1 -and [int]$a -le $found.Count) { return $found[[int]$a - 1] }
        return $null
    }
    Write-Host 'Modern Warfare 2 was not found in your Steam libraries.'
    Write-Host '  You need "Call of Duty: Modern Warfare 2" (2009) - the multiplayer part - from Steam.'
    if (-not (Interactive)) { return $null }
    $a = Read-Host 'Type your MW2 folder (the one with iw4mp.exe), S = open Steam to install MW2, Enter = stop'
    if ($a -eq 's' -or $a -eq 'S') {
        Start-Process 'steam://install/10190'
        Write-Host 'Install it in Steam, then double-click IW4x-32.bat again.'
        return $null
    }
    return $a.Trim('"', ' ')
}
function Copy-Kit($dest) {
    # the kit into <game>\IW4x-32 (an existing backup\ and mode.txt there are kept)
    Say "copying IW4x-32 to $dest"
    New-Item -ItemType Directory -Force -Path (P $dest 'files') | Out-Null
    foreach ($n in 'IW4x-32.bat', 'IW4x-32.sh', 'README.txt') { if (Test-Path -LiteralPath (P $Kit $n)) { Copy-Item -LiteralPath (P $Kit $n) -Destination (P $dest $n) -Force } }
    Get-ChildItem -LiteralPath $Files -Force | Where-Object { $_.Name -ne 'backup' -and $_.Name -ne 'mode.txt' -and $_.Name -notlike '.*' } |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (P $dest 'files') -Recurse -Force }
}
function Make-Shortcuts {
    if ($env:IW4X32_NO_SHORTCUTS -eq '1' -or $env:OS -ne 'Windows_NT') { return }
    try {
        $w = New-Object -ComObject WScript.Shell
        $bat = P $Kit 'IW4x-32.bat'
        $menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'IW4x-32'
        New-Item -ItemType Directory -Force -Path $menu | Out-Null
        $list = @(@([Environment]::GetFolderPath('Desktop'), 'IW4x-32', ''), @($menu, 'IW4x-32', ''),
            @($menu, 'IW4x-32 Server', '--server'), @($menu, 'IW4x (vanilla)', '--vanilla'), @($menu, 'Uninstall IW4x-32', '--uninstall'))
        foreach ($s in $list) {
            $l = $w.CreateShortcut((Join-Path $s[0] ($s[1] + '.lnk')))
            $l.TargetPath = $env:ComSpec
            $l.Arguments = '/c ""' + $bat + '" ' + $s[2] + '"'
            $l.WorkingDirectory = $Kit
            $l.IconLocation = (G 'iw4x.exe') + ',0'
            $l.Description = 'IW4x-32 - Modern Warfare 2 with 32 players'
            $l.Save()
        }
        Say 'shortcuts: "IW4x-32" on your desktop, and an IW4x-32 folder in the Start menu'
    } catch { Say "could not make the shortcuts ($($_.Exception.Message)) - start IW4x-32 with $bat" }
}
function Remove-Shortcuts {
    if ($env:OS -ne 'Windows_NT') { return }
    Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Desktop')) 'IW4x-32.lnk') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath('Programs')) 'IW4x-32') -Recurse -Force -ErrorAction SilentlyContinue
}
function Install-Here {
    # IW4x (official launcher) + IW4x-32 into $Game, then the shortcuts
    Say "setting up IW4x-32 in $Game"
    if (Game-Running) { Say 'ERROR: IW4x is running - close the game and try again'; return $false }
    $ours = Sha (F 'iw4x.dll')
    if ((Sha (G 'iw4x.dll')) -ne $ours -and (Sha (G 'iw4x.dll')) -ne $OFFICIAL_DLL) { Install-Official | Out-Null }
    Restore-V1Exe $OFFICIAL_EXE
    $now = Sha (G 'iw4x.dll')
    if (-not $now -or -not (Test-Path -LiteralPath (G 'iw4x.exe'))) {
        Say 'ERROR: IW4x could not be installed - is the internet working? Start IW4x-32 again to retry.'
        return $false
    }
    if ($now -ne $ours) {
        if ($now -ne $OFFICIAL_DLL) { Warn "this IW4x is not $OFFICIAL_VER, the version IW4x-32 is made for - installing anyway (an IW4x-32 update normally follows within a day)" }
        Backup-Dll
        Install-Ours
    }
    Make-Shortcuts
    Say 'IW4x-32 is installed.'
    return $true
}
function Do-Setup {
    $g = $SetupPath
    if (-not $g) { $g = Pick-Game }
    if (-not $g) { Say 'nothing was changed'; return $false }
    if (-not (Is-Game $g)) { Say "ERROR: no iw4mp.exe or iw4x.exe in $g - nothing was changed"; return $false }
    $g = (Resolve-Path -LiteralPath $g).Path
    $dest = P $g 'IW4x-32'
    if ($dest -ne $Kit) {
        try { Copy-Kit $dest } catch { Say "ERROR: could not copy to $dest - if the game is under Program Files, right-click IW4x-32.bat -> Run as administrator"; return $false }
        $script:Kit = $dest; $script:Files = P $dest 'files'
    }
    $script:Game = $g
    Migrate-Legacy | Out-Null
    return (Install-Here)
}
function Migrate-Legacy {
    # an IW4x-32 v2.0 folder: state into files\, the old scripts out (only when it really is one)
    if (-not (@('iw4x32_update.ps1', 'Play IW4x-32.bat', 'IW4x-32 Launcher.bat', 'install-linux.sh') | Where-Object { Test-Path -LiteralPath (P $Kit $_) })) { return $false }
    foreach ($n in 'backup', 'mode.txt') {
        $old = P $Kit $n
        if (-not (Test-Path -LiteralPath $old)) { continue }
        if (Test-Path -LiteralPath (F $n)) { Remove-Item -LiteralPath $old -Recurse -Force } else { Move-Item -LiteralPath $old -Destination (F $n) }
    }
    foreach ($n in $Legacy) { Remove-Item -LiteralPath (P $Kit $n) -Force -ErrorAction SilentlyContinue }
    foreach ($n in $LegacyDirs) { Remove-Item -LiteralPath (P $Kit $n) -Recurse -Force -ErrorAction SilentlyContinue }
    if (-not @(Get-ChildItem -LiteralPath (P $Kit 'server') -Force -ErrorAction SilentlyContinue)) { Remove-Item -LiteralPath (P $Kit 'server') -Force -ErrorAction SilentlyContinue }
    Say 'tidied up the IW4x-32 folder - everything starts from IW4x-32.bat now'
    return $true
}

# ---- what to start ---------------------------------------------------------------------------------------------
function Read-Mode {
    $f = F 'mode.txt'
    if (Test-Path -LiteralPath $f) {
        $w = "$(Get-Content -LiteralPath $f -TotalCount 1 -ErrorAction SilentlyContinue)".Trim()
        if ($w -in 'iw4x32', 'vanilla', 'server', 'vanilla-server') { return $w }
    }
    return 'iw4x32'
}
function Select-Mode {
    $modes = @('iw4x32', 'vanilla', 'server', 'vanilla-server', 'uninstall')
    $def = Read-Mode
    if ($env:IW4X32_NO_MENU -eq '1' -or -not (Interactive)) { return $def }
    $d = [array]::IndexOf($modes, $def) + 1
    Write-Host ''
    Write-Host "  IW4x-32 $(Installed-Version) - Modern Warfare 2 with 32 players"
    Write-Host "  game: $Game"
    Write-Host ''
    Write-Host '  [1] Play IW4x-32          32-player servers, and normal ones'
    Write-Host '  [2] Play vanilla IW4x     the official IW4x'
    Write-Host "  [3] Host a 32-player server   (port $Port)"
    Write-Host "  [4] Host a normal IW4x server (port $Port)"
    Write-Host '  [5] Uninstall IW4x-32'
    Write-Host ''
    Write-Host -NoNewline "  Press 1-5 - or wait: [$d] starts in 5 s "
    $end = (Get-Date).AddSeconds(5); $pick = $d
    while ((Get-Date) -lt $end) {
        if (-not [Console]::KeyAvailable) { Start-Sleep -Milliseconds 100; continue }
        $k = [Console]::ReadKey($true)
        if ($k.Key -eq [ConsoleKey]::Enter) { break }
        if ("$($k.KeyChar)" -match '^[1-5]$') { $pick = [int]"$($k.KeyChar)"; break }
        $end = (Get-Date).AddSeconds(30)                 # a key that is no choice: wait for one
    }
    Write-Host $pick
    $m = $modes[$pick - 1]
    if ($m -ne 'uninstall') { try { Set-Content -LiteralPath (F 'mode.txt') -Value $m -Encoding ASCII } catch { } }
    return $m
}

# ---- start things ----------------------------------------------------------------------------------------------
function Start-Game {
    # what the official IW4x launcher does, minus its file check: without steam_appid.txt / SteamAppId Steam
    # takes over and starts normal MW2
    $exe = G 'iw4x.exe'
    if (-not (Test-Path -LiteralPath $exe)) { Say "ERROR: no iw4x.exe in $Game - run IW4x-32.bat --setup"; return 1 }
    Write-Host "  command: `"$exe`" $($GameArgs -join ' ')"
    if ($Dry -or $env:IW4X32_NO_START -eq '1') { return 0 }
    if (-not (Test-Path -LiteralPath (G 'steam_appid.txt'))) { Set-Content -LiteralPath (G 'steam_appid.txt') -Value '10190' -Encoding ASCII }
    $env:SteamAppId = '10190'; $env:SteamGameId = '10190'
    Say 'starting IW4x-32 ...'
    if ($GameArgs.Count) { Start-Process -FilePath $exe -WorkingDirectory $Game -ArgumentList $GameArgs } else { Start-Process -FilePath $exe -WorkingDirectory $Game }
    return 0
}
function Start-Server($slots, $cfg, $label) {
    $exe = G 'iw4x.exe'
    if (-not (Test-Path -LiteralPath $exe)) { Say "ERROR: no iw4x.exe in $Game - run IW4x-32.bat --setup"; return 1 }
    if ($slots -eq 32 -and (Sha (G 'iw4x.dll')) -ne (Sha (F 'iw4x.dll'))) { Say 'ERROR: IW4x-32 is not installed - run IW4x-32.bat --setup'; return 1 }
    $user = G 'userraw'
    if (-not $Dry -and -not (Test-Path -LiteralPath (P $user $cfg))) {
        New-Item -ItemType Directory -Force -Path $user | Out-Null
        Copy-Item -LiteralPath (F $cfg) -Destination (P $user $cfg)
        Say "made userraw\$cfg - set your server name and an rcon password there, then restart the server"
    }
    $sa = @('-dedicated', '-stdout', '+set', 'net_port', $Port, '+exec', $cfg, '+set', 'sv_maxclients', $slots, '+set', 'party_maxplayers', $slots, '+set', 'party_enable', '0', '+map_rotate')
    Write-Host $label
    Write-Host "  game folder: $Game"
    Write-Host "  settings:    $(P $user $cfg)"
    Write-Host "  port:        $Port UDP - forward it on your router for players on the internet"
    Write-Host "  bots:        type  spawnBot 10  in the server console"
    Write-Host "  command:     iw4x.exe $($sa -join ' ')"
    if ($Dry -or $env:IW4X32_NO_START -eq '1') { return 0 }
    Start-Process -FilePath $exe -ArgumentList $sa -WorkingDirectory $Game -NoNewWindow -Wait
    Say 'the server stopped'
    Wait-Close
    return 0
}
function Do-Uninstall {
    if ($env:IW4X32_YES -ne '1') {
        if (-not (Interactive)) { Say 'uninstall needs a yes: IW4X32_YES=1'; return 1 }
        if ((Read-Host 'Uninstall IW4x-32 and put the official IW4x files back? [y/N]') -notmatch '^[yY]') { Say 'nothing was changed'; return 0 }
    }
    if (Game-Running) { Say 'ERROR: close the game first'; return 1 }
    if (Test-Path -LiteralPath (F 'backup/iw4x.dll')) {
        Copy-Item -LiteralPath (F 'backup/iw4x.dll') -Destination (G 'iw4x.dll') -Force
        Restore-V1Exe $null
        Say 'the official IW4x files are back'
    } else { Say 'no backup of the official iw4x.dll - the official IW4x launcher repairs it'; Install-Official | Out-Null }
    Remove-Shortcuts
    Say "IW4x-32 is uninstalled. You can delete the folder $Kit"
    Wait-Close
    return 0
}

# ---- main ------------------------------------------------------------------------------------------------------
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$rc = 0
try {
    if (-not (Test-Path -LiteralPath (F 'iw4x.dll'))) {
        # only IW4x-32.bat was downloaded (or the zip was not fully extracted): get the rest of the release
        Say 'getting IW4x-32 from GitHub ...'
        Update-Kit (Get-Json $Manifest 30)
    }
    $migrated = Migrate-Legacy
    if ($env:IW4X32_GAME) { $Game = $env:IW4X32_GAME } elseif (Is-Game (Split-Path -Parent $Kit)) { $Game = Split-Path -Parent $Kit }
    if ($Setup -or -not $Game) {
        if (-not (Do-Setup)) { Wait-Close; exit 1 }
        if (-not $Mode -and $Setup) { exit 0 }
    } elseif (-not (Test-Path -LiteralPath (F 'backup/iw4x.dll')) -and (Sha (G 'iw4x.dll')) -ne (Sha (F 'iw4x.dll'))) {
        if (-not (Install-Here)) { Wait-Close; exit 1 }  # the kit is in the game folder but was never installed
    } elseif ($migrated) { Make-Shortcuts }
    if (-not $Mode) { $Mode = Select-Mode }
    switch ($Mode) {
        'vanilla' {
            Restore-Official
            Say 'starting vanilla IW4x (the official IW4x launcher updates it first) ...'
            if (-not ($Dry -or $env:IW4X32_NO_START -eq '1')) { if (-not (Run-Launcher $null)) { $rc = 1 } }
        }
        'vanilla-server' { if (-not $Dry) { Restore-Official }; $rc = Start-Server 18 'server_vanilla.cfg' 'IW4x server - vanilla, 18 players' }
        'server' { if (-not $Dry) { Do-Update }; $rc = Start-Server 32 'server_iw4x32.cfg' 'IW4x-32 server - 32 players' }
        'uninstall' { $rc = Do-Uninstall }
        default { if (-not $Dry) { Do-Update }; $rc = Start-Game }
    }
} catch {
    Say "ERROR: $($_.Exception.Message)"
    $rc = 1
    if ($Game -and ($Mode -eq 'iw4x32' -or -not $Mode)) { Say 'starting the game anyway'; try { $rc = Start-Game } catch { } }
    if ($rc -ne 0) { Wait-Close }
}
if ($Warned -and (Interactive)) { Start-Sleep -Seconds 5 }   # let a warning be read before the window closes
exit $rc
