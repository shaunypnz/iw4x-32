#!/usr/bin/env python3
"""
gen_tables.py - engine_patches.json -> src/Components/Modules/IW4x32Tables.hpp

    python3 iw4x32/tools/gen_tables.py [--json FILE] [--out FILE]

engine_patches.json is every change IW4x-32 makes to a pristine r5154 iw4x.exe (image base
0x400000): arrays to enlarge, the operands that address them, byte patches, size constants and
hooks. The component (src/Components/Modules/IW4x32.cpp) applies them to the running exe.

The 'new' values in the JSON are the addresses of the reference build's fixed layout. The
component allocates each array wherever VirtualAlloc gives it, so the header stores the offset
inside the array instead: operand = base(array) + offset. Absolute (fixed) operands address cg_s,
which grew in place - they all shift by one constant (CgTailShift).
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # the worktree root
DEFAULT_JSON = os.path.join(ROOT, "iw4x32", "reference", "engine_patches.json")
DEFAULT_OUT = os.path.join(ROOT, "src", "Components", "Modules", "IW4x32Tables.hpp")

ROLE = {"client": 0, "server": 1}


def num(v):
    """JSON numbers are hex strings; signed ones (sentinel offsets) carry a minus sign."""
    return int(v, 16) if isinstance(v, str) else int(v)


def hx(v):
    return "0x%x" % (v & 0xFFFFFFFF)


def bytehex(s):
    return bytes.fromhex(s)


def emit_bytes(out, name, data):
    out.append("static const unsigned char %s[%d] = {" % (name, len(data)))
    for i in range(0, len(data), 24):
        out.append("  " + ",".join("0x%02x" % b for b in data[i:i + 24]) +
                   ("," if i + 24 < len(data) else ""))
    out.append("};")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=DEFAULT_JSON)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()

    src = json.load(open(a.json))
    base = num(src["image_base"])
    arrays = src["arrays"]
    by_name = {arr["name"]: i for i, arr in enumerate(arrays)}

    # ---- operands: keep the offset inside the new array, not the reference build's address ----
    operands = []
    for o in src["relocation_operands"]:
        fixed = bool(o.get("fixed"))
        if fixed:
            offset = num(o["new"]) - num(o["old"])
        else:
            offset = num(o["new_array_offset"])
        operands.append(dict(insn=num(o["insn_va"]), operand=num(o["operand_va"]),
                             old=num(o["old"]), offset=offset, array=by_name[o["array"]],
                             fixed=fixed))
    operands.sort(key=lambda o: (o["array"], o["operand"]))

    # ---- dual operands: an address the layout switch rewrites (array base + one offset per layout) ----
    duals = sorted((dict(insn=num(o["insn_va"]), operand=num(o["operand_va"]), old=num(o["old"]),
                         ours=num(o["ours_offset"]), stock=num(o["stock_offset"]), array=by_name[o["array"]])
                    for o in src.get("dual_operands", [])), key=lambda o: o["operand"])

    # every array's operands go in one block so the component can walk them per array
    first = {}
    for i, o in enumerate(operands):
        first.setdefault(o["array"], i)

    # ---- byte patches (code patches + cvar domains + the bytes a hook overwrites) ----
    pool = bytearray()

    def pool_add(data):
        at = len(pool)
        pool.extend(data)
        return at

    cvars = []
    for c in src["cvar_domains"]:
        old, new = bytehex(c["old"]), bytehex(c["new"])
        assert len(old) == len(new)
        cvars.append(dict(va=num(c["va"]), old=pool_add(old), new=pool_add(new), len=len(old),
                          role=ROLE[c["role"]]))

    patches = []
    for p in src["code_patches"]:
        old, new = bytehex(p["old"]), bytehex(p["new"])
        assert len(old) == len(new) and old != new
        patches.append(dict(va=num(p["va"]), old=pool_add(old), new=pool_add(new), len=len(old),
                            role=ROLE[p["role"]], dual=bool(p.get("dual"))))

    hooks = []
    for h in src["hooks"]:
        rep = bytehex(h["replaced"])
        hooks.append(dict(va=num(h["va"]), rep=pool_add(rep), len=len(rep),
                          role=ROLE[h["role"]], stub=h["stub"], what=h["what"]))

    # ---- size constants: 4-byte operands, from the operand table (it knows the operand VA) ----
    what = {(num(s["va"]), num(s["old"])): s for s in src["size_constants"]}
    sizes = []
    for o in src["size_constant_operands"]:
        key = (num(o["insn_va"]), num(o["old"]))
        s = what.pop(key, None) or what[(num(o["operand_va"]), num(o["old"]))]
        sizes.append(dict(insn=num(o["insn_va"]), operand=num(o["operand_va"]),
                          old=num(o["old"]), new=num(o["new"]), role=ROLE[s["role"]]))
    assert not what, "size_constants without an operand entry: %r" % (what,)

    # ---- cg_tail grows inside cg_s: every absolute operand shifts by one constant ----
    shifts = {o["offset"] for o in operands if o["fixed"]}
    assert len(shifts) == 1, "fixed operands do not share one shift: %r" % (shifts,)
    shift = shifts.pop()

    dual = sum(1 for p in patches if p["dual"])

    # ---- the script-variable pool: one relocated block, addressed by absolute address and by pool index ----
    poolsec = src.get("pool")
    pool_addr, pool_const = [], []
    if poolsec:
        for s in poolsec["address_sites"]:
            pool_addr.append(dict(operand=num(s["operand_va"]), old=num(s["old"]), offset=num(s["offset"])))
        for s in poolsec["constant_sites"]:
            pool_const.append(dict(operand=num(s["operand_va"]), old=num(s["old"]), new=num(s["new"])))
        pool_addr.sort(key=lambda x: x["operand"])
        pool_const.sort(key=lambda x: x["operand"])

    o = []
    o.append("/* generated by iw4x32/tools/gen_tables.py from iw4x32/reference/engine_patches.json - do not edit */")
    o.append("/* %s: %d players, %d arrays, %d operands (+%d dual), %d cvar domains, %d size constants, %d code patches (%d dual), %d hooks%s */" %
             (src["file"], src.get("players", 32), len(arrays), len(operands), len(duals), len(cvars), len(sizes), len(patches), dual, len(hooks),
              ", %d pool addresses, %d pool constants" % (len(pool_addr), len(pool_const)) if poolsec else ""))
    o.append("#pragma once")
    o.append("")
    o.append("namespace Components")
    o.append("{")
    o.append("  // the pristine engine these tables were built for - the component refuses to patch anything else")
    o.append('  inline constexpr const char* IW4x32_ExeMd5 = "%s";' % src["pristine_md5"])
    o.append("  inline constexpr unsigned int IW4x32_ImageBase = %s;" % hx(base))
    o.append("  inline constexpr unsigned int IW4x32_Players = %d;  // the slot count these tables lay the engine out for" % src.get("players", 32))
    o.append("  inline constexpr unsigned int IW4x32_CgTailShift = %s;  // cg_s grew: absolute cg_tail operands" % hx(shift))
    o.append("")
    o.append("  enum IW4x32Role")
    o.append("  {")
    o.append("    IW4X32_CLIENT = 0,   // needed by players")
    o.append("    IW4X32_SERVER = 1,   // only to host more than 18 slots")
    o.append("  };")
    o.append("")
    o.append("  struct IW4x32Array")
    o.append("  {")
    o.append("    const char* name;")
    o.append("    unsigned int oldLo, oldHi;      // the stock array in the exe image")
    o.append("    unsigned int newSize;           // allocate this many zeroed bytes")
    o.append("    unsigned int operandFirst, operandCount;")
    o.append("    unsigned char role, grownInPlace;")
    o.append("  };")
    o.append("")
    o.append("  struct IW4x32Operand")
    o.append("  {")
    o.append("    unsigned int insnVa, operandVa;")
    o.append("    unsigned int old;               // the value the stock exe holds there")
    o.append("    unsigned int offset;            // new value = array base + offset")
    o.append("    unsigned short array;           // index into IW4x32_Arrays")
    o.append("    unsigned char fixed;            // absolute: cg_s grew in place, new = old + CgTailShift")
    o.append("  };")
    o.append("")
    o.append("  // an operand inside a moved array whose value depends on the server's player/body layout: the")
    o.append("  // layout switch writes array base + oursOffset (our layout) or base + stockOffset (stock 18-slot)")
    o.append("  struct IW4x32DualOperand")
    o.append("  {")
    o.append("    unsigned int insnVa, operandVa;")
    o.append("    unsigned int old;               // the value the stock exe holds there")
    o.append("    unsigned int oursOffset, stockOffset;")
    o.append("    unsigned short array;           // index into IW4x32_Arrays")
    o.append("  };")
    o.append("")
    o.append("  struct IW4x32BytePatch")
    o.append("  {")
    o.append("    unsigned int va;")
    o.append("    unsigned int oldFirst, newFirst;    // index into IW4x32_Bytes")
    o.append("    unsigned char len, role, dual;")
    o.append("  };")
    o.append("")
    o.append("  struct IW4x32SizeConstant")
    o.append("  {")
    o.append("    unsigned int insnVa, operandVa;")
    o.append("    unsigned int oldValue, newValue;")
    o.append("    unsigned char role;")
    o.append("  };")
    o.append("")
    o.append("  struct IW4x32Hook")
    o.append("  {")
    o.append("    unsigned int va;")
    o.append("    unsigned int replacedFirst;     // index into IW4x32_Bytes: the bytes the jmp overwrites")
    o.append("    unsigned char replacedLen, role;")
    o.append("    const char* stub;               // IW4x32::HookStub name")
    o.append("  };")
    o.append("")
    if poolsec:
        o.append("  // IW4x-32: the GSC script-variable pool, relocated and grown (see engine_patches.json 'pool')")
        o.append("  struct IW4x32PoolAddress")
        o.append("  {")
        o.append("    unsigned int operandVa;     // the instruction operand holding a pool address")
        o.append("    unsigned int old;           // the value the stock exe holds there")
        o.append("    unsigned int offset;        // new value = pool base + offset")
        o.append("  };")
        o.append("")
        o.append("  struct IW4x32PoolConstant")
        o.append("  {")
        o.append("    unsigned int operandVa;     // the instruction operand holding a pool INDEX constant")
        o.append("    unsigned int oldValue;      // the stock geometry value")
        o.append("    unsigned int newValue;      // the grown geometry value")
        o.append("  };")
        o.append("")

    for name, count in (("Arrays", len(arrays)), ("Operands", len(operands)), ("CvarDomains", len(cvars)),
                        ("SizeConstants", len(sizes)), ("CodePatches", len(patches)), ("Hooks", len(hooks)),
                        ("PoolAddresses", len(pool_addr)), ("PoolConstants", len(pool_const)),
                        ("DualOperands", len(duals))):
        o.append("  inline constexpr unsigned int IW4x32_%sCount = %d;" % (name, count))
    o.append("  inline constexpr unsigned int IW4x32_DualCount = %d;" % dual)
    o.append("")
    o.append("  static const IW4x32Array IW4x32_Arrays[] = {")
    for i, arr in enumerate(arrays):
        n = len([x for x in operands if x["array"] == i])
        o.append("    {%s,%s,%s,%s,%d,%d,%d,%d}," %
                 (json.dumps(arr["name"]), hx(num(arr["old_lo"])), hx(num(arr["old_hi"])), hx(num(arr["new_size"])),
                  first.get(i, len(operands)), n, ROLE[arr["role"]], 1 if arr["grown_in_place"] else 0))
    o.append("  };")
    o.append("")
    o.append("  static const IW4x32Operand IW4x32_Operands[] = {")
    for x in operands:
        o.append("    {%s,%s,%s,%s,%d,%d}," %
                 (hx(x["insn"]), hx(x["operand"]), hx(x["old"]), hx(x["offset"]), x["array"], 1 if x["fixed"] else 0))
    o.append("  };")
    o.append("")
    if duals:
        o.append("  static const IW4x32DualOperand IW4x32_DualOperands[] = {")
        for x in duals:
            o.append("    {%s,%s,%s,%s,%s,%d}," % (hx(x["insn"]), hx(x["operand"]), hx(x["old"]), hx(x["ours"]),
                                                  hx(x["stock"]), x["array"]))
        o.append("  };")
    else:  # no zero-length arrays in C++: the component walks IW4x32_DualOperandsCount entries
        o.append("  static const IW4x32DualOperand* const IW4x32_DualOperands = nullptr;")
    o.append("")
    emit_bytes(o, "IW4x32_Bytes", bytes(pool))
    o.append("")
    o.append("  static const IW4x32BytePatch IW4x32_CvarDomains[] = {")
    for x in cvars:
        o.append("    {%s,%d,%d,%d,%d,0}," % (hx(x["va"]), x["old"], x["new"], x["len"], x["role"]))
    o.append("  };")
    o.append("")
    o.append("  static const IW4x32SizeConstant IW4x32_SizeConstants[] = {")
    for x in sizes:
        o.append("    {%s,%s,%s,%s,%d}," % (hx(x["insn"]), hx(x["operand"]), hx(x["old"]), hx(x["new"]), x["role"]))
    o.append("  };")
    o.append("")
    o.append("  static const IW4x32BytePatch IW4x32_CodePatches[] = {")
    for x in patches:
        o.append("    {%s,%d,%d,%d,%d,%d}," % (hx(x["va"]), x["old"], x["new"], x["len"], x["role"], 1 if x["dual"] else 0))
    o.append("  };")
    o.append("")
    o.append("  static const IW4x32Hook IW4x32_Hooks[] = {")
    for x in hooks:
        o.append("    {%s,%d,%d,%d,%s}," % (hx(x["va"]), x["rep"], x["len"], x["role"], json.dumps(x["stub"])))
    o.append("  };")
    o.append("")
    if poolsec:
        o.append("  // the stock block these sites were found in, and the geometry to run instead. The pool is one")
        o.append("  // contiguous array of 16-byte entries: index 0 is the header, 1..ParentCap the parent pool,")
        o.append("  // Child0Base.. child pool 0, Child1Base.. child pool 1.")
        for key, name in (("base", "Pool_StockBase"), ("old_parent_cap", "Pool_OldParentCap"),
                          ("old_child0_base", "Pool_OldChild0Base"), ("old_child_cap", "Pool_OldChildCap"),
                          ("old_child1_base", "Pool_OldChild1Base"), ("old_entries", "Pool_OldEntries"),
                          ("parent_cap", "Pool_ParentCap"), ("child0_base", "Pool_Child0Base"),
                          ("child_cap", "Pool_ChildCap"), ("child1_base", "Pool_Child1Base"),
                          ("entries", "Pool_Entries")):
            o.append("  inline constexpr unsigned int IW4x32_%s = %s;" % (name, hx(num(poolsec[key]))))
        o.append('  inline constexpr unsigned int IW4x32_Pool_EntrySize = 0x10;')
        o.append("")
        o.append("  static const IW4x32PoolAddress IW4x32_PoolAddresses[] = {")
        for x in pool_addr:
            o.append("    {%s,%s,%s}," % (hx(x["operand"]), hx(x["old"]), hx(x["offset"])))
        o.append("  };")
        o.append("")
        o.append("  static const IW4x32PoolConstant IW4x32_PoolConstants[] = {")
        for x in pool_const:
            o.append("    {%s,%s,%s}," % (hx(x["operand"]), hx(x["old"]), hx(x["new"])))
        o.append("  };")
    o.append("}")
    o.append("")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", newline="\n") as f:
        f.write("\n".join(o))
    print("wrote %s: %d arrays, %d operands, %d cvar domains, %d size constants, "
          "%d code patches (%d dual), %d hooks, %d bytes" %
          (a.out, len(arrays), len(operands), len(cvars), len(sizes), len(patches), dual, len(hooks), len(pool)))
    if poolsec:
        print("  pool: %d address sites, %d constant sites - parent %d entries, child %d entries x2"
              % (len(pool_addr), len(pool_const), num(poolsec["parent_cap"]), num(poolsec["child_cap"])))


if __name__ == "__main__":
    main()
