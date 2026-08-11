"""Route a driver request: validated template path vs LLM path.

The template engine stays authoritative for families it covers — deterministic
and simulation-verified is a feature (V1 behavior, untouched). Everything else
goes to the LLM path, framed as either a memory-mapped register driver or a
command/transaction driver (Amendment 2).

Every decision is logged to artifacts/router_log.jsonl and carried in the
result payload so the UI can show which path produced the driver.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass

# Families the V1 deterministic template engine covers. A template match
# requires BOTH the chip and the target platform to match — the BMP180
# template emits Arduino/Wire code for ESP32 I2C0, nothing else.
TEMPLATE_REGISTRY = [
    {
        "template_id": "bmp180-esp32-i2c",
        "chip_pattern": r"bmp[\s\-_]?180",
        "platforms": {"esp32", "esp32-arduino"},
        "description": "BMP180 on ESP32 I2C0 (V1 deterministic template, Wokwi-verified)",
    },
]

LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "artifacts", "router_log.jsonl",
)


@dataclass
class RouteDecision:
    path: str            # "template" | "llm"
    framing: str | None  # llm only: "register" | "command"
    template_id: str | None
    reason: str
    user_label: str      # shown verbatim in the UI

    def to_json(self) -> dict:
        return asdict(self)


def route(register_map: dict, platform: str, log: bool = True) -> RouteDecision:
    chip = register_map.get("chip", "")
    plat = platform.strip().lower()

    decision = None
    for entry in TEMPLATE_REGISTRY:
        if re.search(entry["chip_pattern"], chip, re.IGNORECASE) and plat in entry["platforms"]:
            decision = RouteDecision(
                path="template",
                framing=None,
                template_id=entry["template_id"],
                reason=f"chip '{chip}' + platform '{platform}' matched {entry['template_id']}",
                user_label="Generated via validated template",
            )
            break

    if decision is None:
        registers = register_map.get("registers", [])
        commands = register_map.get("commands", [])
        # base_address is the authoritative memory-mapped-vs-bus signal (WS2
        # contract): a real base means the peripheral is memory-mapped; null
        # means it is a bus-attached device (I2C/SPI) driven through transfer
        # callbacks. The framing label MUST agree with the worker's addressing
        # contract, which keys off the same base — otherwise the prompt carries
        # a "register-based" label over bus-attached instructions (the V1.6.1
        # BMP085 bug: a byte-addressed sensor mislabeled memory-mapped).
        base = register_map.get("base_address")
        if commands and len(registers) <= 2:
            framing = "command"
            reason = (
                f"no template for chip '{chip}' on '{platform}'; "
                f"{len(commands)} commands vs {len(registers)} registers -> command-driver framing"
            )
        elif base:
            framing = "register"
            reason = (
                f"no template for chip '{chip}' on '{platform}'; "
                f"base {base} + {len(registers)} registers -> memory-mapped register framing"
            )
        else:
            framing = "bus"
            reason = (
                f"no template for chip '{chip}' on '{platform}'; "
                f"{len(registers)} registers, base_address null -> "
                "bus-attached (I2C/SPI) transfer-callback framing"
            )
        decision = RouteDecision(
            path="llm",
            framing=framing,
            template_id=None,
            reason=reason,
            user_label="Generated via AI with validation",
        )

    if log:
        _log(decision, chip, platform)
    return decision


def _log(decision: RouteDecision, chip: str, platform: str) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "chip": chip,
             "platform": platform, **decision.to_json()}
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
