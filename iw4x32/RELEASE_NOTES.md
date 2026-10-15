**IW4x-32: Modern Warfare 2 multiplayer with up to 32 players instead of 18 (bots included).** One file, `iw4x.dll`, on
top of a normal IW4x install; your `iw4x.exe` stays the official one. Normal 18-player IW4x servers keep working.

### You need
- Call of Duty: Modern Warfare 2 (2009) from **Steam**, with **IW4x** installed by the [official IW4x launcher](https://github.com/iw4x/launcher).
- Start IW4x once with its launcher so it is up to date - this release is for **official IW4x r5168**.

### Play (Windows)
1. Download **IW4x-32-&lt;version&gt;.zip** below.
2. Extract it so the **`IW4x-32` folder is inside your game folder** (the folder with `iw4x.exe`).
3. Double-click **`IW4x-32\Install IW4x-32.bat`**.
4. Start the game with **`IW4x-32\Play IW4x-32.bat`** (not the IW4x launcher's normal start - its file check puts the 18-player DLL back).

### Play (Linux - Wine / Proton)
Same steps 1-2, then in the `IW4x-32` folder: `./install-linux.sh`, and start with `./play-linux.sh`.

### Host a 32-player server
1. Install exactly as above (steps 1-3, or `./install-linux.sh`).
2. Start it: **`IW4x-32\Start IW4x-32 Server.bat`** (Windows) or **`./start-server-linux.sh`** (Linux, runs under Wine).
   Another port: `Start IW4x-32 Server.bat 28961` / `./start-server-linux.sh 28961` (default 28960).
3. The first start makes **`userraw\server_iw4x32.cfg`** in your game folder: set the server name, an rcon password and
   the map rotation there, then restart. For players on the internet, forward the port (**UDP**) on your router.
4. Bots: type `spawnBot 10` in the server console.

### Undo
`Uninstall IW4x-32.bat` / `./uninstall-linux.sh` puts your original `iw4x.dll` back.

Every file's SHA-256 is in `SHA256SUMS.txt`. What changed and why: `CHANGES.txt` in the zip. Source: this repository
(the IW4x client with the IW4x-32 changes as ordinary commits - search the code for `IW4x-32:`), GPL-3.0 like IW4x.
