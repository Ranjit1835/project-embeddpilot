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
import re
from dataclasses import dataclass, field

from generation.inputs import assert_input_provenance, platform_profile
from generation.provider import LLMProvider, ProviderError
from generation.router import RouteDecision

UNVERIFIED_COMMENT = (
    "/* UNVERIFIED: bit positions not confirmed against datasheet — "
    "verify manually (see p.{pages}) */"
)

# Marker for functions whose compensation/conversion math is transcribed from
# datasheet prose (V1.6.1 Fix 3). The validator greps for this exact substring
# to downgrade the verdict to validated-with-unverified-fields. Keep the leading
# text in sync with validator/crosscheck.py::COMPUTATION_MARKER (no shared import
# — the contamination guard forbids it).
COMPUTATION_UNVERIFIED_COMMENT = (
    "/* UNVERIFIED: computation transcribed from datasheet prose — not "
    "cross-checked against the register map */"
)

# V1.7: an ordered init/config SEQUENCE derived from reference-manual prose is
# not cross-checkable (only the registers/bits it touches are). Keep the leading
# text in sync with validator/crosscheck.py::SEQUENCE_MARKER.
SEQUENCE_UNVERIFIED_COMMENT = (
    "/* UNVERIFIED: sequence transcribed from reference manual prose — not "
    "cross-checked */"
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
4. Compile-clean under -Wall -Wextra -Werror — this applies to EVERY file, \
INCLUDING the example and any stub/placeholder function in it. Concretely: \
every function (stubs included) must consume every parameter it declares — add \
`(void)param;` for any it does not use, or it fails -Werror=unused-parameter. \
#include every header you use (e.g. <string.h> for memcpy/memset, <stdint.h> \
for fixed-width types). Match every printf/sprintf conversion to its argument \
type — an int32_t needs %ld or a cast to (int)/(long), never a bare %d, or it \
fails -Werror=format. Do NOT define a static function or variable you never \
call/use — either use it or remove it, or it fails -Werror=unused-function / \
-Werror=unused-variable. No implicit conversions losing precision, no missing \
prototypes. Register pointers are volatile. Prefer static or caller-provided \
buffers; do NOT use malloc/free unless the conventions explicitly allow it.
5. If the map lacks data a device feature needs (e.g. some calibration \
registers are missing), OMIT that feature and say so in "notes" — never \
reference registers or coefficients that are not in the map.
6. Any function whose body implements compensation, calibration, or unit- \
conversion math transcribed from the datasheet's prose or pseudocode (e.g. a \
pressure/temperature compensation formula) is NOT verifiable from the register \
map. Immediately precede each such function definition with exactly this \
comment: {computation_comment}  Balance every parenthesis and shift with care; \
this math is the easiest place to introduce a silent numeric error.
7. Respond with a single JSON object, keys: "header_c", "source_c", \
"example_c", "notes". Values are complete file contents (or a short string \
for notes). No markdown, no commentary outside the JSON.""".replace(
    "{computation_comment}", COMPUTATION_UNVERIFIED_COMMENT
)


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
    mcu_map: dict | None = None,
    prior_files: dict[str, str] | None = None,
) -> WorkerResult:
    chip = _c_ident(register_map["chip"]).lower()
    # Targeted-edit retry: echo the prior failing code back so the model fixes
    # only the named error instead of cold re-rolling the whole driver (the
    # V1.6.1 finding). Only for large-window providers — on Groq's ~8000 TPM
    # free tier the echo does not fit (413 / output truncation), so fall back to
    # the cold re-roll there.
    echo = prior_files if getattr(provider, "large_window", False) else None
    user_prompt = build_worker_prompt(
        register_map, decision, platform, conventions, feedback, mcu_map, echo
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
    mcu_map: dict | None = None,
    prior_files: dict[str, str] | None = None,
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
    is_bus = not base  # bus-attached device (I2C/SPI): base_address is null
    if profile and is_bus:
        # A bus device driver must be portable standalone C routed through
        # user callbacks — the platform matters for the TOOLCHAIN only, not the
        # code. Telling the model to "use ESP-IDF idioms" here makes it emit
        # i2c_cmd_link_create / vTaskDelay etc., which is exactly wrong (and
        # won't compile standalone). Keep the toolchain, drop the HAL idiom.
        lines.append(
            f"Target toolchain: {profile['toolchain']} (compile target only). "
            f"The driver must be PLATFORM-AGNOSTIC standalone C — do NOT write "
            f"{profile['hal']}-specific code; see the bus-attached contract below."
        )
    elif profile:
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
            "- define a transfer-callback interface (e.g. typedef "
            "int (*reg_read_fn)(uint8_t reg, uint8_t *buf, uint32_t len); and a "
            "matching reg_write_fn) and route ALL device register access through "
            "those callbacks"
        )
        if mcu_map:
            # A complete driver ON a target MCU: the callbacks are IMPLEMENTED
            # against that MCU's peripheral (see MCU CONFIGURATION below), not
            # left as user stubs. This overrides the platform-agnostic bus
            # contract used when no MCU map is present.
            lines.append(
                "- IMPLEMENT those callbacks using the target MCU's peripheral as "
                "described in the MCU CONFIGURATION section below — this IS the "
                "complete driver for this device on that MCU, not a portable stub. "
                "Include the MCU header and drive the peripheral registers there."
            )
            lines.append(
                "- example_c must show the REAL bring-up: call the MCU init "
                "(clock enable, GPIO/AF, peripheral init) and then read the device "
                "through the driver. Every function still compiles clean under "
                "-Wall -Wextra -Werror (consume unused params with `(void)x;`)."
            )
        else:
            lines.append(
                "- STANDALONE & PORTABLE: every file must compile using ONLY the C "
                "standard library (<stdint.h>, <stddef.h>, <string.h>). Do NOT "
                "#include any SDK/vendor HAL header — NO <driver/i2c.h>, "
                "<driver/spi_master.h>, <freertos/*.h>, <esp_*.h>, <Arduino.h>, or "
                "CMSIS — and do NOT call any SDK/HAL function (i2c_master_*, "
                "i2c_cmd_link_*, spi_*, vTaskDelay, HAL_*, digitalWrite, delay, "
                "...). If a delay is needed, take a user-provided delay callback."
            )
            lines.append(
                "- example_c must demonstrate usage by IMPLEMENTING the callbacks "
                "as trivial self-contained stubs (return 0, fill a static buffer) "
                "and calling the driver API — it must NOT touch real hardware or "
                "any SDK. Each stub MUST consume every parameter it declares (add "
                "`(void)reg;` for unused ones) so it compiles clean under "
                "-Werror=unused-parameter"
            )
            lines.append(
                "- do NOT require a *_BASE define and do NOT use #error guards — "
                "the files must compile standalone exactly as generated"
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

    if mcu_map:
        lines.extend(_mcu_config_section(mcu_map, peripheral))

    if feedback:
        lines.append("")
        if prior_files:
            # Targeted-edit retry (V1.7, enabled by a large-window provider): give
            # the model its OWN previous code back so it fixes only the named
            # errors instead of cold re-rolling and reintroducing new -Werror
            # slips each attempt (the V1.6.1 cold-reroll finding). Echo the files
            # the failures name (the edit is there); fall back to all if none.
            named = [f for f in prior_files if f in feedback] or list(prior_files)
            shown = ", ".join(named)
            lines.append(
                "PREVIOUS ATTEMPT FAILED VALIDATION. Below is the EXACT code you "
                f"produced last time for: {shown}. Return ALL three files again; "
                f"for {shown}, keep every line byte-for-byte identical EXCEPT the "
                "minimal edits that fix the errors listed after the code. Do NOT "
                "rewrite functions the errors do not name — a full rewrite "
                "reintroduces bugs you already fixed."
            )
            for fname in named:
                lines.append("")
                lines.append(f"--- PREVIOUS {fname} ---")
                lines.append(prior_files[fname].rstrip("\n"))
            lines.append("")
            lines.append("ERRORS TO FIX (change only what these name):")
            lines.append(feedback)
        else:
            lines.append(
                "PREVIOUS ATTEMPT FAILED VALIDATION. Fix exactly these issues and "
                "regenerate all three files. Pay special attention to balanced "
                "parentheses and shifts in any compensation math:"
            )
            lines.append(feedback)

    lines.append("")
    lines.append(
        'Respond with JSON: {"header_c": ..., "source_c": ..., "example_c": ..., "notes": ...}'
    )
    return "\n".join(lines)


def _mcu_config_section(mcu_map: dict, device_peripheral: str) -> list[str]:
    """Prompt lines that turn the MCU map into the host-side bring-up the driver
    needs (items 4-7). The worker must use ONLY registers/bits present here, so
    the validator can cross-check clock/GPIO/peripheral usage against the map.
    Slimmed for tokens: the peripheral's clock-enable rows, GPIO register
    names+offsets, and the peripheral registers with their bit fields."""
    fam = mcu_map.get("mcu_family", "the MCU")
    variant = mcu_map.get("variant") or ""
    # the instance(s) of the target peripheral, e.g. I2C1/I2C2/I2C3
    pfx = re.match(r"[A-Za-z]+", device_peripheral or "")
    ptoken = (pfx.group(0) if pfx else device_peripheral or "").upper()
    clk = [c for c in mcu_map.get("clock_enables", [])
           if c["peripheral"].upper().startswith(ptoken)]
    gpio_clk = [c for c in mcu_map.get("clock_enables", [])
                if c["peripheral"].upper().startswith("GPIO")]

    def reg_brief(regs, with_fields):
        out = []
        for r in regs:
            entry = {"name": r["name"], "offset": r.get("offset")}
            if with_fields:
                entry["fields"] = [{"name": f["name"], "bits": f["bits"]}
                                   for f in r.get("fields", [])]
            out.append(entry)
        return out

    L = ["", f"MCU CONFIGURATION — target: {fam} {variant} "
             "(compile target: arm-none-eabi-gcc).",
         "You are producing a COMPLETE driver for this device ON this MCU. Beyond "
         "device register access, generate the MCU bring-up using ONLY the "
         "registers and bit positions in the MCU map below — never an RCC/GPIO/"
         f"{ptoken} register or bit that is not listed."]

    L.append("")
    L.append(f"1. CLOCK ENABLE (item 4): before using {ptoken}, set its clock-"
             "enable bit, and the GPIO port clock-enable bit for the pins used. "
             "Use exactly these register+bit entries:")
    L.append(json.dumps({"peripheral_clock": clk, "gpio_clock": gpio_clk},
                        separators=(",", ":")))

    L.append("")
    L.append("2. GPIO / PIN CONFIG (item 5): configure the SDA/SCL pins via these "
             "GPIO registers (set alternate-function mode in MODER, open-drain in "
             "OTYPER for I2C, pull-ups in PUPDR, and the AF number in AFRL/AFRH):")
    # only the pin-config registers matter here — drop IDR/ODR/BSRR/LCKR to keep
    # the prompt inside the admission window when both maps are present.
    gpio_cfg = [r for r in mcu_map.get("gpio_registers", [])
                if any(k in r["name"].upper()
                       for k in ("MODER", "OTYPER", "OSPEEDR", "PUPDR", "AFR"))]
    L.append(json.dumps(reg_brief(gpio_cfg, False), separators=(",", ":")))
    L.append("The specific PIN NUMBERS and AF NUMBER are USER INPUT — they are "
             "NOT in this map (the pin->AF table lives in the device datasheet). "
             "Expose them as #define parameters with a CONCRETE placeholder value "
             "the user edits — e.g. `#define SCL_PIN 6`, `#define SDA_PIN 7`, "
             "`#define I2C_AF 4` — NEVER `#define SCL_PIN SCL_PIN` or a reference "
             "to an undefined symbol (that fails to compile). Add a comment that "
             "the value is user-configurable.")

    L.append("")
    L.append(f"3. PERIPHERAL INIT + I/O (item 6) and 4. ERROR HANDLING (item 7): "
             f"initialize {ptoken} and program read/write transactions using these "
             "control registers; after operations, check the status/error flags "
             "(e.g. BERR, ARLO, AF/NACK, OVR) in the status registers:")
    L.append(json.dumps(reg_brief(mcu_map.get("peripheral_registers", []), True),
                        separators=(",", ":")))

    L.append("")
    L.append("REGISTER ACCESS: #include <stm32f4xx.h> for the peripheral register "
             "definitions (the RCC, GPIOx and I2Cx pointers and their struct "
             "members like RCC->APB1ENR, I2C1->CR1, GPIOB->AFR[0]). Do NOT "
             "redefine those structs or base addresses — they come from that "
             "header. Access registers through those pointers.")

    L.append("")
    L.append("CROSS-CHECKABLE CONSTANTS: define every RCC/GPIO/peripheral bit "
             "position and register offset you use as a NAMED #define built from "
             "the map's own name — e.g. `#define RCC_APB1ENR_I2C1EN_Pos 21` and "
             "`#define I2C_CR1_OFFSET 0x00` — then use those names. This lets the "
             "validator confirm every bit/offset against the MCU map; an unnamed "
             "inline `(1<<21)` cannot be checked.")

    L.append("")
    L.append("Any ordered init/config SEQUENCE you write is derived from "
             "reference-manual prose and is NOT cross-checkable — immediately "
             "precede each such function definition with exactly this comment: "
             + SEQUENCE_UNVERIFIED_COMMENT)
    return L


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
