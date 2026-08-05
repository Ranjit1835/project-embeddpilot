"""Input-provenance guard (V1.6 Priority 1).

Foundational rule: nothing unverified is ever presented as verified. That
guarantee has to hold UPSTREAM of the worker too — a chip/interface/platform
value that was invented (a filename, a placeholder, a silent UI default) frames
the worker wrongly, and the validator cannot catch it, because the generated
code can be perfectly consistent with the extracted map while being the wrong
driver entirely.

So every one of {chip, peripheral/interface, platform} that reaches the worker
must carry a provenance of `user` (the human typed/selected it) or `detected`
(pulled from the document AND confirmed on the review screen). Anything else —
empty, unknown, or detected-but-unconfirmed — is BLOCKED with a specific,
field-naming error. There is no third option and no silent fill.
"""

from __future__ import annotations

# provenance a field may carry to be allowed through to the worker
ALLOWED = {"user", "detected"}
# a detected value that pre-filled the form but has NOT been confirmed yet
UNCONFIRMED = "detected_unconfirmed"


class InputProvenanceError(ValueError):
    """A required input field is missing, unconfirmed, or of unknown origin."""


# Canonical target platforms (Priority 3). Each maps to a toolchain family and
# HAL convention the validator's compile check and the worker prompt understand.
# "other" is free text resolved by the validator's substring matcher.
PLATFORM_CATALOG: dict[str, dict[str, str]] = {
    "stm32": {"label": "STM32", "toolchain": "arm-none-eabi-gcc", "hal": "STM32 HAL / CMSIS"},
    "esp32": {"label": "ESP32", "toolchain": "xtensa-esp32-elf-gcc", "hal": "ESP-IDF / Arduino-ESP32"},
    "nxp": {"label": "NXP", "toolchain": "arm-none-eabi-gcc", "hal": "NXP MCUXpresso SDK"},
    "ti": {"label": "TI", "toolchain": "arm-none-eabi-gcc", "hal": "TI driverlib / TivaWare"},
    "raspberry-pi": {"label": "Raspberry Pi", "toolchain": "gcc", "hal": "Linux userspace (spidev/i2c-dev)"},
    "avr": {"label": "AVR / Arduino", "toolchain": "avr-gcc", "hal": "Arduino / avr-libc"},
    "cortex-m": {"label": "Generic ARM Cortex-M", "toolchain": "arm-none-eabi-gcc", "hal": "CMSIS"},
}


def platform_profile(platform: str) -> dict[str, str] | None:
    """Toolchain/HAL profile for a canonical platform token, or None for
    free-text ('Other') platforms the catalog does not define."""
    return PLATFORM_CATALOG.get((platform or "").strip().lower())


def _check_field(label: str, value: str, provenance: str | None) -> None:
    value = (value or "").strip()
    if not value:
        raise InputProvenanceError(
            f"{label} is required — no value was provided or detected. "
            "Enter it before generating."
        )
    if provenance == UNCONFIRMED:
        raise InputProvenanceError(
            f"Detected {label.lower()} '{value}' is not confirmed — confirm or "
            "correct it on the review screen before generating."
        )
    if provenance not in ALLOWED:
        # a value with no legitimate origin: the invented-value path this guard
        # exists to stop. Fail loudly rather than frame the worker on a guess.
        raise InputProvenanceError(
            f"{label} '{value}' has unknown provenance ({provenance!r}) — "
            "refusing to generate from an unverified input value."
        )


def assert_input_provenance(register_map: dict, platform: str) -> None:
    """Raise InputProvenanceError naming the first field that is missing,
    unconfirmed, or of unknown origin. Returns None when all inputs are clean.

    Used both at the API boundary (translated to a 422) and again at worker
    prompt construction (belt-and-suspenders: construction fails loudly)."""
    prov = register_map.get("provenance") or {}
    _check_field("Chip / part number", register_map.get("chip", ""), prov.get("chip"))
    _check_field("Interface / peripheral", register_map.get("peripheral", ""),
                 prov.get("peripheral"))
    # platform is not part of the map; the dropdown makes every selection a user
    # choice, so a non-empty value is a user-sourced value by construction.
    if not (platform or "").strip():
        raise InputProvenanceError(
            "Target platform is required — select a platform before generating."
        )
