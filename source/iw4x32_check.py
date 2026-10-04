#!/usr/bin/env python3
"""iw4x32_check.py - check or rebuild the IW4x-32 files from YOUR OWN official IW4x files.

Plain Python 3 (no extra packages). Run it from the IW4x-32 folder, or anywhere with explicit paths.

  python iw4x32_check.py                      after installing: checks files\\ against backup\\ (your official files)
  python iw4x32_check.py verify OURS OFFICIAL MANIFEST
                                              every byte of OURS that differs from OFFICIAL must be listed in
                                              MANIFEST (with the reason), and nothing else may differ
  python iw4x32_check.py build OFFICIAL MANIFEST OUT
                                              make the IW4x-32 file yourself from your official file (no need to
                                              trust our binaries: the result must hash to the published SHA-256)
  python iw4x32_check.py explain MANIFEST     list every change and why

The manifests are source\\manifest_iw4x_exe.json and source\\manifest_iw4x_dll.json.
"""
import hashlib, json, os, struct, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def apply(official, m):
    if sha256(official) != m["official_sha256"]:
        raise SystemExit(f"  your official {m['file']} is not the version this release was made from "
                         f"(sha256 {sha256(official)} != {m['official_sha256']})")
    out = bytearray(official) + bytearray(max(0, m["ours_size"] - len(official)))
    for e in m["entries"]:
        off, old, new = int(e["offset"], 16), bytes.fromhex(e["old"]), bytes.fromhex(e["new"])
        if bytes(official[off:off + len(old)]) != old:
            raise SystemExit(f"  manifest entry {e['offset']}: official bytes differ")
        out[off:off + len(new)] = new
    return bytes(out)


def pe_sections(b):
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    n = struct.unpack_from("<H", b, pe + 6)[0]
    opt = pe + 24
    sect = opt + struct.unpack_from("<H", b, pe + 20)[0]
    out = []
    for i in range(n):
        o = sect + 40 * i
        name = b[o:o + 8].rstrip(b"\0").decode("latin1")
        vsize, va, rsize, roff = struct.unpack_from("<IIII", b, o + 8)
        flags = struct.unpack_from("<I", b, o + 36)[0]
        out.append((name, va, vsize, roff, rsize, flags))
    return opt, out


def pe_imports(b):
    opt, secs = pe_sections(b)
    magic = struct.unpack_from("<H", b, opt)[0]
    dd = opt + (96 if magic == 0x10B else 112)
    imp_rva = struct.unpack_from("<I", b, dd + 8)[0]

    def off(rva):
        for _, va, vs, ro, rs, _ in secs:
            if va <= rva < va + max(vs, rs):
                return rva - va + ro
        return None

    res, o = [], off(imp_rva)
    while o is not None:
        ilt, _, _, name_rva, iat = struct.unpack_from("<IIIII", b, o)
        if not name_rva:
            break
        no = off(name_rva)
        dll = b[no:b.index(b"\0", no)].decode("latin1").lower()
        t = off(ilt or iat)
        while t is not None:
            v = struct.unpack_from("<I", b, t)[0]
            if not v:
                break
            if v & 0x80000000:
                res.append(f"{dll}!#{v & 0xFFFF}")
            else:
                h = off(v)
                res.append(f"{dll}!{b[h + 2:b.index(b'\0', h + 2)].decode('latin1')}")
            t += 4
        o += 20
    return sorted(res)


def strings_in(b, lo, hi, n=5):
    out, cur = [], bytearray()
    for c in b[lo:hi]:
        if 32 <= c < 127:
            cur.append(c)
        else:
            if len(cur) >= n:
                out.append(cur.decode())
            cur = bytearray()
    return out


def verify(ours_path, official_path, manifest_path):
    m = json.load(open(manifest_path))
    ours, official = open(ours_path, "rb").read(), open(official_path, "rb").read()
    print(f"== {m['file']} ({m['build']})")
    print(f"   official: {official_path}  sha256 {sha256(official)}")
    print(f"   ours    : {ours_path}  sha256 {sha256(ours)}")
    if sha256(ours) != m["ours_sha256"]:
        raise SystemExit("   FAIL: this is not the published IW4x-32 file (sha256 differs)")
    rebuilt = apply(official, m)
    if rebuilt != ours:
        raise SystemExit("   FAIL: official file + listed changes != our file (an unlisted change exists)")
    changed = sum(1 for i in range(len(ours)) if i >= len(official) or ours[i] != official[i])
    print(f"   OK: every one of the {changed} changed bytes is listed in the manifest ({len(m['entries'])} entries)")
    kinds = Counter(e["why"].split(":")[0].split(" (")[0][:60] for e in m["entries"])
    for k, n in kinds.most_common(12):
        print(f"      {n:4d} x {k}")
    a, b = pe_imports(official), pe_imports(ours)
    print("   imports (Windows APIs the file can call): " + ("IDENTICAL to the official file" if a == b else
          f"DIFFER: added {sorted(set(b) - set(a))}, removed {sorted(set(a) - set(b))}"))
    _, so = pe_sections(official)
    _, sn = pe_sections(ours)
    names = {s[0] for s in so}
    for name, va, vs, ro, rs, flags in sn:
        if name in names:
            continue
        kind = "code" if flags & 0x20000000 else "data"
        print(f"   new section {name}: {kind}, {vs:#x} bytes in memory, {rs:#x} bytes in the file")
        if rs:
            st = strings_in(ours, ro, ro + rs)
            print(f"      all text strings inside it: {st}")
    return True


def main():
    a = sys.argv[1:]
    if not a:
        pairs = [("iw4x.exe", "manifest_iw4x_exe.json"), ("iw4x.dll", "manifest_iw4x_dll.json")]
        ok = True
        for f, man in pairs:
            ours, off = os.path.join(KIT, "files", f), os.path.join(KIT, "backup", f)
            if not os.path.exists(off):
                print(f"{off} not found: install first (the installer backs up your official files), or use:\n"
                      f"  python iw4x32_check.py verify <our {f}> <your official {f}> {man}")
                ok = False
                continue
            verify(ours, off, os.path.join(HERE, man))
        return 0 if ok else 1
    if a[0] == "verify" and len(a) == 4:
        verify(a[1], a[2], a[3])
    elif a[0] == "build" and len(a) == 4:
        m = json.load(open(a[2]))
        out = apply(open(a[1], "rb").read(), m)
        if sha256(out) != m["ours_sha256"]:
            raise SystemExit("FAIL: rebuilt file does not match the published hash")
        open(a[3], "wb").write(out)
        print(f"wrote {a[3]}  sha256 {sha256(out)} (matches the published IW4x-32 {m['file']})")
    elif a[0] == "explain" and len(a) == 2:
        m = json.load(open(a[1]))
        print(f"{m['file']} {m['build']}: {len(m['entries'])} changes, {m['changed_bytes']} bytes")
        for e in m["entries"]:
            print(f"  {e['offset']:>9} +{e['length']:<5} {e['why']}")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
