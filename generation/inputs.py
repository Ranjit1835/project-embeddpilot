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

import re

# provenance a field may carry to be allowed through to the worker:
#   user     — the human typed/selected it
#   detected — pulled from the document AND confirmed on the review screen
#   sample   — a value baked into a bundled sample/demo map by the project. The
#              old sample maps claimed `user`, which was untrue (no human typed
#              them). `sample` is a truthful origin that the gate still trusts,
#              because bundled fixtures are project-curated, not unverified input.
ALLOWED = {"user", "detected", "sample"}
# a detected value that pre-filled the form but has NOT been confirmed yet
UNCONFIRMED = "detected_unconfirmed"


class InputProvenanceError(ValueError):
    """A required input field is missing, unconfirmed, or of unknown origin."""


# ---------------------------------------------------------------------------
# Supported-interface gate (V1.8 B2). The generator only knows how to produce
# I2C and SPI drivers. A device on any other bus (e.g. TI's SMAART Wire, a
# UART daisy-chain, 1-Wire) must be BLOCKED with a clear message naming the
# detected interface — never silently generated against an I2C/SPI assumption.
SUPPORTED_INTERFACES = {"I2C", "SPI"}

# leading-token -> canonical bus. Order matters (longest/again-specific first).
_INTERFACE_CANON: list[tuple[tuple[str, ...], str]] = [
    (("I2C", "IIC", "TWI"), "I2C"),
    (("SPI", "QSPI", "DSPI"), "SPI"),
    (("SMAART", "SMART"), "SMAART Wire"),
    (("USART", "UART"), "UART"),
    (("ONEWIRE", "1WIRE"), "1-Wire"),
]


class UnsupportedInterfaceError(ValueError):
    """The device's interface is outside the supported {I2C, SPI} set."""


class InterfaceMismatchError(ValueError):
    """The selected interface contradicts what the document indicates."""


class ChipConsistencyError(ValueError):
    """Detected chip, map chip, and generated names disagree."""


def canonical_bus(peripheral: str) -> str | None:
    """Map a peripheral/interface string to a RECOGNIZED bus name, or None when
    it is not a bus token at all. 'I2C1' -> 'I2C', 'SPI2' -> 'SPI', 'USART3' ->
    'UART', 'SMAART Wire' -> 'SMAART Wire'. A device-role descriptor like
    'pressure-sensor' (not a bus) returns None so the interface gates ignore it —
    they act only on an actual interface claim."""
    squashed = re.sub(r"[^A-Za-z0-9]", "", (peripheral or "")).upper()
    if not squashed:
        return None
    for keys, canon in _INTERFACE_CANON:
        if any(squashed.startswith(k) for k in keys):
            return canon
    return None


def assert_supported_interface(peripheral: str) -> None:
    """Block generation for any RECOGNIZED bus outside {I2C, SPI}. A non-bus
    descriptor (None from canonical_bus) is left alone; emptiness is the
    provenance guard's job. This fires on a present, recognized, unsupported
    interface — TMP107's UART/SMAART Wire being the motivating case."""
    bus = canonical_bus(peripheral)
    if bus is not None and bus not in SUPPORTED_INTERFACES:
        raise UnsupportedInterfaceError(
            f"Interface '{peripheral}' (recognized as {bus}) is not supported. "
            "EmbeddPilot generates drivers for I2C and SPI devices only — "
            f"{bus}-based parts (e.g. TI SMAART Wire / UART daisy-chained "
            "sensors) are blocked rather than generated against a wrong I2C/SPI "
            "assumption. Provide an I2C or SPI part, or this device is out of scope."
        )


def _detected_interface_set(register_map: dict) -> set[str]:
    det = (register_map.get("detected") or {}).get("interfaces") or []
    out = set()
    for d in det:
        bus = canonical_bus(d.get("value", ""))
        if bus:
            out.add(bus)
    return out


def assert_interface_matches_document(register_map: dict) -> None:
    """B1 cross-check: if the document clearly indicates a SINGLE bus and the
    selected interface is a different one, block and ask rather than proceeding
    (BMP183 is SPI; a stray I2C selection would build a structurally wrong
    driver the register cross-check cannot catch). Multi-bus documents (BME280 =
    I2C+SPI) are a legitimate user choice and never blocked here."""
    chosen = canonical_bus(register_map.get("peripheral", ""))
    if chosen is None or chosen not in SUPPORTED_INTERFACES:
        return  # not a bus claim, or already handled by assert_supported_interface
    doc = _detected_interface_set(register_map)
    supported_doc = doc & SUPPORTED_INTERFACES
    if len(supported_doc) == 1 and chosen not in supported_doc:
        (indicated,) = tuple(supported_doc)
        raise InterfaceMismatchError(
            f"Selected interface '{chosen}' contradicts the datasheet, which "
            f"indicates {indicated}. This usually means the wrong sibling part "
            "was identified (an I2C part confused for its SPI sibling or vice "
            f"versa). Confirm the interface on the review screen — proceeding as "
            f"{chosen} would build a structurally wrong driver."
        )


def _chip_token(value: str) -> str:
    """Comparable chip identity: strip separators/spaces, uppercase."""
    return re.sub(r"[^A-Za-z0-9]", "", (value or "")).upper()


def assert_chip_consistency(
    map_chip: str, detected_chip: str | None, generated_names: list[str]
) -> None:
    """B1 hard consistency gate: the chip recorded in the register map, the chip
    detected from the document (when present), and the chip baked into generated
    file/class names must all agree. Disagreement is a HARD FAILURE — the
    observed BMP183 run had them disagreeing and still shipped output."""
    ref = _chip_token(map_chip)
    if not ref:
        return  # emptiness handled by the provenance guard
    if detected_chip and _chip_token(detected_chip) != ref:
        raise ChipConsistencyError(
            f"Detected chip '{detected_chip}' disagrees with the map chip "
            f"'{map_chip}'. Refusing to ship a driver whose identity is "
            "inconsistent — confirm the correct part on the review screen."
        )
    for name in generated_names:
        # The chip identity must appear somewhere in the artifact PATH — in the
        # filename for the bare-metal target (bmp183_driver.c) or in the library
        # folder for the Arduino target (BMP183/src/BMP183.h, BMP183/keywords.txt).
        # Boilerplate files (library.properties, README.md) carry it via the
        # folder. A different family token anywhere here is the bug this stops.
        path_token = _chip_token(name)
        if ref not in path_token:
            raise ChipConsistencyError(
                f"Generated artifact '{name}' does not match the map chip "
                f"'{map_chip}'. The route/naming identified a different part than "
                "the map — hard failure to prevent shipping the wrong driver."
            )


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
    # V1.8 B2: even a well-provenanced interface must be one we actually support.
    assert_supported_interface(register_map.get("peripheral", ""))
    # V1.8 B1: a supported interface must not contradict the document's own bus.
    assert_interface_matches_document(register_map)
    # platform is not part of the map; the dropdown makes every selection a user
    # choice, so a non-empty value is a user-sourced value by construction.
    if not (platform or "").strip():
        raise InputProvenanceError(
            "Target platform is required — select a platform before generating."
        )
