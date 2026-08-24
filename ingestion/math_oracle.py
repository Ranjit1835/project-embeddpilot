"""V1.10a: extract a document-sourced MATH ORACLE from a datasheet.

The oracle is the ground truth the math cross-check executes against. It MUST
come from the document — never the model. Two kinds the V1.10a spike found to be
text-extractable (worked numeric examples in Bosch pressure sensors are trapped
in figures and are intentionally NOT handled here — they stay UNVERIFIED):

  - "table"          a conversion table of (digital code -> physical value), the
                     negative two's-complement rows included (LM75B S7.5.2).
  - "reference_code" the datasheet's own reference compensation functions, used
                     for a differential test (BME280 S4.2.3).

Each extractor returns None (never a guess) when the pattern is not present or is
ambiguous — the WS1 discipline: a null with a warning beats a confident wrong
value. `provenance` is always "detected" (from the document); a model value is
never allowed by the downstream provenance guard.
"""

from __future__ import annotations

import re

# unicode minus (U+2212) appears in TI/other datasheets instead of ASCII '-'
_MINUS = "−"
_TEMP_RE = re.compile(r"^([\-" + _MINUS + r"]?\d+(?:\.\d+)?)\s*°?\s*C?$")
# a table row: <temp>°C <binary(>=8 digits)> <hex>h  (spacing varies)
_ROW_RE = re.compile(
    r"([\-" + _MINUS + r"]?\d+(?:\.\d+)?)\s*°?C?\s+([01]{8,})\s+([0-9A-Fa-f]+)\s*[hH]\b")


def _c_ident(name: str) -> str:
    ident = re.sub(r"[^A-Za-z0-9]", "_", name or "")
    return (ident if ident and not ident[0].isdigit() else "_" + ident).lower()


def _num(s: str) -> float:
    return float(s.replace(_MINUS, "-"))


def extract_conversion_table(pages: list, chip: str) -> dict | None:
    """A (code -> temperature) table with an explicit LSB, e.g. LM75B S7.5.2
    'Temperature Data Format'. The hex code is the input the conversion function
    receives; the temperature is the expected output. Requires >=3 rows and at
    least one NEGATIVE row (the two's-complement path is the whole point of
    verifying this math)."""
    for p in pages:
        text = getattr(p, "text", "") or ""
        # some PDFs (TI) concatenate words with no spaces, so gate on a
        # whitespace-stripped form: 'TemperatureDataFormat' / 'DigitalOutput'.
        low_ns = re.sub(r"\s+", "", text.lower())
        if "temperaturedataformat" not in low_ns and "digitaloutput" not in low_ns:
            continue
        rows = _ROW_RE.findall(text)
        vectors, seen = [], set()
        for temp_s, _binary, hex_s in rows:
            code = int(hex_s, 16)
            out = _num(temp_s)
            if code in seen:
                continue
            seen.add(code)
            vectors.append({"in": code, "out": out})
        n_neg = sum(1 for v in vectors if v["out"] < 0)
        if len(vectors) >= 3 and n_neg >= 1:
            ident = _c_ident(chip)
            return {
                "kind": "table",
                "entry": f"{ident}_raw_to_celsius",
                "input_ctype": "int32_t",
                "output_ctype": "float",
                "vectors": vectors,
                "tolerance": "exact",
                "source_pages": [getattr(p, "number", 0)],
                "provenance": "detected",
                "notes": (
                    "conversion table extracted from the datasheet; the hex code "
                    "is passed to the generated conversion function and the result "
                    "compared exactly to the tabulated temperature"),
            }
    return None


# BME280 reference compensation function, located in the text layer (S4.2.3).
_BME_T_SIG = "BME280_compensate_T_int32"
_BME_TYPEDEFS = (
    "typedef int32_t BME280_S32_t;\n"
    "typedef uint32_t BME280_U32_t;\n"
    "typedef int64_t BME280_S64_t;\n")


def extract_reference_code(pages: list, chip: str) -> dict | None:
    """The datasheet's integer reference temperature-compensation function
    (BME280 S4.2.3), for a differential test. We extract the function TEXT,
    normalise typography (en-dash/minus, non-breaking spaces), and prepend the
    datasheet's own typedefs so it compiles standalone. Returns None if the
    function cannot be located and closed cleanly."""
    joined = "\n".join((getattr(p, "text", "") or "") for p in pages)
    if _BME_T_SIG not in joined:
        return None
    body = _slice_function(joined, _BME_T_SIG)
    if body is None:
        return None
    body = _normalise_c(body)
    # the reference reads calibration + t_fine as globals (datasheet names)
    ref_c = _BME_TYPEDEFS + "extern BME280_S32_t t_fine;\n" + body
    ident = _c_ident(chip)
    pnums = [getattr(p, "number", 0) for p in pages
             if _BME_T_SIG in (getattr(p, "text", "") or "")]
    return {
        "kind": "reference_code",
        "entry": f"{ident}_compensate_temperature",
        "reference_entry": _BME_T_SIG,
        "reference_c": ref_c,
        "input_ctype": "int32_t",
        "output_ctype": "int32_t",
        "tolerance": "exact",
        # harness-chosen calibration constants (NOT model-supplied answers): the
        # differential test only requires both sides use the SAME values. dig_T1
        # unsigned, dig_T2/T3 signed; t_fine is shared state initialised to 0.
        "calibration": {"dig_T1": 27504, "dig_T2": 26435, "dig_T3": -1000,
                        "t_fine": 0},
        "input_spread": [0, 131072, 262144, 519888, 400000, 16000, 524287, -50000],
        "source_pages": pnums or [0],
        "provenance": "detected",
        "notes": (
            "datasheet reference compensation function extracted for a "
            "differential test; verifies transcription fidelity of the generated "
            "math, not the algorithm's independent correctness"),
    }


def _slice_function(text: str, signature: str) -> str | None:
    """From the signature to its matching closing brace, brace-balanced."""
    i = text.find(signature)
    if i < 0:
        return None
    b = text.find("{", i)
    if b < 0:
        return None
    depth, j = 0, b
    while j < len(text):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                # include the return type on the signature line
                line_start = text.rfind("\n", 0, i) + 1
                return text[line_start:j + 1]
        j += 1
    return None


def _normalise_c(src: str) -> str:
    """PDF text mangles operators: en/em dashes for minus, NBSP for space, and
    smart quotes. Restore them so the reference compiles."""
    for bad, good in (("–", "-"), ("—", "-"), (_MINUS, "-"),
                      (" ", " "), ("“", '"'), ("”", '"')):
        src = src.replace(bad, good)
    return src


def extract_math_oracle(pages: list, chip: str, interface_hint: str = "") -> dict | None:
    """Try the text-extractable oracle kinds in order; return the first hit or
    None. Bosch pressure-sensor figure examples are intentionally unreachable
    here (they stay UNVERIFIED)."""
    table = extract_conversion_table(pages, chip)
    if table:
        return table
    return extract_reference_code(pages, chip)
