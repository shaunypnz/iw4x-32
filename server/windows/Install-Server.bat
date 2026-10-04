@echo off
setlocal EnableExtensions
title IW4x-32 server - install
REM =====================================================================================
REM  Install the IW4x-32 SERVER build (hosts 32-player servers, also plays).  Put the IW4x-32-server folder INSIDE your
REM  MW2 / IW4x game folder (the folder that has iw4x.exe), then double-click windows\Install-Server.bat.
REM
REM  What it does (plain cmd + certutil, nothing downloaded, nothing else touched):
REM   1. checks your iw4x.exe and iw4x.dll are the OFFICIAL IW4x r5154 files (SHA-256)
REM   2. copies them to IW4x-32-server\backup\
REM   3. copies IW4x-32-server\files\iw4x.exe and iw4x.dll into the game folder and checks them
REM  Undo: windows\Uninstall-Server.bat.  Every changed byte is listed in source\manifest_*.json.
REM =====================================================================================
set "OFFICIAL_EXE=49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009"
set "OFFICIAL_DLL=82819f1a0c8e3758af8acb8773dc2e2f5cc069202b995e79772a23c9551236cd"
set "OURS_EXE=e692442e7d9a33108aa69472b459b024f4a4fff25fc437fbe996920d2d502424"
set "OURS_DLL=4809ef276852e8c41de027298499546789cb0612abb20b5f13e9b800e2cd6fba"
for %%I in ("%~dp0..") do set "KIT=%%~fI"
for %%I in ("%~dp0..\..") do set "GAME=%%~fI"
echo IW4x-32 SERVER install
echo   game folder: %GAME%
echo.
if not exist "%GAME%\iw4x.exe" goto :nogame
if not exist "%KIT%\files\iw4x.exe" goto :nokit
if not exist "%KIT%\files\iw4x.dll" goto :nokit
tasklist /fi "imagename eq iw4x.exe" 2>nul | find /i "iw4x.exe" >nul && goto :running

call :sha "%GAME%\iw4x.exe" EXE_NOW
call :sha "%GAME%\iw4x.dll" DLL_NOW
if /i "%EXE_NOW%"=="%OURS_EXE%" if /i "%DLL_NOW%"=="%OURS_DLL%" (
    echo The IW4x-32 server build is already installed.
    goto :end
)
echo [1/3] Checking your current IW4x files ...
if /i not "%EXE_NOW%"=="%OFFICIAL_EXE%" goto :notofficial
if /i not "%DLL_NOW%"=="%OFFICIAL_DLL%" goto :notofficial
echo        OK - official IW4x r5154 iw4x.exe and iw4x.dll

echo [2/3] Backing up to IW4x-32-server\backup\ ...
if not exist "%KIT%\backup" mkdir "%KIT%\backup"
copy /y "%GAME%\iw4x.exe" "%KIT%\backup\iw4x.exe" >nul || goto :copyfail
copy /y "%GAME%\iw4x.dll" "%KIT%\backup\iw4x.dll" >nul || goto :copyfail

echo [3/3] Installing the IW4x-32 server build ...
copy /y "%KIT%\files\iw4x.exe" "%GAME%\iw4x.exe" >nul || goto :copyfail
copy /y "%KIT%\files\iw4x.dll" "%GAME%\iw4x.dll" >nul || goto :copyfail
call :sha "%GAME%\iw4x.exe" EXE_NOW
call :sha "%GAME%\iw4x.dll" DLL_NOW
if /i not "%EXE_NOW%"=="%OURS_EXE%" goto :verifyfail
if /i not "%DLL_NOW%"=="%OURS_DLL%" goto :verifyfail
echo.
echo  Done. The IW4x-32 server build is installed.
echo   - Create userraw\server.cfg (see IW4x-32-server\README.md - set an rcon password!),
echo     then start the server with windows\Start-Server.bat. Do NOT run the IW4x launcher/updater:
echo     it puts the official 18-player files back.
echo   - The same files also play as a normal client (32-player and normal IW4x servers).
echo   - Undo any time: windows\Uninstall-Server.bat
goto :end

:sha
set "%2="
for /f "skip=1 tokens=* delims=" %%a in ('certutil -hashfile "%~1" SHA256 2^>nul') do if not defined %2 set "%2=%%a"
call set "%2=%%%2: =%%"
exit /b 0

:nogame
echo ERROR: no iw4x.exe in "%GAME%".
echo        Put the IW4x-32-server folder INSIDE your MW2/IW4x game folder and run this again.
goto :end
:nokit
echo ERROR: IW4x-32-server\files\iw4x.exe or iw4x.dll is missing - extract the whole zip again.
goto :end
:running
echo ERROR: IW4x is running. Close the game and run this again.
goto :end
:notofficial
echo.
echo  STOPPED: your iw4x.exe / iw4x.dll are not the official IW4x r5154 files.
echo   - If IW4x was updated since this release, wait for a matching IW4x-32 update.
echo   - If you modded them yourself, run the IW4x launcher once to repair, then try again.
echo  Nothing was changed.
goto :end
:copyfail
echo ERROR: copying failed - is the game running? If the game is under "Program Files", right-click
echo        Install-Server.bat and choose "Run as administrator". To undo, run Uninstall-Server.bat.
goto :end
:verifyfail
echo ERROR: the installed files do not match IW4x-32-server\files (antivirus?). Run Uninstall-Server.bat to restore.
goto :end
:end
echo.
pause
