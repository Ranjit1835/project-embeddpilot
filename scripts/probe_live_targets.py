#!/usr/bin/env python3
"""Exercise the real requirement -> verdict path, end to end.

WHY THIS EXISTS AND ISN'T A UNIT TEST
-------------------------------------
Two production bugs passed the entire unit suite and were caught only by
running a real requirement through the pipeline:

  * a requirement naming an ESP32 (Xtensa, not even ARM) was accepted, built as
    an STM32F4, shipped an stm32f4.ld linker script inside the ESP32 project,
    and reported `working-emulated`;
  * "produce a cmake project" -- the wording in the product's own showcase
    example -- hard-failed, because the unit tests only ever used the canonical
    token "cmake-project" and never the words a person actually types.

Both were invisible to mocked tests by construction. This script needs a live
model provider, so it cannot live in pytest; run it by hand before shipping a
change to intake, the target gate, or the generator.

    EMBEDDPILOT_PROVIDER=gemini python scripts/probe_live_targets.py

Exit code 0 = both probes passed.

Probe 2 matters as much as probe 1: a gate that refused everything would pass
probe 1 while destroying the product.
"""
from __future__ import annotations

import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from generation.provider import make_provider              # noqa: E402
from orchestration.v2_pipeline import run_application_pipeline  # noqa: E402

ESP32_REQUIREMENT = (
    "On an ESP32-WROOM-32 devkit with an ESP32 SoC, read the BMP180 over I2C "
    "at 0x77. When the raw reading is above 18500, turn on the relay on GPIO5. "
    "Sample every 500 ms, retry on a failed read, produce a cmake project."
)

STM32_REQUIREMENT = (
    "On a Nucleo-F411RE with an STM32F411RET6, read the BMP180 over I2C at "
    "0x77. When the raw reading is above 18500, turn on the relay on PB5. "
    "Sample every 500 ms, retry on a failed read, produce a cmake project."
)

# Answers to the clarifying questions. "raw" for the threshold unit is the
# truthful answer AND the permitted one: BMP180's compensation math is
# figure-trapped with no oracle, so an engineering-unit threshold is refused.
ANSWERS = {
    "q:devices[0].role": "temperature sensor, read as raw uncompensated counts",
    "q:devices[1].name": "plain GPIO output",
    "q:devices[1].interface": "GPIO",
    "q:devices[1].role": "actuator - switches the relay load",
    "q:behaviors[0].trigger.unit": "raw",
    "q:output_target": "cmake-project",
    "q:model:devices[0].pins": "SCL on PB8, SDA on PB9",
}


def resolve_register_map(requirement: str):
    """The rule api/main.py::_resolve_register_map uses: a V1-extracted map
    whose chip is named in the requirement. Without it the pipeline correctly
    refuses to generate ("no read plan -- the pipeline does not fabricate
    one"), and the probe never reaches the path it means to test."""
    hay = (requirement + " " + " ".join(map(str, ANSWERS.values()))).upper()
    for path in glob.glob(os.path.join(ROOT, "artifacts", "*extracted-map.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                candidate = json.load(fh)
        except (OSError, ValueError):
            continue
        chip = str(candidate.get("chip") or "").upper()
        if chip and chip in hay:
            return candidate, os.path.basename(path)
    return None, None


def probe(label: str, requirement: str, expected_status: str) -> bool:
    print("=" * 72)
    print(f"{label}   (expecting: {expected_status})")
    print("=" * 72)
    register_map, source = resolve_register_map(requirement)
    print(f"  register map: {source or 'NONE'}")

    result = run_application_pipeline(
        requirement,
        answers=ANSWERS,
        provider=make_provider(),
        register_map=register_map,
        measurement="Temperature",
    )

    for st in result.get("stages", []):
        print(f"    {st.get('stage'):10} {st.get('state'):9} "
              f"{str(st.get('detail') or '')[:130]}")
    files = sorted((result.get("files") or {}).keys())
    if files:
        print(f"  files : {files}")

    status = result.get("status")
    ok = status == expected_status
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}  (got {status})\n")
    return ok


def main() -> int:
    refused = probe("1. ESP32 (Xtensa - unsupported)",
                    ESP32_REQUIREMENT, "blocked-unsupported-target")
    still_works = probe("2. STM32F411 (supported)",
                        STM32_REQUIREMENT, "working-emulated")

    print("=" * 72)
    print(f"ESP32 refused         : {'PASS' if refused else 'FAIL'}")
    print(f"STM32F411 still works : {'PASS' if still_works else 'FAIL'}")
    print("=" * 72)

    if not (refused and still_works):
        print("\nNOTE: extraction is non-deterministic and occasionally returns"
              "\nnothing at all, which shows up as a spec blocked on questions"
              "\nthe requirement plainly answers. If that is what you see, run"
              "\nit again before concluding the code is broken.")
    return 0 if (refused and still_works) else 1


if __name__ == "__main__":
    raise SystemExit(main())
