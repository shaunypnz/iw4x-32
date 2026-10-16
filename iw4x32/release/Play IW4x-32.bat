@echo off
REM IW4x-32 - start playing. A thin wrapper around "IW4x-32 Launcher.bat --play", so shortcuts and habits
REM made before v2.0 keep working; the launcher is where the modes live (it also takes --vanilla, --server,
REM --vanilla-server, --dry and --no-update). Extra arguments go to the game, e.g.:
REM     "Play IW4x-32.bat" +connect <server address>
REM Skip the version check: "Play IW4x-32 (no update).bat", or set IW4X32_NO_UPDATE=1.
REM One line on purpose: the updater may replace files while it runs.
call "%~dp0IW4x-32 Launcher.bat" --play %*
