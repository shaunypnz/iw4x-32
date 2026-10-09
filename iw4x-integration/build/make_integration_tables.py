#!/usr/bin/env python3
"""make_integration_tables.py — machine-readable tables of EVERY IW4x-32 change, for the IW4x team.

    python3 tools-re/make_integration_tables.py OUTDIR

Writes OUTDIR/engine_patches.json (iw4x.exe, pristine r5154 = 9c42ffa4..., image base 0x400000) and
OUTDIR/dll_patches.json (iw4x.dll r5154). Every entry carries role "client" (needed by players) or "server"
(only needed to host > 18 slots). Relocation operands are recorded symbolically (array + offset into the NEW
array) so a runtime patcher can allocate the arrays anywhere and rewrite each operand at start-up — the same way
loader/loader.c does it, and the way an iw4x-client component would."""
import json, os, re, struct, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import patch_engine as pe   # noqa: E402
import patch_dll as pd      # noqa: E402

out = sys.argv[1]
BASE = os.environ.get("IW4X32_BASE", "r5154")      # upstream IW4x release the tables describe
os.makedirs(out, exist_ok=True)
pd.apply_role("server", BASE)            # = everything
SERVER_LABELS = {w for rva, o, n, w in pd.CONSTS if rva in pd.DLL_SERVER_CONSTS["r5121"]}
SERVER_LABELS |= {w for rva, o, n, w in pd.BASE_EXTRA[BASE]["consts"] if rva in pd.DLL_SERVER_CONSTS[BASE]}
pristine = open(os.path.join(HERE, "upstream", BASE, "iw4x.exe"), "rb").read()
d = bytearray(pristine)
vsize = pe.layout()
relocs = {r["name"]: r for r in pe.RELOCS}

records = []
orig = pe.rewrite_operand


def rec(dd, ins, old, new):
    raw = bytes(ins.bytes)
    k = raw.find(struct.pack("<I", old))
    m = re.match(r"relocate array (\S+) ", pe.CUR or "")
    name = m.group(1) if m else None
    r = relocs.get(name)
    e = dict(insn_va=f"{ins.address:#x}", operand_va=f"{ins.address + k:#x}", insn=f"{ins.mnemonic} {ins.op_str}",
             old=f"{old:#x}", new=f"{new:#x}")
    if r is not None:
        e["array"] = name
        if "fixed_new_lo" in r:
            e["fixed"] = True                                        # grown in place: absolute new value
        elif r.get("rel_disp") and r["rel_disp"][0] <= old < r["rel_disp"][1]:
            e["kind"] = "base-relative displacement"                  # cg-relative: absolute new value
        else:
            e["new_array_offset"] = f"{(new - r['new_lo']) & 0xFFFFFFFF:#x}"  # operand = new array base + this
    else:
        e["label"] = pe.CUR
    records.append(e)
    orig(dd, ins, old, new)


pe.rewrite_operand = rec
pe.p1_section(d, vsize)
pe.p2_relocate(d)
reloc_ops = list(records)
records.clear()
pe.p4_sizes(d)
size_ops = list(records)

role = lambda va: "server" if va in pe.SERVER_ONLY_VAS else "client"
dual = {va for va, _ in pe.DUAL_SITES}
eng = dict(
    file="iw4x.exe", pristine_md5=pe.PRISTINE_MD5, image_base=f"{pe.IMAGE_BASE:#x}",
    notes=["role 'client' = needed by players, 'server' = only to host more than 18 slots",
           "relocations: allocate each array with new_size bytes (zeroed), then rewrite every operand: "
           "operand = base(array) + new_array_offset; 'fixed' entries are absolute (cg_tail grows cg_s in place, "
           "post_cg_globals must therefore move out of its way)",
           "dual sites: written back to their original bytes while connected to a stock 18-slot server "
           "(engine32c/compat.c e32_set_layout), our bytes on a 32-slot server",
           "hooks: jmp to the injected code (engine32c/*.c/.S), which re-executes the replaced instructions"],
    arrays=[dict(name=r["name"], old_lo=f"{r['lo']:#x}", old_hi=f"{r['hi']:#x}", new_size=f"{r['new_size']:#x}",
                 grown_in_place=("fixed_new_lo" in r), role="server" if r["name"] in pe.SERVER_ONLY_RELOCS else "client",
                 operands=sum(1 for o in reloc_ops if o.get("array") == r["name"]),
                 sentinels={f"{k:#x}": f"{v:#x}" for k, v in r["sentinels"].items()},
                 excluded_sites=[f"{x:#x}" for x in sorted(r["exclude"])]) for r in pe.RELOCS],
    relocation_operands=reloc_ops,
    cvar_domains=[dict(file_offset=f"{off:#x}", va=f"{off + pe.IMAGE_BASE:#x}", old="6a12", new="6a20", what=w, role="server")
                  for off, w in pe.P3_SITES],
    size_constants=[dict(va=f"{va:#x}", old=f"{o:#x}", new=f"{n:#x}", what=w, role=role(va)) for va, o, n, w in pe.P4_SITES],
    size_constant_operands=size_ops,
    code_patches=[dict(va=f"{va:#x}", old=o, new=n, what=w, role=role(va), dual=va in dual) for va, o, n, w in pe.P5_SITES],
    hooks=[dict(va=f"{va:#x}", replaced=o, stub=st, what=w, role=role(va)) for va, o, st, w in pe.P6_HOOKS],
    injected_code="engine32c/: compat.c (layout switch, marker dvars, connect check), antilag.c (32-client lag "
                  "compensation), stubs.S (hook stubs), util.c; built with i686-w64-mingw32-gcc 13, linked at 0x8800000",
)
json.dump(eng, open(os.path.join(out, "engine_patches.json"), "w"), indent=1)

dll = dict(
    file="iw4x.dll", base=f"IW4x {BASE}", md5=pd.BASES[BASE]["md5"],
    notes=["these are binary patches to the release DLL; in iw4x-client source most of them are simply "
           "Game::MAX_CLIENTS = 32 (arrays sized by it, loops/clamps/filters bounded by it) - see README",
           "engine_pointers: the DLL's hard-coded engine addresses of arrays that the engine patch moves"],
    engine_pointers=[dict(file_offset=f"{fo:#x}", array=name, what=w) for fo, name, off, w in pd.ENGINE_PTRS],
    arrays=[dict(name=r["name"], lo=f"{r['lo']:#x}", stride=f"{r['stride']:#x}", n_old=r["n_old"], n_new=32,
                 expect_operands=r["expect"], role="server" if r["name"] in pd.DLL_SERVER_RELOCS else "client")
            for r in pd.DLL_RELOCS],
    constants=[dict(rva=f"{rva:#x}", old=o, new=n, what=w) for rva, o, n, w in pd.CONSTS],
)
# note: pd tables above are the r5121 originals until translate_tables(); translate for r5154 RVAs
pd.translate_tables(BASE)
dll["engine_pointers"] = [dict(file_offset=f"{fo:#x}", array=name, what=w) for fo, name, off, w in pd.ENGINE_PTRS]
dll["arrays"] = [dict(name=r["name"], lo=f"{r['lo']:#x}", stride=f"{r['stride']:#x}", n_old=r["n_old"], n_new=32,
                      expect_operands=r["expect"], role="server" if r["name"] in pd.DLL_SERVER_RELOCS else "client")
                 for r in pd.DLL_RELOCS]
dll["constants"] = [dict(rva=f"{rva:#x}", old=o, new=n, what=w, role="server" if w in SERVER_LABELS else "client")
                    for rva, o, n, w in pd.CONSTS]
dll["rdata_constants"] = [dict(rva=f"{rva:#x}", old=o, new=n, what=w, role="server") for rva, o, n, w in pd.RDATA_CONSTS]
json.dump(dll, open(os.path.join(out, "dll_patches.json"), "w"), indent=1)
print(f"engine: {len(eng['arrays'])} arrays, {len(reloc_ops)} relocated operands, {len(eng['size_constants'])} size constants, "
      f"{len(eng['code_patches'])} code patches ({sum(1 for c in eng['code_patches'] if c['dual'])} dual), {len(eng['hooks'])} hooks")
print(f"dll: {len(dll['engine_pointers'])} engine pointers, {len(dll['arrays'])} arrays, {len(dll['constants'])} constants")
