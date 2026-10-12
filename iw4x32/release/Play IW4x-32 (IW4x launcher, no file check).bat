@echo off
setlocal EnableExtensions
title IW4x-32 - play through the IW4x launcher
REM Fallback if "Play IW4x-32.bat" does not start the game: runs the OFFICIAL IW4x launcher with its own options
REM   --skip-remote      "Skip all remote checks and file reconciliation"  (keeps the IW4x-32 iw4x.dll)
REM   --no-self-update   "Skip the automatic launcher self-update check"
REM and afterwards checks the IW4x-32 iw4x.dll is still installed.
set "OURS_DLL=0d8a8f630df43d25babb847b08f74c9a416a2e05c9336dd40ad0a15460ad9c7c"
for %%I in ("%~dp0..") do set "GAME=%%~fI"
set "L="
if exist "%GAME%\iw4x-launcher.exe" set "L=%GAME%\iw4x-launcher.exe"
if not defined L if exist "%GAME%\iw4x-launcher-x86.exe" set "L=%GAME%\iw4x-launcher-x86.exe"
if not defined L (echo The IW4x launcher was not found in "%GAME%". & pause & exit /b 1)
cd /d "%GAME%"
echo Starting the IW4x launcher without file checks or updates ...
"%L%" --skip-remote --no-self-update %*
call :sha "%GAME%\iw4x.dll" DLL_NOW
if /i "%DLL_NOW%"=="%OURS_DLL%" (echo IW4x-32 is still installed. & exit /b 0)
echo.
echo WARNING: the IW4x launcher replaced iw4x.dll with the official 18-player one.
echo          Run "Install IW4x-32.bat" again and start the game with "Play IW4x-32.bat".
pause
exit /b 1

:sha
set "%2="
for /f "skip=1 tokens=* delims=" %%a in ('certutil -hashfile "%~1" SHA256 2^>nul') do if not defined %2 set "%2=%%a"
call set "%2=%%%2: =%%"
exit /b 0
