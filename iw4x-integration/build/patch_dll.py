#!/usr/bin/env python3
"""
patch_dll.py — build a 32-client-compatible iw4x.dll from the STOCK MSVC IW4x DLL (r5121).

    python3 patch_dll.py [--src STOCK] [--dst OUT]

Defaults: --src $MODDED/iw4x.dll.orig-msvc (MD5 c7b4cf031545f9bcc753313adce77f92)
          --dst $MODDED/iw4x.dll.stock32
Interim vehicle until a source build (clang-cl or fixed MinGW) exists.

  D1  Engine pointers: the DLL hard-codes engine addresses of arrays that patch_engine.py
      relocates. New addresses are taken from patch_engine.RELOCS/layout() so the two
      builders can never disagree.
  D2  DLL-internal arrays sized [18] are moved to a new zero-filled section `.iw432d`
      appended to the DLL. Every .text operand inside the old array is shifted; each patched
      operand must already have a .reloc (HIGHLOW) entry so Wine's loader still rebases it.
  D3  Constants: spawnBot count clamps 18 -> 32.
"""
import argparse, hashlib, os, struct, sys

import capstone
import pefile
from capstone.x86 import X86_OP_IMM, X86_OP_MEM

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_engine  # noqa: E402  (layout source of truth)

MODDED = patch_engine.MODDED
STOCK_MD5 = "c7b4cf031545f9bcc753313adce77f92"
NEW_N = 32

# D1: (file offset, engine array name, offset within that array, label)
ENGINE_PTRS = (
    (0x35EC30, "svs_clients", 0, ".data  Game::svs_clients"),
    (0x038B9E, "level_bgs", 0, ".text  mov [esi+0xC], level_bgs (TLS bgs)"),
    (0x297818, "level_bgs", 0, ".rdata engine address table: level_bgs"),
    (0x33F2B, "cg_tail", 0, ".text  cmp eax,&cg.clientinfo[18] (find client by name) -> &clientinfo[32]"),
    (0x3F343, "post_cg_globals", 0, ".text  push [0x8EE4B8] (first global after cg_s)"),
    (0x3F3AA, "post_cg_globals", 0, ".text  push [0x8EE4B8] (first global after cg_s)"),
    (0xA9A6C, "ui_playerClientNums", 0, ".text  voice mute UI: sharedUiInfo.playerClientNums[i]"),
    (0xAB225, "ui_playerNames", 0, ".text  sharedUiInfo.playerNames[i]"),
    (0xAB279, "ui_playerNames", 0, ".text  sharedUiInfo.playerNames[i]"),
    # NOT 0x938EC `add edx,0x62E5078`: that is gameTypes[idx-1] (numerically inside playerClientNums).
)

# D2: DLL arrays (preferred-base VAs, image base 0x10000000)
DLL_RELOCS = [
    dict(name="g_botai", lo=0x1045C080, stride=0x24, n_old=18, expect=45),  # Bots.cpp BotMovementInfo[18]
    # ClanTags::ClientState[18][5]: written by ClientUserinfoChanged for EVERY client (bots too),
    # so slots 18..31 overran 70 bytes of whatever followed it.
    dict(name="ClanTags_ClientState", lo=0x103D8C10, stride=5, n_old=18, expect=6),
    # Voice (r5121 layout: VoicePacket_t is 0x108, 40 queued per client -> 0x2940 per client).
    # G_BroadcastVoice / SV_QueueVoicePacket loop to sv_maxclients, so listeners 18..31 overran these.
    dict(name="Voice_mute_a", lo=0x103FEEB0, stride=1, n_old=18, expect=9),             # bool[18]
    dict(name="Voice_PacketCount", lo=0x103FEED0, stride=4, n_old=18, expect=8),        # int[18]
    dict(name="Voice_mute_b", lo=0x103FEF18, stride=1, n_old=18, expect=6),             # bool[18]
    dict(name="Voice_Packets", lo=0x103FEF30, stride=0x2940, n_old=18, expect=5),       # VoicePacket_t[18][40]
    # (constructor memsets of these use the old 18-sized lengths; harmless — the .iw432d copies start zeroed)
]

# D3: (rva, old bytes hex, new bytes hex, label)
CONSTS = (
    (0x32F76, "6a12", "6a20", "spawnBot all: count = MAX_CLIENTS 18 -> 32"),
    (0x32FAB, "83fb12", "83fb20", "spawnBot: std::min(count, MAX_CLIENTS) compare 18 -> 32"),
    (0x38285, "c745a812000000", "c745a820000000", "ClanTags::SendClanTagsToClients loop count 18 -> 32"),
    (0x3837B, "6a12", "6a20", "ClanTags::ParseClanTags loop count 18 -> 32"),
    # runtime mute reset (callback 0x100AA47C): 4x stosd + stosw cleared 18 bytes -> rep stosd x8 = 32
    (0xAA484, "abababab66ab5fc3", "6a0859f3ab5fc390", "Voice mute reset: clear 32 entries (push 8; pop ecx; rep stosd)"),
    # MSVC-inserted bounds checks (`cmp eax,0x12; jae __report_rangecheckfailure`) in front of the
    # relocated mute arrays. Voice::SV_UnmuteClient runs on EVERY client disconnect (Events::
    # OnClientDisconnect, from the SV_FreeClient hook): freeing client 18+ hit the check and the
    # process fast-failed (int 0x29: no dump, no log) - the "server dies when a real player in slot
    # 19-32 leaves" bug (c19/c22/c23/c25/c26; caught with gdb at RVA 0x1A2DCE, caller chain 0x3488E).
    (0xA9EB5, "83f812", "83f820", "Voice::SV_UnmuteClient bounds check 18 -> 32 (runs on every disconnect)"),
    (0xAA4BF, "83f812", "83f820", "Voice_UnmuteMember_Hk bounds check 18 -> 32"),
    (0xAA5AC, "3c12", "3c20", "CL_VoicePacket: talker < 18 -> 32 (engine talkTime/decoders are 32 since r15)"),
    # stock32i: upstream r5121 crash fix (not a 32-player limit). The Updater's async HTTP thread compares the latest
    # GitHub release tag_name with its own version and, when they differ (always, for r5121), calls
    # Dvar_SetBool(cl_updateAvailable, 1) ON THAT THREAD; the engine's dvar-set logging uses va() -> Sys_GetValue(1)
    # with no thread values -> null read at 0x4EC749 (client c46, server in the 2026-10-02 human session). Only
    # happens when the API request succeeds (rate limits hide it). jne -> jmp: never set the flag (no menu notice).
    (0xA93D4, "7511", "eb11", "Updater: do not set cl_updateAvailable from the HTTP thread (va() TLS crash 0x4EC749)"),
)
RDATA_CONSTS = (
    (0x226BC4, 18, 32, "const int MAX_CLIENTS (only user: spawnBot clamp @+0x32FB2)"),
)


def die(msg):
    sys.exit(f"ERROR: {msg}")


WRITES = []      # (file offset, length, reason) for --manifest


# Upstream bases. The site tables above are written against r5121; for another base every site is translated
# through the port maps made by tools-re/port_sites.py (qwen27b Q9a: consts/engine ptrs, Q15: DLL arrays, updater).
HERE = os.path.dirname(os.path.abspath(__file__))
BASES = {
    "r5121": dict(src=os.path.join(MODDED, "iw4x.dll.orig-msvc"), md5=STOCK_MD5),
    "r5154": dict(src=os.path.join(HERE, "upstream", "r5154", "iw4x.dll"), md5="c5d73b3ec5e4b36e284a4ae0cfc7fb13",
                  consts=os.path.join(HERE, "upstream", "r5154", "sites_consts.json"),
                  relocs=os.path.join(HERE, "upstream", "r5154", "sites_dll_relocs.json")),
}


# Sites that exist ONLY in a newer base (no r5121 counterpart), added after translation. r5154: a new per-client flag
# byte[18] at 0x103E3040 (set/cleared/tested by client number; clientNum parsed with strtol at 0x39630) — followed by
# separate globals at 0x103E3052/53 and an object at 0x103E3054, so it is relocated, not just re-bounded. Found by
# diffing every `cmp reg,0x12` against r5121 (6 new) and qwen27b's Q16 classification (0xC00A4 = a state/enum
# compare in a container routine, 0x140EA5 = key codes: left alone). Verified against the disassembly.
BASE_EXTRA = {
    "r5121": dict(
        relocs=[],
        consts=(
            (0x96FAC, "83bd68ffffff12", "83bd68ffffff20", "ServerList: drop servers with clients > 18 -> 32 (browser)"),
            (0x96FC1, "83bd70ffffff12", "83bd70ffffff20", "ServerList: drop servers with sv_maxclients > 18 -> 32 (browser)"),
        )),
    "r5154": dict(
        relocs=[dict(name="r5154_client_flag", lo=0x103E3040, stride=1, n_old=18, expect=6),
                # CardTitles::CustomTitles[MAX_CLIENTS][18] (qwen27b Q18 found 2 refs; the scan found the 3rd)
                dict(name="r5154_CustomTitles", lo=0x103E2E40, stride=18, n_old=18, expect=3)],  # + lea eax,[eax+base] @0x34DB8 (lookup)
        consts=(
            (0x39642, "83f812", "83f820", "r5154: clientNum parsed from a command argument < 18 -> 32"),
            (0x39998, "83f812", "83f820", "r5154: client flag test: clientNum < 18 -> 32"),
            (0x3A79B, "83f812", "83f820", "r5154: client flag clear: clientNum < 18 -> 32"),
            (0x3A7E3, "83ff12", "83ff20", "r5154: client flag set: clientNum < 18 -> 32"),
            (0x3A74D, "abababab66ab", "6a0859f3ab90", "r5154: client flags reset: 18 bytes -> 32 (push 8; pop ecx; rep stosd)"),
            (0x3A775, "abababab66ab", "6a0859f3ab90", "r5154: client flags reset: 18 bytes -> 32 (push 8; pop ecx; rep stosd)"),
            # IW4x ServerList: "Servers with more than 18 players ... are faking for sure" -> 32-slot servers were
            # never listed in the in-game browser (source ServerList.cpp; found via the aimAssist/voiceChat refs)
            (0x98C40, "83bd68ffffff12", "83bd68ffffff20", "ServerList: drop servers with clients > 18 -> 32 (browser)"),
            (0x98C55, "83bd70ffffff12", "83bd70ffffff20", "ServerList: drop servers with sv_maxclients > 18 -> 32 (browser)"),
            # Q18 (qwen27b, verified): admin / public-server paths still limited to 18. Loops over svs_clients use a
            # folded end offset 18*sizeof(client_s) = 0xBB4820 -> 32*0xA6790 = 0x14CF200.
            (0x2F806, "83f812", "83f820", "Bans: client slot < 18 -> 32 (ban by slot number)"),
            (0x36C11, "6a12", "6a20", "Chat sayTo: clientNum = min(arg, 18) -> 32"),
            (0x36E05, "6a12", "6a20", "Chat tellTo: clientNum = min(arg, 18) -> 32"),
            (0x4543F, "81fb2048bb00", "81fb00f24c01", "Download /info JSON: player list over 18 clients -> 32"),
            (0x94A26, "81fe2048bb00", "81fe00f24c01", "ServerInfo getstatus: player list over 18 clients -> 32"),
            (0x82BF5, "6a12", "6a20", "ServerInfo: bot count min(n, 18) -> 32"),
            (0x34F03, "81fe2048bb00", "81fe00f24c01", "CardTitles: send custom titles for 18 clients -> 32"),
            (0x34F90, "6a12", "6a20", "CardTitles: parse 18 custom titles -> 32"),
            (0x3503C, "6844010000", "6840020000", "CardTitles: memset(CustomTitles) 18*18 -> 32*18 bytes"),
            (0x34D35, "80f912", "80f920", "CardTitles: TableLookupByRow client index < 18 -> 32"),
        )),
}


# ---- build roles (see patch_engine.apply_role) ---------------------------------------------------------------------
# client = the PUBLIC player DLL: only the client-side changes. Server-only: bots (g_botai, spawnBot), the server voice
# relay (VoicePackets/VoicePacketCount/MuteList = Voice_mute_b, SV_UnmuteClient), clan-tag/card-title SENDING, the
# r5154 per-client server flag (give/ammo command), admin/getstatus/ban/chat/download paths over svs_clients.
# Kept: ClanTags (parse), S_PlayerMute (= Voice_mute_a, client mute), CardTitles (parse/lookup), CL_VoicePacket,
# server browser filter, updater fix, and the engine pointers of the client-side arrays.
DLL_SERVER_RELOCS = {"g_botai", "Voice_PacketCount", "Voice_mute_b", "Voice_Packets", "r5154_client_flag"}
DLL_SERVER_CONSTS = {   # r5121 RVAs (CONSTS) and per-base RVAs (BASE_EXTRA)
    "r5121": {0x32F76, 0x32FAB, 0x38285, 0xA9EB5},
    "r5154": {0x39642, 0x39998, 0x3A79B, 0x3A7E3, 0x3A74D, 0x3A775, 0x2F806, 0x36C11, 0x36E05, 0x4543F, 0x94A26,
              0x82BF5, 0x34F03},
}


def apply_role(role, base):
    global CONSTS, RDATA_CONSTS, DLL_RELOCS
    patch_engine.apply_role(role)
    if role == "server":
        return
    CONSTS = tuple(c for c in CONSTS if c[0] not in DLL_SERVER_CONSTS["r5121"])
    RDATA_CONSTS = ()                                       # MAX_CLIENTS: only the spawnBot clamp uses it
    DLL_RELOCS = [r for r in DLL_RELOCS if r["name"] not in DLL_SERVER_RELOCS]
    ex = BASE_EXTRA.get(base, {})
    if ex:
        ex["relocs"] = [r for r in ex.get("relocs", []) if r["name"] not in DLL_SERVER_RELOCS]
        ex["consts"] = tuple(c for c in ex.get("consts", ()) if c[0] not in DLL_SERVER_CONSTS.get(base, set()))


def translate_tables(base):
    """Rewrite ENGINE_PTRS / DLL_RELOCS / CONSTS / RDATA_CONSTS for another upstream base. Any site without a
    resolved mapping aborts the build (never guess)."""
    import json
    global ENGINE_PTRS, CONSTS, RDATA_CONSTS
    b = BASES[base]
    cmap = {int(x["old_rva"], 16): int(x["new_rva"], 16) for x in json.load(open(b["consts"]))
            if x.get("resolved") and x.get("new_rva") and x["kind"] in ("const", "rdata_const")}
    rj = json.load(open(b["relocs"]))
    emap = {int(str(x["old_file_off"]), 0): int(str(x["new_file_off"]), 0) for x in rj["engine_ptrs"]
            if x.get("new_file_off") is not None}
    lomap = {x["name"]: int(str(x["new_lo"]), 0) for x in rj["relocs"] if x.get("agree") and x.get("new_lo") is not None}
    up = rj.get("updater") or {}
    if up.get("new_rva") is not None:
        cmap[int(str(up["old_rva"]), 0)] = int(str(up["new_rva"]), 0)

    def need(m, k, what):
        if k not in m:
            die(f"{base}: no mapping for {what} ({k:#x})" if isinstance(k, int) else f"{base}: no mapping for {what}")
        return m[k]
    ENGINE_PTRS = tuple((need(emap, fo, w), n, o, w) for fo, n, o, w in ENGINE_PTRS)
    CONSTS = tuple((need(cmap, rva, w), old, new, w) for rva, old, new, w in CONSTS)
    RDATA_CONSTS = tuple((need(cmap, rva, w), old, new, w) for rva, old, new, w in RDATA_CONSTS)
    for r in DLL_RELOCS:
        r["lo"] = need(lomap, r["name"], r["name"])
    ex = BASE_EXTRA.get(base, {})
    DLL_RELOCS.extend(dict(r) for r in ex.get("relocs", []))
    CONSTS = CONSTS + tuple(ex.get("consts", ()))
    print(f"base {base}: {len(ENGINE_PTRS)} engine ptrs, {len(CONSTS)} consts, {len(RDATA_CONSTS)} rdata, "
          f"{len(DLL_RELOCS)} arrays (incl. {len(ex.get('relocs', []))} + {len(ex.get('consts', ()))} {base}-only sites)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="r5121", choices=sorted(BASES), help="upstream iw4x.dll release to patch")
    ap.add_argument("--src", default=None, help="default: the base's stock DLL")
    ap.add_argument("--dst", default=os.path.join(MODDED, "iw4x.dll.stock32"))
    ap.add_argument("--alt-layout", action="store_true",
                    help="loader/gen_tables.py only: engine .iw432 at +0x10000000 (see patch_engine --alt-layout)")
    ap.add_argument("--role", default="server", choices=("server", "client"),
                    help="client = public player DLL without the server-side changes (pairs with patch_engine --role client)")
    ap.add_argument("--manifest", help="also write a release manifest (every changed byte + reason) to this JSON file")
    a = ap.parse_args()
    apply_role(a.role, a.base)
    if a.alt_layout:
        patch_engine.SECTION_VA += 0x10000000

    b = BASES[a.base]
    src = a.src or b["src"]
    raw = open(src, "rb").read()
    if hashlib.md5(raw).hexdigest() != b["md5"]:
        die(f"{src} is not the stock {a.base} DLL (md5 {b['md5']})")
    if a.base != "r5121":
        translate_tables(a.base)
    else:
        global CONSTS
        ex = BASE_EXTRA.get("r5121", {})
        DLL_RELOCS.extend(dict(r) for r in ex.get("relocs", []))
        CONSTS = CONSTS + tuple(ex.get("consts", ()))
    pe = pefile.PE(data=raw)
    IB = pe.OPTIONAL_HEADER.ImageBase
    d = bytearray(raw)

    # ---- D1 -----------------------------------------------------------------------
    patch_engine.layout()
    eng = {r["name"]: r for r in patch_engine.RELOCS}
    for fo, name, off, what in ENGINE_PTRS:
        if name not in eng:                     # array not relocated in this role's exe: keep the stock address
            print(f"D1  {what}: kept (not relocated in the {a.role} exe)")
            continue
        old = eng[name]["lo"] + off
        new = eng[name]["new_lo"] + off
        if struct.unpack_from("<I", d, fo)[0] != old:
            die(f"D1 {what} @file {fo:#x}: expected {old:#x}")
        struct.pack_into("<I", d, fo, new)
        WRITES.append((fo, 4, f"engine address {old:#x} -> {new:#x} (array moved/grown in our iw4x.exe): {what}"))
        print(f"D1  {what}: {old:#x} -> {new:#x}")

    # ---- D2: new section + operand relocation ---------------------------------------
    sa = pe.OPTIONAL_HEADER.SectionAlignment
    last = pe.sections[-1]
    sect_va = (last.VirtualAddress + last.Misc_VirtualSize + sa - 1) & ~(sa - 1)
    cur = sect_va
    for r in DLL_RELOCS:
        r["hi"] = r["lo"] + r["stride"] * r["n_old"]
        r["new_lo"] = IB + cur
        cur += (r["stride"] * NEW_N + 0xF) & ~0xF
    vsize = (cur - sect_va + sa - 1) & ~(sa - 1)

    hdr_off = last.get_file_offset() + 40
    if hdr_off + 40 > pe.OPTIONAL_HEADER.SizeOfHeaders or any(d[hdr_off:hdr_off + 40]):
        die("no room for an extra section header")
    d[hdr_off:hdr_off + 40] = b".iw432d\0" + struct.pack("<IIIIIIHHI", vsize, sect_va, 0, 0, 0, 0, 0, 0, 0xC0000080)
    struct.pack_into("<H", d, pe.FILE_HEADER.get_file_offset() + 2, pe.FILE_HEADER.NumberOfSections + 1)
    struct.pack_into("<I", d, pe.OPTIONAL_HEADER.get_file_offset() + 0x38, sect_va + vsize)
    WRITES.append((hdr_off, 40, "PE header: new section .iw432d (zero-filled data: 32-player copies of IW4x arrays, no file bytes)"))
    WRITES.append((pe.FILE_HEADER.get_file_offset() + 2, 2, "PE header: NumberOfSections"))
    WRITES.append((pe.OPTIONAL_HEADER.get_file_offset() + 0x38, 4, "PE header: SizeOfImage"))
    print(f"D2  .iw432d @ rva {sect_va:#x} size {vsize:#x}")

    relocs = set()
    for blk in pe.DIRECTORY_ENTRY_BASERELOC:
        for e in blk.entries:
            if e.type == 3:  # IMAGE_REL_BASED_HIGHLOW
                relocs.add(e.rva)

    text = next(s for s in pe.sections if s.Name.startswith(b".text"))
    img = pe.get_memory_mapped_image()
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    t_lo, t_hi = text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
    ops = []
    off = t_lo
    while off < t_hi:
        progressed = False
        for ins in md.disasm(img[off:min(off + 0x4000, t_hi)], IB + off):
            progressed = True
            off = ins.address - IB + ins.size
            for op in ins.operands:
                if op.type == X86_OP_MEM:
                    ops.append((ins, op.mem.disp & 0xFFFFFFFF))
                elif op.type == X86_OP_IMM:
                    ops.append((ins, op.imm & 0xFFFFFFFF))
            if off >= t_hi:
                break
        if not progressed:
            off += 1
    for r in DLL_RELOCS:
        n = 0
        for ins, v in ops:
            if r["lo"] <= v < r["hi"]:
                rawb = bytes(ins.bytes)
                k = rawb.find(struct.pack("<I", v))
                if k < 0 or rawb.find(struct.pack("<I", v), k + 1) >= 0:
                    die(f"{r['name']}: cannot locate operand in {ins.address:#x}")
                rva = ins.address - IB + k
                if rva not in relocs:
                    die(f"{r['name']}: operand @rva {rva:#x} has no .reloc entry")
                fo = pe.get_offset_from_rva(rva)
                struct.pack_into("<I", d, fo, v - r["lo"] + r["new_lo"])
                WRITES.append((fo, 4, f"relocate IW4x array {r['name']} [{r['n_old']}] -> [{NEW_N}] at {r['new_lo']:#x}: "
                                      f"address operand"))
                n += 1
        # data-section pointers into the array would also need moving — refuse if any exist
        for s in pe.sections:
            if s.Name.startswith(b".text"):
                continue
            blob = s.get_data()
            for i in range(0, len(blob) - 3, 4):
                if r["lo"] <= struct.unpack_from("<I", blob, i)[0] < r["hi"] and (s.VirtualAddress + i) in relocs:
                    die(f"{r['name']}: relocated data pointer at rva {s.VirtualAddress + i:#x}")
        if r["expect"] is not None and n != r["expect"]:
            die(f"{r['name']}: expected {r['expect']} refs, got {n}")
        print(f"D2  {r['name']} [{r['n_old']}]x{r['stride']:#x} {r['lo']:#x} -> {r['new_lo']:#x} [{NEW_N}]: {n} operands")

    # ---- D3 ---------------------------------------------------------------------------
    for rva, old, new, what in CONSTS:
        fo = pe.get_offset_from_rva(rva)
        if bytes(d[fo:fo + len(old) // 2]).hex() != old:
            die(f"D3 {what}: unexpected bytes")
        d[fo:fo + len(new) // 2] = bytes.fromhex(new)
        WRITES.append((fo, len(new) // 2, f"rva {rva:#x}: {what}"))
        print(f"D3  +{rva:#x} {what}")
    for rva, old, new, what in RDATA_CONSTS:
        fo = pe.get_offset_from_rva(rva)
        if struct.unpack_from("<I", d, fo)[0] != old:
            die(f"D3 {what}: unexpected value")
        struct.pack_into("<I", d, fo, new)
        WRITES.append((fo, 4, f"rva {rva:#x}: {what}"))
        print(f"D3  +{rva:#x} {what}: {old} -> {new}")

    tmp = a.dst + ".tmp"
    open(tmp, "wb").write(d)
    os.replace(tmp, a.dst)
    print(f"\nwrote {a.dst}  md5 {hashlib.md5(d).hexdigest()}")
    if a.manifest:
        sys.path.insert(0, os.path.join(HERE, "tools-re"))
        import manifest_lib
        manifest_lib.write_manifest(a.manifest, raw, d, WRITES, dict(
            file="iw4x.dll", role=a.role, build=f"{a.base}-32d" + ("-player" if a.role == "client" else ""),
            official=f"iw4x.dll from IW4x {a.base} (GPL-3.0, https://github.com/iw4x/iw4x-client)"))


if __name__ == "__main__":
    main()
