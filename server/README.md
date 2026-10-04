# IW4x-32 server: host a 32-player IW4x server

This is the **server build** of IW4x-32: `iw4x.exe` + `iw4x.dll`, built on the official IW4x release **r5154**
(protocol 153). It hosts up to **32 players**, and it also plays as a normal client.

- **More than 18 slots:** only players with IW4x-32 files can join (the player build or this one). Anyone else gets
  an install message.
- **18 slots or fewer:** the server runs in compatibility mode with the stock layout, and everyone can join,
  including normal IW4x players.
- **Server browser:** normal IW4x hides servers with more than 18 slots. IW4x-32 players see them.

> **Tested on:** Linux under Wine (Ubuntu, Wine 10, xvfb). The Windows scripts follow the same steps but haven't
> been run on Windows yet.

## What's in here

| Path | What |
|---|---|
| `files/` | the server build `iw4x.exe` + `iw4x.dll` |
| `windows/` | `Install-Server.bat`, `Start-Server.bat`, `Uninstall-Server.bat` |
| `linux/` | `install-server.sh`, `uninstall-server.sh`, `iw4x-server.service` (systemd), `server.env.example` |
| `source/` | manifests of every changed byte, `iw4x32_check.py`, full source of the injected code (`engine32c/`) |
| `CHANGES.txt` | every change, client and server, with `[srv]` marking the server-only ones |

## Install

You need MW2 with **IW4x r5154** installed, then **start it once** (IW4x rearranges the folder on the first run).

### Windows
1. Move the `IW4x-32-server` folder into your MW2 folder, the one with `iw4x.exe`.
2. Run `IW4x-32-server\windows\Install-Server.bat`. It checks your files are the official r5154 ones, backs them
   up and installs the server build.
3. Create `userraw\server.cfg` (see *Server config* below).
4. Run `IW4x-32-server\windows\Start-Server.bat`. It starts a 32-slot dedicated server on UDP 28960; edit `PORT` /
   `SLOTS` at the top to change those.
5. Forward the UDP port on your router.

### Linux (Wine)
```bash
sudo dpkg --add-architecture i386 && sudo apt update && sudo apt install -y wine wine32:i386 xvfb
sudo useradd -r -m -d /srv/iw4x iw4x            # the server runs as this user
# copy the MW2 + IW4x r5154 game folder to /srv/iw4x/root, then put IW4x-32-server inside it:
sudo -u iw4x bash /srv/iw4x/root/IW4x-32-server/linux/install-server.sh
sudo -u iw4x nano /srv/iw4x/root/userraw/server.cfg                                       # see "Server config"
sudo cp /srv/iw4x/root/IW4x-32-server/linux/server.env.example /srv/iw4x/server.env       # PORT, MAXCLIENTS
sudo cp /srv/iw4x/root/IW4x-32-server/linux/iw4x-server.service /etc/systemd/system/
sudo -u iw4x env WINEPREFIX=/srv/iw4x/wineprefix wineboot -i                                # once
sudo systemctl daemon-reload && sudo systemctl enable --now iw4x-server
```
Then forward the UDP port (`PORT` in `server.env`) on your router, and open it in the host firewall
(`sudo ufw allow 28960/udp`).

The unit runs `xvfb-run wine iw4x.exe -dedicated …` with systemd hardening: no capabilities, read-only system,
and write access to `/srv/iw4x` only. The console log is in `userraw/console_mp.log`.

Uninstalling (`Uninstall-Server.bat` / `uninstall-server.sh`) only restores `iw4x.exe` / `iw4x.dll`; your
`userraw` files stay. Don't run the IW4x launcher or updater on a server: it puts the official 18-player files
back. When IW4x releases a new version, wait for a matching IW4x-32 update.

## Server config

A normal IW4x `server.cfg` works. What matters for 32 players:
- **Slots:** set `sv_maxclients` on the **command line** (the start scripts do this), together with
  `party_maxplayers` and `party_enable 0`. More than 18 means 32-player mode.
- **rcon:** set a long `rcon_password`. IW4x's `RconWhitelistAdd "<ip>"` limits rcon to the listed addresses
  (add `127.0.0.1` for local tools).
- **Comments:** the game treats `;` as a command separator **even inside `//` comments**, so never put one in a
  cfg comment.

Minimal example:
```
set sv_hostname "My IW4x-32 server"
set rcon_password "a-long-random-password"
set g_gametype "war"
set sv_maprotation "gametype war map mp_terminal gametype war map mp_highrise"
```

## Verify the files
```bash
python IW4x-32-server/source/iw4x32_check.py verify IW4x-32-server/files/iw4x.exe <official iw4x.exe> IW4x-32-server/source/manifest_iw4x_exe.json
python IW4x-32-server/source/iw4x32_check.py verify IW4x-32-server/files/iw4x.dll <official iw4x.dll> IW4x-32-server/source/manifest_iw4x_dll.json
```
This proves that every changed byte is listed with its reason, and that the Windows functions the files can
import are identical to the official ones. Its `build` mode makes our files from your official ones.

## Known limits
- End-of-match stats record players 1-18 only. Host migration is off: the match ends instead.
- The game logic runs on one CPU core, and 32 players cost more per frame than 18, so a host needs good
  single-core speed.

## Licence
`iw4x.dll` is IW4x's code ([GPL-3.0](https://github.com/iw4x/iw4x-client)) with binary patches. The manifests,
the build tools (`iw4x-integration/build/`) and the injected-code source are the complete source of our changes.
Not affiliated with Activision, Infinity Ward or the IW4x team.
