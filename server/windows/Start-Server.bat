@echo off
setlocal EnableExtensions
title IW4x-32 dedicated server
REM Starts a 32-player IW4x-32 dedicated server. Needs your own userraw\server.cfg (see README.md).
REM Change PORT / SLOTS below if you like. Forward UDP %PORT% on your router.
set "PORT=28960"
set "SLOTS=32"
for %%I in ("%~dp0..\..") do set "GAME=%%~fI"
if not exist "%GAME%\iw4x.exe" (echo iw4x.exe not found in "%GAME%". & pause & exit /b 1)
if not exist "%GAME%\userraw\server.cfg" (echo Missing "%GAME%\userraw\server.cfg" - create it first, see IW4x-32-server\README.md. & pause & exit /b 1)
cd /d "%GAME%"
start "IW4x-32 server" "%GAME%\iw4x.exe" -dedicated +set sv_lanonly 0 +set net_port %PORT% +exec server.cfg +set sv_maxclients %SLOTS% +set party_maxplayers %SLOTS% +set party_enable 0 +map_rotate
