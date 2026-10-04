"""manifest_lib.py — turn a build's recorded writes into a release manifest: every byte that differs between the
official IW4x file and ours, with the reason. Used by patch_engine.py / patch_dll.py --manifest. The shipped checker
(release/iw4x32_check.py) verifies a file against it or rebuilds our file from the official one."""
import hashlib, json


def build_manifest(src, out, writes, meta):
    src, out = bytes(src), bytes(out)
    covered = bytearray(len(out))
    for fo, n, _ in writes:
        for i in range(fo, min(fo + n, len(out))):
            covered[i] = 1
    for i in range(len(out)):
        changed = i >= len(src) or src[i] != out[i]
        if changed and not covered[i]:
            raise SystemExit(f"manifest: byte {i:#x} changed but not recorded")
    if len(out) < len(src):
        raise SystemExit("manifest: output shorter than the official file")
    entries, seen = [], set()
    for fo, n, label in sorted(writes, key=lambda w: (w[0], w[1])):
        key = (fo, n)
        if key in seen:
            continue
        seen.add(key)
        old = src[fo:fo + n] if fo < len(src) else b""
        new = out[fo:fo + n]
        if old == new:
            continue
        entries.append(dict(offset=f"{fo:#x}", length=n, old=old.hex(), new=new.hex(), why=label))
    m = dict(meta)
    m.update(official_size=len(src), official_sha256=hashlib.sha256(src).hexdigest(),
             official_md5=hashlib.md5(src).hexdigest(),
             ours_size=len(out), ours_sha256=hashlib.sha256(out).hexdigest(), ours_md5=hashlib.md5(out).hexdigest(),
             changed_bytes=sum(1 for i in range(len(out)) if i >= len(src) or src[i] != out[i]),
             entries=entries)
    return m


def write_manifest(path, src, out, writes, meta):
    m = build_manifest(src, out, writes, meta)
    with open(path, "w") as f:
        json.dump(m, f, indent=1)
    print(f"manifest {path}: {len(m['entries'])} entries, {m['changed_bytes']} changed bytes")
