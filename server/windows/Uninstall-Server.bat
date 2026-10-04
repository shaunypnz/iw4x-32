@echo off
setlocal EnableExtensions
title IW4x-32 server - uninstall
REM Puts your original iw4x.exe / iw4x.dll back from IW4x-32-server\backup\ (made by the installer).
for %%I in ("%~dp0..") do set "KIT=%%~fI"
for %%I in ("%~dp0..\..") do set "GAME=%%~fI"
tasklist /fi "imagename eq iw4x.exe" 2>nul | find /i "iw4x.exe" >nul && (echo ERROR: close the game first. & goto :end)
if not exist "%KIT%\backup\iw4x.exe" goto :nobackup
if not exist "%KIT%\backup\iw4x.dll" goto :nobackup
copy /y "%KIT%\backup\iw4x.exe" "%GAME%\iw4x.exe" >nul || (echo ERROR: could not restore iw4x.exe & goto :end)
copy /y "%KIT%\backup\iw4x.dll" "%GAME%\iw4x.dll" >nul || (echo ERROR: could not restore iw4x.dll & goto :end)
echo Restored the original IW4x files. the IW4x-32 server build is uninstalled (you can delete the IW4x-32-server folder).
goto :end
:nobackup
echo No backup found in IW4x-32-server\backup\. Run the official IW4x launcher once: it repairs iw4x.exe / iw4x.dll.
:end
echo.
pause
