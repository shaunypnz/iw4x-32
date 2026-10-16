IW4x-32 v2.0 - play IW4x (MW2 2009 PC) on 32-player servers
==============================================================

QUICK START
  Windows - extract the zip and double-click "IW4x-32 Setup.bat". It finds your
  MW2 folder (asks if there is more than one), installs official IW4x if you do
  not have it yet, installs IW4x-32 and makes four shortcuts. Then double-click
  the "IW4x-32 (32 players)" shortcut and play.

  Linux - extract the zip and run, in a terminal:
      cd IW4x-32 && ./setup-linux.sh
  It asks where the game is, does the same, and makes four menu entries. Then:
      ./launcher-linux.sh
  (or the "IW4x-32 (32 players)" entry in your applications menu)

  Host a 32-player server: the "IW4x-32 Server" shortcut, or
      ./launcher-linux.sh --server          (a port: --server 28961)
  Just want normal IW4x: the "IW4x (vanilla)" shortcut, or
      ./launcher-linux.sh --vanilla

  Nothing else is required. The rest of this file is the detail.

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
  - One-click setup and one launcher for everything. Windows: "IW4x-32 Setup.bat"
    and "IW4x-32 Launcher.bat". Linux: setup-linux.sh and launcher-linux.sh.
    The old scripts ("Install IW4x-32.bat", "Play IW4x-32.bat", play-linux.sh,
    "Start IW4x-32 Server.bat", start-server-linux.sh) still work: they are thin
    wrappers of the launcher now.
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
  - IW4x r5168 (the current official release). You do not have to install it
    yourself: the setup gets it with the official IW4x launcher.

INSTALL
  Windows: double-click "IW4x-32 Setup.bat". Linux: ./setup-linux.sh
  It does, in this order:
   1. finds the MW2 multiplayer folder (iw4mp.exe / iw2mp.exe / iw4x.exe): this
      folder's parent, then your Steam libraries. Several: you pick one by number.
      None: you type the path - Enter stops with nothing changed.
   2. copies the IW4x-32 folder into the game folder as <game>\IW4x-32.
   3. if official IW4x r5168 is missing or is another version, it lets the OFFICIAL
      IW4x launcher install it. IW4x-32 never downloads IW4x's own files itself.
   4. installs IW4x-32: checks your iw4x.dll is the official r5168 file, backs it up
      to IW4x-32\backup\, installs ours and checks it. A file it does not recognise
      is never overwritten - it stops and changes nothing.
   5. makes four shortcuts (Desktop and Start Menu on Windows, .desktop entries on
      Linux): IW4x-32 (32 players), IW4x (vanilla), IW4x-32 Server,
      IW4x Server (vanilla). --no-shortcuts skips this.
  Linux + Steam (Proton): then set this ONCE in Steam -> "Modern Warfare 2 -
  Multiplayer" -> Properties -> Launch Options, so Steam runs IW4x-32 in the game's
  own Proton prefix:
      bash -c 'exec "${@/iw4mp.exe/iw4x.exe}"' -- %command%

THE LAUNCHER
  "IW4x-32 Launcher.bat" (Windows) and ./launcher-linux.sh (Linux) start
  everything. With no argument they ask what to start:
      [1] IW4x-32        - 32-player servers, and normal ones
      [2] Vanilla IW4x   - the official IW4x, always the latest version
      [3] IW4x-32 server - 32-player dedicated server
      [4] IW4x server    - normal 18-player dedicated server
  Enter takes what you started last time (remembered in IW4x-32\mode.txt) and it
  starts after 5 s. Say it straight with a flag instead:
      --play   --vanilla   --server [port]   --vanilla-server [port]
  and anything else goes to the game, e.g.  --play +connect <server address>.
  Two more flags: --dry only checks the install and prints the command, and
  --no-update skips the version check. Environment: IW4X32_NO_UPDATE=1 (same as
  --no-update), IW4X32_NO_MENU=1 (start what mode.txt says, do not ask),
  IW4X32_GAME=<path> (the game folder, for the Linux launcher).
  - Vanilla IW4x always starts through the official IW4x launcher (it is downloaded
    into the game folder when it is missing): that updates IW4x to the newest version
    and starts the game. IW4x-32's dll is put back from IW4x-32\backup\ first, and the
    next IW4x-32 start puts IW4x-32 back by itself.
  - A vanilla server does the same thing to the dll and then runs the normal
    18-player server with its own settings file, userraw\server_vanilla.cfg.
  - Windows: starting IW4x-32 prepares Steam the way the IW4x launcher does
    (steam_appid.txt + Steam app id 10190, otherwise Steam starts normal MW2
    instead) and starts iw4x.exe without the launcher's file check. If that does not
    start the game, use "Play IW4x-32 (IW4x launcher, no file check).bat": it runs the
    official launcher with --skip-remote --no-self-update and afterwards confirms
    IW4x-32 is still installed.
  - Linux + Steam: press Play on "Modern Warfare 2 - Multiplayer" in Steam (with the
    launch option above), or run ./launcher-linux.sh --play - it checks the launch
    option and starts the game through Steam; --direct runs it with the game's Proton
    without Steam's launcher. Without Steam it uses Wine (set WINEPREFIX if needed).
    To go back to stock MW2 multiplayer in Steam, remove the launch option.
  - Do NOT start the game through the IW4x launcher normally: its file check puts
    the official 18-player iw4x.dll back (the next IW4x-32 start puts IW4x-32 back).
  - 32-player servers now appear in the in-game server browser. Normal IW4x hides
    servers with more than 18 slots, so players without IW4x-32 will not see them
    (and get an install message if they try to join).

STAYING UP TO DATE
  Every start checks for a new IW4x-32 release (both GitHub repos, 5 seconds each).
  When there is one it updates IW4x to the version that release is made for - with
  the official IW4x launcher, update only - then downloads the new IW4x-32 files,
  checks every file's SHA-256 and installs them. Nothing is downloaded when you are
  up to date, and without internet the game just starts.
  When official IW4x has released something NEWER than the IW4x-32 you have, you get
  a warning and IW4x-32 starts anyway: it never stops you from playing. If that newer
  IW4x really does not work with this IW4x-32, the game tells you, and the matching
  IW4x-32 update arrives by itself once it is out.
  Skip the check: --no-update, "Play IW4x-32 (no update).bat", or IW4X32_NO_UPDATE=1.

HOST A 32-PLAYER SERVER
  1. Install as above (the setup does it; a game folder is enough - no shortcuts
     needed, use --no-shortcuts).
  2. Windows: the "IW4x-32 Server" shortcut, or "Start IW4x-32 Server.bat".
     Linux: ./launcher-linux.sh --server [port] - it runs iw4x.exe -dedicated under
     Wine (prefix ~/.wine-iw4x32-server unless WINEPREFIX is set).
     Another port for a second server:  --server 28961.
  3. The first start makes userraw\server_iw4x32.cfg in your game folder: set the
     server name (sv_hostname), an rcon password and the map rotation there, then
     restart.
  4. Players on the internet: forward the port (UDP, default 28960) on your router.
     Add bots: type  spawnBot 10  in the server console.
  A normal 18-player IW4x server from the same folder: the "IW4x Server (vanilla)"
  shortcut, or ./launcher-linux.sh --vanilla-server [port] (userraw\server_vanilla.cfg).
  "--dry" only checks the install and prints the command.

UNINSTALL
  Double-click "Uninstall IW4x-32.bat" (Linux: ./uninstall-linux.sh) to restore your
  backup, or run the IW4x launcher once (it re-downloads the official files). Then
  delete the IW4x-32 folder and its shortcuts.

IS IT SAFE?
  You do not have to take our word for it:
  - SHA256SUMS.txt lists the hash of every file in this release, and latest.json on
    GitHub lists them again for the auto-update.
  - iw4x.dll is built from public source: https://github.com/shaunypnz/iw4x-32
    (a fork of https://github.com/iw4x/iw4x-client, GPL-3.0). GitHub Actions builds
    every release from the tag it names, so you can check the DLL against the source
    or build it yourself.
  - CHANGES.txt explains what the DLL does and lists every engine site it changes.
  - The scripts only ever write to your game folder: one dll in, your own files in
    backup\, and the launcher's mode.txt. Nothing else, no services, no registry.
  - The DLL changes the game in memory only, and only when it recognises the IW4x
    r5168 engine: if the check fails it changes nothing at all. A file named
    iw4x32-disable next to iw4x.exe switches it off.
  - Like IW4x itself, this is a client mod for a 2009 game: use it on your own
    install, and keep your backup.

KNOWN LIMITS
  - Made for IW4x r5168. When IW4x updates, the matching IW4x-32 update arrives by
    itself the next time you start (after it has passed its tests). Until then you
    are warned and can keep playing.
  - Hosting 32 players needs this IW4x-32 build on the server too - start it with
    the "IW4x-32 Server" shortcut / ./launcher-linux.sh --server (they set
    sv_maxclients 32).
  - End-of-match stats for players 19-32 have not been checked yet.

TROUBLESHOOTING
  - "STOPPED: your iw4x.dll is not the official IW4x r5168 file": run the IW4x
    launcher once to repair it (or "IW4x-32 Setup.bat", which does it for you), then
    install again. If IW4x has released a newer version, wait for an IW4x-32 update.
  - Steam opens normal MW2, or nothing happens: start with the IW4x-32 shortcut or
    "Play IW4x-32.bat" (not by double-clicking iw4x.exe), or use the
    "(IW4x launcher, no file check)" script.
  - The 32-player servers are missing from the browser: you started the game through
    the IW4x launcher, which restored the official iw4x.dll. Start with IW4x-32 again
    (it puts itself back).
  - "IW4x is running": close the game before installing or uninstalling.
  - Linux: "Permission denied" - the scripts are executable in the zip, but a copy
    that lost the bit needs  chmod +x *.sh  once.

CREDITS AND LICENCE
  IW4x-32 v2.0 is a fork of IW4x (https://github.com/iw4x/iw4x-client, GPL-3.0) with
  the IW4x-32 changes on top; the v1.x mod it replaces is at
  https://github.com/shaunypnz/iw4x-32-old. Made with AI help - see AI_CREDITS.txt.
  Not affiliated with Activision, Infinity Ward or the IW4x team.
