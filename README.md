# IW4x-32 v1.0

Play **IW4x** (Call of Duty: Modern Warfare 2, 2009, PC) on **32-player servers**.

IW4x-32 replaces two IW4x files, `iw4x.exe` and `iw4x.dll`, built on the official IW4x release **r5154**. With them,
everything works for players 1-32:
- the scoreboard, minimap, kill feed and name tags;
- dead bodies and voice;
- killstreak views (AC-130, chopper gunner, predator);
- clan tags and calling-card titles.

Normal 18-player IW4x servers keep working: the game detects the server type when you join.

> **Tested on:** Linux under Wine/Proton. Windows reports are welcome.


**Host a 32-player server:** [`server/`](server/README.md). **IW4x developers:** everything needed to merge 32-player support into IW4x is in [`iw4x-integration/`](iw4x-integration/README.md).

## Download

Grab `IW4x-32-v1.0.zip` from [Releases](../../releases), or use **Code → Download ZIP**. Either way you get one
folder that goes inside your game folder.

## Install

1. You need MW2 on Steam, with **IW4x r5154** installed and started once.
2. Extract the zip and move the folder (`IW4x-32`) **into your MW2 game folder**, the one with `iw4x.exe`.
3. Run the installer:
   - **Windows:** double-click `Install IW4x-32.bat`.
   - **Linux:** run `bash IW4x-32/install-linux.sh`.

   The installer checks that your `iw4x.exe` / `iw4x.dll` are the official r5154 files (SHA-256), backs them up to
   `IW4x-32/backup/`, installs ours and verifies them. If your files aren't the official ones, it stops and changes
   nothing.

## Play

| | |
|---|---|
| **Windows** | `Play IW4x-32.bat`. It prepares Steam the way the IW4x launcher does (`steam_appid.txt`, app id 10190) and starts `iw4x.exe`, without the launcher's file check. If that doesn't start the game, use `Play IW4x-32 (IW4x launcher, no file check).bat`: it runs the official launcher with `--skip-remote --no-self-update` and then confirms the IW4x-32 files are still installed. |
| **Linux + Steam (Proton)** | Set this **once** in Steam → *Modern Warfare 2 - Multiplayer* → Properties → Launch Options, then press Play: `bash -c 'exec "${@/iw4mp.exe/iw4x.exe}"' -- %command%` (`bash IW4x-32/play-linux.sh` checks this and starts the game through Steam.) |
| **Linux without Steam** | `bash IW4x-32/play-linux.sh` (Wine; set `WINEPREFIX` if needed). |

Don't start the game through the normal IW4x launcher, and don't let it update: that puts the official 18-player
files back. That also works as an uninstall.

32-player servers appear in the in-game server browser. Normal IW4x hides servers with more than 18 slots, so players without IW4x-32 won't see them. If they try to join
one, they get an install message.

## Is it safe?

You don't have to take our word for it.

- [`SHA256SUMS.txt`](SHA256SUMS.txt) lists the hash of every file.
- [`CHANGES.txt`](CHANGES.txt) explains every change.
- [`source/manifest_iw4x_exe.json`](source/manifest_iw4x_exe.json) and
  [`source/manifest_iw4x_dll.json`](source/manifest_iw4x_dll.json) list **every changed byte**, each with its reason.
- [`source/iw4x32_check.py`](source/iw4x32_check.py) is plain Python 3. Run `python IW4x-32/source/iw4x32_check.py`
  after installing. It uses your own official files to prove that:
  - nothing outside the listed changes differs;
  - the Windows functions the files can import are **identical** to the official files, so there's no new network or
    file code;
  - every text string in the added code is listed.

  It can also **build our files from your official ones**, so you never need to trust our binaries.
- The added code is about 250 lines of C/assembly, in [`source/engine32c/`](source/engine32c). It only switches 16
  code sites between the normal and the 32-player layout when you join a server.
- One deliberate change: the IW4x "update available" notice is off. It was set from a background thread, which
  could crash the game, and updating would remove IW4x-32 anyway.
- The exe is modified and therefore unsigned, like IW4x's own. If your antivirus complains, check the SHA-256, or
  scan the file on virustotal.com yourself.

## Known limits

- A server started with these files is limited to 18 players, like normal IW4x.
- End-of-match stats are recorded for players 1-18 only.
- Made for IW4x r5154. When IW4x updates, wait for a matching IW4x-32 update.

## Troubleshooting

- **"STOPPED: … not the official IW4x r5154 files":** run the IW4x launcher once to repair them, then install again.
- **Steam opens normal MW2, or nothing happens:** start with `Play IW4x-32.bat`, not by double-clicking `iw4x.exe`.
  On Linux, use the Steam launch option above.
- **The 32-player servers are missing from the browser:** the IW4x launcher restored the official files. Install
  again.

## Host your own server

The **server build** (hosts up to 32 players, also plays), its byte manifests and Windows/Linux install scripts
are in [`server/`](server/README.md).

## For the IW4x team

[`iw4x-integration/`](iw4x-integration/README.md) lists every engine and DLL change, with machine-readable tables
(each entry tagged client or server), the injected-code source, the build tools and a reference in-memory
patcher. It's meant to make merging 32-player support into the main IW4x as easy as possible.

## Credits and licence

Made with AI help: Claude (Anthropic) did the reverse engineering, code and testing. Local qwen and gemma models
helped with analysis and docs. See [`AI_CREDITS.txt`](AI_CREDITS.txt).

`iw4x.dll` is IW4x's code ([GPL-3.0](https://github.com/iw4x/iw4x-client)) with binary patches. The manifests and the
checker in `source/` are the complete source of our changes.

Not affiliated with Activision, Infinity Ward or the IW4x team.
