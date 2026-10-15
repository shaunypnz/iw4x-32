@echo off
setlocal EnableExtensions
title IW4x-32 - 32-player dedicated server
REM =====================================================================================
REM  Start an IW4x-32 dedicated server (up to 32 players, bots included).
REM  First run "Install IW4x-32.bat" (same as for playing), then double-click this file.
REM
REM    Start IW4x-32 Server.bat           port 28960
REM    Start IW4x-32 Server.bat 28961     another port (one port per server)
REM    Start IW4x-32 Server.bat --dry     only check the install and print the command
REM
REM  Your settings: the game folder's userraw\server_iw4x32.cfg (made from server\server_iw4x32.cfg
REM  on the first start - set the server name and an rcon password there).
REM  Players on the internet: forward the port (UDP) on your router to this PC.
REM  Add bots: in the server console type  spawnBot 10
REM =====================================================================================
set "OURS_DLL=f0a247ff84e1307330d43a03c4e8e4f8b8f921a465c6206e0b14a825f736a2d1"
for %%I in ("%~dp0.") do set "KIT=%%~fI"
for %%I in ("%~dp0..") do set "GAME=%%~fI"
set "DRY="
if /i "%~1"=="--dry" (set "DRY=1" & shift)
set "PORT=%~1"
if "%PORT%"=="" set "PORT=28960"
if not exist "%GAME%\iw4x.exe" goto :nogame
call :sha "%GAME%\iw4x.dll" DLL_NOW
if /i not "%DLL_NOW%"=="%OURS_DLL%" goto :notinstalled
if not exist "%GAME%\userraw" mkdir "%GAME%\userraw"
if not exist "%GAME%\userraw\server_iw4x32.cfg" (
    copy /y "%KIT%\server\server_iw4x32.cfg" "%GAME%\userraw\server_iw4x32.cfg" >nul || goto :copyfail
    echo Made userraw\server_iw4x32.cfg - edit it to name your server and set an rcon password.
)
set "CMD=iw4x.exe -dedicated -stdout +set net_port %PORT% +exec server_iw4x32.cfg +set sv_maxclients 32 +set party_maxplayers 32 +set party_enable 0 +map_rotate"
echo IW4x-32 server
echo   game folder: %GAME%
echo   port:        %PORT% (UDP)
echo   command:     %CMD%
if defined DRY goto :end
echo.
cd /d "%GAME%"
%CMD%
echo.
echo The server stopped.
goto :end

:sha
set "%2="
for /f "skip=1 tokens=* delims=" %%a in ('certutil -hashfile "%~1" SHA256 2^>nul') do if not defined %2 set "%2=%%a"
call set "%2=%%%2: =%%"
exit /b 0

:nogame
echo ERROR: no iw4x.exe in "%GAME%".
echo        Put the IW4x-32 folder INSIDE your MW2/IW4x game folder and run this again.
goto :end
:notinstalled
echo ERROR: IW4x-32 is not installed in "%GAME%" (its iw4x.dll is not the IW4x-32 one).
echo        Run "Install IW4x-32.bat" first, then start the server again.
goto :end
:copyfail
echo ERROR: could not create userraw\server_iw4x32.cfg - is the game folder under "Program Files"?
echo        Right-click this file and choose "Run as administrator".
goto :end
:end
if not defined DRY pause
endlocal
