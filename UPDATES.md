# IW4x-32 updates

## v1.2 - 2026-10-10 - on IW4x r5154

# Choose vanilla IW4x or IW4x-32 at start, IW4x launcher fetched automatically

- **Start menu**: every start through "Play IW4x-32.bat" / play-linux.sh asks which game to play - **IW4x-32**
  (32-player servers, and normal ones) or **Vanilla IW4x** (the official IW4x, always the latest version). Enter or 5
  seconds = the one you picked last time. Skip the menu with `--iw4x32` or `--vanilla`.
- **Vanilla** puts the official IW4x files back and starts the official IW4x launcher, which updates IW4x and starts
  the game. Switching back to IW4x-32 puts IW4x-32 back. If vanilla updated IW4x past what IW4x-32 supports, IW4x-32
  says so and starts vanilla until the matching IW4x-32 update is out.
- **No IW4x launcher yet?** IW4x-32 downloads the official launcher from IW4x's GitHub, checks its SHA-256 and puts it
  in your game folder.
- Updates are no longer blocked by an iw4x.exe running from a different folder (e.g. a dedicated server).

Developed by qwen (Strata), reviewed and tested by Claude: 12 updater scenarios x Windows/Linux updater, all pass.

Still on the official IW4x **r5154**.

Automated tests:

| Test | Result | Detail |
|---|---|---|
| Server soak: 32 slots, 31 bots, 10 min, 2 map rotations | ✅ pass | alive_at_end=True map_up=yes new_minidumps=[] |
| Player build joins a 32-slot server with 30 bots, map rotation while connected | ✅ pass | client connected and alive, no crash dumps |
| Stock IW4x client joins an 18-slot server running the server build | ✅ pass | connected and alive |

Overall: **PASS** (Wine, this VM, 2026-10-10 01:40)

## v1.1 - 2026-10-09 - on IW4x r5154

# Automatic updates

IW4x-32 now keeps itself up to date. Every start through **Play IW4x-32.bat** (Windows) or **play-linux.sh** (Linux)
first checks for a new IW4x-32 release:

- if there is one, it updates IW4x (with the official IW4x launcher, update only) to the version that release is
  made for, downloads the new IW4x-32 files, checks every file's SHA-256 and installs them;
- it never updates IW4x past what IW4x-32 supports - when IW4x is newer, you keep playing the last working pair
  until the matching IW4x-32 update is out;
- it puts IW4x-32 back if the IW4x launcher restored the official 18-player files;
- nothing is downloaded when you are up to date, and without internet the game just starts.

Skip it with **Play IW4x-32 (no update).bat**, `play-linux.sh --no-update`, or `IW4X32_NO_UPDATE=1`.
The game files (iw4x.exe, iw4x.dll) are unchanged from v1.0. If you have v1.0: download this version once; from
now on updates arrive by themselves.

Still on the official IW4x **r5154**.

Automated tests:

| Test | Result | Detail |
|---|---|---|
| Server soak: 32 slots, 31 bots, 10 min, 2 map rotations | ✅ pass | alive_at_end=True map_up=yes new_minidumps=[] |
| Player build joins a 32-slot server with 30 bots, map rotation while connected | ✅ pass | client connected and alive, no crash dumps |
| Stock IW4x client joins an 18-slot server running the server build | ✅ pass | connected and alive |

Overall: **PASS** (Wine, this VM, 2026-10-09 21:42)
