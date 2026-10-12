# Task (qwen): IW4x-32 player kit + GitHub release workflow in the fork

The fork now gives 32 players from iw4x.dll alone (stock iw4x.exe). This repo will REPLACE the public repo
shaunypnz/iw4x-32, whose installed players run an auto-updater (`iw4x32/reference/../` see the old kit:
`$HOME/Projects/iw4x-32-public/`) that reads `https://raw.githubusercontent.com/shaunypnz/iw4x-32/main/latest.json`
and downloads `base_url` + each path in `files`, checking SHA-256.

## Deliverables
1. `iw4x32/release/`: the player kit, adapted from the old kit (`$HOME/Projects/iw4x-32-public/`: installers,
   Play*.bat, play-linux.sh, updater .py/.ps1, README.txt, CHANGES.txt, AI_CREDITS.txt). Changes: players now get
   ONLY `files/iw4x.dll` (no iw4x.exe replacement - the installers stop copying/patching iw4x.exe and restore a
   previously replaced one from their backup); keep the "skip the IW4x launcher's file check" logic, because the
   official launcher would put the stock iw4x.dll back. README/CHANGES: v2.0 = one DLL, source is this fork (GPL-3.0).
2. `latest.json` at the repo ROOT (same format as the old one): version "v2.0", base_url
   `https://raw.githubusercontent.com/shaunypnz/iw4x-32/v2.0/iw4x32/release/`, files = every kit file + SHA-256
   (generate it with `iw4x32/tools/make_latest.py`; `files/iw4x.dll` is the Release build's DLL copied in).
3. `.github/workflows/iw4x32-release.yml`: on a `v*` tag: build Release on windows-2022 exactly like
   `.github/workflows/build.yml`, zip `iw4x32/release/` with the built DLL as `IW4x-32-<tag>.zip`, and publish a GitHub
   Release with the zip + iw4x.dll + SHA256SUMS.txt (use `ncipollo/release-action@v1` like release.yml).
4. `iw4x32/tools/check_kit.py`: fails unless latest.json parses, every listed file exists with that SHA-256, no
   installer references replacing iw4x.exe, and the workflow YAML parses with a `v*` tag trigger.
Line endings: .bat/.ps1/.txt in the kit stay CRLF (Windows players). Never push. No internal details in any file.
