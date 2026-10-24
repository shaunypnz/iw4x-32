**IW4x-32: Modern Warfare 2 multiplayer with up to 32 players instead of 18 (bots included).** One file, `iw4x.dll`, on
top of a normal IW4x install; your `iw4x.exe` stays the official one. Normal 18-player IW4x servers keep working.

<!-- whats-new -->
### What's new in v2.7-r5292
Built for official **IW4x r5292** (previous release: r5278) and live-tested on a 32-slot server (31 bots + a real client). It carries every IW4x fix from r5278 to r5292:
- Fix outdated legacy fastfiles replacing current ones during zone adoption
- Fix fatal error when dropping weapon with no world model
- Fix recoil multiplier discarding accumulated gun kick
- Change script stack corruption from crash to error
- Remove set optimal settings prompt
- Fix fatal error when starting match on DLC map not owned
- Fix unlocked items not marked new after map rotation
- Fix stats request putting disconnected client back to connecting
- Fix black screen after missing DLC error on map rotation
- Fix players reconnecting on every map rotation
- Fix client command overflow from repeated notifies
- Fix crash when Direct3D 9 fails to initialize
- Bump iw4-open-formats
- Fix ZoneBuilder not building secondary sound aliases
- Localize server browser toasts
- Fix localized zone not replacing stock strings
- Fix server browser counts not being localized
- Fix sounds silenced by late sound driver init
<!-- /whats-new -->

### Install
You need **Call of Duty: Modern Warfare 2 (2009) from Steam**. Nothing else - IW4x is installed for you.

| Windows | Linux / Steam Deck |
|---|---|
| Download **IW4x-32-@VERSION@.zip**, extract it, double-click **`IW4x-32.bat`** | same zip, run **`./IW4x-32.sh`** |

The first start finds your game, lets the official IW4x launcher install IW4x (made for **IW4x @IW4X@**), installs
IW4x-32 and puts an **IW4x-32** shortcut on your desktop (Linux: applications menu). From then on the shortcut opens a
menu: **play IW4x-32, play vanilla IW4x, host a 32-player server, host a normal server, uninstall** - press a number or
wait 5 s. Updates install themselves.

Only want one file? **`IW4x-32.bat`** / **`IW4x-32.sh`** below work on their own: they download the rest of this
release (every file SHA-256 checked against `latest.json`).

### Host a 32-player server
Pick **3** in the menu (or `IW4x-32.bat --server 28961` for another port). The first start makes
**`userraw\server_iw4x32.cfg`** in your game folder: set the server name, an rcon password and the map rotation there,
then restart. Forward the port (**UDP**, default 28960). Bots: `spawnBot 10` in the server console.

Upgrading from v2.0: your next start updates as usual, and the start after that tidies the old scripts away
(`Play IW4x-32.bat` etc.) and makes the new shortcut.

Every file's SHA-256 is in `files/SHA256SUMS.txt` and `latest.json`. What changed and why: `files/CHANGES.txt`.
Source: this repository (the IW4x client with the IW4x-32 changes as ordinary commits - search the code for
`IW4x-32:`), GPL-3.0 like IW4x.
