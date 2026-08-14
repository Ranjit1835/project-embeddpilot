"""Stage 4: parse stitched logical tables into registers and bit fields.

Three table shapes are recognized:
  A. register-index tables   (name + address columns, one register per row)
  B. bit-field tables        (bits + field-name columns, rows attach to a register)
  C. bit-column memory maps  (header has bit7..bit0 columns; BME280-style)

Everything else is ignored. Every parsed register records which pages it came
from and a per-register confidence based on how cleanly its cells parsed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ingestion.tables import LogicalTable

HEX_RE = re.compile(r"^(?:0[xX]([0-9A-Fa-f]+)|([0-9A-Fa-f]{2,})\s*[hH])$")
BITRANGE_RE = re.compile(r"\[?\s*(\d+)\s*[:.]{1,2}\s*(\d+)\s*\]?")
SINGLE_BIT_RE = re.compile(r"^\[?\s*(\d+)\s*\]?$")
BINARY_RE = re.compile(r"^[01]{4,}$")
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-\. /()\[\]]*$")
# headerless tables get no benefit of the doubt: identifier-shaped names only
NAME_STRICT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,23}$")
# field labels embed their range in vendor notation: adc_out_xlsb<7:3>,
# oss<1:0>, osrs_t[2:0], spi3w_en[0]
EMBEDDED_RANGE_RE = re.compile(r"[<\[]\s*(\d+)(?:\s*:\s*(\d+))?\s*[>\]]?")

# dict order is match priority: 'name' goes LAST because its aliases are
# generic — 'Register Address' must resolve to address, not name
COLUMN_ROLES = {
    "address": ["address offset", "offset", "address", "addr", "reg addr", "hex address"],
    "reset": ["reset value", "reset state", "reset", "default", "por", "initial value"],
    "access": ["access", "acc", "type", "r/w", "rw", "attribute", "mode"],
    "bits": ["bit position", "bit range", "bits", "bit", "position"],
    "field": ["field name", "bit name", "field", "bit symbol"],
    "description": ["description", "function", "comment", "definition"],
    "name": ["register name", "register", "name", "mnemonic", "symbol", "reg"],
}


@dataclass
class ExtractedField:
    name: str
    bits: str                 # normalized "[msb:lsb]"
    description: str = ""


@dataclass
class ExtractedRegister:
    name: str
    offset: str               # normalized "0x.."
    reset_value: str | None = None
    access: str | None = None # RW | RO | WO
    fields: list[ExtractedField] = field(default_factory=list)
    confidence: str = "high"
    source_pages: list[int] = field(default_factory=list)
    parse_issues: list[str] = field(default_factory=list)


def _norm_hex(cell: str) -> str | None:
    """Strict: the whole cell must be one hex value. Garbled cells
    ('stat0e0 h', 'BFh d own to AAh') must NOT silently yield a number —
    a wrong offset presented confidently is worse than no offset.
    No decimal fallback either: electrical tables are full of plain numbers
    ('20' is a rise time, not address 0x14); register addresses are
    hex-notated in practice."""
    cell = cell.strip().rstrip(".")
    if cell.lower() in ("n/a", "na", "-", "--", "x", "tbd", ""):
        return None
    m = HEX_RE.match(cell)
    if m:
        return "0x" + (m.group(1) or m.group(2)).upper()
    if BINARY_RE.fullmatch(cell):
        return f"0x{int(cell, 2):X}"
    return None


def _norm_hex_pair(cell: str) -> list[str] | None:
    """'0x88 / 0x89' — a multi-byte value stored across two addresses."""
    parts = [p.strip() for p in cell.split("/")]
    if len(parts) == 2:
        both = [_norm_hex(p) for p in parts]
        if all(both):
            return both  # type: ignore[return-value]
    return None


def _parse_field_label(label: str) -> tuple[str | None, int | None]:
    """'> adc_out_lsb<7:0' -> ('adc_out_lsb', 8); 'osrs_t[2:0]' -> ('osrs_t', 3);
    'spi3w_en[0]' -> ('spi3w_en', 1); 'id<7:0> control' -> ('id', 8).
    The embedded range gives the field WIDTH (its indices may be field-relative
    or register-absolute depending on vendor, so only the width is trusted).
    Returns (None, None) for reserved/hardwired cells ('0', '1', '-', 'x')."""
    # text bleeding from a neighboring column often arrives as a '>' prefix
    label = label.strip().lstrip(">").strip()
    width = None
    m = EMBEDDED_RANGE_RE.search(label)
    if m:
        hi = int(m.group(1))
        lo = int(m.group(2)) if m.group(2) is not None else hi
        width = abs(hi - lo) + 1
        label = label[: m.start()].strip() or EMBEDDED_RANGE_RE.sub("", label).strip()
    if not label or re.fullmatch(r"[01xX\-/]+", label):
        return None, None
    if not NAME_RE.match(label):
        return None, None
    return label, width


def _clean_field_name(label: str) -> str | None:
    return _parse_field_label(label)[0]


def _identifier_prefix(cell: str) -> str | None:
    """Leading identifier of a decorated cell: 'dig_T1 [7:0] / [15:8]' -> 'dig_T1'."""
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]+)", cell.strip())
    return m.group(1) if m else None


def _pair_suffixes(t: LogicalTable, col_a: int, col_b: int) -> tuple[str, str]:
    """Which of the two address columns is MSB vs LSB, from their labels."""
    def label(col: int) -> str:
        cells = [t.header[col]] if col < len(t.header) else []
        cells += [r[col] for r in t.rows if col < len(r)]
        for c in cells:
            if c.strip().upper() in ("MSB", "LSB"):
                return c.strip().upper()
        return ""

    return ("_LSB", "_MSB") if label(col_a) == "LSB" else ("_MSB", "_LSB")


def _norm_access(cell: str) -> str | None:
    c = re.sub(r"[^a-z/]", "", cell.lower())
    if c in ("rw", "r/w", "readwrite", "read/write"):
        return "RW"
    if c in ("r", "ro", "readonly", "read", "read/only"):
        return "RO"
    if c in ("w", "wo", "writeonly", "write", "write/only", "w/o", "r/wc"):
        return "WO"
    return None


def _norm_bits(cell: str) -> str | None:
    m = BITRANGE_RE.search(cell)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return f"[{max(a, b)}:{min(a, b)}]"
    m = SINGLE_BIT_RE.match(cell.strip())
    if m:
        return f"[{m.group(1)}:{m.group(1)}]"
    return None


def _map_columns(header: list[str]) -> dict[str, int]:
    """Assign each schema role the best-matching column, longest alias first
    so 'register name' wins over 'register'."""
    roles: dict[str, int] = {}
    taken: set[int] = set()
    for role, aliases in COLUMN_ROLES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            for i, h in enumerate(header):
                if i in taken:
                    continue
                if alias in h.lower():
                    roles[role] = i
                    taken.add(i)
                    break
            if role in roles:
                break
    return roles


def table_roles(t: LogicalTable) -> dict[str, int]:
    """Header aliases first, then data-driven correction and fallback.

    Correction: merged header cells duplicate across columns ('Register
    Address' labeling an empty column while the hex lives one column over),
    so an alias-assigned column that is mostly empty loses its role to a
    column whose DATA matches much better.

    Fallback: summary tables name address columns after the peripheral
    instance ('I2C0', 'I2C1') — a column of hex cells IS the address column.
    """
    roles = _map_columns(t.header)
    checks = {
        "address": lambda c: _norm_hex(c) is not None or _norm_hex_pair(c) is not None,
        "access": lambda c: _norm_access(c) is not None,
        # cells like 'dig_T1 [7:0] / [15:8]' — an identifier leads the cell
        "name": lambda c: (
            re.match(r"^[A-Za-z_][A-Za-z0-9_]*(\s|\[|<|$)", c) is not None
            and _norm_hex(c) is None
        ),
    }
    ncols = max((len(r) for r in t.rows), default=0)
    nrows = len(t.rows)

    def density(col: int, pred) -> float:
        if nrows == 0:
            return 0.0
        hits = sum(
            1 for r in t.rows if col < len(r) and r[col].strip() and pred(r[col].strip())
        )
        return hits / nrows  # empty cells count against: roles need data

    for role, pred in checks.items():
        assigned = roles.get(role)
        best_col, best_d = None, 0.0
        for i in range(ncols):
            if i in roles.values() and i != assigned:
                continue
            d = density(i, pred)
            if d > best_d:
                best_col, best_d = i, d
        if assigned is not None:
            if density(assigned, pred) < 0.5 and best_d >= 0.7 and best_col != assigned:
                roles[role] = best_col
        elif best_col is not None and best_d >= 0.6 and nrows >= 3:
            roles[role] = best_col

    # a SECOND hex column labeled MSB/LSB is the other half of a multi-byte
    # register pair (BMP180 calibration layout) — per-instance address columns
    # (I2C0/I2C1) carry no such label and must NOT be treated as a pair
    addr = roles.get("address")
    if addr is not None:
        pred = checks["address"]
        for i in range(ncols):
            if i in roles.values() or density(i, pred) < 0.6:
                continue
            cols_text = {
                t.header[c].strip().upper() if c < len(t.header) else ""
                for c in (addr, i)
            } | {
                r[c].strip().upper()
                for r in t.rows for c in (addr, i) if c < len(r)
            }
            if {"MSB", "LSB"} <= cols_text:
                roles["address2"] = i
            break
    return roles


def _bit_column_map(header: list[str]) -> dict[int, int] | None:
    """Detect BME280-style headers where each column IS a bit: bit7..bit0."""
    bit_cols: dict[int, int] = {}
    for i, h in enumerate(header):
        m = re.fullmatch(r"(?:bit\s*)?([0-7])", h.lower().strip())
        if m:
            bit_cols[int(m.group(1))] = i
    return bit_cols if len(bit_cols) >= 4 else None


# A digital-output code column: 5+ contiguous bits. Register addresses and
# reset values are never presented as a whole column of these; a
# temperature->code conversion table is (V1.9 item 1).
_LONGBIN_RE = re.compile(r"^[01]{5,}$")


def _is_value_code_lookup(t: LogicalTable) -> bool:
    """A value->digital-output lookup table (e.g. temperature -> binary/hex code)
    masquerades as a register index: its binary code column is read as hex
    'addresses' via BINARY_RE, so rows look address-bearing. A register map is
    never a full COLUMN of multi-bit binary codes. Reject such a table from
    register classification.

    The observed false positives (TMP100 p.9-10, LM75B p.14) parsed to 0
    registers only by luck (their value column isn't identifier-shaped); the same
    misclassification on another document could emit spurious registers, which
    would poison the map the cross-check treats as ground truth. This is the
    highest-risk item in the round, fixed before anything builds on the parser.
    """
    rows = t.rows
    if len(rows) < 3:
        return False
    ncols = max((len(r) for r in rows), default=0)

    def col_frac(col: int, pred) -> float:
        cells = [r[col].strip() for r in rows if col < len(r) and r[col].strip()]
        return (sum(1 for x in cells if pred(x)) / len(cells)) if cells else 0.0

    has_binary_code_col = any(
        col_frac(c, lambda x: bool(_LONGBIN_RE.match(x))) >= 0.5 for c in range(ncols)
    )
    if not has_binary_code_col:
        return False
    # a real register index names its access (R/W/RO); a lookup table never does.
    has_access_col = any(
        col_frac(c, lambda x: _norm_access(x) is not None) >= 0.5 for c in range(ncols)
    )
    return not has_access_col


def classify_table(t: LogicalTable) -> str:
    # V1.9 item 1: a value->code lookup table must never be read as registers —
    # a spurious register poisons the map the validator trusts as ground truth.
    if _is_value_code_lookup(t):
        return "other"
    roles = table_roles(t)
    if _bit_column_map(t.header) and ("name" in roles or "address" in roles):
        return "bit_column_map"
    if "address" in roles and ("name" in roles or "field" in roles):
        return "register_index"
    if "bits" in roles and ("field" in roles or "name" in roles):
        return "bit_fields"
    # headerless salvage: rows where some cell parses as hex address and
    # another looks like an identifier
    if t.rows and not any(t.header):
        hexish = sum(1 for r in t.rows if any(_norm_hex(c) for c in r))
        if hexish >= max(2, len(t.rows) // 2):
            return "register_index_headerless"
    return "other"


def _get(row: list[str], idx: int | None) -> str:
    return row[idx].strip() if idx is not None and idx < len(row) else ""


def parse_register_index(t: LogicalTable) -> list[ExtractedRegister]:
    """Row semantics, decided by which identity cells the row itself has:
      name + address        -> new register
      neither (merged span) -> continuation of the previous register (field rows)
      name only             -> section subheader ('Status registers') — skip;
                               forward-filling an address here fabricates registers
    """
    if _is_value_code_lookup(t):
        return []  # V1.9 item 1: defense-in-depth against lookup false positives
    roles = table_roles(t)
    name_i = roles.get("name", roles.get("field"))
    out: list[ExtractedRegister] = []
    current: ExtractedRegister | None = None
    for row in t.rows:
        raw_name = _get(row, name_i)
        raw_reset = _get(row, roles.get("reset"))
        raw_access = _get(row, roles.get("access"))
        raw_addr = _get(row, roles.get("address"))
        offset = _norm_hex(raw_addr)

        if offset is None:
            # '0x88 / 0x89' with 'dig_T1 [7:0] / [15:8]': one value, two bytes
            pair = _norm_hex_pair(raw_addr)
            if pair:
                base_name = _identifier_prefix(raw_name)
                if base_name:
                    ranges = re.findall(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", raw_name)
                    for k, addr in enumerate(pair):
                        if len(ranges) == len(pair):
                            suffix = "_LSB" if int(ranges[k][1]) == 0 else "_MSB"
                        else:
                            suffix = f"_{k}"
                        out.append(
                            ExtractedRegister(
                                name=base_name + suffix, offset=addr,
                                confidence="medium",
                                source_pages=list(t.source_pages),
                                parse_issues=[f"split from paired cell '{raw_addr}'"],
                            )
                        )
                current = None
                continue

        if offset is not None:
            name = raw_name if raw_name and NAME_RE.match(raw_name) else (
                _identifier_prefix(raw_name) or f"REG_{offset}"
            )
            offset2 = _norm_hex(_get(row, roles.get("address2")))
            if offset2 is not None:
                # MSB/LSB address pair: one logical value, two byte registers
                suf = _pair_suffixes(t, roles["address"], roles["address2"])
                for s, off in zip(suf, (offset, offset2)):
                    out.append(
                        ExtractedRegister(
                            name=name + s, offset=off, confidence="medium",
                            source_pages=list(t.source_pages),
                            parse_issues=["split from MSB/LSB column pair"],
                        )
                    )
                current = None
                continue
            current = ExtractedRegister(
                name=name, offset=offset, source_pages=list(t.source_pages)
            )
            if raw_reset:
                current.reset_value = _norm_hex(raw_reset)
                if current.reset_value is None:
                    current.parse_issues.append(f"unparsed reset value '{raw_reset}'")
            if raw_access:
                current.access = _norm_access(raw_access)
                if current.access is None:
                    current.parse_issues.append(f"unparsed access '{raw_access}'")
            current.confidence = _register_confidence(current, raw_reset, raw_access)
            out.append(current)
        elif raw_name:
            current = None  # subheader breaks field-row attachment
            continue

        # inline bits/field cells belong to the row's register (new or continued)
        if current is not None:
            raw_bits = _norm_bits(_get(row, roles.get("bits")))
            raw_field = _get(row, roles.get("field"))
            if raw_bits and raw_field and raw_field != current.name:
                fname = _clean_field_name(raw_field)
                if fname:
                    current.fields.append(
                        ExtractedField(
                            name=fname, bits=raw_bits,
                            description=_get(row, roles.get("description")),
                        )
                    )
    return out


def parse_headerless(t: LogicalTable) -> list[ExtractedRegister]:
    """No trusted header, so demand structural consistency instead:
    strict identifier names in ONE column, hex addresses in consistent
    columns, at least 3 such rows. This is what stops command/timing
    tables (hex values + prose) from masquerading as register maps.

    Two consistent hex columns are treated as an MSB/LSB address pair
    (common for calibration/multi-byte parameters) and emit two registers
    per row, suffixed from the column's own label row when present."""
    if _is_value_code_lookup(t):
        return []  # V1.9 item 1: defense-in-depth against lookup false positives
    candidates = []  # (row, name_col, name, {col: hex})
    for row in t.rows:
        hexes = {i: h for i, c in enumerate(row) if (h := _norm_hex(c))}
        names = {
            i: c.strip() for i, c in enumerate(row)
            if c.strip() and i not in hexes and NAME_STRICT_RE.match(c.strip())
        }
        if hexes and names:
            candidates.append((row, names, hexes))
    if len(candidates) < 3:
        return []

    # majority vote on which columns hold names and addresses
    from collections import Counter

    name_col = Counter(i for _, names, _ in candidates for i in names).most_common(1)[0][0]
    hex_cols = [
        col for col, n in Counter(
            i for _, _, hexes in candidates for i in hexes
        ).most_common(2)
        if n >= len(candidates) * 0.6
    ]
    if not hex_cols:
        return []
    hex_cols.sort()

    # column labels like 'MSB'/'LSB' live in a non-candidate row of the same column
    suffixes = {}
    if len(hex_cols) == 2:
        for col in hex_cols:
            for row in t.rows:
                cell = row[col].strip().upper() if col < len(row) else ""
                if cell in ("MSB", "LSB"):
                    suffixes[col] = "_" + cell
                    break
        if len(suffixes) < 2:
            suffixes = {hex_cols[0]: "_MSB", hex_cols[1]: "_LSB"}

    out: list[ExtractedRegister] = []
    for row, names, hexes in candidates:
        if name_col not in names:
            continue
        for col in hex_cols:
            if col not in hexes:
                continue
            out.append(
                ExtractedRegister(
                    name=names[name_col] + suffixes.get(col, ""),
                    offset=hexes[col],
                    confidence="medium",
                    source_pages=list(t.source_pages),
                    parse_issues=["parsed from headerless table"],
                )
            )
    return out


def parse_bit_fields(t: LogicalTable) -> list[ExtractedField]:
    roles = _map_columns(t.header)
    field_i = roles.get("field", roles.get("name"))
    out: list[ExtractedField] = []
    for row in t.rows:
        bits = _norm_bits(_get(row, roles.get("bits")))
        fname = _get(row, field_i)
        if bits and fname and NAME_RE.match(fname):
            out.append(
                ExtractedField(
                    name=fname, bits=bits,
                    description=_get(row, roles.get("description")),
                )
            )
    return out


def parse_bit_column_map(t: LogicalTable) -> list[ExtractedRegister]:
    """One register per row; bit7..bit0 are columns. Merged field cells arrive
    as empty strings, so a label followed by empties IS the field's span
    (e.g. 'oss' in bit7, blank bit6, 'sco' in bit5 -> oss=[7:6])."""
    roles = _map_columns(t.header)
    bit_cols = _bit_column_map(t.header) or {}
    name_i = roles.get("name")
    out: list[ExtractedRegister] = []
    for row in t.rows:
        offset = _norm_hex(_get(row, roles.get("address")))
        if offset is None:
            continue  # strict hex: garbled range rows ('BFh down to AAh') drop out
        raw_name = _get(row, name_i) if name_i is not None else ""
        name = _clean_field_name(raw_name) or f"REG_{offset}"
        reg = ExtractedRegister(
            name=name, offset=offset, source_pages=list(t.source_pages)
        )
        raw_reset = _get(row, roles.get("reset"))
        if raw_reset:
            reg.reset_value = _norm_hex(raw_reset)
            if reg.reset_value is None and raw_reset.lower() not in ("n/a", "-", "x"):
                reg.parse_issues.append(f"unparsed reset value '{raw_reset}'")

        # walk msb -> lsb: non-empty cell starts a span, empties extend it
        span: tuple[str, int, int] | None = None  # (raw label, msb, lsb)
        for bit in sorted(bit_cols, reverse=True):
            label = _get(row, bit_cols[bit])
            if label:
                if span is not None:
                    _emit_field(reg, span)
                span = (label, bit, bit)
            elif span is not None:
                span = (span[0], span[1], bit)
        if span is not None:
            _emit_field(reg, span)

        garbled_name = name.startswith("REG_") and bool(raw_name)
        reg.confidence = (
            "low" if garbled_name
            else "high" if reg.fields and reg.reset_value is not None
            else "medium"
        )
        out.append(reg)
    return out


def _emit_field(reg: ExtractedRegister, span: tuple[str, int, int]) -> None:
    label, msb, lsb = span
    name, width = _parse_field_label(label)
    if name is None:
        return  # reserved / hardwired bits, not a named field
    # merged empty cells can't distinguish "field continues" from "reserved
    # gap"; the label's own width hint resolves it (status: measuring[0] at
    # bit3 followed by empties is [3:3], not [3:1])
    if width is not None and width <= msb - lsb:
        lsb = msb - width + 1
    reg.fields.append(ExtractedField(name=name, bits=f"[{msb}:{lsb}]"))


def _register_confidence(
    reg: ExtractedRegister, raw_reset: str, raw_access: str
) -> str:
    attempted = 2 + (1 if raw_reset else 0) + (1 if raw_access else 0)
    ok = 2  # name+offset are prerequisites for existing at all
    ok += 1 if (raw_reset and reg.reset_value is not None) else 0
    ok += 1 if (raw_access and reg.access is not None) else 0
    ratio = ok / attempted
    if ratio >= 0.99:
        return "high"
    if ratio >= 0.7:
        return "medium"
    return "low"
