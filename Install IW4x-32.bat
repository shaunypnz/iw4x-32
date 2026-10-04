@echo off
setlocal EnableExtensions
title IW4x-32 - install
REM =====================================================================================
REM  Install IW4x-32 (32-player IW4x client).  Put this IW4x-32 folder INSIDE your
REM  MW2 / IW4x game folder (the folder that has iw4x.exe), then double-click this file.
REM
REM  What it does (plain cmd + certutil, nothing downloaded, nothing else touched):
REM   1. checks your iw4x.exe and iw4x.dll are the OFFICIAL IW4x r5154 files (SHA-256)
REM   2. copies them to IW4x-32\backup\
REM   3. copies IW4x-32\files\iw4x.exe and iw4x.dll into the game folder and checks them
REM  Undo: "Uninstall IW4x-32.bat".  Every changed byte is listed in CHANGES.txt.
REM =====================================================================================
set "OFFICIAL_EXE=49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009"
set "OFFICIAL_DLL=82819f1a0c8e3758af8acb8773dc2e2f5cc069202b995e79772a23c9551236cd"
set "OURS_EXE=2609c2687dd2ffb3f32c7687ed04f57b38ef6879c14b1c546faf8bfd8f35ea6b"
set "OURS_DLL=57f1189ebfcb6a6acc7338311e862a7fa0974a5242c5991e6f1267a17afb3cef"
for %%I in ("%~dp0.") do set "KIT=%%~fI"
for %%I in ("%~dp0..") do set "GAME=%%~fI"
echo IW4x-32 install
echo   game folder: %GAME%
echo.
if not exist "%GAME%\iw4x.exe" goto :nogame
if not exist "%KIT%\files\iw4x.exe" goto :nokit
if not exist "%KIT%\files\iw4x.dll" goto :nokit
tasklist /fi "imagename eq iw4x.exe" 2>nul | find /i "iw4x.exe" >nul && goto :running

call :sha "%GAME%\iw4x.exe" EXE_NOW
call :sha "%GAME%\iw4x.dll" DLL_NOW
if /i "%EXE_NOW%"=="%OURS_EXE%" if /i "%DLL_NOW%"=="%OURS_DLL%" (
    echo IW4x-32 is already installed. Start the game with "Play IW4x-32.bat".
    goto :end
)
echo [1/3] Checking your current IW4x files ...
if /i not "%EXE_NOW%"=="%OFFICIAL_EXE%" goto :notofficial
if /i not "%DLL_NOW%"=="%OFFICIAL_DLL%" goto :notofficial
echo        OK - official IW4x r5154 iw4x.exe and iw4x.dll

echo [2/3] Backing up to IW4x-32\backup\ ...
if not exist "%KIT%\backup" mkdir "%KIT%\backup"
copy /y "%GAME%\iw4x.exe" "%KIT%\backup\iw4x.exe" >nul || goto :copyfail
copy /y "%GAME%\iw4x.dll" "%KIT%\backup\iw4x.dll" >nul || goto :copyfail

echo [3/3] Installing IW4x-32 ...
copy /y "%KIT%\files\iw4x.exe" "%GAME%\iw4x.exe" >nul || goto :copyfail
copy /y "%KIT%\files\iw4x.dll" "%GAME%\iw4x.dll" >nul || goto :copyfail
call :sha "%GAME%\iw4x.exe" EXE_NOW
call :sha "%GAME%\iw4x.dll" DLL_NOW
if /i not "%EXE_NOW%"=="%OURS_EXE%" goto :verifyfail
if /i not "%DLL_NOW%"=="%OURS_DLL%" goto :verifyfail
echo.
echo  Done. IW4x-32 is installed.
echo   - Start the game with "Play IW4x-32.bat" (or iw4x.exe). Do NOT use the IW4x
echo     launcher/updater: it puts the official 18-player files back.
echo   - 32-player servers now show in the server browser. Normal IW4x servers still work.
echo   - Undo any time: "Uninstall IW4x-32.bat".
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
:nokit
echo ERROR: IW4x-32\files\iw4x.exe or iw4x.dll is missing - extract the whole zip again.
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
echo        "Install IW4x-32.bat" and choose "Run as administrator". To undo, run "Uninstall IW4x-32.bat".
goto :end
:verifyfail
echo ERROR: the installed files do not match IW4x-32\files (antivirus?). Run "Uninstall IW4x-32.bat" to restore.
goto :end
:end
echo.
pause
