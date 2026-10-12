@echo off
setlocal EnableExtensions
title IW4x-32 - install
REM =====================================================================================
REM  Install IW4x-32 v2.0 (32-player IW4x).  Put this IW4x-32 folder INSIDE your
REM  MW2 / IW4x game folder (the folder that has iw4x.exe), then double-click this file.
REM
REM  What it does (plain cmd + certutil, nothing downloaded, nothing else touched):
REM   1. checks your iw4x.dll is the OFFICIAL IW4x r5154 file (SHA-256)
REM   2. copies it to IW4x-32\backup\
REM   3. copies IW4x-32\files\iw4x.dll into the game folder and checks it
REM
REM  IW4x-32 v2.0 is ONE file: your iw4x.exe stays the official IW4x one - the DLL lifts
REM  the 18-player limits in memory when the game starts.  If an older IW4x-32 (v1.x)
REM  replaced your iw4x.exe, the official one is put back from IW4x-32\backup\ first.
REM  Undo any time: "Uninstall IW4x-32.bat".  What changes and why: CHANGES.txt.
REM =====================================================================================
set "OFFICIAL_EXE=49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009"
set "OFFICIAL_DLL=82819f1a0c8e3758af8acb8773dc2e2f5cc069202b995e79772a23c9551236cd"
set "OURS_DLL=0d8a8f630df43d25babb847b08f74c9a416a2e05c9336dd40ad0a15460ad9c7c"
set "V1_EXE=2609c2687dd2ffb3f32c7687ed04f57b38ef6879c14b1c546faf8bfd8f35ea6b"
for %%I in ("%~dp0.") do set "KIT=%%~fI"
for %%I in ("%~dp0..") do set "GAME=%%~fI"
echo IW4x-32 install
echo   game folder: %GAME%
echo.
if not exist "%GAME%\iw4x.exe" goto :nogame
if not exist "%KIT%\files\iw4x.dll" goto :nokit
tasklist /fi "imagename eq iw4x.exe" 2>nul | find /i "iw4x.exe" >nul && goto :running

call :sha "%GAME%\iw4x.exe" EXE_NOW
call :sha "%GAME%\iw4x.dll" DLL_NOW
if /i "%DLL_NOW%"=="%OURS_DLL%" if /i not "%EXE_NOW%"=="%V1_EXE%" (
    echo IW4x-32 is already installed. Start the game with "Play IW4x-32.bat".
    goto :end
)
echo [1/3] Checking your current IW4x files ...
if /i not "%DLL_NOW%"=="%OFFICIAL_DLL%" if /i not "%DLL_NOW%"=="%OURS_DLL%" goto :notofficial
echo        OK - official IW4x r5154

echo [2/3] Backing up to IW4x-32\backup\ ...
if not exist "%KIT%\backup" mkdir "%KIT%\backup"
if /i "%DLL_NOW%"=="%OFFICIAL_DLL%" copy /y "%GAME%\iw4x.dll" "%KIT%\backup\iw4x.dll" >nul || goto :copyfail
if /i "%EXE_NOW%"=="%V1_EXE%" call :restore_v1_exe || goto :end

echo [3/3] Installing IW4x-32 ...
copy /y "%KIT%\files\iw4x.dll" "%GAME%\iw4x.dll" >nul || goto :copyfail
call :sha "%GAME%\iw4x.dll" DLL_NOW
if /i not "%DLL_NOW%"=="%OURS_DLL%" goto :verifyfail
echo.
echo  Done. IW4x-32 is installed.
echo   - Start the game with "Play IW4x-32.bat". Do NOT use the IW4x launcher's normal
echo     start: its file check puts the official 18-player iw4x.dll back.
echo   - 32-player servers now show in the server browser. Normal IW4x servers still work.
echo   - Undo any time: "Uninstall IW4x-32.bat".
goto :end

:sha
set "%2="
for /f "skip=1 tokens=* delims=" %%a in ('certutil -hashfile "%~1" SHA256 2^>nul') do if not defined %2 set "%2=%%a"
call set "%2=%%%2: =%%"
exit /b 0

:restore_v1_exe
REM an IW4x-32 v1.x install put its own iw4x.exe in the game folder; v2.0 does not need it
call :sha "%KIT%\backup\iw4x.exe" EXE_BAK
if /i not "%EXE_BAK%"=="%OFFICIAL_EXE%" goto :rv_no
echo        an older IW4x-32 replaced iw4x.exe - putting your official one back
copy /y "%KIT%\backup\iw4x.exe" "%GAME%\iw4x.exe" >nul || goto :rv_no
exit /b 0

:rv_no
REM a called routine must exit /b, never goto :end - the caller would carry on installing after the message
REM (that is how a v1.x exe without a usable backup used to end up with iw4x.dll installed anyway)
echo.
echo  STOPPED: an older IW4x-32 replaced your iw4x.exe and this folder has no backup of it.
echo   - Run the official IW4x launcher once: it repairs iw4x.exe. Then install again.
echo  Nothing was changed.
exit /b 1

:nogame
echo ERROR: no iw4x.exe in "%GAME%".
echo        Put the IW4x-32 folder INSIDE your MW2/IW4x game folder and run this again.
goto :end
:nokit
echo ERROR: IW4x-32\files\iw4x.dll is missing - extract the whole zip again.
goto :end
:running
echo ERROR: IW4x is running. Close the game and run this again.
goto :end
:notofficial
echo.
echo  STOPPED: your iw4x.dll is not the official IW4x r5154 file.
echo   - If IW4x was updated since this release, wait for a matching IW4x-32 update.
echo   - If you modded it yourself, run the IW4x launcher once to repair, then try again.
echo  Nothing was changed.
goto :end
:copyfail
echo ERROR: copying failed - is the game running? If the game is under "Program Files", right-click
echo        "Install IW4x-32.bat" and choose "Run as administrator". To undo, run "Uninstall IW4x-32.bat".
goto :end
:verifyfail
echo ERROR: the installed iw4x.dll does not match IW4x-32\files (antivirus?). Run "Uninstall IW4x-32.bat" to restore.
goto :end
:end
echo.
pause
