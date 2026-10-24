#!/usr/bin/env python3
"""make_latest.py - write the IW4x-32 player kit's hash files: latest.json (repo root) and SHA256SUMS.txt (kit).

    python3 iw4x32/tools/make_latest.py [--dll PATH] [--version v2.6-r5278] [--iw4x r5278] [--kit DIR] [--out FILE]

  --dll PATH   copy a built Release iw4x.dll into <kit>/files/iw4x.dll before hashing (what the release
               workflow does; without it the kit's committed DLL is used as it is)
  --version    the release version: latest.json's "version", the tag in base_url and README.txt line 1
  --iw4x       the official IW4x release this kit is made for

What it writes:
  - the OFFICIAL_DLL / OFFICIAL_EXE / OFFICIAL_VER constants in the launchers (files/iw4x32.ps1, files/iw4x32.py)
    are set to the official IW4x release the kit is made for;
  - <kit>/files/SHA256SUMS.txt: "sha256  path" for every kit file (CRLF, plain sha256sum format, for players);
  - latest.json at the repo root: what the installed players' auto-update reads (see iw4x32_update.py/.ps1) -
    version, the official IW4x hashes it repairs to, base_url (the tag's copy of the kit on GitHub raw) and the
    SHA-256 of every kit file. "legacy" names the v2.0 compatibility shims (top-level iw4x32_update.ps1/.py): they
    are listed so that a v2.0 updater fetches them, the zip leaves them out and v2.1+ launchers skip them.
Bytes are hashed exactly as they sit in the tree: GitHub raw serves them unchanged (see the -text rule for the
kit in .gitattributes), and the updater compares those bytes' SHA-256 with what is written here."""
import argparse, hashlib, json, os, re, shutil, sys
import next_version                                   # the version format: iw4x32/tools/next_version.py

REPO = "shaunypnz/iw4x-32"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# official IW4x files per release - what a player's game folder must hold before we put our dll over it. A new
# upstream release: add its iw4x.dll SHA-256 (the release asset) here; iw4x.exe comes from the launcher and rarely changes.
OFFICIAL_BY_IW4X = {
    "r5154": {"iw4x.dll": "82819f1a0c8e3758af8acb8773dc2e2f5cc069202b995e79772a23c9551236cd",
              "iw4x.exe": "49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009"},
    "r5168": {"iw4x.dll": "e0d8adc473f04f2d0988cffec3ecb8128e9faeba1e169c0acb13118d29aff6ea",
              "iw4x.exe": "49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009"},
    "r5250": {"iw4x.dll": "4c895880fabdd627e071c8f2b558d90286a4bd088373f57ca4a7d59aa9cb59a0",
              "iw4x.exe": "49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009"},
    "r5275": {"iw4x.dll": "5e4bdedf1c7bd5ca08bf3844549d1c915118491d8dbba7385b93c0ca9072d862",
              "iw4x.exe": "49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009"},
    "r5278": {"iw4x.dll": "57922527bbbb5dd5a256b8a6243179eb5e28d7e2bcc7bbf53f5ace0518f6da1c",
              "iw4x.exe": "49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009"},
    "r5292": {"iw4x.dll": "890a310c9b594824ff3da71d24647821991c9ab5d1f2f9870fd9a07cb2341ba4",
              "iw4x.exe": "49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009"},
}
# the constants as the launchers write them:  $OFFICIAL_DLL = '...'  (ps1)  /  OFFICIAL_DLL = "..."  (py)
OFFICIAL_CONST = {k: re.compile(rf"^(\$?OFFICIAL_{k} = [\"'])[0-9A-Za-z_]*", re.M) for k in ("DLL", "EXE", "VER")}
SUMS = "files/SHA256SUMS.txt"
LEGACY = ["iw4x32_update.ps1", "iw4x32_update.py"]   # v2.0 shims: in the manifest, not in the zip


def sha(b):
    return hashlib.sha256(b).hexdigest()


JUNK = re.compile(r"(^|/)(__pycache__|\.git|\.DS_Store|Thumbs\.db)|\.pyc$|~$")


def kit_files(kit):
    """every kit file, path relative to the kit, SHA256SUMS.txt itself excluded (it lists the others).
    Build/editor leftovers (__pycache__, .pyc, dotfiles, backup tildes) are never kit files: players
    download everything listed, so a stray .pyc in the kit folder must not end up in the manifest."""
    out = []
    for d, sub, names in os.walk(kit):
        sub[:] = sorted(dn for dn in sub if not JUNK.search(dn))
        for n in sorted(names):
            p = os.path.relpath(os.path.join(d, n), kit).replace(os.sep, "/")
            if p != SUMS and not JUNK.search(p):
                out.append(p)
    return sorted(out)


def sync_official(kit, iw4x, off):
    """set OFFICIAL_DLL= / OFFICIAL_EXE= / OFFICIAL_VER= in the installers to the official IW4x release the kit is for"""
    done = []
    want = {"DLL": off["iw4x.dll"], "EXE": off["iw4x.exe"], "VER": iw4x}
    for p in kit_files(kit):
        if not p.endswith((".ps1", ".py")):
            continue
        text = open(os.path.join(kit, p), "rb").read().decode("utf-8")
        new = text
        for k, rx in OFFICIAL_CONST.items():
            new = rx.sub(lambda m, v=want[k]: m.group(1) + v, new)
        if new != text:
            open(os.path.join(kit, p), "wb").write(new.encode("utf-8"))
            done.append(p)
    return done


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--dll", help="built iw4x.dll to copy into the kit first")
    ap.add_argument("--version", default="v2.0")
    ap.add_argument("--iw4x", default="r5168", choices=sorted(OFFICIAL_BY_IW4X))
    ap.add_argument("--kit", default=os.path.join(ROOT, "iw4x32", "release"))
    ap.add_argument("--out", default=os.path.join(ROOT, "latest.json"))
    a = ap.parse_args()

    try:
        next_version.check(a.version, a.iw4x)               # v2.N-rNNNN, its rNNNN = --iw4x
    except ValueError as e:
        sys.exit(f"make_latest: {e}")
    if a.dll:
        dst = os.path.join(a.kit, "files", "iw4x.dll")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(a.dll, dst)
        os.chmod(dst, 0o644)
        print(f"make_latest: {a.dll} -> {os.path.relpath(dst, ROOT)}")
    dll = os.path.join(a.kit, "files", "iw4x.dll")
    if not os.path.isfile(dll):
        sys.exit(f"make_latest: {dll} is missing - build Release and pass --dll, or copy the DLL in by hand")

    OFFICIAL = OFFICIAL_BY_IW4X[a.iw4x]
    for p in sync_official(a.kit, a.iw4x, OFFICIAL):
        print(f"make_latest: official IW4x {a.iw4x} hashes set in {p}")
    digest = sha(open(dll, "rb").read())

    files = {p: sha(open(os.path.join(a.kit, p), "rb").read()) for p in kit_files(a.kit)}
    sums = os.path.join(a.kit, *SUMS.split("/"))
    with open(sums, "wb") as f:
        for p, h in files.items():
            if p not in LEGACY:
                f.write(f"{h}  {p}\r\n".encode())
    files[SUMS] = sha(open(sums, "rb").read())

    manifest = {"version": a.version, "iw4x": a.iw4x, "official": OFFICIAL,
                "base_url": f"https://raw.githubusercontent.com/{REPO}/{a.version}/iw4x32/release/",
                "files": files, "legacy": [p for p in LEGACY if p in files]}
    with open(a.out, "w", newline="\n") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    print(f"make_latest: {os.path.relpath(a.out, ROOT)} - {a.version} on {a.iw4x}, {len(files)} file(s), "
          f"iw4x.dll {digest[:12]}...")


if __name__ == "__main__":
    main()
