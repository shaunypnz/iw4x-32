@echo off
setlocal EnableExtensions
title IW4x-32 - setup
REM =====================================================================================
REM  IW4x-32 v2.0 - one-click setup. Run this from the folder you extracted; the kit does
REM  NOT have to be inside the game folder yet.
REM
REM    "IW4x-32 Setup.bat"                       find your MW2 folder and set everything up
REM    "IW4x-32 Setup.bat" "D:\Steam\...\Modern Warfare 2"   use this game folder
REM    "IW4x-32 Setup.bat" --no-shortcuts        do not make shortcuts
REM
REM  What it does, in order:
REM   1. finds the MW2 multiplayer folder: this folder's parent when it has iw4mp.exe /
REM      iw2mp.exe / iw4x.exe, then your Steam libraries (the Steam folder from the
REM      registry and every library in steamapps\libraryfolders.vdf). Several: pick one
REM      by number. None: type the path - Enter stops with nothing changed.
REM   2. copies this folder to <game>\IW4x-32
REM   3. official IW4x missing, or not the version this kit is made for: the OFFICIAL
REM      IW4x launcher installs it (iw4x32_update.ps1 --install-official: downloaded from
REM      its GitHub release, SHA-256 checked, run with --skip-launch). IW4x-32 never
REM      downloads IW4x's own files - the official launcher does that.
REM   4. runs "Install IW4x-32.bat" - the installer itself, not a copy of it
REM   5. makes four shortcuts (Desktop and Start Menu): IW4x-32, vanilla IW4x, and the
REM      two servers, then prints what it did. --no-shortcuts skips that.
REM  Nothing is downloaded when official IW4x is already in place.
REM =====================================================================================
set "OFFICIAL_VER=r5168"
set "OFFICIAL_DLL=e0d8adc473f04f2d0988cffec3ecb8128e9faeba1e169c0acb13118d29aff6ea"
set "OURS_DLL=f0a247ff84e1307330d43a03c4e8e4f8b8f921a465c6206e0b14a825f736a2d1"
for %%I in ("%~dp0.") do set "KIT=%%~fI"
set "NOSHORT="
set "GAME="

:args
if "%~1"=="" goto :argsdone
if /i "%~1"=="--no-shortcuts" (set "NOSHORT=1" & shift & goto :args)
if /i "%~1"=="--shortcuts" (set "NOSHORT=" & shift & goto :args)
if not defined GAME set "GAME=%~1"
shift
goto :args

:argsdone
if defined GAME goto :havegame

REM ---- 1. where is the game? ----------------------------------------------------------------------------------
set "N=0"
set "C1="
set "C2="
set "C3="
set "C4="
set "C5="
set "C6="
call :check "%KIT%\.."
set "STEAMPATH="
for /f "tokens=2,*" %%a in ('reg query "HKCU\Software\Valve\Steam" /v SteamPath 2^>nul ^| find /i "SteamPath"') do set "STEAMPATH=%%b"
if defined STEAMPATH call :check "%STEAMPATH%\steamapps\common\Call of Duty Modern Warfare 2"
if defined STEAMPATH for /f "usebackq tokens=2,*" %%a in (`findstr /i path "%STEAMPATH%\steamapps\libraryfolders.vdf" 2^>nul`) do call :check "%%~a\steamapps\common\Call of Duty Modern Warfare 2"
if "%N%"=="0" goto :ask
if not "%N%"=="1" goto :many
set "GAME=%C1%"
echo Found Modern Warfare 2: %C1%
goto :havegame

:many
echo Found Modern Warfare 2 in more than one place:
if defined C1 echo   [1] %C1%
if defined C2 echo   [2] %C2%
if defined C3 echo   [3] %C3%
if defined C4 echo   [4] %C4%
if defined C5 echo   [5] %C5%
if defined C6 echo   [6] %C6%
set "ANSWER="
set /p "ANSWER=Which one? Enter = 1, 0 = stop, nothing is changed: "
if "%ANSWER%"=="" set "ANSWER=1"
set "GAME="
if "%ANSWER%"=="1" set "GAME=%C1%"
if "%ANSWER%"=="2" set "GAME=%C2%"
if "%ANSWER%"=="3" set "GAME=%C3%"
if "%ANSWER%"=="4" set "GAME=%C4%"
if "%ANSWER%"=="5" set "GAME=%C5%"
if "%ANSWER%"=="6" set "GAME=%C6%"
if not defined GAME goto :stop
goto :havegame

:ask
echo I could not find Modern Warfare 2 - no iw4mp.exe next to this folder or in your Steam libraries.
set "GAME="
set /p "GAME=Type the path of your MW2 folder, Enter = stop, nothing is changed: "
if not defined GAME goto :stop

:havegame
if exist "%GAME%\iw4mp.exe" goto :found
if exist "%GAME%\iw2mp.exe" goto :found
if exist "%GAME%\iw4x.exe" goto :found
echo ERROR: no iw4mp.exe, iw2mp.exe or iw4x.exe in "%GAME%" - nothing was changed.
goto :fail
:found
for %%I in ("%GAME%") do set "GAME=%%~fI"
set "DEST=%GAME%\IW4x-32"
echo   game folder: %GAME%

REM ---- 2. the kit goes into the game folder -------------------------------------------------------------------
if /i "%DEST%"=="%KIT%" goto :official
echo Copying the IW4x-32 folder to %DEST% ...
if not exist "%DEST%" mkdir "%DEST%"
xcopy "%KIT%\*" "%DEST%\" /E /I /Y /Q >nul || goto :copyfail

REM ---- 3. official IW4x, with the official launcher -----------------------------------------------------------
:official
call :sha "%GAME%\iw4x.dll" DLL_NOW
if /i "%DLL_NOW%"=="%OFFICIAL_DLL%" goto :official_ok
if /i "%DLL_NOW%"=="%OURS_DLL%" goto :official_ok
call :sha "%DEST%\backup\iw4x.dll" BAK_NOW
if /i "%BAK_NOW%"=="%OFFICIAL_DLL%" goto :official_ok
echo Official IW4x %OFFICIAL_VER% is missing here or is another version - the official launcher fixes that.
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\iw4x32_update.ps1" --install-official
call :sha "%GAME%\iw4x.dll" DLL_NOW
if /i "%DLL_NOW%"=="%OFFICIAL_DLL%" goto :official_2
if /i "%DLL_NOW%"=="%OURS_DLL%" goto :official_2
echo        it is still not the official IW4x %OFFICIAL_VER% file - the installer below says what to do
goto :install
:official_2
echo        OK - official IW4x is in place
:official_ok

REM ---- 4. install IW4x-32 (the installer itself does it) ------------------------------------------------------
:install
set "IW4X32_QUIET=1"
call "%DEST%\Install IW4x-32.bat"
set "IW4X32_QUIET="
call :sha "%GAME%\iw4x.dll" DLL_NOW
if /i not "%DLL_NOW%"=="%OURS_DLL%" goto :installfail

REM ---- 5. shortcuts ---------------------------------------------------------------------------------------------
if defined NOSHORT goto :summary
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $k='%DEST%'; $w=New-Object -ComObject WScript.Shell; $d=[Environment]::GetFolderPath('Desktop'); $p=Join-Path ([Environment]::GetFolderPath('Programs')) 'IW4x-32'; New-Item -ItemType Directory -Force -Path $p | Out-Null; foreach($t in @('IW4x-32 - 32 players|--play','IW4x - vanilla|--vanilla','IW4x-32 Server|--server','IW4x Server - vanilla|--vanilla-server')){ $n=$t.Split('|')[0]; $m=$t.Split('|')[1]; foreach($f in @($d,$p)){ $l=$w.CreateShortcut((Join-Path $f ($n+'.lnk'))); $l.TargetPath=$env:ComSpec; $l.Arguments='/c call \"'+$k+'\IW4x-32 Launcher.bat\" '+$m; $l.WorkingDirectory=$k; $l.Description='IW4x-32'; $l.Save() } }; Write-Host ('  '+$d); Write-Host ('  '+$p)" || goto :shortcutsfail

echo.
echo IW4x-32 is set up.
echo   game folder: %GAME%
echo   IW4x-32:     %DEST%
if defined NOSHORT goto :summary_noshort
echo   shortcuts:   IW4x-32 - 32 players, IW4x - vanilla, IW4x-32 Server, IW4x Server - vanilla
goto :summary_tail
:summary_noshort
echo   shortcuts:   skipped - start it with "%DEST%\IW4x-32 Launcher.bat"
:summary_tail
echo.
echo Play: the "IW4x-32 - 32 players" shortcut, or
echo     "%DEST%\IW4x-32 Launcher.bat"            it asks what to start
echo Host a 32-player server: the "IW4x-32 Server" shortcut, or
echo     "%DEST%\Start IW4x-32 Server.bat"
goto :end

:check
REM one candidate folder: really an MW2 multiplayer folder, and not listed yet -> C1..C6
if not exist "%~1\iw4mp.exe" if not exist "%~1\iw2mp.exe" if not exist "%~1\iw4x.exe" exit /b 0
for %%I in ("%~1") do set "C=%%~fI"
if /i "%C%"=="%C1%" exit /b 0
if /i "%C%"=="%C2%" exit /b 0
if /i "%C%"=="%C3%" exit /b 0
if /i "%C%"=="%C4%" exit /b 0
if /i "%C%"=="%C5%" exit /b 0
if /i "%C%"=="%C6%" exit /b 0
if "%N%"=="6" exit /b 0
set /a N+=1
if "%N%"=="1" set "C1=%C%"
if "%N%"=="2" set "C2=%C%"
if "%N%"=="3" set "C3=%C%"
if "%N%"=="4" set "C4=%C%"
if "%N%"=="5" set "C5=%C%"
if "%N%"=="6" set "C6=%C%"
exit /b 0

:sha
set "%2="
for /f "skip=1 tokens=* delims=" %%a in ('certutil -hashfile "%~1" SHA256 2^>nul') do if not defined %2 set "%2=%%a"
call set "%2=%%%2: =%%"
exit /b 0

:stop
echo Nothing was changed.
goto :end
:installfail
echo.
echo Setup stopped - IW4x-32 is not installed. See the message above; nothing else was changed.
goto :fail
:shortcutsfail
echo.
echo ERROR: the shortcuts could not be made. IW4x-32 itself is installed - start it with
echo        "%DEST%\IW4x-32 Launcher.bat".
goto :fail
:copyfail
echo ERROR: could not copy to "%DEST%" - is the game running? If the game is under "Program
echo        Files", right-click this file and choose "Run as administrator".
goto :fail
:end
echo.
pause
if defined FAIL exit /b 1
exit /b 0
:fail
set "FAIL=1"
goto :end
