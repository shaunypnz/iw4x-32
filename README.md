# IW4x-32 — 32-player IW4x

**IW4x-32 is a fork of [iw4x/iw4x-client](https://github.com/iw4x/iw4x-client) remixed with the original
[IW4x-32 mod](https://github.com/shaunypnz/iw4x-32-old): 32 players on Modern Warfare 2 multiplayer instead of 18.**

| | |
|---|---|
| **What it is** | The real IW4x client source, with the IW4x-32 changes applied on top as ordinary commits (search the code for `IW4x-32:`), so it stays easy to follow and to rebase on new IW4x releases. |
| **What's different** | Up to **32 players** per server (bots included); the scoreboard, minimap, voice, clan tags, card titles and server browser all handle 32. Joining normal 18-player IW4x servers keeps working. |
| **Goal of v2.0** | **One `iw4x.dll` does everything**: no patched `iw4x.exe`. The engine's 18-player limits are lifted in memory at start-up by the `IW4x32` component - drop the DLL into a normal IW4x install and you have 32-player IW4x. *(in progress)* |
| **Where v1.x lives** | The original binary-patched releases (v1.0-v1.2), installers and the IW4x integration kit: **[shaunypnz/iw4x-32-old](https://github.com/shaunypnz/iw4x-32-old)**. Installed players keep auto-updating; nothing to do. |
| **Branches** | `iw4x-32` (default) = upstream IW4x + IW4x-32. `main` = the updater channel (`latest.json` only). |
| **Releases** | Built by GitHub Actions from version tags (`v2.0`, ...): `IW4x-32-<version>.zip` + `iw4x.dll`. |

### For the IW4x team
Every change is tagged `IW4x-32:` in the source; the engine changes are described entry by entry in
[`iw4x32/reference/`](iw4x32/reference/README.md) (the patch tables, each tagged `role: client` or `role: server`).
Everything here is GPL-3.0, like IW4x - take whatever is useful.

Credits: the IW4x team for IW4x; IW4x-32 by shaunypnz (see the original repo's AI_CREDITS.txt).

---

*Upstream IW4x README follows.*

![license](https://img.shields.io/github/license/iw4x/iw4x-client.svg)
[![build](https://github.com/iw4x/iw4x-client/actions/workflows/build.yml/badge.svg?branch=develop)](https://github.com/iw4x/iw4x-client/actions)

# IW4x: Client

<img src=".github/assets/readme/icon.png" align="right" width="100" height="100">

IW4x is a community-driven project that aims to revitalize and enhance the [Call of Duty: Modern Warfare 2 (2009)](https://store.steampowered.com/app/10180/Call_of_Duty_Modern_Warfare_2_2009/) multiplayer experience by providing a stable platform with support for dedicated servers and modding.

A [__Steam__](https://store.steampowered.com/app/10180/Call_of_Duty_Modern_Warfare_2_2009/) installation of Modern Warfare 2 is required to run IW4x, copies from the Microsoft Store are **not compatible**.

IW4x is distributed through the [IW4x Launcher](https://github.com/iw4x/launcher).

## Compiling from Source

> [!IMPORTANT]
> **Clone** the git repository instead of downloading the ZIP, as the latter will not work.

1. Clone the repository - `git clone https://github.com/iw4x/iw4x-client.git`
2. Run `generate.bat` to initialize and update submodules and generate the Visual Studio solution
3. Open/build the generated solution file `build\iw4x.sln` with Visual Studio

To use the `iw4x.dll`, you must have a valid Modern Warfare 2 installation with the [IW4x Rawfiles](https://github.com/iw4x/iw4x-rawfiles) installed.

<details>
<summary>Development Setup</summary>

### Build to MW2 Directory

1. Right-click the IW4x solution in Visual Studio
2. Select Properties
3. Set the output directory to your MW2 install path

![](.github/assets/readme/output_directory.png)

### Setup Debugger

1. Right-click the IW4x solution in Visual Studio
2. Select Properties
3. Select Debugging
4. Set the Command value to the path of your `iw4x.exe` inside your MW2 game files

> Tip:
> - Switch to Windowed mode in-game, as breakpoints will lock the window.
> - Pressing `F5` will launch the game and attach the debugger.
> - The default hotkey for stopping the debugger is `Shift+F5`.

![](.github/assets/readme/debug_command.png)
</details>

## Premake arguments

| Argument                    | Description                                    |
|:----------------------------|:-----------------------------------------------|
| `--copy-to=PATH`            | Optional, copy the DLL to a custom folder after build, define the path here if wanted. |
| `--copy-pdb`                | Copy debug information for binaries as well to the path given via --copy-to. |
| `--disable-binary-check`    | Do not perform integrity checks on the exe. |

## Command line arguments

| Argument                | Description                                    |
|:------------------------|:-----------------------------------------------|
| `-entries`              | Print to the console a list of every asset as they are loaded from zonefiles. |
| `-stdout`               | Redirect all logging output to the terminal iw4x is started from, or if there is none, creates a new terminal window to write log information in. |
| `-console`              | Allow the game to display its own separate interactive console window. |
| `-dedicated`            | Starts the game as a headless dedicated server. |
| `-bigminidumps`         | Include all code sections from loaded modules in the dump. |
| `-reallybigminidumps`   | Include data sections from all loaded modules in the dump. |
| `-dump`                 | Write info of loaded assets to the raw folder as they are being loaded. |
| `-nointro`              | Skip game's cinematic intro.                   |
| `-version`              | Print IW4x build info on startup.              |
| `-steam`                | Enable friends feature and other Steam integrations. |
| `-unprotect-dvars`      | Allow the server to modify saved/archive dvars. |
| `-zonebuilder`          | Start the interactive zonebuilder tool console instead of starting the game. |
| `-original-str-parsing` | (ZoneBuilder mode only) Parse .str files in the same manner as the CoD4 Mod Tools. |
| `-disable-notifies`     | Disable "Anti-CFG" checks |
| `-disable-mongoose`     | Disable Mongoose HTTP server |
| `-disable-rate-limit-check` | Disable RCon rate limit checks |
| `-disable-mod-unloading` | Disable automatic mod (fs_game) unloading when disconnecting |

## Disclaimer

This software has been created purely for the purposes of
academic research. It is not intended to be used to attack
other systems. Project maintainers are not responsible or
liable for misuse of the software. Use responsibly.
