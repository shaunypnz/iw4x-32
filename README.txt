IW4x-32 v1.1 - play IW4x (MW2 2009 PC) on 32-player servers
==============================================================

WHAT IT IS
  IW4x-32 replaces two IW4x files (iw4x.exe and iw4x.dll) so your game can join
  32-player servers: scoreboard, minimap, kill feed, name tags, dead bodies, voice,
  killstreak views (AC-130, chopper gunner, predator), clan tags and calling-card
  titles all work for players 1-32.
  Normal 18-player IW4x servers keep working: the game detects the server type
  when you join.

TESTED ON
  Tested ONLY under Wine on Linux (Ubuntu, Wine 10 + DXVK, and Wine for the servers).
  It has NOT been tested on Windows yet. It should work the same way there, but please
  report how it goes.

REQUIREMENTS
  - Modern Warfare 2 (2009) on Steam.
  - IW4x r5154 (the current official release) installed and started once.

INSTALL
  1. Extract the zip.
  2. Move the IW4x-32 folder INTO your MW2 game folder (the folder with iw4x.exe).
  3. Double-click "Install IW4x-32.bat".
     It checks your iw4x.exe and iw4x.dll are the official IW4x r5154 files,
     backs them up to IW4x-32\backup\, installs ours and checks them.
     If your files are not the official ones it stops and changes nothing.
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
    IW4x launcher restored the official files. Skip it: "Play IW4x-32 (no update).bat",
    play-linux.sh --no-update, or set IW4X32_NO_UPDATE=1. What changed: UPDATES.md on GitHub.
  - Windows: start the game with "Play IW4x-32.bat". It prepares Steam the same way the
    IW4x launcher does (steam_appid.txt + Steam app id 10190, otherwise Steam starts normal
    MW2 instead) and starts iw4x.exe, without the launcher's file check.
    If that does not start the game, use "Play IW4x-32 (IW4x launcher, no file check).bat":
    it runs the official IW4x launcher with --skip-remote --no-self-update (no file check,
    no update) and afterwards confirms the IW4x-32 files are still installed.
    Linux + Steam: press Play on "Modern Warfare 2 - Multiplayer" in Steam (with the launch
    option above), or run  bash IW4x-32/play-linux.sh  (it checks the launch option and starts
    the game through Steam; --direct runs it with the game's Proton without Steam's launcher).
    Linux without Steam: bash IW4x-32/play-linux.sh uses Wine (set WINEPREFIX if needed).
    To go back to stock MW2 multiplayer in Steam, remove the launch option.
  - Do NOT start it through the IW4x launcher normally: that puts the official 18-player
    files back (the next start through "Play IW4x-32" puts IW4x-32 back).
  - 32-player servers now appear in the in-game server browser.
    Normal IW4x hides servers with more than 18 slots, so players without
    IW4x-32 will not see them (and get an install message if they try to join).

UNINSTALL
  Double-click "Uninstall IW4x-32.bat" (Linux: bash IW4x-32/uninstall-linux.sh) to
  restore your backup, or run the IW4x
  launcher once (it re-downloads the official files). Then delete the IW4x-32 folder.

IS IT SAFE?
  You do not have to take our word for it:
  - SHA256SUMS.txt lists the hash of every file in this release.
  - CHANGES.txt explains every change. source\manifest_iw4x_exe.json and
    source\manifest_iw4x_dll.json list every single changed byte with its reason.
  - source\iw4x32_check.py (plain Python 3, no extra packages) proves that, using
    your own official files:
      python IW4x-32\source\iw4x32_check.py
    It shows that nothing outside the listed changes differs, that the Windows
    functions the files can call are IDENTICAL to the official files (nothing new
    imported, no network code added), and every text string in the added code.
    It can also BUILD our files from your official ones, so you never need to
    trust our binaries.
  - The added code (about 250 lines of C/assembly, source\engine32c\) only
    switches 16 code sites between the normal and the 32-player layout when you
    join a server.
  - One deliberate change: the IW4x "update available" notice is switched off
    (it was set from a background thread, which could crash the game, and
    updating would remove IW4x-32 anyway).
  - The exe is modified and therefore unsigned, like IW4x's own. If your
    antivirus complains, check the SHA-256 or scan it on virustotal.com yourself.

KNOWN LIMITS
  - A server started with these files is limited to 18 players, like normal IW4x.
  - End-of-match stats are recorded for players 1-18 only.
  - Made for IW4x r5154. When IW4x updates, the matching IW4x-32 update arrives by itself
    the next time you start through "Play IW4x-32" (after it has passed its tests).

TROUBLESHOOTING
  - "STOPPED: your iw4x.exe / iw4x.dll are not the official IW4x r5154 files":
    run the IW4x launcher once to repair them, then install again. If IW4x has
    released a newer version, wait for an IW4x-32 update.
  - Steam opens normal MW2, or nothing happens: start with "Play IW4x-32.bat" (not by
    double-clicking iw4x.exe), or use the "(IW4x launcher, no file check)" script.
  - The 32-player servers are missing from the browser: you started the game
    through the IW4x launcher, which restored the official files. Start with
    "Play IW4x-32.bat" (it puts IW4x-32 back).
  - "IW4x is running": close the game before installing or uninstalling.

CREDITS AND LICENCE
  Made with AI help: Claude (Anthropic) did the reverse engineering, code and
  testing; local qwen and gemma models helped with analysis and documentation.
  See AI_CREDITS.txt.
  iw4x.dll is IW4x's code (GPL-3.0, https://github.com/iw4x/iw4x-client) with
  binary patches. The manifests and the checker in source\ are the complete
  source of our changes.
  Not affiliated with Activision, Infinity Ward or the IW4x team.
