"""Score an extracted register map against a known-good sensor IR.

Usage: python scripts/score_extraction.py <extracted-map.json> <ground-truth-ir.json>

Matching is by address (the value that actually corrupts generated drivers);
names are compared leniently (case-insensitive, containment either way)
since vendors and IR authors abbreviate differently.
"""

import json
import re
import sys


def norm_name(n: str) -> str:
    return re.sub(r"[^a-z0-9]", "", n.lower())


def main() -> int:
    extracted = json.load(open(sys.argv[1], encoding="utf-8"))
    truth = json.load(open(sys.argv[2], encoding="utf-8"))

    truth_regs = {
        int(r.get("address") or r["offset"], 16): r["name"]
        for r in truth["registers"]
    }
    ext_regs = {
        int(r["offset"], 16): r["name"] for r in extracted["registers"]
    }

    found, name_ok, missing = 0, 0, []
    for addr, tname in sorted(truth_regs.items()):
        if addr in ext_regs:
            found += 1
            en, tn = norm_name(ext_regs[addr]), norm_name(tname)
            if en in tn or tn in en:
                name_ok += 1
        else:
            missing.append(f"0x{addr:02X} {tname}")

    spurious = [
        f"0x{a:02X} {n}" for a, n in sorted(ext_regs.items()) if a not in truth_regs
    ]

    n = len(truth_regs)
    print(f"address recall : {found}/{n} ({100 * found / n:.0f}%)")
    print(f"name agreement : {name_ok}/{found} of found")
    print(f"spurious       : {len(spurious)}")
    for s in spurious:
        print(f"  + {s}")
    if missing:
        print("missing:")
        for m in missing:
            print(f"  - {m}")
    return 0 if found == n and not spurious else 1


if __name__ == "__main__":
    sys.exit(main())
