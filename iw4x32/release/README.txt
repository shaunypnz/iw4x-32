IW4x-32 v2.7-r5292 - Modern Warfare 2 (2009) multiplayer with 32 players instead of 18
==================================================================================

  WINDOWS:  double-click  IW4x-32.bat
  LINUX / STEAM DECK:  run  ./IW4x-32.sh  in a terminal

That is all. The first time, it:
  1. finds your Modern Warfare 2 in Steam (asks if it is in more than one place),
  2. installs official IW4x with the official IW4x launcher if you do not have it,
  3. installs IW4x-32 and puts an "IW4x-32" shortcut on your desktop
     (Linux: in your applications menu).
After that the shortcut opens this menu - press a number, or wait 5 seconds:
  [1] Play IW4x-32            32-player servers, and normal ones
  [2] Play vanilla IW4x       the official IW4x
  [3] Host a 32-player server
  [4] Host a normal IW4x server
  [5] Uninstall IW4x-32
It updates IW4x-32 (and IW4x) by itself. Without internet the game just starts.

You need: Call of Duty: Modern Warfare 2 (2009) from Steam. Nothing else.

WHAT IT IS
  One file, an iw4x.dll built from public source, on top of a normal IW4x install.
  Your iw4x.exe stays the official one. Scoreboard, minimap, kill feed, voice and
  killstreaks work for all 32 players, and normal 18-player IW4x servers keep working.
  32-player servers show in the in-game server browser.

HOSTING A SERVER
  Pick [3] in the menu (Linux: ./IW4x-32.sh --server; it runs under Wine).
  The first start makes userraw\server_iw4x32.cfg in your game folder: set the server
  name, an rcon password and the map rotation there, then restart the server.
  Forward the port (UDP 28960) on your router. Bots: type  spawnBot 10  in the console.
  Another port / a second server:  IW4x-32.bat --server 28961

OPTIONS (for your own shortcuts, or a terminal)
  --play  --vanilla  --server [port]  --vanilla-server [port]  --uninstall
  --setup [game folder]   set up again (another game folder)
  --no-update             skip the update check
  anything else goes to the game, e.g.  IW4x-32.bat --play +connect 1.2.3.4:28960

GOOD TO KNOW
  - Start the game with IW4x-32, not the IW4x launcher: the launcher's file check puts
    the 18-player iw4x.dll back (IW4x-32 puts itself back on its next start).
  - When IW4x releases something newer than this IW4x-32, you get a warning and it
    starts anyway; the matching IW4x-32 update follows by itself.
  - Linux + Steam: it runs the game with the game's own Proton. To use Steam's Play
    button too, set this once in Steam -> Modern Warfare 2 - Multiplayer ->
    Properties -> Launch Options:   bash -c 'exec "${@/iw4mp.exe/iw4x.exe}"' -- %command%
  - Windows "protected your PC" message: More info -> Run anyway (the files are
    plain scripts; read them first if you like).
  - Tested: the 32-player server and the client under Wine/Proton on Linux.
    The Windows client has not been tested by us yet - please report how it goes.

IS IT SAFE?
  - Source: https://github.com/shaunypnz/iw4x-32 (a fork of IW4x, GPL-3.0). The DLL
    is built from it; files\CHANGES.txt explains every change it makes.
  - Every file's SHA-256 is in files\SHA256SUMS.txt; updates are checked against the
    same hashes before anything is replaced.
  - It only writes to your game folder: one dll (the official one is backed up in
    IW4x-32\files\backup\), plus a shortcut. No services, no registry.
  - The DLL changes the game in memory only, and only when it recognises the IW4x
    engine. A file named iw4x32-disable next to iw4x.exe switches it off.

Not affiliated with Activision, Infinity Ward or the IW4x team. Made with AI help -
see files\AI_CREDITS.txt.
