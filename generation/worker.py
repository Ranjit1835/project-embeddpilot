"""LLM worker: register map JSON -> driver source artifacts.

Contract (Amendments 1 & 3 of the WS2 addendum):
- Input is ONLY the structured register map + platform info + conventions —
  never the raw datasheet.
- Address semantics are explicit: base_address, addressing scheme, normalized
  offsets. Generated code must parameterize the base (#define <PERIPH>_BASE),
  never bake inferred absolute addresses into access macros.
- Registers with unknown field layouts are called out one by one; any bit
  field the worker defines for them must carry an UNVERIFIED comment. The
  worker never invents field layouts silently.
- On retry, the ONLY feedback is the validator's failure artifacts.

The worker never validates its own output (generator is never the judge) and
never imports from validator/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from generation.inputs import assert_input_provenance, platform_profile
from generation.provider import LLMProvider, ProviderError
from generation.router import RouteDecision

UNVERIFIED_COMMENT = (
    "/* UNVERIFIED: bit positions not confirmed against datasheet — "
    "verify manually (see p.{pages}) */"
)

SYSTEM_PROMPT = """You are an embedded systems driver generator. You write \
production-quality C for microcontroller peripherals and external devices.

Hard rules:
1. Use ONLY registers, offsets, bit fields, and command opcodes present in the \
provided register map JSON. Never use values remembered from other datasheets.
2. The register map lists registers whose bit-field layout is UNKNOWN. If you \
define bit masks/positions for those registers, every such #define MUST be \
immediately preceded by the exact comment given in the task. Do not silently \
invent field layouts.
3. Parameterize the peripheral base address as a #define named <PERIPH>_BASE \
taken from the provided base_address (or left for the user if null). Register \
access goes through base + offset. Never hard-code absolute addresses in \
access expressions.
4. Compile-clean under -Wall -Wextra -Werror: no unused parameters or \
variables, no implicit conversions losing precision, no missing prototypes. \
Register pointers are volatile. #include every header you use. Prefer static \
or caller-provided buffers; do NOT use malloc/free unless the conventions \
explicitly allow dynamic allocation.
6. If the map lacks data a device feature needs (e.g. some calibration \
registers are missing), OMIT that feature and say so in "notes" — never \
reference registers or coefficients that are not in the map.
5. Respond with a single JSON object, keys: "header_c", "source_c", \
"example_c", "notes". Values are complete file contents (or a short string \
for notes). No markdown, no commentary outside the JSON."""


@dataclass
class WorkerResult:
    files: dict[str, str]           # filename -> content
    notes: str = ""
    prompt_chars: int = 0
    provider: str = ""
    attempts: list[str] = field(default_factory=list)  # feedback given per retry


def generate_driver(
    provider: LLMProvider,
    register_map: dict,
    decision: RouteDecision,
    platform: str,
    conventions: str = "",
    feedback: str | None = None,
) -> WorkerResult:
    chip = _c_ident(register_map["chip"]).lower()
    user_prompt = build_worker_prompt(
        register_map, decision, platform, conventions, feedback
    )
    raw = provider.complete_json(SYSTEM_PROMPT, user_prompt)

    missing = [k for k in ("header_c", "source_c", "example_c") if not raw.get(k)]
    if missing:
        raise ProviderError(f"worker output missing artifacts: {missing}")

    files = {
        f"{chip}_driver.h": str(raw["header_c"]),
        f"{chip}_driver.c": str(raw["source_c"]),
        f"{chip}_example.c": str(raw["example_c"]),
    }
    return WorkerResult(
        files=files,
        notes=str(raw.get("notes", "")),
        prompt_chars=len(user_prompt),
        provider=provider.name,
    )


def build_worker_prompt(
    register_map: dict,
    decision: RouteDecision,
    platform: str,
    conventions: str = "",
    feedback: str | None = None,
) -> str:
    # Fail loudly if any input reached here without a legitimate origin. The
    # worker must NEVER be framed on an invented chip/interface/platform value.
    assert_input_provenance(register_map, platform)

    chip = register_map["chip"]
    peripheral = register_map["peripheral"]
    base = register_map.get("base_address")
    registers = register_map.get("registers", [])
    commands = register_map.get("commands", [])
    warnings = register_map.get("warnings", [])

    header_name = f"{_c_ident(chip).lower()}_driver.h"
    lines: list[str] = []
    lines.append(f"Target device: {chip} ({peripheral})")
    profile = platform_profile(platform)
    if profile:
        lines.append(
            f"Target platform: {profile['label']} — use {profile['hal']} idioms "
            f"(toolchain: {profile['toolchain']})"
        )
    else:
        lines.append(f"Target platform: {platform}")
    lines.append(f"Driver framing: {decision.framing}-based")
    lines.append(
        f'FILE NAMES: the header will be saved as "{header_name}" — source_c and '
        f'example_c MUST use exactly #include "{header_name}". No other local includes.'
    )
    if conventions:
        lines.append(f"Coding conventions: {conventions}")

    # Amendment 3: explicit address semantics — the worker never guesses.
    # A null base means this is a bus-attached device (I2C/SPI sensor):
    # register addresses go into bus transactions, not pointer arithmetic.
    lines.append("")
    lines.append("ADDRESSING CONTRACT:")
    if base:
        lines.append(f"- base_address: {base}")
        lines.append("- addressing: relative — every register offset below is relative to the base")
        lines.append(
            f"- define the base as {_c_ident(chip).upper()}_BASE and access registers "
            "as (base + offset); never hard-code absolute addresses"
        )
    else:
        lines.append("- base_address: null — this is a BUS-ATTACHED device (I2C/SPI)")
        lines.append(
            "- register 'offset' values are bus register addresses, used as-is in "
            "read/write transactions — there is NO memory-mapped base"
        )
        lines.append(
            "- generate a user-implemented transfer-callback interface "
            "(e.g. int (*reg_read)(uint8_t reg, uint8_t *buf, uint32_t len)) and "
            "route all register access through it"
        )
        lines.append(
            "- do NOT require a *_BASE define and do NOT use #error guards — the "
            "files must compile standalone exactly as generated"
        )
    for w in warnings:
        if "rebased" in w or "base" in w:
            lines.append(f"- ingestion warning (surface in notes): {w}")

    # Amendment 1: per-register unknown-fields notice
    unknown = [r for r in registers if not r.get("fields")]
    if unknown:
        lines.append("")
        lines.append("REGISTERS WITH UNKNOWN FIELD LAYOUT:")
        for r in unknown:
            pages = ",".join(str(p) for p in r.get("source_pages", [])) or "?"
            lines.append(
                f"- {r['name']} (offset {r['offset']}): fields are UNKNOWN. "
                "If you define bit fields for this register they are unverified "
                "and each definition MUST be preceded by exactly: "
                + UNVERIFIED_COMMENT.format(pages=pages)
            )

    lines.append("")
    lines.append("REGISTER MAP (the only source of truth):")
    lines.append(json.dumps(
        {"registers": [_slim(r) for r in registers],
         "commands": [_slim(c) for c in commands]},
        separators=(",", ":"),
    ))

    if decision.framing == "command":
        lines.append("")
        lines.append(
            "This is a command-based device: generate opcode constants from the "
            "commands array, transaction builder functions (opcode + address "
            "bytes + dummy bytes + data phase per the command descriptors), and "
            "a thin bus-transfer callback interface the user implements for "
            "their platform. Do not invent a memory-mapped register interface."
        )

    if feedback:
        lines.append("")
        lines.append(
            "PREVIOUS ATTEMPT FAILED VALIDATION. Fix exactly these issues and "
            "regenerate all three files:"
        )
        lines.append(feedback)

    lines.append("")
    lines.append(
        'Respond with JSON: {"header_c": ..., "source_c": ..., "example_c": ..., "notes": ...}'
    )
    return "\n".join(lines)


def _slim(entry: dict) -> dict:
    """Token diet for the prompt: nulls, empty strings/lists, and per-entry
    provenance carry no information the worker can act on (the unknown-field
    notices above already cite pages)."""
    return {
        k: v for k, v in entry.items()
        if v not in (None, "", []) and k not in ("source_pages", "confidence")
    }


def _c_ident(name: str) -> str:
    import re

    ident = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return ident if ident and not ident[0].isdigit() else "_" + ident
