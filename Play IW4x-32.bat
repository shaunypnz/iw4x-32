@echo off
setlocal EnableExtensions
REM Starts IW4x-32 the way the official IW4x launcher starts the game - steam_appid.txt (10190) in the game folder
REM and SteamAppId/SteamGameId set, so Steam does not take over and start normal MW2 - but WITHOUT the launcher's
REM file check, which would put the official 18-player files back.
REM Extra arguments are passed on, e.g.:  "Play IW4x-32.bat" +connect <server address>
for %%I in ("%~dp0..") do set "GAME=%%~fI"
if not exist "%GAME%\iw4x.exe" (echo iw4x.exe not found in "%GAME%" - is the IW4x-32 folder inside your game folder? & pause & exit /b 1)
cd /d "%GAME%"
if not exist "%GAME%\steam_appid.txt" (>"%GAME%\steam_appid.txt" echo 10190)
set "SteamAppId=10190"
set "SteamGameId=10190"
start "" "%GAME%\iw4x.exe" %*
