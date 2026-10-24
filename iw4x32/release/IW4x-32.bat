@echo off
REM IW4x-32 - Modern Warfare 2 with up to 48 players. DOUBLE-CLICK THIS FILE - that is all.
REM  First time: finds your game, installs official IW4x (with the official IW4x launcher) and IW4x-32, and puts
REM  an "IW4x-32" shortcut on your desktop. After that it is the start menu: play, vanilla IW4x, host a server,
REM  uninstall. It keeps itself and IW4x up to date.
REM This file is enough on its own: without the files\ folder next to it, it downloads the release from GitHub
REM (every file SHA-256 checked) into an IW4x-32 folder next to it first.
REM Options, e.g. for your own shortcuts: --play  --vanilla  --server [port]  --server48 [port]  --vanilla-server [port]
REM  --setup [game folder]  --uninstall  --no-update  --dry; anything else goes to the game: +connect 1.2.3.4:28960
REM Everything happens in files\iw4x32.ps1. The last line is ONE line on purpose: an update may replace this file
REM while it runs.
setlocal
set "IW4X32_PS=%~dp0files\iw4x32.ps1"
if not exist "%IW4X32_PS%" set "IW4X32_PS=%~dp0IW4x-32\files\iw4x32.ps1"
if not exist "%IW4X32_PS%" echo Downloading IW4x-32 ...
if not exist "%IW4X32_PS%" powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor 3072; $u=$env:IW4X32_UPDATE_URL; if(-not $u){$u='https://github.com/shaunypnz/iw4x-32/releases/latest/download/latest.json'}; $w=New-Object Net.WebClient; $w.Headers.Add('User-Agent','iw4x32-setup'); $m=$w.DownloadString($u)|ConvertFrom-Json; $n='files/iw4x32.ps1'; $b=$w.DownloadData($m.base_url+$n); $h=-join([Security.Cryptography.SHA256]::Create().ComputeHash($b)|ForEach-Object{$_.ToString('x2')}); if($h -ne $m.files.$n){throw 'download check failed'}; New-Item -ItemType Directory -Force -Path (Split-Path -Parent $env:IW4X32_PS)|Out-Null; [IO.File]::WriteAllBytes($env:IW4X32_PS,$b)"
if not exist "%IW4X32_PS%" (echo Could not download IW4x-32 - check your internet connection, or get the zip from https://github.com/shaunypnz/iw4x-32/releases & pause & exit /b 1)
(powershell -NoProfile -ExecutionPolicy Bypass -File "%IW4X32_PS%" %* & if errorlevel 9009 (echo IW4x-32 needs Windows PowerShell - it is part of Windows 10 and 11. & pause)) & exit /b
