# Task (qwen): v2.0 client does not come back after a map change

Seen live (2026-10-13): stock iw4x.exe + this branch's iw4x.dll, 32-slot server, 28 bots + 1 real client in slot 28.
When the match ended and the server rotated the map (`ShutdownGame`, then `Server Initialization` ... `iw4x32:
32-slot server - 32-player layout, patched clients only`), NOBODY reconnected - the client stayed off the server
(a stock IW4x client follows a map change by itself). The server itself re-initialised fine.

Find the cause with the live test - `python3 $HOME/Projects/IW4x-32/tools-re/aiboi_test.py --dll
build/bin/Win32/Release/iw4x.dll --bots 8 --client --minutes 5 --map-change-at 2` reproduces it - and fix it in the
engine component (`src/Components/Modules/IW4x32.cpp`): likely suspects are the connect-time 18/32 layout switch
(`dual` sites) running again or not at all on the level reload, an enlarged client-side array not being reset, or
a hook that assumes the first connect. Read the client's console (the test prints the server's; add the client's
console tail to the test output if you need it - `client.log` is empty, IW4x writes `main/console_mp.log`-style
logs in the game folder) BEFORE changing code, and write what you found in QWEN_REPORT.md.
Do not weaken the test. Mark changes `// IW4x-32:`.
