#!/usr/bin/env python3
"""make_changes_txt.py — CHANGES.txt for the player release, generated from the build tables (client role) and the
release manifests, so the text can never disagree with the files.  python3 tools-re/make_changes_txt.py OUT"""
import collections, json, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import patch_engine as pe   # noqa: E402
import patch_dll as pd      # noqa: E402
ROLE = sys.argv[2] if len(sys.argv) > 2 else "client"
BASE = os.environ.get("IW4X32_BASE", "r5154")      # upstream IW4x release the build is made from
VERSION = os.environ.get("IW4X32_VERSION", "v1.0")
REL = os.environ.get("IW4X32_REL_SOURCE") or os.path.join(HERE, "release", "IW4x-32" if ROLE == "client" else "IW4x-32-server", "source")
me = json.load(open(os.path.join(REL, "manifest_iw4x_exe.json")))
md = json.load(open(os.path.join(REL, "manifest_iw4x_dll.json")))
pd.apply_role(ROLE, BASE)
pe.layout()
dual = {va for va, _ in pe.DUAL_SITES}
cnt = collections.Counter(e["why"].split(": address operand")[0] for e in me["entries"] if "relocate array" in e["why"])
W = []
w = W.append
w(f"IW4x-32 {VERSION} - complete list of changes (" + ("player build" if ROLE == "client" else "SERVER build: everything, [srv] = server-side only") + ")")
w("=" * 60)
w("Plain text on purpose, for people and for AI assistants. Every changed byte is in source/manifest_iw4x_exe.json")
w("and source/manifest_iw4x_dll.json; source/iw4x32_check.py verifies both against your own official IW4x files.")
w("")
w("WHY")
w("  MW2's engine and IW4x size everything per-player for 18 players (MAX_CLIENTS = 18): arrays of player info, loop")
w("  bounds, 'is this entity a player' checks (entity numbers 0..17 = players, 18..25 = dead bodies). On a 32-player")
w("  server players 19-32 would be invisible, missing from the scoreboard/minimap, or overwrite memory. The changes")
if ROLE == "client":
    w("  below give the CLIENT room and logic for 32 players. Server-side (hosting) code is not changed: a server started")
    w("  with these files is limited to 18 players (stock sv_maxclients range 1..18).")
else:
    w("  below give the client AND the server room and logic for 32 players (sv_maxclients up to 32). Lines marked [srv]")
    w("  are server-side only (not in the player build). A server with > 18 slots only admits clients with IW4x-32 files;")
    w("  with <= 18 slots it uses the stock layout and admits everyone (compatibility mode).")
w("")
w("FILES")
for m in (me, md):
    w(f"  {m['file']}: built from the official file sha256 {m['official_sha256']} (md5 {m['official_md5']})")
    w(f"  {' ' * len(m['file'])}  ours: sha256 {m['ours_sha256']}, {m['changed_bytes']} bytes changed in {len(m['entries'])} places")
w(f"  Official files = IW4x {BASE} (protocol 153). The official iw4x.exe of {BASE} is the same file IW4x has shipped since r5121.")
w("")
w("SAFETY FACTS (checked by source/iw4x32_check.py)")
w("  - The import tables (Windows functions each file can call) are byte-identical to the official files.")
w("  - No network code, file access or process access was added. The added code calls only game functions and")
w("    VirtualProtect (looked up through the game's own GetProcAddress) to rewrite 16 code sites in its own exe.")
w("  - One behaviour change besides 32 players: the IW4x 'update available' notice is never set (see DLL D3).")
w("")
w("=" * 60)
w("iw4x.exe")
w("=" * 60)
w("E1  Two new PE sections")
w(f"    .iw432 @ {pe.SECTION_VA:#x}: zero-filled data (no bytes in the file) holding the enlarged per-player arrays (E2).")
w(f"    .iw4c  @ {pe.E32C_BASE:#x}: about 250 lines of C/asm compiled with mingw gcc 13 (source/engine32c/): hook stubs + compat code.")
w("")
w("E2  Per-player arrays moved/grown for 32 players (every instruction that addresses them is rewritten)")
for r in pe.RELOCS:
    key = f"relocate array {r['name']} {r['lo']:#x}..{r['hi']:#x} -> {r['new_lo']:#x} (+{r['new_size']:#x}, room for 32 players)"
    n = cnt.get(key, 0)
    tag = "" if ROLE == "client" else ("[srv] " if r["name"] in pe.SERVER_ONLY_RELOCS else "      ")
    w(f"    {tag}{r['name']:20s} {r['lo']:#09x}..{r['hi']:#09x} -> {r['new_lo']:#09x} size {r['new_size']:#07x}  ({n} address operands)")
w("    cg_tail/post_cg_globals: the client's clientinfo[18] inside cg_s grows in place to [32]; what followed it moves.")
w("    compass_actors: minimap actor table 26 -> 40 (players 0..31 + 8 dead bodies). cg_scores: scoreboard rows 18 -> 32.")
w("    ui_player*: UI player list. cl_voice*/snd_voiceBufPool: voice receive state. cl_ring44: per-player history ring.")
w("")
w("E3  Size constants")
for va, old, new, what in pe.P4_SITES:
    w(f"    {'[srv] ' if va in pe.SERVER_ONLY_VAS else ''}{va:#x}  {old:#x} -> {new:#x}  {what}")
if ROLE != "client":
    w("E3b cvar domains (push 0x12 -> push 0x20): " + ", ".join(what for off, what in pe.P3_SITES) + "  [srv]")
w("")
w("E4  Code patches (address, original bytes -> new bytes, meaning). [S] = switched back to the original bytes")
w("    automatically while you play on a normal 18-player server (see E6).")
for va, old, new, what in pe.P5_SITES:
    tag = "" if ROLE == "client" else ("[srv] " if va in pe.SERVER_ONLY_VAS else "      ")
    w(f"    {tag}{va:#x} {'[S]' if va in dual else '   '} {old} -> {new}  {what}")
w("")
w("E5  Hooks (the original instructions are replaced by a jump into .iw4c, which runs them and returns)")
for va, old, stub, what in pe.P6_HOOKS:
    w(f"    {'[srv] ' if va in pe.SERVER_ONLY_VAS else ''}{va:#x}  {old} -> jmp {stub}  {what}")
w("")
w("E6  What the injected code does (source/engine32c/compat.c)")
w("    - registers a read-only userinfo dvar iw4x32=1 so 32-player servers can tell your game has IW4x-32;")
w("    - when the game parses a server's info (CG_ParseServerinfo) it reads sv_iw4x32: if the server is a normal")
w("      18-player IW4x server, the 16 [S] sites are written back to their original bytes (normal player/body layout);")
w("      on a 32-player server our bytes are restored. This uses VirtualProtect on those exact addresses only;")
w("    - Session_* guards: player slots >= 18 are kept out of the 18-entry party/session tables (no overflow);")
w("    - if you start a (max 18-slot) server yourself it always uses the normal layout.")
w("")
w("=" * 60)
w(f"iw4x.dll  (IW4x {BASE}, GPL-3.0 - https://github.com/iw4x/iw4x-client)")
w("=" * 60)
w("D1  Engine addresses of the moved client arrays (E2)")
for fo, name, off, what in pd.ENGINE_PTRS:
    if name in {r["name"] for r in pe.RELOCS}:
        w(f"    file offset {fo:#x}: {what}")
w("D2  New zero-filled section .iw432d with 32-entry copies of IW4x arrays sized [18]")
for r in pd.DLL_RELOCS:
    w(f"    {r['name']:22s} [{r['n_old']}] x {r['stride']:#x} bytes -> [32]   expected references: {r['expect']}")
w("    ClanTags_ClientState = clan tags per player; Voice_mute_a = S_PlayerMute (your client-side mute list);")
w("    r5154_CustomTitles = calling-card titles per player.")
w(f"D3  Constants ({BASE} RVAs)")
for e in md["entries"]:
    if e["why"].startswith("rva "):
        w(f"    {e['why']}   ({e['old']} -> {e['new']})")
w("    The Updater line: IW4x's background HTTP thread set cl_updateAvailable from that thread; the engine's dvar code")
w("    is not thread-safe there and the game could crash (null read at 0x4EC749). The jump makes it never set the")
w("    flag: no update notice. Updating would put the 18-player files back anyway; update IW4x-32 by hand.")
w("")
w("=" * 60)
w("VERIFY OR REBUILD")
w("=" * 60)
w("  python IW4x-32/source/iw4x32_check.py                        (after installing: files/ vs your backup/)")
w("  python IW4x-32/source/iw4x32_check.py verify OURS OFFICIAL MANIFEST")
w("  python IW4x-32/source/iw4x32_check.py build OFFICIAL MANIFEST OUT   (make our file yourself)")
w("  python IW4x-32/source/iw4x32_check.py explain MANIFEST         (all entries with reasons)")
open(sys.argv[1], "w").write("\r\n".join(W) + "\r\n")
print(f"wrote {sys.argv[1]}: {len(W)} lines")
