#!/usr/bin/env python3
"""next_version.py - the version the next IW4x-32 release gets. Owner's rule (2026-10-16): releases go v2.1, v2.2,
v2.3, ... - the major stays 2, the minor counts up by one (v2.9 -> v2.10, never v3.0). Every release tool asks this
script instead of doing its own arithmetic (a "+ 0.1" turns v2.9 into v3.0).

    python3 iw4x32/tools/next_version.py            next after this repo's latest.json version (v2.0 -> v2.1)
    python3 iw4x32/tools/next_version.py v2.9       next after a given version (-> v2.10)
    python3 iw4x32/tools/next_version.py --self-test
The updaters compare versions number by number (iw4x32_update.py vtuple, iw4x32_update.ps1 VNum), so v2.10 > v2.9."""
import json, os, re, sys

MAJOR = 2
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parse(v):
    m = re.fullmatch(r"v(\d+)\.(\d+)", (v or "").strip())
    if not m:
        raise ValueError(f"not an IW4x-32 version (vMAJOR.MINOR): {v!r}")
    return int(m.group(1)), int(m.group(2))


def next_version(v):
    major, minor = parse(v)
    if major != MAJOR:
        raise ValueError(f"{v}: IW4x-32 releases stay on v{MAJOR}.x")
    return f"v{MAJOR}.{minor + 1}"


def self_test():
    cases = {"v2.0": "v2.1", "v2.1": "v2.2", "v2.9": "v2.10", "v2.10": "v2.11", "v2.99": "v2.100"}
    bad = [f"{a} -> {next_version(a)} (want {b})" for a, b in cases.items() if next_version(a) != b]
    for v in ("2.1", "v2", "v3.0", "v2.1.1", ""):
        try:
            next_version(v)
            bad.append(f"{v!r} was accepted")
        except ValueError:
            pass
    print("next_version self-test: " + ("ok" if not bad else "FAIL " + "; ".join(bad)))
    return not bad


if __name__ == "__main__":
    if sys.argv[1:2] == ["--self-test"]:
        sys.exit(0 if self_test() else 1)
    cur = sys.argv[1] if len(sys.argv) > 1 else json.load(open(os.path.join(ROOT, "latest.json")))["version"]
    print(next_version(cur))
