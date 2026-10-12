#!/usr/bin/env python3
"""
check_tables.py - the generated IW4x32Tables.hpp must hold exactly the entries of
iw4x32/reference/engine_patches.json: the counts per kind and per role, and every address,
value and byte of every entry.

    python3 iw4x32/tools/check_tables.py [--json FILE] [--header FILE]

Exits 0 when the header matches, 1 with the first differences listed. Run gen_tables.py to fix it.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DEFAULT_JSON = os.path.join(ROOT, "iw4x32", "reference", "engine_patches.json")
DEFAULT_HEADER = os.path.join(ROOT, "src", "Components", "Modules", "IW4x32Tables.hpp")

ROLE = {"client": 0, "server": 1}


def num(v):
    return int(v, 16) if isinstance(v, str) else int(v)


def table(text, name):
    m = re.search(r"static const [A-Za-z0-9_]+ %s\[\] = \{(.*?)\n  \};" % name, text, re.S)
    if not m:
        raise SystemExit("IW4x32Tables.hpp: no %s table" % name)
    rows = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.startswith("{") or not line.endswith("},"):
            raise SystemExit("IW4x32Tables.hpp: unparsable %s line: %r" % (name, line))
        rows.append(split_fields(line[1:-2]))
    return rows


def split_fields(s):
    out, depth, cur, instr, esc = [], 0, "", False, False
    for ch in s:
        if instr:
            cur += ch
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
            cur += ch
        elif ch == "{":
            depth += 1
            cur += ch
        elif ch == "}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def val(f):
    """header fields are hex (0x...) or plain decimal"""
    return int(f, 16) if f.startswith("0x") or f.startswith("-0x") else int(f)


def bytepool(text):
    m = re.search(r"static const unsigned char IW4x32_Bytes\[(\d+)\] = \{(.*?)\};", text, re.S)
    if not m:
        raise SystemExit("IW4x32Tables.hpp: no IW4x32_Bytes pool")
    data = bytes(int(x, 16) for x in re.findall(r"0x[0-9a-fA-F]{2}", m.group(2)))
    if len(data) != int(m.group(1)):
        raise SystemExit("IW4x32Tables.hpp: IW4x32_Bytes says %s entries, found %d" % (m.group(1), len(data)))
    return data


def counts(rows, key):
    out = {}
    for r in rows:
        k = val(r[key])
        out[k] = out.get(k, 0) + 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=DEFAULT_JSON)
    ap.add_argument("--header", default=DEFAULT_HEADER)
    a = ap.parse_args()

    src = json.load(open(a.json))
    if not os.path.exists(a.header):
        sys.exit("MISSING: %s - run iw4x32/tools/gen_tables.py" % a.header)
    text = open(a.header).read()
    pool = bytepool(text)

    bad = []

    def want(cond, msg):
        if not cond:
            bad.append(msg)

    want('IW4x32_ExeMd5 = "%s"' % src["pristine_md5"] in text, "exe md5 %s not in the header" % src["pristine_md5"])
    want("IW4x32_ImageBase = %s" % ("0x%x" % num(src["image_base"])) in text, "image base not in the header")

    # ---- arrays ----
    arrays = table(text, "IW4x32_Arrays")
    want(len(arrays) == len(src["arrays"]), "arrays: %d in the header, %d in the json" % (len(arrays), len(src["arrays"])))
    by_name = {}
    for r, j in zip(arrays, src["arrays"]):
        want(json.loads(r[0]) == j["name"], "array %d: name %s != %s" % (len(by_name), r[0], j["name"]))
        want((val(r[1]), val(r[2]), val(r[3])) == (num(j["old_lo"]), num(j["old_hi"]), num(j["new_size"])),
             "array %s: range/size %s" % (j["name"], r[1:4]))
        want(val(r[6]) == ROLE[j["role"]], "array %s: role" % j["name"])
        want(val(r[7]) == (1 if j["grown_in_place"] else 0), "array %s: grown_in_place" % j["name"])
        by_name[j["name"]] = len(by_name)

    # ---- operands ----
    operands = table(text, "IW4x32_Operands")
    want(len(operands) == len(src["relocation_operands"]),
         "operands: %d in the header, %d in the json" % (len(operands), len(src["relocation_operands"])))
    seen = set()
    for o in src["relocation_operands"]:
        fixed = bool(o.get("fixed"))
        off = num(o["new_array_offset"]) if not fixed else num(o["new"]) - num(o["old"])
        key = (num(o["insn_va"]), num(o["operand_va"]))
        row = next((r for r in operands if (val(r[0]), val(r[1])) == key), None)
        want(row is not None, "operand %s missing" % ("0x%x" % key[1]))
        if not row:
            continue
        want(val(row[2]) == num(o["old"]), "operand 0x%x: old value" % key[1])
        want(val(row[3]) == off & 0xFFFFFFFF, "operand 0x%x: offset 0x%x != 0x%x" % (key[1], val(row[3]), off))
        want(val(row[4]) == by_name[o["array"]], "operand 0x%x: array" % key[1])
        want(val(row[5]) == (1 if fixed else 0), "operand 0x%x: fixed flag" % key[1])
        seen.add(key)
    extra = {(val(r[0]), val(r[1])) for r in operands} - seen
    want(not extra, "operands not in the json: %s" % sorted("0x%x" % e[1] for e in extra))
    # per-array operand blocks
    for i, j in enumerate(src["arrays"]):
        mine = [r for r in operands if val(r[4]) == i]
        want(len(mine) == j["operands"], "array %s: %d operands in the header, %d in the json"
             % (j["name"], len(mine), j["operands"]))
        want(val(arrays[i][4]) == operands.index(mine[0]), "array %s: operand block first" % j["name"])
        want(val(arrays[i][5]) == len(mine), "array %s: operand block count" % j["name"])

    # ---- cvar domains ----
    cvars = table(text, "IW4x32_CvarDomains")
    want(len(cvars) == len(src["cvar_domains"]), "cvar domains: %d != %d" % (len(cvars), len(src["cvar_domains"])))
    check_bytes(cvars, src["cvar_domains"], pool, bad, "cvar domain")

    # ---- size constants ----
    sizes = table(text, "IW4x32_SizeConstants")
    want(len(sizes) == len(src["size_constants"]), "size constants: %d != %d" % (len(sizes), len(src["size_constants"])))
    role_of = {(num(s["va"]), num(s["old"])): s["role"] for s in src["size_constants"]}
    for o in src["size_constant_operands"]:
        key = (num(o["insn_va"]), num(o["operand_va"]))
        row = next((r for r in sizes if (val(r[0]), val(r[1])) == key), None)
        want(row is not None, "size constant 0x%x missing" % key[0])
        if not row:
            continue
        want((val(row[2]), val(row[3])) == (num(o["old"]), num(o["new"])), "size constant 0x%x: value" % key[0])
        want(val(row[4]) == ROLE[role_of[(key[0], num(o["old"]))]], "size constant 0x%x: role" % key[0])

    # ---- code patches ----
    patches = table(text, "IW4x32_CodePatches")
    want(len(patches) == len(src["code_patches"]), "code patches: %d != %d" % (len(patches), len(src["code_patches"])))
    check_bytes(patches, src["code_patches"], pool, bad, "code patch")
    for r, j in zip(patches, src["code_patches"]):
        want(val(r[5]) == (1 if j.get("dual") else 0), "code patch 0x%x: dual flag" % num(j["va"]))

    # ---- hooks ----
    hooks = table(text, "IW4x32_Hooks")
    want(len(hooks) == len(src["hooks"]), "hooks: %d != %d" % (len(hooks), len(src["hooks"])))
    for r, j in zip(hooks, src["hooks"]):
        want(val(r[0]) == num(j["va"]), "hook: address %s != %s" % (r[0], j["va"]))
        want(json.loads(r[4]) == j["stub"], "hook 0x%x: stub %s != %s" % (num(j["va"]), r[4], j["stub"]))
        want(val(r[2]) == len(bytes.fromhex(j["replaced"])), "hook 0x%x: replaced length" % num(j["va"]))
        want(pool[val(r[1]):val(r[1]) + val(r[2])] == bytes.fromhex(j["replaced"]), "hook 0x%x: replaced bytes" % num(j["va"]))
        want(val(r[3]) == ROLE[j["role"]], "hook 0x%x: role" % num(j["va"]))

    # ---- counts per kind and per role ----
    kinds = [("arrays", arrays, 6), ("cvar domains", cvars, 4), ("size constants", sizes, 4),
             ("code patches", patches, 4), ("hooks", hooks, 3)]
    for name, rows, roleidx in kinds:
        got = counts(rows, roleidx)
        exp = {}
        for j in src[{"arrays": "arrays", "cvar domains": "cvar_domains", "size constants": "size_constants",
                      "code patches": "code_patches", "hooks": "hooks"}[name]]:
            exp[ROLE[j["role"]]] = exp.get(ROLE[j["role"]], 0) + 1
        want(got == exp, "%s per role: %s != %s" % (name, got, exp))
    got_op = {}
    for r in operands:
        got_op[val(arrays[val(r[4])][6])] = got_op.get(val(arrays[val(r[4])][6]), 0) + 1
    exp_op = {}
    for j in src["arrays"]:
        exp_op[ROLE[j["role"]]] = exp_op.get(ROLE[j["role"]], 0) + j["operands"]
    want(got_op == exp_op, "operands per role: %s != %s" % (got_op, exp_op))
    want(counts(patches, 5) == {0: sum(1 for j in src["code_patches"] if not j.get("dual")),
                                1: sum(1 for j in src["code_patches"] if j.get("dual"))}, "code patches per dual")

    # ---- the constexpr counts must match the tables ----
    for name, rows in (("Arrays", arrays), ("Operands", operands), ("CvarDomains", cvars),
                       ("SizeConstants", sizes), ("CodePatches", patches), ("Hooks", hooks)):
        m = re.search(r"IW4x32_%sCount = (\d+);" % name, text)
        want(m is not None and int(m.group(1)) == len(rows), "IW4x32_%sCount != %d" % (name, len(rows)))
    m = re.search(r"IW4x32_DualCount = (\d+);", text)
    want(m is not None and int(m.group(1)) == sum(1 for j in src["code_patches"] if j.get("dual")), "IW4x32_DualCount")

    if bad:
        print("check_tables: %d problem(s):" % len(bad))
        for b in bad[:40]:
            print("  " + b)
        return 1
    print("check_tables: ok - %d arrays, %d operands, %d cvar domains, %d size constants, "
          "%d code patches, %d hooks match engine_patches.json" %
          (len(arrays), len(operands), len(cvars), len(sizes), len(patches), len(hooks)))
    return 0


def check_bytes(rows, entries, pool, bad, what):
    def want(cond, msg):
        if not cond:
            bad.append(msg)

    for r, j in zip(rows, entries):
        old, new = bytes.fromhex(j["old"]), bytes.fromhex(j["new"])
        ln = val(r[3])
        want(val(r[0]) == num(j["va"]), "%s: address %s != %s" % (what, r[0], j["va"]))
        want(ln == len(old), "%s 0x%x: length %d != %d" % (what, num(j["va"]), ln, len(old)))
        want(pool[val(r[1]):val(r[1]) + ln] == old, "%s 0x%x: old bytes" % (what, num(j["va"])))
        want(pool[val(r[2]):val(r[2]) + ln] == new, "%s 0x%x: new bytes" % (what, num(j["va"])))
        want(val(r[4]) == ROLE[j["role"]], "%s 0x%x: role" % (what, num(j["va"])))


if __name__ == "__main__":
    sys.exit(main())
