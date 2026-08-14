"""Scope-honesty panel (V1.8 Part D).

For each generated driver we surface which of the seven roadmap items the output
covers, and HOW each was established — cross-checked against the map, marked
UNVERIFIED, handled by the platform (the Arduino core), your input, or not
covered. An engineer must be able to see at a glance what was verified and what
was not. This reads only the report the judge already produced plus the target;
it verifies nothing new.

The seven items (product roadmap):
  1 identify peripheral/interface   2 register map        3 bit fields
  4 peripheral clock                5 GPIO / pin mapping  6 init sequence
  7 error conditions
"""

from __future__ import annotations

from validator.report import ValidationReport

# status vocabulary the UI renders with distinct badges:
#   cross-checked    verified against the extracted map / MCU map
#   marked-unverified present in the code but flagged UNVERIFIED (not checked)
#   platform-owned   the Arduino core / target platform owns this, not us
#   your-input       a value you supplied/confirmed
#   not-covered      out of scope for this target/inputs


def _it(item: int, title: str, status: str, detail: str) -> dict:
    return {"item": item, "title": title, "status": status, "detail": detail}


def build_scope(
    target: str,
    register_map: dict,
    report: ValidationReport,
    has_mcu_map: bool,
) -> list[dict]:
    reg_ok = report.checks.get("register_crosscheck") == "pass"
    n_fields = len(report.unverified_fields)
    n_comp = len(report.unverified_computations)
    n_map = len(register_map.get("registers", [])) + len(register_map.get("commands", []))
    readout = register_map.get("readout")
    ro_ok = report.checks.get("readout_crosscheck") == "pass"
    prov = register_map.get("provenance") or {}
    peripheral = register_map.get("peripheral", "?")

    items: list[dict] = []

    # 1 — interface identification
    if prov.get("peripheral") == "user":
        items.append(_it(1, "Peripheral / interface identified", "your-input",
                         f"{peripheral} — you confirmed it on the review screen"))
    elif prov.get("peripheral"):
        items.append(_it(1, "Peripheral / interface identified", "cross-checked",
                         f"{peripheral} — detected from the datasheet and confirmed"))
    else:
        items.append(_it(1, "Peripheral / interface identified", "not-covered",
                         "no confirmed interface"))

    # 2 — register map (or, for a fixed-readout device, the readout parameters).
    if readout:
        # V1.9 item 3: a register-less part is not a degraded part — say so, and
        # report the readout parameters as the (cross-checked) ground truth.
        items.append(_it(
            2, "Register map",
            "cross-checked" if ro_ok else "not-covered",
            "no register map — FIXED READOUT device; the value bit-slice "
            f"[{readout['value_msb']}:{readout['value_lsb']}], sign and "
            f"{readout['lsb_weight']}/LSB scale were "
            + ("cross-checked against the datasheet" if ro_ok else "NOT verified")))
    elif n_map == 0:
        # A cross-check over an EMPTY map verifies nothing (TMP100 in V1.8).
        items.append(_it(2, "Register map", "not-covered",
                         "no registers or commands were extracted from this "
                         "datasheet — the driver's register use could NOT be "
                         "cross-checked against a map"))
    elif reg_ok:
        items.append(_it(2, "Register map", "cross-checked",
                         f"every register offset/opcode used in the code exists in "
                         f"the extracted map ({n_map} entries)"))
    else:
        items.append(_it(2, "Register map", "not-covered",
                         "the register cross-check did not pass"))

    # 3 — bit fields (for a readout device the value bit-slice IS the field)
    if readout:
        items.append(_it(3, "Bit fields",
                         "cross-checked" if ro_ok else "not-covered",
                         "the value bit-slice is a readout parameter, "
                         + ("verified against the datasheet" if ro_ok else "unverified")))
    elif n_fields:
        items.append(_it(3, "Bit fields", "marked-unverified",
                         f"{n_fields} bit-field define(s) the map could not confirm "
                         "are flagged UNVERIFIED in the source"))
    else:
        items.append(_it(3, "Bit fields", "cross-checked",
                         "bit positions used match the extracted map"))

    # 4-6 — clock / GPIO / init sequence: ownership depends on the target
    if target == "arduino":
        core = "the Arduino core"
        items.append(_it(4, "Peripheral clock", "platform-owned",
                         f"{core} enables the bus peripheral clock"))
        items.append(_it(5, "GPIO / pin mapping", "platform-owned",
                         f"{core} owns pin configuration; the bus instance and "
                         "pins/CS are your input"))
        items.append(_it(6, "Init sequence", "platform-owned",
                         f"{core} brings up Wire/SPI; begin() only reads the device"))
    elif has_mcu_map:
        items.append(_it(4, "Peripheral clock", "cross-checked",
                         "the RCC clock-enable bit is checked against the MCU map"))
        items.append(_it(5, "GPIO / pin mapping", "cross-checked",
                         "GPIO registers are checked against the MCU map; the pin "
                         "numbers and AF are your input"))
        items.append(_it(6, "Init sequence", "marked-unverified",
                         "the ordered init sequence is transcribed from the "
                         "reference manual and flagged UNVERIFIED"))
    else:
        note = "your MCU's responsibility — add an MCU reference manual (two-doc " \
               "flow) for a complete, cross-checked bring-up"
        items.append(_it(4, "Peripheral clock", "not-covered", note))
        items.append(_it(5, "GPIO / pin mapping", "not-covered", note))
        items.append(_it(6, "Init sequence", "not-covered", note))

    # 7 — error conditions
    items.append(_it(7, "Error conditions",
                     "cross-checked" if reg_ok else "not-covered",
                     "status/error handling is generated in the driver against the "
                     "mapped registers" if reg_ok
                     else "not established"))

    # cross-cutting honesty note: transcribed compensation math is never a clean pass
    if n_comp:
        for it in items:
            if it["item"] == 2:
                it["detail"] += (f" — note: {n_comp} block(s) of compensation math "
                                 "transcribed from datasheet prose are flagged "
                                 "UNVERIFIED (logic not checked)")
    return items
