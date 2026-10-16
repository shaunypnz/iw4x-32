@echo off
setlocal EnableExtensions
title IW4x-32
REM =====================================================================================
REM  IW4x-32 - the one script that starts everything. The shortcuts point here.
REM
REM    IW4x-32 Launcher.bat                    ask what to start (1-4, Enter = last choice)
REM    IW4x-32 Launcher.bat --play             IW4x-32 - 32-player servers (and normal ones)
REM    IW4x-32 Launcher.bat --vanilla          vanilla IW4x - the official IW4x, latest version
REM    IW4x-32 Launcher.bat --server [port]    a 32-player dedicated server, port 28960
REM    IW4x-32 Launcher.bat --vanilla-server [port]  a normal 18-player IW4x server
REM
REM    --dry        only check the install and print the command
REM    --no-update  skip the version check
REM    anything else goes to the game, e.g.  +connect <server address>
REM
REM  "Play IW4x-32.bat" and "Start IW4x-32 Server.bat" are thin wrappers of this file, so
REM  shortcuts and habits made before v2.0 keep working. What you pick is remembered in
REM  IW4x-32\mode.txt. The version check (both GitHub repos, 5 s each, no network = just
REM  start) is done by iw4x32_update.ps1 - the same steps as iw4x32_update.py on Linux.
REM  Lines that start the game are ONE LINE on purpose: the updater may replace this file
REM  while it runs, so nothing may be read from here afterwards. Brackets are kept out of
REM  echoed text inside ( ) blocks for the same reason - cmd.exe cannot echo them there.
REM =====================================================================================
set "OURS_DLL=f0a247ff84e1307330d43a03c4e8e4f8b8f921a465c6206e0b14a825f736a2d1"
for %%I in ("%~dp0.") do set "KIT=%%~fI"
for %%I in ("%~dp0..") do set "GAME=%%~fI"
set "MODE="
set "PORT=28960"
set "DRY="
set "NOUN="

:args
if "%~1"=="" goto :argsdone
if /i "%~1"=="--play" (set "MODE=iw4x32" & shift & goto :args)
if /i "%~1"=="--iw4x32" (set "MODE=iw4x32" & shift & goto :args)
if /i "%~1"=="--vanilla" (set "MODE=vanilla" & shift & goto :args)
if /i "%~1"=="--server" (set "MODE=server" & shift & goto :args)
if /i "%~1"=="--vanilla-server" (set "MODE=vanilla-server" & shift & goto :args)
if /i "%~1"=="--dry" (set "DRY=1" & shift & goto :args)
if /i "%~1"=="--dry-run" (set "DRY=1" & shift & goto :args)
if /i "%~1"=="--no-update" (set "NOUN=1" & shift & goto :args)
REM a bare number is the server port, everything else is an argument for the game
set "A=%~1"
set "NOTNUM="
for /f "delims=0123456789" %%c in ("%A%") do set "NOTNUM=1"
if not defined NOTNUM if defined A (set "PORT=%A%" & shift & goto :args)
shift
goto :args

:argsdone
if defined NOUN set "IW4X32_NO_UPDATE=1"
set "IW4X32_KEEP_MODE=1"
if defined MODE goto :start

REM ---- nothing was asked for: the menu (5 s, Enter = what was started last time) -------------------------------
set "LAST="
if exist "%KIT%\mode.txt" for /f "usebackq tokens=1" %%a in ("%KIT%\mode.txt") do if not defined LAST set "LAST=%%a"
set "KNOWN="
for %%m in (iw4x32 vanilla server vanilla-server) do if /i "%%m"=="%LAST%" set "KNOWN=1"
if not defined KNOWN set "LAST=iw4x32"
if defined NOUN (set "MODE=%LAST%" & goto :start)
if "%IW4X32_NO_MENU%"=="1" (set "MODE=%LAST%" & goto :start)
set "DEF=1"
if /i "%LAST%"=="vanilla" set "DEF=2"
if /i "%LAST%"=="server" set "DEF=3"
if /i "%LAST%"=="vanilla-server" set "DEF=4"
echo Start what?
echo   [1] IW4x-32        - 32-player servers, and normal ones
echo   [2] Vanilla IW4x   - the official IW4x, always the latest version
echo   [3] IW4x-32 server - 32-player dedicated server, port %PORT%
echo   [4] IW4x server    - normal 18-player server, port %PORT%
choice /c 1234 /n /t 5 /d %DEF% /m "Enter = %LAST%, starts in 5 s: "
if errorlevel 5 goto :menu_prompt
if errorlevel 4 set "MODE=vanilla-server"
if errorlevel 3 if not defined MODE set "MODE=server"
if errorlevel 2 if not defined MODE set "MODE=vanilla"
if not defined MODE set "MODE=iw4x32"
goto :picked

:menu_prompt
REM no "choice" program on this Windows - ask the plain way
set "ANSWER="
set /p "ANSWER=Start what? 1-4, Enter = %LAST%: "
if "%ANSWER%"=="1" set "MODE=iw4x32"
if "%ANSWER%"=="2" set "MODE=vanilla"
if "%ANSWER%"=="3" set "MODE=server"
if "%ANSWER%"=="4" set "MODE=vanilla-server"
if not defined MODE set "MODE=%LAST%"

:picked
> "%KIT%\mode.txt" echo %MODE%

:start
if "%MODE%"=="vanilla" goto :vanilla
if "%MODE%"=="server" (set "SLOTS=32" & set "CFG=server_iw4x32.cfg" & set "LABEL=IW4x-32 server" & goto :server)
if "%MODE%"=="vanilla-server" (set "SLOTS=18" & set "CFG=server_vanilla.cfg" & set "LABEL=IW4x server - vanilla, 18 players" & goto :vserver)
if defined DRY goto :dry_play
(powershell -NoProfile -ExecutionPolicy Bypass -File "%KIT%\iw4x32_update.ps1" --iw4x32 %* || (echo. & echo IW4x-32 could not start - try "Play IW4x-32 (no update).bat" & pause)) & exit /b

:vanilla
if defined DRY goto :dry_vanilla
(powershell -NoProfile -ExecutionPolicy Bypass -File "%KIT%\iw4x32_update.ps1" --vanilla %* || echo IW4x did not start - is the official IW4x launcher in "%GAME%"?) & exit /b

:server
REM --dry and --no-update start straight away; otherwise the updater runs first and a fresh run of this
REM file (same line, --no-update) starts the server - the updater may replace this file while it runs
if defined NOUN goto :server_run
if defined DRY goto :server_run
(set "IW4X32_NO_START=1" & powershell -NoProfile -ExecutionPolicy Bypass -File "%KIT%\iw4x32_update.ps1" --iw4x32 & call "%~f0" %* --no-update) & exit /b

:vserver
REM a vanilla server runs the official IW4x dll: put it back first, the same rule the vanilla game start follows
call :sha "%GAME%\iw4x.dll" DLL_NOW
if /i "%DLL_NOW%"=="%OURS_DLL%" if exist "%KIT%\backup\iw4x.dll" (
    echo Putting the official IW4x iw4x.dll back from IW4x-32\backup\ ...
    copy /y "%KIT%\backup\iw4x.dll" "%GAME%\iw4x.dll" >nul
)
goto :server_run

:server_run
REM SLOTS / CFG / LABEL are set by the :start dispatch above
if not exist "%GAME%\iw4x.exe" goto :nogame
if "%SLOTS%"=="32" (
    call :sha "%GAME%\iw4x.dll" DLL_NOW
    if /i not "%DLL_NOW%"=="%OURS_DLL%" goto :notinstalled
)
if not exist "%GAME%\userraw" mkdir "%GAME%\userraw"
if not exist "%GAME%\userraw\%CFG%" (
    copy /y "%KIT%\server\%CFG%" "%GAME%\userraw\%CFG%" >nul || goto :copyfail
    echo Made userraw\%CFG% - edit it to name your server and set an rcon password.
)
set "CMD=iw4x.exe -dedicated -stdout +set net_port %PORT% +exec %CFG% +set sv_maxclients %SLOTS% +set party_maxplayers %SLOTS% +set party_enable 0 +map_rotate"
echo %LABEL%
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

:dry_play
echo IW4x-32
echo   game folder: %GAME%
echo   command:     iw4x.exe %*
echo   before that: iw4x32_update.ps1 checks both GitHub repos and installs a new IW4x-32 when one is out
goto :end

:dry_vanilla
echo Vanilla IW4x
echo   game folder: %GAME%
echo   command:     "%GAME%\iw4x-launcher.exe" - the official IW4x launcher updates IW4x and starts the game
echo   before that: IW4x-32's iw4x.dll is put back to the official one from IW4x-32\backup\
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
echo ERROR: could not create userraw\%CFG% - is the game folder under "Program Files"?
echo        Right-click this file and choose "Run as administrator".
goto :end
:end
if not defined DRY pause
endlocal
