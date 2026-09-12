"""Which hardware targets this pipeline can actually build for.

THE BUG THIS EXISTS TO PREVENT
------------------------------
The V2 firmware path is STM32F4 and nothing else. The scaffold emits STM32F4
peripheral code (RCC, GPIO, USART2, I2C1), the linker script is stm32f4.ld, the
compiler runs with -mcpu=cortex-m4, and the emulator loads
platforms/cpus/stm32f4.repl.

None of that was checked against the MCU the user asked for -- which intake
REQUIRES them to state. A requirement naming an ESP32 (Xtensa, not even ARM)
was accepted with zero blocking questions, built as an STM32F4, shipped with an
stm32f4.ld linker script inside it, emulated on an STM32F4, and reported
`working-emulated`. The system recorded the user saying ESP32 and built
something else.

Substituting the processor and reporting "working" is the precise failure this
project exists to prevent, so an unsupported target is REFUSED here. It is never
approximated, never silently upgraded to the nearest supported part, and never
allowed to reach a verdict. "We cannot build for that yet" is a correct answer;
a green verdict for the wrong architecture is not.
"""

from __future__ import annotations

import re

__all__ = [
    "SUPPORTED_LABEL",
    "SUPPORTED_MCU_PATTERNS",
    "UnsupportedTargetError",
    "assert_target_supported",
    "is_supported_mcu",
    "supported_targets",
]


class UnsupportedTargetError(Exception):
    """The stated target is outside what this pipeline can build.

    Carries the part that was asked for so callers can say so verbatim rather
    than paraphrasing the user's own words back at them.
    """

    def __init__(self, message: str, *, requested: str | None = None) -> None:
        super().__init__(message)
        self.requested = requested


# Keyed by what the firmware path ACTUALLY supports, not by what the vendor
# sells. STM32F1/F7/H7 are deliberately absent: an F1 is Cortex-M3, so the
# -mcpu=cortex-m4 build alone would be wrong, and the peripheral layout differs
# even where the family prefix looks close.
SUPPORTED_MCU_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^STM32F4\d{2}", re.IGNORECASE),
)

SUPPORTED_LABEL = "STM32F4 series (for example STM32F411RET6, STM32F407VGT6)"


def supported_targets() -> dict:
    """What this deployment can build for, for /api/v2/capabilities.

    Reported next to the toolchain so the answer to "can it do my chip?" does
    not require running a build to discover.
    """
    return {
        "mcu_families": ["STM32F4"],
        "label": SUPPORTED_LABEL,
        "consequence": (
            "a requirement naming any other MCU is refused rather than built "
            "as an STM32F4 — the firmware scaffold, linker script, compiler "
            "flags and emulator platform are all STM32F4-specific"
        ),
    }


def _normalise(mcu: str) -> str:
    """Strip packaging noise so 'STM32F411RE-T6' and 'stm32f411ret6' match.

    Only separators are removed. The part number itself is never reshaped —
    guessing that 'F41' means 'F411' is the kind of helpfulness that produced
    the bug in the first place.
    """
    return re.sub(r"[\s_\-/]+", "", (mcu or "").strip())


def is_supported_mcu(mcu: str | None) -> bool:
    """Is this MCU one the firmware path can genuinely build for?

    An empty or unknown value is NOT supported. Absence of evidence that a part
    is wrong is not evidence that it is right, and defaulting to "sure, build
    it" is how the ESP32 run reached a green verdict.
    """
    if not mcu:
        return False
    text = _normalise(str(mcu))
    if not text:
        return False
    return any(p.search(text) for p in SUPPORTED_MCU_PATTERNS)


def assert_target_supported(mcu: str | None, board: str | None = None) -> None:
    """Raise UnsupportedTargetError unless the firmware path can build for `mcu`.

    Names the requested part and what IS supported, so the refusal is
    actionable rather than a dead end. The board is echoed only as context; the
    MCU is the thing that decides, because the board name does not determine
    the core, the linker layout or the emulator platform.
    """
    if is_supported_mcu(mcu):
        return

    asked = str(mcu).strip() if mcu else ""
    if not asked:
        raise UnsupportedTargetError(
            "No target MCU was established, so there is nothing to check the "
            f"firmware against. This pipeline builds for {SUPPORTED_LABEL}.",
            requested=None,
        )

    where = f" on {board}" if board else ""
    raise UnsupportedTargetError(
        f"Cannot build for {asked}{where}. This pipeline builds for "
        f"{SUPPORTED_LABEL} only — the firmware scaffold, linker script, "
        f"compiler flags and emulator platform are all STM32F4-specific. "
        f"Generating STM32F4 firmware and calling it {asked} would be wrong, "
        f"so nothing was generated.",
        requested=asked,
    )
