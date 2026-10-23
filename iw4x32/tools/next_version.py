#!/usr/bin/env python3
"""next_version.py - the version the next IW4x-32 release gets, and the one place the version format is decided.
Owner's rules: releases go v2.1, v2.2, v2.3, ... - the major stays 2, the minor counts up by one (v2.9 -> v2.10,
never v3.0) (2026-10-16); from v2.6 on the version names the official IW4x release the kit is built for:
v2.6-r5278, v2.7-r5280, ... (2026-10-23). Every release tool asks this script instead of doing its own arithmetic
(a "+ 0.1" turns v2.9 into v3.0).

    python3 iw4x32/tools/next_version.py --iw4x r5280            next after this repo's latest.json (v2.6-r5278 -> v2.7-r5280)
    python3 iw4x32/tools/next_version.py v2.9-r5278 --iw4x r5280 next after a given version (-> v2.10-r5280)
    python3 iw4x32/tools/next_version.py --check v2.6-r5278 [--iw4x r5278]   exit 0 = a valid release version
    python3 iw4x32/tools/next_version.py --self-test
--iw4x defaults to latest.json's "iw4x". Versions before v2.6 (v2.0 ... v2.5) have no -rNNNN; they are still read
for counting. The updaters compare only vMAJOR.MINOR, so v2.10-r5300 > v2.9-r5278 and the suffix never makes a
version newer."""
import json, os, re, sys

MAJOR = 2
FIRST_SUFFIXED = 6                      # v2.6 is the first release with -rNNNN
VERSION = re.compile(r"v(\d+)\.(\d+)(?:-(r\d+))?")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse(v):
    """(major, minor, IW4x tag or None) of an IW4x-32 version"""
    m = VERSION.fullmatch((v or "").strip())
    if not m:
        raise ValueError(f"not an IW4x-32 version (vMAJOR.MINOR-rNNNN): {v!r}")
    return int(m.group(1)), int(m.group(2)), m.group(3)


def key(v):
    """what versions are ordered by: vMAJOR.MINOR only"""
    return parse(v)[:2]


def check(v, iw4x=None):
    """a version a release may carry: v2.N-rNNNN (v2.N alone only before v2.6), its rNNNN = the kit's IW4x"""
    major, minor, tag = parse(v)
    if major != MAJOR:
        raise ValueError(f"{v}: IW4x-32 releases stay on v{MAJOR}.x")
    if minor >= FIRST_SUFFIXED and not tag:
        raise ValueError(f"{v}: from v{MAJOR}.{FIRST_SUFFIXED} on a version names its IW4x release (v{MAJOR}.{minor}-rNNNN)")
    if tag and iw4x and tag != iw4x:
        raise ValueError(f"{v}: says IW4x {tag}, but the kit is built for IW4x {iw4x}")
    return v


def next_version(v, iw4x):
    if not re.fullmatch(r"r\d+", iw4x or ""):
        raise ValueError(f"the official IW4x release this kit is built for is needed (rNNNN), got {iw4x!r}")
    major, minor, _ = parse(v)
    if major != MAJOR:
        raise ValueError(f"{v}: IW4x-32 releases stay on v{MAJOR}.x")
    return f"v{MAJOR}.{minor + 1}-{iw4x}"


def self_test():
    cases = {("v2.0", "r5168"): "v2.1-r5168", ("v2.5", "r5278"): "v2.6-r5278", ("v2.6-r5278", "r5280"): "v2.7-r5280",
             ("v2.9-r5278", "r5278"): "v2.10-r5278", ("v2.10-r5300", "r5301"): "v2.11-r5301"}
    bad = [f"{a} -> {next_version(*a)} (want {b})" for a, b in cases.items() if next_version(*a) != b]
    for v in ("2.1", "v2", "v3.0", "v2.1.1", "", "v2.6-5278", "v2.6-r", "v2.6r5278"):
        try:
            parse(v)
            if v == "v3.0":
                check(v)
            bad.append(f"{v!r} was accepted")
        except ValueError:
            pass
    for v, iw4x in (("v2.6", None), ("v2.6-r5278", "r5280"), ("v3.1-r5278", None)):
        try:
            check(v, iw4x)
            bad.append(f"check({v!r}, {iw4x!r}) passed")
        except ValueError:
            pass
    for v, iw4x in (("v2.5", None), ("v2.6-r5278", "r5278"), ("v2.10-r5300", None)):
        try:
            check(v, iw4x)
        except ValueError as e:
            bad.append(f"check({v!r}) refused: {e}")
    if not key("v2.10-r5000") > key("v2.9-r9999") or key("v2.6-r5278") != key("v2.6"):
        bad.append("key() does not order by vMAJOR.MINOR only")
    try:
        next_version("v2.6-r5278", None)
        bad.append("next_version without an IW4x tag was accepted")
    except ValueError:
        pass
    print("next_version self-test: " + ("ok" if not bad else "FAIL " + "; ".join(bad)))
    return not bad


def latest():
    try:
        return json.load(open(os.path.join(ROOT, "latest.json")))
    except (OSError, ValueError):
        return {}


if __name__ == "__main__":
    args = sys.argv[1:]
    iw4x = None
    if "--iw4x" in args:
        i = args.index("--iw4x")
        iw4x = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    try:
        if args[:1] == ["--self-test"]:
            sys.exit(0 if self_test() else 1)
        if args[:1] == ["--check"]:
            print(check(args[1] if len(args) > 1 else "", iw4x))
            sys.exit(0)
        cur = args[0] if args else latest()["version"]
        print(next_version(cur, iw4x or latest().get("iw4x")))
    except (ValueError, KeyError, IndexError) as e:
        sys.exit(f"next_version: {e}")
