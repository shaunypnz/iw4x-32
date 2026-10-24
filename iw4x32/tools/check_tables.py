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
import struct
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
    ap.add_argument("--exe", default=None,
                    help="a pristine iw4x.exe: re-read every site from it (the tables' old values, byte patches "
                         "and hooks must match the file the patcher will find at run time)")
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

    # ---- the in-place cg growth has to fit in the room the tables vacate (IW4x-32) --------------------
    # cg_tail is grown_in_place: cg_s ends at its old_hi and extends by (new - old) of its fixed operands into
    # whatever follows in the image. Every byte of that extension must belong to an array the tables relocate,
    # or CG_Init's memset(cg, 0, <the grown size the tables themselves write>) zeroes live client globals - the
    # client dies seconds after the level loads while a dedicated server (no cgame) never notices. The 48-slot
    # set failed exactly this: growth 0x9B28 into a 0x5318 hole, 0x4810 bytes of globals and the first 12
    # cg_entities entries clobbered (QWEN_REPORT.md, the client_process_up failure).
    tail = next((a for a in src["arrays"] if a["name"] == "cg_tail"), None)
    if tail:
        shifts = {num(o["new"]) - num(o["old"]) for o in src["relocation_operands"] if o.get("fixed")}
        want(len(shifts) == 1, "cg_tail: the fixed operands do not share one shift: %s"
             % sorted("0x%x" % s for s in shifts))
        if len(shifts) == 1:
            shift, at = shifts.pop(), num(tail["old_hi"])          # at = how far cg may grow in place
            need = at + shift
            moved = sorted((num(a["old_lo"]), num(a["old_hi"])) for a in src["arrays"] if not a["grown_in_place"])
            widened = True
            while widened:                                        # merge the relocated ranges into one run
                widened = False
                for lo, hi in moved:
                    if lo <= at < hi:
                        at, widened = hi, True
            want(at >= need,
                 "layout: cg grows in place by 0x%x to 0x%x, but the arrays the tables relocate only cover up to "
                 "0x%x - %d byte(s) of client globals (cg_entities starts at 0x8F60F0) would be zeroed by "
                 "CG_Init's memset(cg). The in-place growth fits at most %d players; past that the tables must "
                 "relocate the globals up to and including cg_entities."
                 % (shift, need, at, need - at, 18 + (at - num(tail["old_hi"])) // 0x52C))

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

    # ---- the script-variable pool (IW4x-32) ----
    psec = src.get("pool")
    paddr, pconst = [], []
    if psec:
        paddr = table(text, "IW4x32_PoolAddresses")
        pconst = table(text, "IW4x32_PoolConstants")
        want(len(paddr) == len(psec["address_sites"]),
             "pool address sites: %d in the header, %d in the json" % (len(paddr), len(psec["address_sites"])))
        want(len(pconst) == len(psec["constant_sites"]),
             "pool constant sites: %d in the header, %d in the json" % (len(pconst), len(psec["constant_sites"])))
        # every pool site carries the whole instruction it was found in, and its operand address must be that
        # instruction's ONE match for the old value - the rule the tables are built with. A site whose operand_va
        # is off by two bytes passes every count and makes the patcher refuse the exe at run time, so it is
        # checked here, where a mistake costs seconds instead of a live test.
        stock_consts = {num(psec[k]): k[4:] for k in ("old_parent_cap", "old_child0_base", "old_child_cap",
                                                      "old_child1_base")}
        stock_consts[num(psec["old_child0_base"]) + num(psec["old_child_cap"]) - 1] = "child0_last"
        stock_consts[num(psec["old_entries"]) - 1] = "child1_last"
        new_of = {"parent_cap": num(psec["parent_cap"]), "child0_base": num(psec["child0_base"]),
                  "child_cap": num(psec["child_cap"]), "child1_base": num(psec["child1_base"]),
                  "child0_last": num(psec["child0_base"]) + num(psec["child_cap"]) - 1,
                  "child1_last": num(psec["entries"]) - 1}
        for s in psec["address_sites"] + psec["constant_sites"]:
            if "bytes" not in s:
                bad.append("pool site %s carries no instruction bytes - every pool site must, so the tables can "
                           "be checked without the exe" % s.get("operand_va", "?"))
                continue
            raw = bytes.fromhex(s["bytes"])
            le = struct.pack("<I", num(s["old"]))
            at = [i for i in range(len(raw) - 3) if raw[i:i + 4] == le]
            want(len(at) == 1, "pool site %s: %s appears %d times in its own instruction %s"
                 % (s["insn_va"], s["old"], len(at), s["bytes"]))
            want(len(at) == 1 and num(s["operand_va"]) == num(s["insn_va"]) + at[0],
                 "pool site %s: operand %s is not where %s sits in [%s] %s"
                 % (s["insn_va"], s["operand_va"], s["old"], s["bytes"], s.get("insn_text", "")))
        for s in psec["constant_sites"]:
            kind = stock_consts.get(num(s["old"]))
            want(kind is not None, "pool constant site %s: %s is not a stock pool geometry value"
                 % (s["insn_va"], s["old"]))
            want(kind is not None and num(s["new"]) == new_of[kind],
                 "pool constant site %s: %s -> %s, want %s" % (s["insn_va"], s["old"], s["new"],
                                                               "0x%x" % new_of[kind] if kind else "-"))
        # the sampler reads the block address out of the allocator's own instruction: that site must be in the set
        want(any(s["insn_va"] == psec.get("alloc_site") and num(s["old"]) == num(psec["base"]) + 4
                 for s in psec["address_sites"]),
             "pool: no site at the allocator (%s) holding base+4 - the pool sampler cannot find the block" %
             psec.get("alloc_site"))
        by_op = {val(r[0]): r for r in paddr}
        want(len(by_op) == len(paddr), "pool address sites: duplicate operand addresses in the header")
        for s in psec["address_sites"]:
            r = by_op.get(num(s["operand_va"]))
            want(r is not None, "pool address site 0x%x missing" % num(s["operand_va"]))
            if not r:
                continue
            want(val(r[1]) == num(s["old"]), "pool address site 0x%x: old value" % num(s["operand_va"]))
            want(val(r[2]) == num(s["offset"]), "pool address site 0x%x: offset" % num(s["operand_va"]))
            want(num(s["old"]) == num(psec["base"]) + num(s["offset"]),
                 "pool address site 0x%x: old != base + offset" % num(s["operand_va"]))
        want(len({val(r[0]) for r in pconst}) == len(pconst), "pool constant sites: duplicates in the header")
        for s in psec["constant_sites"]:
            r = next((x for x in pconst if val(x[0]) == num(s["operand_va"])), None)
            want(r is not None, "pool constant site 0x%x missing" % num(s["operand_va"]))
            if not r:
                continue
            want((val(r[1]), val(r[2])) == (num(s["old"]), num(s["new"])),
                 "pool constant site 0x%x: value" % num(s["operand_va"]))
        # the geometry itself: parent, then child0, then child1, one contiguous block of 16-byte entries
        pc, c0, cc, c1, ent = (num(psec[k]) for k in ("parent_cap", "child0_base", "child_cap",
                                                      "child1_base", "entries"))
        want(c0 == pc + 1, "pool geometry: child0_base %x != parent_cap %x + 1" % (c0, pc))
        want(c1 == c0 + cc, "pool geometry: child1_base %x != child0_base %x + child_cap %x" % (c1, c0, cc))
        want(ent == c1 + cc, "pool geometry: entries %x != child1_base %x + child_cap %x" % (ent, c1, cc))
        want(pc > num(psec["old_parent_cap"]) and cc > num(psec["old_child_cap"]),
             "pool geometry: the new pools are not bigger than the stock ones - what is this relocation for?")
        want(ent * 0x10 > num(psec["old_entries"]) * 0x10, "pool geometry: the new block is not bigger")
        # every link in a pool entry is 16 bits: the init writes entry+0 = index - the pool's first index (up to
        # cap-1) and the allocator walks the free list as next = base + (index + word)*16. A pool of 0x10000
        # entries or more truncates its own links, and the first script the level compiles fails on it.
        want(pc < 0x10000 and cc < 0x10000,
             "pool geometry: parent_cap %x and child_cap %x must stay under 0x10000 - every pool link is 16 bits"
             % (pc, cc))
        for key, name in (("base", "Pool_StockBase"), ("old_parent_cap", "Pool_OldParentCap"),
                          ("old_child0_base", "Pool_OldChild0Base"), ("old_child_cap", "Pool_OldChildCap"),
                          ("old_child1_base", "Pool_OldChild1Base"), ("old_entries", "Pool_OldEntries"),
                          ("parent_cap", "Pool_ParentCap"), ("child0_base", "Pool_Child0Base"),
                          ("child_cap", "Pool_ChildCap"), ("child1_base", "Pool_Child1Base"),
                          ("entries", "Pool_Entries")):
            want("IW4x32_%s = %s;" % (name, "0x%x" % num(psec[key])) in text, "IW4x32_%s wrong or missing" % name)

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
    pool_kinds = (("PoolAddresses", paddr), ("PoolConstants", pconst)) if psec else ()
    for name, rows in (("Arrays", arrays), ("Operands", operands), ("CvarDomains", cvars),
                       ("SizeConstants", sizes), ("CodePatches", patches), ("Hooks", hooks)) + pool_kinds:
        m = re.search(r"IW4x32_%sCount = (\d+);" % name, text)
        want(m is not None and int(m.group(1)) == len(rows), "IW4x32_%sCount != %d" % (name, len(rows)))
    m = re.search(r"IW4x32_DualCount = (\d+);", text)
    want(m is not None and int(m.group(1)) == sum(1 for j in src["code_patches"] if j.get("dual")), "IW4x32_DualCount")

    # ---- optional: every site against the pristine exe it was read out of (--exe) ----
    if a.exe:
        check_against_exe(src, a.exe, bad)

    if bad:
        print("check_tables: %d problem(s):" % len(bad))
        for b in bad[:40]:
            print("  " + b)
        return 1
    print("check_tables: ok - %d arrays, %d operands, %d cvar domains, %d size constants, "
          "%d code patches, %d hooks match engine_patches.json" %
          (len(arrays), len(operands), len(cvars), len(sizes), len(patches), len(hooks))
          + (", %d pool addresses, %d pool constants" % (len(paddr), len(pconst)) if psec else ""))
    return 0


def check_against_exe(src, path, bad):
    """re-read the tables from the pristine exe: this is exactly what the component's VerifyEngine does in the
    running game, so a table that does not match the exe fails here instead of refusing to patch at run time."""
    data = open(path, "rb").read()
    base = num(src["image_base"])
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    off = pe + 24 + struct.unpack_from("<H", data, pe + 20)[0]
    secs = []
    for _ in range(nsec):
        vsz, rva, rsz, ro = struct.unpack_from("<IIII", data, off + 8)
        secs.append((base + rva, vsz, ro, rsz))
        off += 40

    def at(va, n):
        for va_lo, vsz, ro, rsz in secs:
            if va_lo <= va < va_lo + vsz and va - va_lo < rsz:
                return data[ro + va - va_lo:ro + va - va_lo + n]
        return None

    def want(cond, msg):
        if not cond:
            bad.append(msg)

    import hashlib
    want(hashlib.md5(data).hexdigest() == src["pristine_md5"],
         "%s: md5 %s, the tables want %s" % (path, hashlib.md5(data).hexdigest(), src["pristine_md5"]))
    for o in src["relocation_operands"]:
        want(at(num(o["operand_va"]), 4) == struct.pack("<I", num(o["old"])),
             "exe: operand 0x%x does not hold %s" % (num(o["operand_va"]), o["old"]))
    for s in src["size_constant_operands"]:
        want(at(num(s["operand_va"]), 4) == struct.pack("<I", num(s["old"])),
             "exe: size constant 0x%x does not hold %s" % (num(s["operand_va"]), s["old"]))
    for group in ("cvar_domains", "code_patches"):
        for p in src[group]:
            want(at(num(p["va"]), len(bytes.fromhex(p["old"]))) == bytes.fromhex(p["old"]),
                 "exe: bytes at 0x%x are not the %s old bytes" % (num(p["va"]), group))
    for h in src["hooks"]:
        want(at(num(h["va"]), len(bytes.fromhex(h["replaced"]))) == bytes.fromhex(h["replaced"]),
             "exe: bytes at 0x%x are not the hook %s bytes being replaced" % (num(h["va"]), h["stub"]))
    psec = src.get("pool")
    if psec:
        for s in psec["address_sites"] + psec["constant_sites"]:
            if "bytes" not in s:
                continue
            want(at(num(s["operand_va"]), 4) == struct.pack("<I", num(s["old"])),
                 "exe: pool site 0x%x does not hold %s" % (num(s["operand_va"]), s["old"]))
            want(at(num(s["insn_va"]), len(bytes.fromhex(s["bytes"]))) == bytes.fromhex(s["bytes"]),
                 "exe: instruction at 0x%x is not [%s]" % (num(s["insn_va"]), s["bytes"]))


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
