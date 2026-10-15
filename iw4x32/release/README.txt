IW4x-32 v2.0 - play IW4x (MW2 2009 PC) on 32-player servers
==============================================================

WHAT IT IS
  IW4x-32 is ONE file: an iw4x.dll that lets your game join 32-player servers.
  Your iw4x.exe stays the official IW4x one - the DLL lifts the engine's 18-player
  limits in memory when the game starts, the same way IW4x itself patches the engine
  for its own fixes. Scoreboard, minimap, kill feed, name tags, dead bodies, voice,
  killstreak views (AC-130, chopper gunner, predator), clan tags and calling-card
  titles all work for players 1-32.
  Normal 18-player IW4x servers keep working: the game detects the server type
  when you join.

WHAT IS NEW IN v2.0
  - One DLL instead of two patched files. Nothing about your iw4x.exe is touched.
  - The source is the whole program: a fork of IW4x (GPL-3.0),
    https://github.com/shaunypnz/iw4x-32 - IW4x's own code with the IW4x-32 changes
    as ordinary commits. No binary patches, no manifests, no injected assembly:
    the 32-player work is a normal IW4x component (src/Components/Modules/IW4x32.cpp).
  - If you had IW4x-32 v1.x (which replaced iw4x.exe too), the installer puts your
    official IW4x iw4x.exe back from IW4x-32\backup\.

TESTED ON
  The 32-player server side is tested under Wine on Linux (32 slots, 31 bots, soak
  runs and map rotations). The Windows client install described here has NOT been
  tested by us yet - please report how it goes.

REQUIREMENTS
  - Modern Warfare 2 (2009) on Steam.
  - IW4x r5168 (the current official release) installed and started once.

INSTALL
  1. Extract the zip.
  2. Move the IW4x-32 folder INTO your MW2 game folder (the folder with iw4x.exe).
  3. Double-click "Install IW4x-32.bat".
     It checks your iw4x.dll is the official IW4x r5168 file, backs it up to
     IW4x-32\backup\, installs ours and checks it. If your file is not the official
     one it stops and changes nothing.
     Linux: same steps, but run  bash IW4x-32/install-linux.sh
  Linux + Steam (Proton): then set this ONCE in Steam -> "Modern Warfare 2 - Multiplayer"
  -> Properties -> Launch Options, so Steam runs IW4x-32 in the game's own Proton prefix:
      bash -c 'exec "${@/iw4mp.exe/iw4x.exe}"' -- %command%

PLAY
  - IW4x-32 keeps itself up to date: every start through "Play IW4x-32.bat" or play-linux.sh
    first checks for a new IW4x-32 release. If there is one, it updates IW4x (with the
    official IW4x launcher, update only) to the version that release is made for, downloads
    the new IW4x-32 files, checks every file's SHA-256 and installs them. Nothing is
    downloaded when you are up to date, and without internet the game just starts. It never
    updates IW4x past what IW4x-32 supports: when IW4x is newer, you keep playing the last
    working pair until the matching IW4x-32 update is out. It also puts IW4x-32 back if the
    IW4x launcher's file check restored the official iw4x.dll. Skip it: "Play IW4x-32
    (no update).bat", play-linux.sh --no-update, or set IW4X32_NO_UPDATE=1.
  - Then it asks which game to start:
        [1] IW4x-32 - 32-player servers (and normal ones)
        [2] Vanilla IW4x - the official IW4x, always the latest version
    Enter takes the default (what you started last time, IW4x-32 the first time) and it starts after 5 s. The
    choice is remembered in IW4x-32\mode.txt. To answer without being asked, add --vanilla or --iw4x32:
    "Play IW4x-32.bat" --vanilla , or  bash IW4x-32/play-linux.sh --vanilla . Vanilla IW4x always starts through
    the official IW4x launcher (downloaded into the game folder when it is missing): it updates IW4x to the
    newest version and starts the game itself. Switching back to IW4x-32 puts the IW4x-32 dll back by itself;
    if vanilla updated IW4x past what IW4x-32 supports yet, vanilla starts that time and IW4x-32 comes back with
    the matching IW4x-32 update.
  - Windows: start the game with "Play IW4x-32.bat". It prepares Steam the same way the
    IW4x launcher does (steam_appid.txt + Steam app id 10190, otherwise Steam starts normal
    MW2 instead) and starts iw4x.exe, without the launcher's file check.
    If that does not start the game, use "Play IW4x-32 (IW4x launcher, no file check).bat":
    it runs the official IW4x launcher with --skip-remote --no-self-update (no file check,
    no update) and afterwards confirms IW4x-32 is still installed.
    Linux + Steam: press Play on "Modern Warfare 2 - Multiplayer" in Steam (with the launch
    option above), or run  bash IW4x-32/play-linux.sh  (it checks the launch option and starts
    the game through Steam; --direct runs it with the game's Proton without Steam's launcher).
    Linux without Steam: bash IW4x-32/play-linux.sh uses Wine (set WINEPREFIX if needed).
    To go back to stock MW2 multiplayer in Steam, remove the launch option.
  - Do NOT start it through the IW4x launcher normally: its file check puts the official
    18-player iw4x.dll back (the next start through "Play IW4x-32" puts IW4x-32 back).
  - 32-player servers now appear in the in-game server browser.
    Normal IW4x hides servers with more than 18 slots, so players without
    IW4x-32 will not see them (and get an install message if they try to join).

HOST A 32-PLAYER SERVER
  1. Install exactly as above ("Install IW4x-32.bat", or ./install-linux.sh on Linux).
  2. Windows: double-click "Start IW4x-32 Server.bat" (another port: run it as
     "Start IW4x-32 Server.bat 28961"). Linux: ./start-server-linux.sh [port] - it runs
     iw4x.exe -dedicated under Wine (prefix ~/.wine-iw4x32-server unless WINEPREFIX is set).
  3. The first start makes userraw\server_iw4x32.cfg in your game folder: set the server
     name (sv_hostname), an rcon password and the map rotation there, then restart.
  4. Players on the internet: forward the port (UDP, default 28960) on your router.
     Add bots: type  spawnBot 10  in the server console.
  "--dry" as the first argument only checks the install and prints the command.

UNINSTALL
  Double-click "Uninstall IW4x-32.bat" (Linux: bash IW4x-32/uninstall-linux.sh) to
  restore your backup, or run the IW4x launcher once (it re-downloads the official
  files). Then delete the IW4x-32 folder.

IS IT SAFE?
  You do not have to take our word for it:
  - SHA256SUMS.txt lists the hash of every file in this release, and latest.json on
    GitHub lists them again for the auto-update.
  - iw4x.dll is built from public source: https://github.com/shaunypnz/iw4x-32
    (a fork of https://github.com/iw4x/iw4x-client, GPL-3.0). GitHub Actions builds
    every release from the tag it names, so you can check the DLL against the source
    or build it yourself.
  - CHANGES.txt explains what the DLL does and lists every engine site it changes.
  - The DLL changes the game in memory only, and only when it recognises the IW4x
    r5168 engine: if the check fails it changes nothing at all. A file named
    iw4x32-disable next to iw4x.exe switches it off.
  - Like IW4x itself, this is a client mod for a 2009 game: use it on your own
    install, and keep your backup.

KNOWN LIMITS
  - Made for IW4x r5168. When IW4x updates, the matching IW4x-32 update arrives by itself
    the next time you start through "Play IW4x-32" (after it has passed its tests).
  - Hosting 32 players needs this IW4x-32 build on the server too - start it with
    "Start IW4x-32 Server.bat" / start-server-linux.sh (they set sv_maxclients 32).
  - End-of-match stats for players 19-32 have not been checked yet.

TROUBLESHOOTING
  - "STOPPED: your iw4x.dll is not the official IW4x r5168 file": run the IW4x launcher
    once to repair it, then install again. If IW4x has released a newer version, wait for
    an IW4x-32 update.
  - Steam opens normal MW2, or nothing happens: start with "Play IW4x-32.bat" (not by
    double-clicking iw4x.exe), or use the "(IW4x launcher, no file check)" script.
  - The 32-player servers are missing from the browser: you started the game
    through the IW4x launcher, which restored the official iw4x.dll. Start with
    "Play IW4x-32.bat" (it puts IW4x-32 back).
  - "IW4x is running": close the game before installing or uninstalling.

CREDITS AND LICENCE
  IW4x-32 v2.0 is a fork of IW4x (https://github.com/iw4x/iw4x-client, GPL-3.0) with the
  IW4x-32 changes on top; the v1.x mod it replaces is at
  https://github.com/shaunypnz/iw4x-32-old. Made with AI help - see AI_CREDITS.txt.
  Not affiliated with Activision, Infinity Ward or the IW4x team.
