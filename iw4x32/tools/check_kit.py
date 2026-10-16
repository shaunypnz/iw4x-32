#!/usr/bin/env python3
"""
check_kit.py - the IW4x-32 player kit must be installable as it stands:

    python3 iw4x32/tools/check_kit.py [--root DIR]

  - latest.json (repo root) parses and names the version, the IW4x release it is made for and a base_url
    that points at that tag's copy of the kit;
  - every file it lists exists in iw4x32/release/ with exactly that SHA-256, and every kit file is listed
    (an unlisted file would never reach a player);
  - no installer or updater installs an iw4x.exe: the kit carries no files/iw4x.exe, nothing refers to one,
    and the only iw4x.exe any of them writes is a restore from backup/ (v1.x leftovers);
  - the layout a player sees is IW4x-32.bat, IW4x-32.sh, README.txt and files/ - nothing else at the top (the
    v2.0 shims iw4x32_update.ps1/.py are the only exception: listed as "legacy" in latest.json, left out of the
    zip); the launchers files/iw4x32.ps1 and files/iw4x32.py are there, .sh/.py executable in git;
  - the OFFICIAL_DLL/EXE/VER constants in the launchers match latest.json's official IW4x release, and README.txt
    line 1 states latest.json's version (the updater reads it to know what it has);
  - .bat/.ps1/.txt keep CRLF, .sh/.py keep LF, and .gitattributes keeps the kit's bytes verbatim
    (GitHub raw serves them as-is and the updater checks those hashes);
  - .github/workflows/iw4x32-release.yml parses and triggers on a v* tag, builds Release|Win32 on
    windows-2022 and publishes the kit with ncipollo/release-action@v1.

Exits 1 with everything it found wrong. Run iw4x32/tools/make_latest.py to rewrite the hashes."""
import argparse, hashlib, json, os, re, sys

try:
    import yaml
except ImportError:
    yaml = None

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(os.path.dirname(HERE))
REPO = "shaunypnz/iw4x-32"
SUMS = "files/SHA256SUMS.txt"
TOP = {"IW4x-32.bat", "IW4x-32.sh", "README.txt", "files"}
LEGACY = {"iw4x32_update.ps1", "iw4x32_update.py"}
SCRIPTS = (".bat", ".sh", ".ps1", ".py")
CRLF_EXT, LF_EXT = (".bat", ".ps1", ".txt"), (".sh", ".py")
# a line that writes an iw4x.exe into the game folder: only a restore from backup/ is allowed
COPY = re.compile(r"(?<![\w/])(copy|cp|mv)\b|Copy-Item|shutil\.copy|Move-Item", re.I)
GAME_EXE = re.compile(r"""GAME%?["']?\s*[\\/]\s*iw4x\.exe|GAME\s*,\s*["']iw4x\.exe|Game\s+["']iw4x\.exe|\bG\(?\s*["']iw4x\.exe""")
KIT_EXE = re.compile(r"files[\\/][\"']?iw4x\.exe", re.I)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def kit_files(kit):
    out = []
    for d, sub, names in os.walk(kit):
        sub.sort()
        for n in sorted(names):
            p = os.path.relpath(os.path.join(d, n), kit).replace(os.sep, "/")
            if p != SUMS:
                out.append(p)
    return sorted(out)


JUNK = re.compile(r"(^|/)(__pycache__|\.git|\.DS_Store|Thumbs\.db)|\.pyc$|~$")
# what a player gets when they unzip: one script per OS, and the launcher each one runs
ENTRY = ("IW4x-32.bat", "IW4x-32.sh", "files/iw4x32.ps1", "files/iw4x32.py")


def check_no_junk(files, bad):
    """everything in the kit folder is something a player downloads and the updater verifies"""
    for p in files:
        if JUNK.search(p):
            bad.append(f"kit: {p} is not a kit file - it would be zipped, listed and downloaded; delete it")


def check_entry_points(kit, files, bad):
    """one-click: the kit must carry its own setup and launcher, and Linux players must be able to run them"""
    for p in ENTRY:
        if p not in files:
            bad.append(f"kit: {p} is missing - the kit is not one-click without it")
    for p in sorted({f.split("/")[0] for f in files}):
        if p not in TOP and p not in LEGACY:
            bad.append(f"kit: {p} at the top of the kit - players see only IW4x-32.bat, IW4x-32.sh, README.txt and "
                       "files/; put it in files/")
    for p in files:
        if p.endswith((".sh", ".py")) and not os.access(os.path.join(kit, p), os.X_OK):
            bad.append(f"kit: {p} is not executable - git stores that mode, and ./<name> is how players run it")


def check_manifest(root, kit, files, bad):
    path = os.path.join(root, "latest.json")
    if not os.path.isfile(path):
        bad.append("latest.json: missing at the repo root")
        return None
    try:
        m = json.load(open(path, encoding="utf-8"))
    except ValueError as e:
        bad.append(f"latest.json: does not parse: {e}")
        return None
    for k in ("version", "iw4x", "official", "base_url", "files"):
        if k not in m:
            bad.append(f"latest.json: no {k!r}")
    if not re.fullmatch(r"v\d+(\.\d+)*", str(m.get("version", ""))):
        bad.append(f"latest.json: version {m.get('version')!r} must look like v2.0")
    want = f"https://raw.githubusercontent.com/{REPO}/{m.get('version')}/iw4x32/release/"
    if m.get("base_url") != want:
        bad.append(f"latest.json: base_url {m.get('base_url')!r} != {want!r} (the tag's copy of the kit)")
    listed = m.get("files") or {}
    for p, h in sorted(listed.items()):
        f = os.path.join(kit, p)
        if not os.path.isfile(f):
            bad.append(f"latest.json: {p} is listed but not in the kit")
        elif sha(open(f, "rb").read()) != h:
            bad.append(f"latest.json: {p} does not have SHA-256 {h}")
    for p in files:
        if p not in listed:
            bad.append(f"latest.json: kit file {p} is not listed - players would never get it")
    if set(m.get("legacy") or []) != LEGACY & set(files):
        bad.append(f"latest.json: legacy {m.get('legacy')} != the v2.0 shims in the kit {sorted(LEGACY & set(files))}")
    for f in ("iw4x.dll", "iw4x.exe"):
        if not re.fullmatch(r"[0-9a-f]{64}", str((m.get("official") or {}).get(f, ""))):
            bad.append(f"latest.json: official[{f!r}] must be a sha256 - the updater repairs to it")
    return m


def check_no_exe_install(kit, files, bad):
    """v2.0 installs one DLL: nothing may put an iw4x.exe of ours into the game folder"""
    if "files/iw4x.exe" in files:
        bad.append("kit: files/iw4x.exe is in the kit - v2.0 ships only files/iw4x.dll")
    for p in files:
        if not p.endswith(SCRIPTS):
            continue
        text = open(os.path.join(kit, p), encoding="utf-8", errors="replace").read()
        for n, line in enumerate(text.splitlines(), 1):
            if KIT_EXE.search(line) and COPY.search(line):      # naming it to delete it (v1.x leftovers) is fine
                bad.append(f"{p}:{n}: copies the kit's own iw4x.exe: {line.strip()[:90]}")
            if COPY.search(line) and GAME_EXE.search(line) and "backup" not in line.lower():
                bad.append(f"{p}:{n}: writes an iw4x.exe into the game folder (only a restore from backup/ "
                           f"is allowed): {line.strip()[:90]}")


def check_hashes_match(kit, files, manifest, bad):
    """the launchers' OFFICIAL_* constants describe the official IW4x release latest.json is made for"""
    if not os.path.isfile(os.path.join(kit, "files", "iw4x.dll")):
        bad.append("kit: files/iw4x.dll is missing - build Release and copy it in (make_latest.py --dll)")
        return
    if not manifest:
        return
    want = {"DLL": (manifest.get("official") or {}).get("iw4x.dll"), "EXE": (manifest.get("official") or {}).get("iw4x.exe"),
            "VER": manifest.get("iw4x")}
    for p in ("files/iw4x32.ps1", "files/iw4x32.py"):
        if p not in files:
            continue
        text = open(os.path.join(kit, p), encoding="utf-8", errors="replace").read()
        for k, v in want.items():
            m = re.search(rf"^\$?OFFICIAL_{k} = [\"']([0-9A-Za-z_]*)", text, re.M)
            if not m:
                bad.append(f"{p}: no OFFICIAL_{k} constant")
            elif m.group(1) != v:
                bad.append(f"{p}: OFFICIAL_{k} = {m.group(1)!r}, latest.json says {v!r} - run make_latest.py")


def check_line_endings(kit, files, bad):
    for p in files:
        raw = open(os.path.join(kit, p), "rb").read()
        if p.endswith(CRLF_EXT):
            if b"\n" in raw.replace(b"\r\n", b"") or b"\r" in raw.replace(b"\r\n", b""):
                bad.append(f"{p}: not every line ends CRLF (Windows players)")
        elif p.endswith(LF_EXT):
            if b"\r" in raw:
                bad.append(f"{p}: has CR - it must stay LF")


def check_readme(kit, manifest, bad):
    f = os.path.join(kit, "README.txt")
    if not os.path.isfile(f):
        bad.append("kit: README.txt is missing (the updater reads its first line)")
        return
    first = open(f, encoding="utf-8", errors="replace").readline()
    m = re.match(r"IW4x-32 (v[\d.]+)", first)
    if not m:
        bad.append("kit: README.txt line 1 must start 'IW4x-32 vX.Y' - the updater reads the version there")
    elif manifest and m.group(1) != manifest.get("version"):
        bad.append(f"kit: README.txt says {m.group(1)} but latest.json says {manifest.get('version')}")


def check_workflow(root, bad):
    path = os.path.join(root, ".github", "workflows", "iw4x32-release.yml")
    if not os.path.isfile(path):
        bad.append(".github/workflows/iw4x32-release.yml: missing")
        return
    text = open(path, encoding="utf-8").read()
    runs_on, steps, tags = [], [], []
    if yaml:
        try:
            wf = yaml.safe_load(text)
        except yaml.YAMLError as e:
            bad.append(f"iw4x32-release.yml: YAML does not parse: {e}")
            return
        on = (wf.get("on") or wf.get(True) or {}) if isinstance(wf, dict) else {}
        tags = list((on.get("push") or {}).get("tags") or [])
        for job in (wf.get("jobs") or {}).values():
            runs_on.append(str(job.get("runs-on")))
            for s in job.get("steps") or []:
                steps.append(str(s.get("uses", "")) + " " + str(s.get("run", "")))
    else:
        block = re.search(r"^on:\s*$((?:^[ \t]+.*\n?)+)", text, re.M)
        tags = re.findall(r"^\s*-\s*[\"']?([^\"'\n]+)", block.group(1), re.M) if block else []
        runs_on = re.findall(r"runs-on:\s*(\S+)", text)
        steps = [text]
    if "v*" not in tags:
        bad.append(f"iw4x32-release.yml: on.push.tags must contain v*, got {tags}")
    if "windows-2022" not in runs_on:
        bad.append("iw4x32-release.yml: nothing builds on windows-2022")
    if not any("msbuild" in s and "Configuration=Release" in s and "Platform=Win32" in s for s in steps):
        bad.append("iw4x32-release.yml: no msbuild Release|Win32 step (build it like build.yml)")
    if not any("ncipollo/release-action@v1" in s for s in steps):
        bad.append("iw4x32-release.yml: no ncipollo/release-action@v1 step")
    if "iw4x32/release" not in text or not re.search(r"IW4x-32-[^\n]*ref_name[^\n]*\.zip", text, re.I):
        bad.append("iw4x32-release.yml: does not zip iw4x32/release/ as IW4x-32-<tag>.zip")
    if not re.search(r"iw4x32_update", text) or "latest.json" not in re.sub(r"(?s).*artifacts:", "", text):
        bad.append("iw4x32-release.yml: the zip must leave out iw4x32_update.ps1/.py, and latest.json must be a release "
                   "asset (the launchers and the standalone IW4x-32.bat read releases/latest/download/latest.json)")
    if not yaml:
        print("check_kit: note - PyYAML is not installed, the workflow was checked as text only")


def check_gitattributes(root, bad):
    path = os.path.join(root, ".gitattributes")
    text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    if not re.search(r"iw4x32/release/\S*\s+.*-text", text):
        bad.append(".gitattributes: the kit needs a -text rule - git must store the kit's bytes exactly as "
                   "hashed (GitHub raw serves them to the updater)")


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--root", default=DEFAULT_ROOT, help="repo root (for testing a copy of the kit)")
    a = ap.parse_args()
    kit = os.path.join(a.root, "iw4x32", "release")
    if not os.path.isdir(kit):
        print(f"check_kit: no kit in {kit}")
        return 1
    files = kit_files(kit)
    bad = []
    manifest = check_manifest(a.root, kit, files, bad)
    check_no_junk(files, bad)
    check_entry_points(kit, files, bad)
    check_no_exe_install(kit, files, bad)
    check_hashes_match(kit, files, manifest, bad)
    check_line_endings(kit, files, bad)
    check_readme(kit, manifest, bad)
    check_workflow(a.root, bad)
    check_gitattributes(a.root, bad)
    if bad:
        print("check_kit: %d problem(s):" % len(bad))
        for b in bad:
            print("  " + b)
        return 1
    print("check_kit: ok - latest.json %s on %s: %d kit file(s) with their SHA-256, only files/iw4x.dll is "
          "installed, iw4x32-release.yml builds and releases it on a v* tag"
          % (manifest["version"], manifest["iw4x"], len(files) + 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
