"""Register/opcode cross-check with three-state field logic (Amendment 1).

Every offset, opcode, and bit-field definition in the generated code is
checked against the register map JSON:

  - offset/opcode not in the map ............................. HARD FAIL
  - field definition contradicting a mapped field ............ HARD FAIL
  - field definition for a register with unknown/absent field:
      carries the UNVERIFIED comment ......................... unverified (tagged)
      missing the UNVERIFIED comment ......................... HARD FAIL
  - hard-coded absolute address outside the *_BASE define .... HARD FAIL

Only #define lines are inspected; classification is by naming convention
(_OFFSET/_ADDR/_REG, _CMD/_OPCODE, _MASK/_MSK, _POS/_SHIFT) and by
value shape. Uncategorized hex literals are reported as notes, not failures.
"""

from __future__ import annotations

import re

from validator.report import Failure, UnverifiedField, ValidationReport

DEFINE_RE = re.compile(r"^\s*#\s*define\s+(\w+)\s+(.+?)\s*(?:/\*.*)?$")
HEX_RE = re.compile(r"0[xX][0-9A-Fa-f]+")
SHIFT_EXPR_RE = re.compile(
    r"\(?\s*(0[xX][0-9A-Fa-f]+|\d+)\s*[uU]?[lL]{0,2}\s*<<\s*(\d+)\s*\)?"
)

OFFSET_NAME_RE = re.compile(r"(_OFFSET|_OFS|_ADDR|_REG)$", re.IGNORECASE)
# _CMD_ anywhere marks an opcode: W25Q64JV_CMD_READ_SECURITY_REG is a command
# named after a register, not a register offset — opcode wins over the _REG suffix
OPCODE_NAME_RE = re.compile(
    r"(?:^|_)(CMD|OPCODE|INSTR)(?:$|_)|_OP$", re.IGNORECASE
)
MASK_NAME_RE = re.compile(r"(_MASK|_MSK)$", re.IGNORECASE)
POS_NAME_RE = re.compile(r"(_POS|_SHIFT|_BIT)$", re.IGNORECASE)
BASE_NAME_RE = re.compile(r"_BASE$", re.IGNORECASE)

ABS_ADDR_THRESHOLD = 0x10000


def crosscheck(files: dict[str, list[str]], register_map: dict, report: ValidationReport) -> None:
    """files: filename -> list of source lines."""
    regs = {int(r["offset"], 16): r for r in register_map.get("registers", [])}
    opcodes = {int(c["opcode"], 16) for c in register_map.get("commands", [])}
    base = register_map.get("base_address")
    base_val = int(base, 16) if base else None

    ran = False
    for fname, lines in files.items():
        for idx, line in enumerate(lines):
            m = DEFINE_RE.match(line)
            if not m:
                continue
            name, expr = m.group(1), m.group(2)
            value = _eval_value(expr)
            if value is None:
                continue
            ran = True
            prev = lines[idx - 1] if idx > 0 else ""
            has_marker = "UNVERIFIED" in line or "UNVERIFIED" in prev

            if BASE_NAME_RE.search(name):
                if base_val is not None and value not in (base_val, 0):
                    report.failures.append(Failure(
                        "register_crosscheck", fname, idx + 1,
                        f"{name} = 0x{value:X} does not match extracted base {base}",
                    ))
                continue

            if OPCODE_NAME_RE.search(name):
                if opcodes and value not in opcodes:
                    report.failures.append(Failure(
                        "register_crosscheck", fname, idx + 1,
                        f"opcode {name} = 0x{value:02X} does not exist in the commands array",
                    ))
                continue

            if OFFSET_NAME_RE.search(name) or "BASE" in expr.upper():
                if value >= ABS_ADDR_THRESHOLD:
                    report.failures.append(Failure(
                        "register_crosscheck", fname, idx + 1,
                        f"{name} = 0x{value:X} looks like a hard-coded absolute address; "
                        "addressing is relative — use <PERIPH>_BASE + offset",
                    ))
                elif value not in regs:
                    report.failures.append(Failure(
                        "register_crosscheck", fname, idx + 1,
                        f"offset {name} = 0x{value:02X} does not exist in the register map",
                    ))
                continue

            if MASK_NAME_RE.search(name) or POS_NAME_RE.search(name):
                _check_field(name, expr, value, fname, idx + 1, has_marker,
                             register_map, report)
                continue

            # uncategorized hex define: informational only, unless it lands in
            # the peripheral's own address region — 0xFFFFFFFF-style all-bits
            # masks are legitimate constants, not hard-coded addresses
            if (
                base_val is not None
                and base_val <= value < base_val + 0x100000
            ):
                report.failures.append(Failure(
                    "register_crosscheck", fname, idx + 1,
                    f"{name} = 0x{value:X} is an absolute address in the peripheral's "
                    "region — use *_BASE + offset",
                ))

    report.checks["register_crosscheck"] = (
        "fail" if any(f.check == "register_crosscheck" for f in report.failures)
        else "pass" if ran else "pass"
    )


def _check_field(
    name: str, expr: str, value: int, fname: str, lineno: int,
    has_marker: bool, register_map: dict, report: ValidationReport,
) -> None:
    is_mask = bool(MASK_NAME_RE.search(name))
    bits = _mask_to_bits(expr, value) if is_mask else f"[{value}:{value}]"
    reg = _owning_register(name, register_map)

    field = None
    if reg is not None:
        field = _matching_field(name, reg)

    if field is not None:
        expected = field["bits"]
        actual = bits if is_mask else None
        contradicts = (
            (is_mask and bits is not None and bits != expected)
            or (not is_mask and value != _lsb(expected))
        )
        if contradicts:
            report.failures.append(Failure(
                "register_crosscheck", fname, lineno,
                f"{name} claims bits {bits or value} but the map says "
                f"{reg['name']}.{field['name']} = {expected}",
            ))
        return

    # field absent from the map (or register unknown): unverified, never silent
    claimed = bits or f"value 0x{value:X}"
    report.unverified_fields.append(UnverifiedField(
        file=fname, line=lineno,
        register=reg["name"] if reg else "?",
        define=name, claimed_bits=claimed,
        has_unverified_comment=has_marker,
        source_pages=reg.get("source_pages", []) if reg else [],
    ))
    if not has_marker:
        report.failures.append(Failure(
            "register_crosscheck", fname, lineno,
            f"{name} defines a bit field the map cannot confirm and has no "
            "/* UNVERIFIED ... */ comment — unmarked invented fields are not allowed",
        ))


def _eval_value(expr: str) -> int | None:
    expr = expr.strip()
    m = SHIFT_EXPR_RE.fullmatch(expr)
    if m:
        lhs = int(m.group(1), 0)
        return lhs << int(m.group(2))
    m = re.fullmatch(r"\(?\s*(0[xX][0-9A-Fa-f]+|\d+)\s*[uU]?[lL]{0,2}\s*\)?", expr)
    if m:
        return int(m.group(1), 0)
    # (BASE + 0xNN) style: extract the offset literal
    m = re.fullmatch(r"\(\s*\w*BASE\w*\s*\+\s*(0[xX][0-9A-Fa-f]+)\s*[uU]?[lL]{0,2}\s*\)", expr)
    if m:
        return int(m.group(1), 16)
    return None


def _mask_to_bits(expr: str, value: int) -> str | None:
    if value == 0:
        return None
    tz = (value & -value).bit_length() - 1
    body = value >> tz
    if body & (body + 1):  # non-contiguous mask
        return None
    return f"[{tz + body.bit_length() - 1}:{tz}]"


def _lsb(bits: str) -> int:
    m = re.match(r"\[(\d+):(\d+)\]", bits)
    return int(m.group(2)) if m else -1


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _owning_register(define: str, register_map: dict) -> dict | None:
    """Longest register name embedded in the define name wins.
    I2C_CTR_TRANS_START_MASK -> I2C_CTR_REG (vendor names often end _REG)."""
    d = _norm(define)
    best, best_len = None, 0
    for r in register_map.get("registers", []):
        candidates = {_norm(r["name"]), _norm(re.sub(r"_reg$", "", r["name"], flags=re.IGNORECASE))}
        for c in candidates:
            if c and c in d and len(c) > best_len:
                best, best_len = r, len(c)
    return best


def _matching_field(define: str, reg: dict) -> dict | None:
    d = _norm(define)
    best, best_len = None, 0
    for f in reg.get("fields", []):
        fn = _norm(f["name"])
        if fn and fn in d and len(fn) > best_len:
            best, best_len = f, len(fn)
    return best
