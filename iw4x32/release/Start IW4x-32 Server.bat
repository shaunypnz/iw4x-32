@echo off
REM =====================================================================================
REM  IW4x-32 - 32-player dedicated server. A thin wrapper around
REM  "IW4x-32 Launcher.bat --server", so shortcuts and habits made before v2.0 keep
REM  working. A normal 18-player IW4x server is "--vanilla-server".
REM
REM    Start IW4x-32 Server.bat           port 28960
REM    Start IW4x-32 Server.bat 28961     another port (one port per server)
REM    Start IW4x-32 Server.bat --dry     only check the install and print the command
REM
REM  First run "Install IW4x-32.bat" (same as for playing), then double-click this file.
REM  Your settings: the game folder's userraw\server_iw4x32.cfg (made from
REM  server\server_iw4x32.cfg on the first start - set the server name and an rcon
REM  password there). Players on the internet: forward the port (UDP) on your router.
REM  Add bots: in the server console type  spawnBot 10
REM =====================================================================================
call "%~dp0IW4x-32 Launcher.bat" --server %*
