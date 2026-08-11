"""Cross-check generated MCU bring-up against the MCU map (V1.7, piece 6).

The device cross-check (crosscheck.py) verifies register OFFSET/opcode/bit usage
against the device register map. This does the analogous job for the host MCU:
every RCC/GPIO/peripheral bit position and register offset the generated code
defines must match the MCU map. A clock enabled on the wrong bit (bit 22 instead
of I2C1's bit 21) is a real, silent hardware bug that compiles clean — the same
class the device offset check catches, now for the MCU side.

Conservative by design: it checks `#define`d constants that clearly reference a
known MCU field/register (so it never false-fails on CMSIS symbols it cannot
resolve). Only runs when an MCU map is supplied.
"""

from __future__ import annotations

import re

from validator.crosscheck import DEFINE_RE, SHIFT_EXPR_RE, _eval_value
from validator.report import Failure, ValidationReport

_OFFSET_SUFFIX = re.compile(r"_(OFFSET|OFS|BASE)$", re.IGNORECASE)
_BIT_SUFFIX = re.compile(r"_(POS|SHIFT|BIT|MSK|MASK|EN|Pos|Msk)$", re.IGNORECASE)


def _norm(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", s).upper()


def _known_bits(mcu_map: dict) -> dict[str, int]:
    """field/enable name -> bit position. Clock enables and resets are named
    <peripheral>EN / <peripheral>RST (I2C1EN -> bit 21); register fields keep
    their own names (BERR, PE, ...)."""
    bits: dict[str, int] = {}
    for c in mcu_map.get("clock_enables", []):
        bits.setdefault(_norm(c["peripheral"] + "EN"), c["bit"])
    for c in mcu_map.get("reset_controls", []):
        bits.setdefault(_norm(c["peripheral"] + "RST"), c["bit"])
    for group in ("clock_registers", "gpio_registers", "peripheral_registers"):
        for r in mcu_map.get(group, []):
            for f in r.get("fields", []):
                m = re.match(r"\[(\d+):(\d+)\]", f["bits"])
                if m:
                    bits.setdefault(_norm(f["name"]), int(m.group(2)))
    return bits


def _known_offsets(mcu_map: dict) -> dict[str, int]:
    offs: dict[str, int] = {}
    for group in ("clock_registers", "gpio_registers", "peripheral_registers"):
        for r in mcu_map.get(group, []):
            if r.get("offset"):
                offs.setdefault(_norm(r["name"]), int(r["offset"], 16))
    return offs


def _match_known(define_name: str, known: dict[str, int]) -> tuple[str, int] | None:
    """Longest known name that is a suffix of the define's stem wins.
    'RCC_APB1ENR_I2C1EN_Pos' -> stem 'RCCAPB1ENRI2C1EN' -> matches 'I2C1EN'."""
    stem = _norm(_BIT_SUFFIX.sub("", _OFFSET_SUFFIX.sub("", define_name)))
    best, best_len = None, 0
    for kname, kval in known.items():
        if len(kname) >= 4 and stem.endswith(kname) and len(kname) > best_len:
            best, best_len = (kname, kval), len(kname)
    return best


def _bit_positions(expr: str) -> set[int]:
    """Candidate bit positions an expression could denote. Lenient (accepts a
    bare N as a position AND a power-of-two as a mask's low bit) so it never
    false-fails on notation; a genuinely wrong bit still fails because none of
    its candidates equals the map's position."""
    cands: set[int] = set()
    m = SHIFT_EXPR_RE.search(expr)
    if m:
        cands.add(int(m.group(2)))          # (1 << N) -> N
    v = _eval_value(expr)
    if v is not None:
        if 0 <= v <= 31:
            cands.add(v)                     # bare position
        if v > 1 and (v & (v - 1)) == 0:
            cands.add((v & -v).bit_length() - 1)  # single-bit mask -> low bit
    return cands


def mcu_crosscheck(
    files: dict[str, list[str]], mcu_map: dict, report: ValidationReport
) -> None:
    known_bits = _known_bits(mcu_map)
    known_offs = _known_offsets(mcu_map)
    ran = False
    for fname, lines in files.items():
        for idx, line in enumerate(lines):
            m = DEFINE_RE.match(line)
            if not m:
                continue
            name, expr = m.group(1), m.group(2)

            if _OFFSET_SUFFIX.search(name):
                hit = _match_known(name, known_offs)
                v = _eval_value(expr)
                if hit and v is not None:
                    ran = True
                    if v != hit[1]:
                        report.failures.append(Failure(
                            "mcu_crosscheck", fname, idx + 1,
                            f"{name} = 0x{v:X} does not match MCU-map offset "
                            f"0x{hit[1]:X} for register {hit[0]}",
                        ))
                continue

            hit = _match_known(name, known_bits)
            if hit is None:
                continue
            cands = _bit_positions(expr)
            if not cands:
                continue
            ran = True
            if hit[1] not in cands:
                report.failures.append(Failure(
                    "mcu_crosscheck", fname, idx + 1,
                    f"{name} = {sorted(cands)} does not match MCU-map bit "
                    f"{hit[1]} for {hit[0]} — wrong clock/peripheral bit",
                ))
    report.checks["mcu_crosscheck"] = (
        "fail" if any(f.check == "mcu_crosscheck" for f in report.failures)
        else "pass" if ran else "skipped"
    )
    if not ran:
        report.notes.append(
            "MCU cross-check found no named RCC/GPIO/peripheral bit or offset "
            "defines to verify (generated code may use CMSIS symbols directly)"
        )
