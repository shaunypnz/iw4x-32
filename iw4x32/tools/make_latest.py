#!/usr/bin/env python3
"""make_latest.py - write the IW4x-32 player kit's hash files: latest.json (repo root) and SHA256SUMS.txt (kit).

    python3 iw4x32/tools/make_latest.py [--dll PATH] [--version v2.0] [--iw4x r5154] [--kit DIR] [--out FILE]

  --dll PATH   copy a built Release iw4x.dll into <kit>/files/iw4x.dll before hashing (what the release
               workflow does; without it the kit's committed DLL is used as it is)
  --version    the release version: latest.json's "version", the tag in base_url and README.txt line 1
  --iw4x       the official IW4x release this kit is made for

What it writes:
  - the OURS_DLL= constants in the kit's installers/start scripts are set to the SHA-256 of the kit's
    files/iw4x.dll, so an installer can never carry a hash of a DLL that is not in the kit;
  - <kit>/SHA256SUMS.txt: "sha256  path" for every kit file (CRLF, plain sha256sum format, for players);
  - latest.json at the repo root: what the installed players' auto-update reads (see iw4x32_update.py/.ps1) -
    version, the official IW4x hashes it repairs to, base_url (the tag's copy of the kit on GitHub raw) and the
    SHA-256 of every kit file.
Bytes are hashed exactly as they sit in the tree: GitHub raw serves them unchanged (see the -text rule for the
kit in .gitattributes), and the updater compares those bytes' SHA-256 with what is written here."""
import argparse, hashlib, json, os, re, shutil, sys

REPO = "shaunypnz/iw4x-32"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# official IW4x r5154 files - what a player's game folder must hold before we put our dll over it
OFFICIAL = {"iw4x.dll": "82819f1a0c8e3758af8acb8773dc2e2f5cc069202b995e79772a23c9551236cd",
            "iw4x.exe": "49ea90e34c9cd64d9d0ae7f4b399e4ecc5ea13976823b2b8667390a4b8767009"}
OURS_CONST = re.compile(r"^(\s*(?:set \"?)?OURS_DLL=)[0-9A-Za-z_]*", re.M)


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
            if p != "SHA256SUMS.txt" and not JUNK.search(p):
                out.append(p)
    return sorted(out)


def sync_ours_dll(kit, digest):
    """set the OURS_DLL= constant every installer/start script checks against, to the kit's dll"""
    done = []
    for p in kit_files(kit):
        if not p.endswith((".bat", ".sh")):
            continue
        raw = open(os.path.join(kit, p), "rb").read()
        text = raw.decode("utf-8")
        new = OURS_CONST.sub(lambda m: m.group(1) + digest, text)
        if new != text:
            open(os.path.join(kit, p), "wb").write(new.encode("utf-8"))
            done.append(p)
    return done


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--dll", help="built iw4x.dll to copy into the kit first")
    ap.add_argument("--version", default="v2.0")
    ap.add_argument("--iw4x", default="r5154")
    ap.add_argument("--kit", default=os.path.join(ROOT, "iw4x32", "release"))
    ap.add_argument("--out", default=os.path.join(ROOT, "latest.json"))
    a = ap.parse_args()

    if not re.fullmatch(r"v\d+(\.\d+)*", a.version):
        sys.exit(f"make_latest: version must look like v2.0, got {a.version!r}")
    if a.dll:
        dst = os.path.join(a.kit, "files", "iw4x.dll")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(a.dll, dst)
        os.chmod(dst, 0o644)
        print(f"make_latest: {a.dll} -> {os.path.relpath(dst, ROOT)}")
    dll = os.path.join(a.kit, "files", "iw4x.dll")
    if not os.path.isfile(dll):
        sys.exit(f"make_latest: {dll} is missing - build Release and pass --dll, or copy the DLL in by hand")

    digest = sha(open(dll, "rb").read())
    for p in sync_ours_dll(a.kit, digest):
        print(f"make_latest: OURS_DLL set in {p}")

    files = {p: sha(open(os.path.join(a.kit, p), "rb").read()) for p in kit_files(a.kit)}
    sums = os.path.join(a.kit, "SHA256SUMS.txt")
    with open(sums, "wb") as f:
        for p, h in files.items():
            f.write(f"{h}  {p}\r\n".encode())
    files["SHA256SUMS.txt"] = sha(open(sums, "rb").read())

    manifest = {"version": a.version, "iw4x": a.iw4x, "official": OFFICIAL,
                "base_url": f"https://raw.githubusercontent.com/{REPO}/{a.version}/iw4x32/release/",
                "files": files}
    with open(a.out, "w", newline="\n") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    print(f"make_latest: {os.path.relpath(a.out, ROOT)} - {a.version} on {a.iw4x}, {len(files)} file(s), "
          f"iw4x.dll {digest[:12]}...")


if __name__ == "__main__":
    main()
