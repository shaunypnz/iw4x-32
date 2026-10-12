#!/usr/bin/env python3
"""
gen_tables.py — turn the patched builds into in-memory patch tables for the IW4x-32 loader.

    python3 loader/gen_tables.py --exe-new <A.exe> --exe-alt <B.exe> --dll-new <A.dll> --dll-alt <B.dll>
    (A = normal build, B = same build with --alt-layout; see loader/build_tables.sh)

The loader (loader.c, a binkw32.dll proxy) applies to the UNMODIFIED r5121 iw4x.exe/iw4x.dll, in
memory, the bytes patch_engine.py / patch_dll.py write into the patched files, so the patch scripts
stay the single source of truth. Nothing is assumed about where memory is free: the engine's two
appended blocks (.iw432 data, .iw4c code) are allocated wherever the OS puts them, and every patched
4-byte slot that refers to them is fixed up at runtime.

Finding those slots: build B moves .iw432 by +0x10000000 and .iw4c by +0x40000000. Every byte that
differs between A and B is the top byte of a slot whose value changed by a*0x10000000 + c*0x40000000
with a, c in {-1, 0, 1} (all 8 combinations have distinct top bytes); the loader adds
a*(data_alloc - data_va) + c*(code_alloc - code_va). Absolute pointers into a block get +1, a rel32
jump from a fixed engine site into .iw4c gets c=+1, a rel32 from .iw4c code to a fixed engine
address gets c=-1.

DLL: relocatable, so runs are widened to whole .reloc slots; slots the ORIGINAL .reloc rebases give
the expected in-memory old bytes (+delta), slots the PATCHED .reloc rebases get +delta or, if they
point into the appended .iw432d, the loader's allocation for it. Slots that point into the engine's
.iw432 (D1 engine pointers) are found with the same A/B diff (a=+1).
"""
import argparse, hashlib, os, struct, sys

import pefile

MODDED = "~/Projects/Call of Duty Modern Warfare 2 - modded"
D_DATA, D_CODE = 0x10000000, 0x40000000
TOP = {}
for a in (-1, 0, 1):
    for c in (-1, 0, 1):
        if a or c:
            TOP[((a * D_DATA + c * D_CODE) >> 24) & 0xFF] = (a, c)
assert len(TOP) == 8


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def image(pe, size):
    img = bytearray(pe.get_memory_mapped_image())
    return img + bytearray(max(0, size - len(img)))


def resolve(p):
    return p if os.path.exists(p) else os.path.join(MODDED, p)


def reloc_slots(pe):
    s = set()
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_BASERELOC"]])
    for blk in getattr(pe, "DIRECTORY_ENTRY_BASERELOC", []):
        for e in blk.entries:
            if e.type == 3:  # HIGHLOW
                s.add(e.rva)
    return s


def ab_fixups(A, B, lo, hi, where):
    """slot offset -> kind for every A/B difference in [lo, hi)"""
    fx = {}
    for i in range(lo, hi):
        if A[i] == B[i]:
            continue
        t = (B[i] - A[i]) & 0xFF
        if t not in TOP:
            sys.exit(f"{where}: byte {i:#x} changes by {t:#x}, not a known block shift")
        s = i - 3
        a, c = TOP[t]
        va, vb = struct.unpack_from("<I", A, s)[0], struct.unpack_from("<I", B, s)[0]
        if (vb - va) & 0xFFFFFFFF != (a * D_DATA + c * D_CODE) & 0xFFFFFFFF:
            sys.exit(f"{where}: slot {s:#x} {va:#x}->{vb:#x} is not a clean block shift")
        fx[s] = (a + 1) + 3 * (c + 1)          # 0..8, 4 = none
    return fx


def merge(spans):
    spans.sort()
    out = []
    for lo, hi in spans:
        if out and lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def diff_spans(X, Y, lo, hi):
    out, i = [], lo
    while i < hi:
        if X[i] != Y[i]:
            j = i
            while j < hi and X[j] != Y[j]:
                j += 1
            out.append([i, j])
            i = j
        else:
            i += 1
    return out


def carr(name, data, ctype="unsigned char"):
    body = ",".join(str(x) for x in data) if len(data) else "0"
    return f"static const {ctype} {name}[] = {{{body}}};\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe-orig", default=os.path.join(MODDED, "iw4x.exe.orig32"))
    ap.add_argument("--exe-new", required=True)
    ap.add_argument("--exe-alt", required=True)
    ap.add_argument("--dll-orig", default=os.path.join(MODDED, "iw4x.dll.orig-msvc"))
    ap.add_argument("--dll-new", required=True)
    ap.add_argument("--dll-alt", required=True)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "tables.h"))
    a = ap.parse_args()
    exe_new, exe_alt, dll_new, dll_alt = map(resolve, (a.exe_new, a.exe_alt, a.dll_new, a.dll_alt))

    # ---------------- exe ----------------
    eo, ea, eb = pefile.PE(a.exe_orig), pefile.PE(exe_new), pefile.PE(exe_alt)
    base = eo.OPTIONAL_HEADER.ImageBase
    osize = eo.OPTIONAL_HEADER.SizeOfImage
    O, A, B = image(eo, osize), image(ea, osize), image(eb, osize)
    hdr = eo.sections[0].VirtualAddress
    fx = ab_fixups(A, B, hdr, osize, "exe")
    spans = diff_spans(O, A, hdr, osize) + diff_spans(O, B, hdr, osize) + [[s, s + 4] for s in fx]
    erun = merge(spans)
    eold, enew, etab, efix = [], [], [], []
    for lo, hi in erun:
        f = sorted(s for s in fx if lo <= s < hi)
        etab.append((base + lo, hi - lo, len(eold), len(efix), len(f)))
        efix += [(s - lo, fx[s]) for s in f]
        eold += O[lo:hi]
        enew += A[lo:hi]
    blocks = []
    secs_b = {s.Name: s for s in eb.sections}
    for sc in ea.sections:
        if sc.VirtualAddress < osize:
            continue
        name = sc.Name.rstrip(b"\0").decode()
        sb = secs_b[sc.Name]
        vsize = (max(sc.Misc_VirtualSize, sc.SizeOfRawData) + 0xFFF) & ~0xFFF
        rawA = bytes(sc.get_data()[:sc.SizeOfRawData]) if sc.SizeOfRawData else b""
        rawB = bytes(sb.get_data()[:sb.SizeOfRawData]) if sb.SizeOfRawData else b""
        bf = ab_fixups(bytearray(rawA), bytearray(rawB), 0, len(rawA), name) if rawA else {}
        blocks.append(dict(name=name, va=base + sc.VirtualAddress, vsize=vsize, raw=rawA,
                           exec=bool(sc.Characteristics & 0x20000000), fix=sorted(bf.items())))
    data_blk = [b for b in blocks if b["name"] == ".iw432"][0]
    code_blk = [b for b in blocks if b["name"] == ".iw4c"][0]

    # ---------------- dll ----------------
    do, da, db = pefile.PE(a.dll_orig), pefile.PE(dll_new), pefile.PE(dll_alt)
    pref = do.OPTIONAL_HEADER.ImageBase
    dosize = do.OPTIONAL_HEADER.SizeOfImage
    C, D, E = image(do, dosize), image(da, dosize), image(db, dosize)
    ro, rn = reloc_slots(do), reloc_slots(da)
    reloc_sec = [sc for sc in da.sections if sc.Name.startswith(b".reloc")][0]
    rlo, rhi = reloc_sec.VirtualAddress, reloc_sec.VirtualAddress + reloc_sec.Misc_VirtualSize
    newsec = [sc for sc in da.sections if sc.VirtualAddress >= dosize]
    if len(newsec) != 1 or newsec[0].SizeOfRawData:
        sys.exit("expected exactly one zero-fill appended DLL section")
    ns = newsec[0]
    ns_lo, ns_hi = ns.VirtualAddress, ns.VirtualAddress + ((ns.Misc_VirtualSize + 0xFFF) & ~0xFFF)
    dlo = do.sections[0].VirtualAddress
    efx = {s: k for s, k in ab_fixups(D, E, dlo, dosize, "dll").items() if not (rlo <= s < rhi)}
    for s, k in efx.items():
        if k != (1 + 1) + 3 * (0 + 1):
            sys.exit(f"dll slot {s:#x}: unexpected block kind {k}")
        if s in ro or s in rn:
            sys.exit(f"dll slot {s:#x}: engine pointer slot also has a .reloc entry")
    spans = [sp for sp in diff_spans(C, D, dlo, dosize) if not (rlo <= sp[0] < rhi)] + [[s, s + 4] for s in efx]
    widened = []
    for lo, hi in spans:
        changed = True
        while changed:
            changed = False
            for r in range(lo - 3, hi):
                if (r in ro or r in rn) and (r < lo or r + 4 > hi):
                    lo, hi = min(lo, r), max(hi, r + 4)
                    changed = True
        widened.append([lo, hi])
    drun = merge(widened)
    dold, dnew, dtab, dslots = [], [], [], []
    n_into_new = 0
    for lo, hi in drun:
        so = [r - lo for r in range(lo, hi) if r in ro]
        sn = [r - lo for r in range(lo, hi) if r in rn]
        se = [r - lo for r in range(lo, hi) if r in efx]
        for r in sn:
            v = struct.unpack_from("<I", D, lo + r)[0]
            if pref + ns_lo <= v < pref + ns_hi:
                n_into_new += 1
        dtab.append((lo, hi - lo, len(dold), len(dslots), len(so), len(sn), len(se)))
        dslots += so + sn + se
        dold += C[lo:hi]
        dnew += D[lo:hi]

    # ---------------- emit ----------------
    o = ["/* generated by loader/gen_tables.py — do not edit */\n#pragma once\n",
         f'#define EXE_ORIG_MD5 "{md5(a.exe_orig)}"\n#define DLL_ORIG_MD5 "{md5(a.dll_orig)}"\n',
         f'#define EXE_SRC "{os.path.basename(exe_new)}"  /* md5 {md5(exe_new)} */\n',
         f'#define DLL_SRC "{os.path.basename(dll_new)}"  /* md5 {md5(dll_new)} */\n',
         "/* fixup kind k: value += ((k % 3) - 1) * data_delta + ((k / 3) - 1) * code_delta */\n",
         "typedef struct { unsigned va; unsigned short len; unsigned off; unsigned fix; unsigned short nfix; } exe_run_t;\n",
         "typedef struct { unsigned short off; unsigned char kind; } fix_t;\n",
         "typedef struct { unsigned rva; unsigned short len; unsigned off; unsigned short slot; unsigned char nold, nnew, neng; } dll_run_t;\n",
         f"#define EXE_NRUNS {len(etab)}\n#define DLL_NRUNS {len(dtab)}\n",
         f"#define DATA_VA {data_blk['va']:#x}\n#define DATA_SIZE {data_blk['vsize']:#x}\n",
         f"#define CODE_VA {code_blk['va']:#x}\n#define CODE_SIZE {code_blk['vsize']:#x}\n#define CODE_RAWLEN {len(code_blk['raw'])}\n",
         f"#define CODE_NFIX {len(code_blk['fix'])}\n"]
    if data_blk["raw"] or data_blk["fix"]:
        sys.exit(".iw432 is expected to be zero-fill")
    o.append(carr("exe_old", eold))
    o.append(carr("exe_new", enew))
    o.append("static const exe_run_t exe_runs[] = {" + ",".join(f"{{{va:#x},{n},{off},{fi},{nf}}}" for va, n, off, fi, nf in etab) + "};\n")
    o.append("static const fix_t exe_fix[] = {" + (",".join(f"{{{s},{k}}}" for s, k in efix) or "{0,4}") + "};\n")
    o.append(carr("code_raw", code_blk["raw"]))
    o.append("static const struct { unsigned off; unsigned char kind; } code_fix[] = {" +
             (",".join(f"{{{s},{k}}}" for s, k in code_blk["fix"]) or "{0,4}") + "};\n")
    o.append(f"#define DLL_PREF_BASE {pref:#x}\n#define DLL_NEWSEC_RVA {ns_lo:#x}\n#define DLL_NEWSEC_SIZE {ns_hi - ns_lo:#x}\n")
    o.append(carr("dll_old", dold))
    o.append(carr("dll_new", dnew))
    o.append(carr("dll_slots", dslots, "unsigned short"))
    o.append("static const dll_run_t dll_runs[] = {" + ",".join(
        f"{{{rva:#x},{n},{off},{sl},{nold},{nnew},{neng}}}" for rva, n, off, sl, nold, nnew, neng in dtab) + "};\n")
    open(a.out, "w").write("".join(o))
    kinds = {}
    for _, k in efix:
        kinds[k] = kinds.get(k, 0) + 1
    print(f"exe: {len(etab)} runs, {len(eold)} bytes, {len(efix)} block fixups {dict(sorted(kinds.items()))}")
    print(f"     .iw432 {data_blk['vsize']:#x} zero-fill; .iw4c {len(code_blk['raw'])} bytes, {len(code_blk['fix'])} internal fixups "
          f"{dict((k, sum(1 for _, x in code_blk['fix'] if x == k)) for k in sorted({x for _, x in code_blk['fix']}))}")
    print(f"dll: {len(dtab)} runs, {len(dold)} bytes, {sum(t[4] for t in dtab)} old reloc / {sum(t[5] for t in dtab)} new reloc "
          f"({n_into_new} into .iw432d) / {sum(t[6] for t in dtab)} engine-.iw432 slots")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
