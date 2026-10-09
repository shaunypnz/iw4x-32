@echo off
REM Starts IW4x-32. First iw4x32_update.ps1 brings IW4x + IW4x-32 to the newest tested pair: it downloads only when a
REM new IW4x-32 release is out, checks every file's SHA-256, never updates IW4x past what IW4x-32 supports, and puts
REM IW4x-32 back if the IW4x launcher replaced it. Then it starts iw4x.exe like the official IW4x launcher does.
REM Skip the update: set IW4X32_NO_UPDATE=1, or use "Play IW4x-32 (no update).bat".
REM Extra arguments go to the game, e.g.:  "Play IW4x-32.bat" +connect <server address>
REM The next line is the whole script on purpose: the updater may replace this file while it runs.
(powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0iw4x32_update.ps1" %* || (echo. & echo IW4x-32 could not start - try "Play IW4x-32 (no update).bat" & pause)) & exit /b
