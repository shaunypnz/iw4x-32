@echo off
setlocal EnableExtensions
title IW4x-32 - play through the IW4x launcher
REM Fallback if "Play IW4x-32.bat" does not start the game: runs the OFFICIAL IW4x launcher with its own options
REM   --skip-remote      "Skip all remote checks and file reconciliation"  (keeps the IW4x-32 files)
REM   --no-self-update   "Skip the automatic launcher self-update check"
REM and afterwards checks the IW4x-32 files are still installed.
set "OURS_EXE=2609c2687dd2ffb3f32c7687ed04f57b38ef6879c14b1c546faf8bfd8f35ea6b"
set "OURS_DLL=57f1189ebfcb6a6acc7338311e862a7fa0974a5242c5991e6f1267a17afb3cef"
for %%I in ("%~dp0..") do set "GAME=%%~fI"
set "L="
if exist "%GAME%\iw4x-launcher.exe" set "L=%GAME%\iw4x-launcher.exe"
if not defined L if exist "%GAME%\iw4x-launcher-x86.exe" set "L=%GAME%\iw4x-launcher-x86.exe"
if not defined L (echo The IW4x launcher was not found in "%GAME%". & pause & exit /b 1)
cd /d "%GAME%"
echo Starting the IW4x launcher without file checks or updates ...
"%L%" --skip-remote --no-self-update %*
call :sha "%GAME%\iw4x.exe" EXE_NOW
call :sha "%GAME%\iw4x.dll" DLL_NOW
if /i "%EXE_NOW%"=="%OURS_EXE%" if /i "%DLL_NOW%"=="%OURS_DLL%" (echo IW4x-32 files are still installed. & exit /b 0)
echo.
echo WARNING: the IW4x launcher replaced the IW4x-32 files with the official ones.
echo          Run "Install IW4x-32.bat" again and start the game with "Play IW4x-32.bat".
pause
exit /b 1

:sha
set "%2="
for /f "skip=1 tokens=* delims=" %%a in ('certutil -hashfile "%~1" SHA256 2^>nul') do if not defined %2 set "%2=%%a"
call set "%2=%%%2: =%%"
exit /b 0
