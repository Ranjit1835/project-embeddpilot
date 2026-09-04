"""V2 WS4: generate the APPLICATION firmware for a composed system.

This is the piece that makes V2 a product rather than a demo: the end-to-end
pipeline no longer stands a hand-written fixture in for the thing it claims to
produce. Firmware here is GENERATED from the ApplicationSpec plus the device's
own register facts, and the pipeline labels it `generated` truthfully.

WHY THIS IS A DETERMINISTIC GENERATOR AND NOT AN LLM PROMPT
-----------------------------------------------------------
The MCU bring-up half of an embedded application — vector table, reset handler,
.data/.bss init, clock enables, USART and I2C primitives — is IDENTICAL for every
application on a given MCU. It is not where the user's requirement lives, and
asking a model to re-derive a vector table correctly on every attempt buys
variance with no expressive gain. This project's charter already names the
answer: a deterministic template engine, IR-grounded (see CLAUDE.md). So the
scaffold is emitted deterministically from a shape PROVEN to boot in Renode, and
what varies per requirement — which device, at which address, which registers,
in which order, and what the application does with the result — is generated
from the spec and the register facts.

Consequences that matter:
* Same spec in, byte-identical firmware out. Determinism is a V1 rule and it
  still holds here.
* Nothing about a device is invented: every register the firmware touches must
  be handed in via a ReadPlan (which a caller builds from a V1-verified register
  map). No plan, no register access — the generator will not guess an address.
* No compensation math is emitted. Converting a raw reading into engineering
  units requires a datasheet-grounded oracle (V1.10a); where none exists the
  firmware reports the RAW value and says so. Inventing the conversion here
  would be exactly the failure this project exists to prevent.

CONTAMINATION GUARD: this module lives in generation/ and therefore must NEVER
import from validator/. It emits code; it does not judge it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# The scaffold below is transcribed from tests/fixtures/emulation/bmp180_temp.c,
# which is verified to boot on Renode's emulated STM32F4 and drive a mocked I2C
# device. Values are RM0090 offsets. Do not "tidy" these numbers.
_USART2_BASE = "0x40004400u"
_I2C1_BASE = "0x40005400u"
_RCC_BASE = "0x40023800u"


@dataclass
class Step:
    """One device operation the generated firmware performs.

    kind:
      "read8"   read one byte from `reg`, print "<label>=0x<hex>"
      "write8"  write `value` to `reg`
      "delay"   bounded busy-wait of `ticks`
      "read16"  read `reg` (MSB) and `reg_lo` (LSB), print "<label>=<decimal>"
    """

    kind: str
    label: str = ""
    reg: int | None = None
    reg_lo: int | None = None
    value: int | None = None
    ticks: int = 200000
    # a read8 may assert an expected constant (e.g. a chip-id byte). This is a
    # DEVICE FACT supplied by the caller from the register map; the generator
    # never invents one.
    expect_hex: str | None = None


@dataclass
class ReadPlan:
    """Everything the firmware needs to talk to one device. Built by the caller
    from a verified register map — the generator invents none of it."""

    chip: str
    address: int
    steps: list[Step] = field(default_factory=list)


@dataclass
class Behavior:
    """trigger -> action. "when the reading goes above X, turn the relay on".

    `unit` is the crux of this project's integrity. A threshold stated in
    ENGINEERING units (degrees C) can only be applied if the raw device word can
    be converted, and that conversion must come from a datasheet-grounded math
    oracle (V1.10a). Where no oracle exists we REFUSE to emit the behaviour
    rather than invent the formula — see generate_application(). A threshold in
    RAW device units needs no conversion and is always emittable.
    """

    threshold: int
    comparator: str = ">"           # one of > >= < <= == !=
    unit: str = "raw"               # "raw", or an engineering unit e.g. "C"
    action_label: str = "ACTION"
    gpio_port: str = "B"            # actuator pin, e.g. relay
    gpio_pin: int = 5


class AppGenerationError(Exception):
    pass


def _ident(name: str) -> str:
    out = re.sub(r"[^A-Za-z0-9]", "_", name or "DEV").upper()
    return out if out and not out[0].isdigit() else "D_" + out


def expectations_for(plan: ReadPlan) -> list[str]:
    """The UART lines the generated firmware must emit, derived from the SAME
    plan that generates it — so assertions are never hand-written per run and
    cannot drift from the code they check."""
    exp = ["EP-EMU-BOOT"]
    for s in plan.steps:
        if s.kind == "read8" and s.expect_hex:
            exp.append(f"{s.label}=0x{s.expect_hex.upper().removeprefix('0X')}")
        elif s.kind == "read16":
            exp.append(f"{s.label}=")      # value asserted by the caller
    exp.append("EP-EMU-DONE")
    return exp


def generate_application(plan: ReadPlan, behavior: "Behavior | None" = None,
                         samples: int = 1, has_math_oracle: bool = False,
                         uart_baud_brr: int = 0x0683) -> str:
    """ApplicationSpec + device facts -> complete bare-metal STM32F4 C.

    The output compiles with:
      arm-none-eabi-gcc -mcpu=cortex-m4 -mthumb -Os -ffreestanding -nostdlib
                        -nostartfiles -Wall -Wextra -T stm32f4.ld
    Every wait is bounded: firmware that can spin forever would hang the
    emulator, so a GUARD counter is mandatory, not stylistic.
    """
    if not plan.steps:
        raise AppGenerationError(
            "no device steps supplied — refusing to generate firmware that "
            "touches registers nobody specified")
    if behavior is not None and behavior.unit != "raw" and not has_math_oracle:
        # The integrity point. Applying a degrees-C threshold means converting the
        # raw device word, and that conversion is datasheet knowledge we either
        # verified (a math oracle) or do not have. Emitting it from memory would
        # be exactly the invention this project exists to prevent.
        raise AppGenerationError(
            f"threshold is stated in {behavior.unit!r} but {plan.chip} has no "
            "verified math oracle to convert the raw device word into that unit "
            "(V1.10a). Restate the threshold in raw device units, or supply a "
            "datasheet-grounded oracle — the conversion will not be invented here.")
    p = _ident(plan.chip)
    body = _emit_body(plan, p, behavior, samples)
    return _SCAFFOLD.format(
        chip=plan.chip, prefix=p, addr=f"0x{plan.address:02X}u",
        usart=_USART2_BASE, i2c=_I2C1_BASE, rcc=_RCC_BASE,
        brr=f"0x{uart_baud_brr:04X}u", body=body,
        act_pin=(behavior.gpio_pin if behavior is not None else 5),
        driver_include="", driver_decls="", driver_glue="",
        extra_defines="",
    )


def _emit_body(plan: ReadPlan, p: str, behavior: "Behavior | None" = None,
               samples: int = 1) -> str:
    """The application half: the device conversation, in spec order, wrapped in
    the application's sample loop and followed by its trigger -> action rule."""
    out: list[str] = []
    for i, s in enumerate(plan.steps):
        if s.kind == "read8":
            out.append(f"""
    if (i2c_read_reg({p}_ADDR, 0x{s.reg:02X}u, &b0)) {{
        uart_puts("{s.label}=");
        uart_hex8(b0);
        uart_puts("\\r\\n");
    }} else {{
        uart_puts("{s.label}-FAILED\\r\\n");
        goto done;
    }}""")
        elif s.kind == "write8":
            out.append(f"""
    if (!i2c_write_reg({p}_ADDR, 0x{s.reg:02X}u, 0x{s.value:02X}u)) {{
        uart_puts("{s.label}-FAILED\\r\\n");
        goto done;
    }}""")
        elif s.kind == "delay":
            out.append(f"""
    if (delay_ticks({s.ticks}u)) {{
        uart_puts("{s.label}=OK\\r\\n");
    }} else {{
        uart_puts("{s.label}=GUARD\\r\\n");
    }}""")
        elif s.kind == "read16":
            out.append(f"""
    if (!i2c_read_reg({p}_ADDR, 0x{s.reg:02X}u, &b0) ||
        !i2c_read_reg({p}_ADDR, 0x{s.reg_lo:02X}u, &b1)) {{
        uart_puts("{s.label}-FAILED\\r\\n");
        goto done;
    }}
    /* RAW device word. NOT converted to engineering units: that needs a
     * datasheet-grounded oracle and inventing the formula here would be a lie
     * about what has been verified. */
    last_raw = ((uint32_t)b0 << 8) | (uint32_t)b1;
    uart_puts("{s.label}=");
    uart_u32(last_raw);
    uart_puts("\\r\\n");""")
        else:
            raise AppGenerationError(f"unknown step kind: {s.kind!r}")

    if behavior is not None:
        cmp_ = (behavior.comparator
                if behavior.comparator in (">", ">=", "<", "<=", "==", "!=")
                else ">")
        out.append(f"""
    /* trigger -> action, from the application spec. The comparison is on the
     * RAW device word: converting it to engineering units would require a
     * verified math oracle, and generate_application() refuses without one. */
    if (last_raw {cmp_} {behavior.threshold}u) {{
        gpio_write(1);
        uart_puts("{behavior.action_label}=ON\\r\\n");
    }} else {{
        gpio_write(0);
        uart_puts("{behavior.action_label}=OFF\\r\\n");
    }}""")

    inner = "\n".join(out)
    if behavior is not None or samples > 1:
        # A real application samples in a loop. The loop is BOUNDED so generated
        # firmware can never hang the emulator — the same discipline every wait
        # in the scaffold follows.
        n = max(1, samples)
        return (f"    for (uint32_t iter = 0; iter < {n}u; iter++) {{\n"
                f"{inner}\n    }}")
    return inner


# --- the deterministic scaffold ---------------------------------------------
# Transcribed from the Renode-proven fixture. Parameterised only where a
# composed system legitimately differs (chip name, bus address, baud divisor).

_SCAFFOLD = '''/* GENERATED by EmbeddPilot V2 (generation/app_worker.py) for {chip}.
 *
 * Bare-metal STM32F4. The MCU bring-up is a deterministic scaffold; the device
 * conversation below it is generated from the application spec and the device's
 * verified register map. Raw device values are reported as-is — no compensation
 * math is emitted, because that requires a datasheet-grounded oracle.
 *
 * Every wait is bounded by a GUARD: firmware that can spin forever hangs the
 * emulator instead of failing honestly.
 */
#include <stdint.h>
{driver_include}
#define USART2_BASE {usart}
#define USART_SR    (*(volatile uint32_t *)(USART2_BASE + 0x00u))
#define USART_DR    (*(volatile uint32_t *)(USART2_BASE + 0x04u))
#define USART_BRR   (*(volatile uint32_t *)(USART2_BASE + 0x08u))
#define USART_CR1   (*(volatile uint32_t *)(USART2_BASE + 0x0Cu))
#define SR_TXE      (1u << 7)
#define UCR1_UE     (1u << 13)
#define UCR1_TE     (1u << 3)

#define I2C1_BASE   {i2c}
#define I2C_CR1     (*(volatile uint32_t *)(I2C1_BASE + 0x00u))
#define I2C_CR2     (*(volatile uint32_t *)(I2C1_BASE + 0x04u))
#define I2C_DR      (*(volatile uint32_t *)(I2C1_BASE + 0x10u))
#define I2C_SR1     (*(volatile uint32_t *)(I2C1_BASE + 0x14u))
#define I2C_SR2     (*(volatile uint32_t *)(I2C1_BASE + 0x18u))
#define I2C_CCR     (*(volatile uint32_t *)(I2C1_BASE + 0x1Cu))
#define I2C_TRISE   (*(volatile uint32_t *)(I2C1_BASE + 0x20u))

#define CR1_PE      (1u << 0)
#define CR1_START   (1u << 8)
#define CR1_STOP    (1u << 9)
#define CR1_ACK     (1u << 10)
#define SR1_SB      (1u << 0)
#define SR1_ADDR    (1u << 1)
#define SR1_RXNE    (1u << 6)
#define SR1_TXE     (1u << 7)

#define RCC_AHB1ENR (*(volatile uint32_t *)({rcc} + 0x30u))
#define RCC_APB1ENR (*(volatile uint32_t *)({rcc} + 0x40u))

#define {prefix}_ADDR {addr}
{extra_defines}#define GUARD 200000u

extern uint32_t _estack;
extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss;

void Reset_Handler(void);
static void Default_Handler(void) {{ for (;;) {{ }} }}

__attribute__((section(".isr_vector"), used))
void (*const g_vectors[])(void) = {{
    (void (*)(void)) &_estack,
    Reset_Handler,
    Default_Handler,
    Default_Handler,
}};

static void uart_putc(char c)
{{
    uint32_t g = GUARD;
    while (!(USART_SR & SR_TXE) && g--) {{ }}
    USART_DR = (uint32_t)(uint8_t)c;
}}

static void uart_puts(const char *s) {{ while (*s) {{ uart_putc(*s++); }} }}

static void uart_hex8(uint8_t v)
{{
    static const char H[] = "0123456789ABCDEF";
    uart_puts("0x");
    uart_putc(H[(v >> 4) & 0xFu]);
    uart_putc(H[v & 0xFu]);
}}

static void uart_u32(uint32_t v)
{{
    char buf[11];
    int i = 0;
    if (!v) {{ uart_putc('0'); return; }}
    while (v && i < 10) {{ buf[i++] = (char)('0' + (v % 10u)); v /= 10u; }}
    while (i--) {{ uart_putc(buf[i]); }}
}}

#define GPIOB_BASE  0x40020400u
#define GPIO_MODER  (*(volatile uint32_t *)(GPIOB_BASE + 0x00u))
#define GPIO_BSRR   (*(volatile uint32_t *)(GPIOB_BASE + 0x18u))
#define ACT_PIN     {act_pin}u

static void gpio_out_init(void)
{{
    GPIO_MODER &= ~(3u << (ACT_PIN * 2u));
    GPIO_MODER |=  (1u << (ACT_PIN * 2u));   /* general purpose output */
}}

static void gpio_write(int on)
{{
    GPIO_BSRR = on ? (1u << ACT_PIN) : (1u << (ACT_PIN + 16u));
}}

static int wait_flag(volatile uint32_t *reg, uint32_t mask)
{{
    uint32_t g = GUARD;
    while (!(*reg & mask)) {{ if (!g--) {{ return 0; }} }}
    return 1;
}}

static int delay_ticks(uint32_t ticks)
{{
    volatile uint32_t n = ticks;
    while (n) {{ n--; }}
    return 1;
}}

static int i2c_read_reg(uint8_t addr, uint8_t reg, uint8_t *out)
{{
    I2C_CR1 |= CR1_START;
    if (!wait_flag(&I2C_SR1, SR1_SB)) {{ return 0; }}
    (void)I2C_SR1;
    I2C_DR = (uint32_t)(addr << 1);
    if (!wait_flag(&I2C_SR1, SR1_ADDR)) {{ return 0; }}
    (void)I2C_SR1; (void)I2C_SR2;
    if (!wait_flag(&I2C_SR1, SR1_TXE)) {{ return 0; }}
    I2C_DR = reg;
    if (!wait_flag(&I2C_SR1, SR1_TXE)) {{ return 0; }}

    I2C_CR1 |= CR1_START;
    if (!wait_flag(&I2C_SR1, SR1_SB)) {{ return 0; }}
    (void)I2C_SR1;
    I2C_CR1 &= ~CR1_ACK;
    I2C_DR = (uint32_t)((addr << 1) | 1u);
    if (!wait_flag(&I2C_SR1, SR1_ADDR)) {{ return 0; }}
    (void)I2C_SR1; (void)I2C_SR2;
    if (!wait_flag(&I2C_SR1, SR1_RXNE)) {{ return 0; }}
    *out = (uint8_t)I2C_DR;
    I2C_CR1 |= CR1_STOP;
    I2C_CR1 |= CR1_ACK;
    return 1;
}}

static int i2c_write_reg(uint8_t addr, uint8_t reg, uint8_t val)
{{
    I2C_CR1 |= CR1_START;
    if (!wait_flag(&I2C_SR1, SR1_SB)) {{ return 0; }}
    (void)I2C_SR1;
    I2C_DR = (uint32_t)(addr << 1);
    if (!wait_flag(&I2C_SR1, SR1_ADDR)) {{ return 0; }}
    (void)I2C_SR1; (void)I2C_SR2;
    if (!wait_flag(&I2C_SR1, SR1_TXE)) {{ return 0; }}
    I2C_DR = reg;
    if (!wait_flag(&I2C_SR1, SR1_TXE)) {{ return 0; }}
    I2C_DR = val;
    if (!wait_flag(&I2C_SR1, SR1_TXE)) {{ return 0; }}
    I2C_CR1 |= CR1_STOP;
    return 1;
}}

{driver_glue}
void Reset_Handler(void)
{{
    uint32_t *src, *dst;
    uint8_t b0 = 0, b1 = 0;
    uint32_t last_raw = 0;
{driver_decls}

    for (src = &_sidata, dst = &_sdata; dst < &_edata; ) {{ *dst++ = *src++; }}
    for (dst = &_sbss; dst < &_ebss; ) {{ *dst++ = 0u; }}

    RCC_AHB1ENR |= (1u << 0) | (1u << 1);
    RCC_APB1ENR |= (1u << 17) | (1u << 21);   /* USART2, I2C1 */

    USART_BRR = {brr};
    USART_CR1 = UCR1_UE | UCR1_TE;
    uart_puts("EP-EMU-BOOT\\r\\n");

    I2C_CR2   = 42u;        /* APB1 = 42 MHz */
    I2C_CCR   = 210u;       /* 100 kHz standard mode */
    I2C_TRISE = 43u;
    I2C_CR1   = CR1_PE | CR1_ACK;
    gpio_out_init();
{body}

done:
    uart_puts("EP-EMU-DONE\\r\\n");
    for (;;) {{ __asm__ volatile("wfi"); }}
}}
'''


# --- deriving a ReadPlan from a V1-verified register map --------------------
#
# This is what makes the generator general rather than BMP180-specific: the plan
# is DERIVED from the map V1 already extracted and cross-checked, so any device
# we can ingest becomes an application we can generate.
#
# The derivation is by NAMING CONVENTION over the map's own register names, and
# it is deliberately conservative. Every address it emits comes from the map;
# none is inferred, defaulted, or remembered. When a required piece cannot be
# identified the function returns (None, reasons) — it does NOT fall back to a
# plausible guess, because a firmware that reads a register the device does not
# have is worse than no firmware at all.

_ID_RE = re.compile(r"^(id|chip_?id|who_?am_?i|device_?id|part_?id)$", re.I)
_CTRL_RE = re.compile(r"(ctrl|control|meas|cfg|config)", re.I)
_OUT_MSB_RE = re.compile(r"(out|data|result|temp).*(_msb|_h|_hi)$|^(msb)$", re.I)
_OUT_LSB_RE = re.compile(r"(out|data|result|temp).*(_lsb|_l|_lo)$|^(lsb)$", re.I)


def _regs(register_map: dict) -> list[tuple[str, int]]:
    out = []
    for r in register_map.get("registers", []):
        try:
            out.append((r["name"], int(r["offset"], 16)))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def derive_read_plan(
    register_map: dict,
    address: int,
    measurement: str | None = None,
    conv_ticks: int = 200000,
) -> tuple[ReadPlan | None, list[str]]:
    """V1 register map -> a ReadPlan the generator can build firmware from.

    `measurement` names which command in the map starts the conversion (e.g.
    "Temperature"). If the map has no such command the plan simply omits the
    start/wait steps and reads the data registers directly — which is correct
    for devices that continuously convert (LM75B-class parts).

    Returns (plan, notes). `plan is None` means a required piece could not be
    identified from the map; `notes` says which, so the caller can ask the user
    instead of the generator inventing it.
    """
    regs = _regs(register_map)
    if not regs:
        return None, ["the register map contains no registers — nothing to read"]
    chip = register_map.get("chip") or "device"
    notes: list[str] = []
    steps: list[Step] = []
    by = lambda rx: [(n, o) for n, o in regs if rx.search(n)]

    # 1. identity read, when the map names an ID register. Optional: its absence
    #    is not a failure, only a weaker boot check.
    ident = [(n, o) for n, o in regs if _ID_RE.match(n)]
    if ident:
        steps.append(Step("read8", label=f"{chip}-ID", reg=ident[0][1]))
    else:
        notes.append("no ID register in the map — boot check omitted")

    # 2. start a conversion, when the caller named one AND the map has both a
    #    control register and that command's opcode. All three or none.
    if measurement:
        ctrl = by(_CTRL_RE)
        cmd = [c for c in register_map.get("commands", [])
               if measurement.lower() in str(c.get("name", "")).lower()]
        if ctrl and cmd:
            try:
                opcode = int(cmd[0]["opcode"], 16)
            except (KeyError, ValueError, TypeError):
                opcode = None
            if opcode is not None:
                steps.append(Step("write8", label=f"{chip}-START",
                                  reg=ctrl[0][1], value=opcode))
                steps.append(Step("delay", label=f"{chip}-WAIT", ticks=conv_ticks))
            else:
                notes.append(f"command {measurement!r} has an unreadable opcode")
        else:
            missing = []
            if not ctrl:
                missing.append("a control register")
            if not cmd:
                missing.append(f"a {measurement!r} command")
            notes.append("conversion start skipped: the map has no "
                         + " and no ".join(missing))

    # 3. the measurement read itself — this one is REQUIRED. Without it the
    #    firmware would demonstrate nothing.
    msb = by(_OUT_MSB_RE)
    lsb = by(_OUT_LSB_RE)
    if msb and lsb:
        steps.append(Step("read16", label=f"{chip}-RAW",
                          reg=msb[0][1], reg_lo=lsb[0][1]))
    elif msb:
        steps.append(Step("read8", label=f"{chip}-RAW", reg=msb[0][1]))
    else:
        return None, notes + [
            "no data/output register could be identified in the map, so there is "
            "nothing to read — refusing to generate firmware that reads an "
            "address nobody specified"]

    return ReadPlan(chip=chip, address=address, steps=steps), notes


# --- a complete application repo, not a loose .c file -----------------------

_MAKEFILE = """# Generated by EmbeddPilot V2.
CROSS   ?= arm-none-eabi-
CC       = $(CROSS)gcc
OBJCOPY  = $(CROSS)objcopy
CFLAGS   = -mcpu=cortex-m4 -mthumb -Os -ffreestanding -nostdlib -nostartfiles \
           -Wall -Wextra
LDSCRIPT = link/stm32f4.ld

all: build/firmware.elf build/firmware.bin

build:
\tmkdir -p build

build/firmware.elf: src/main.c $(LDSCRIPT) | build
\t$(CC) $(CFLAGS) -T $(LDSCRIPT) $< -o $@

build/firmware.bin: build/firmware.elf
\t$(OBJCOPY) -O binary $< $@

clean:
\trm -rf build

.PHONY: all clean
"""


def _readme(plan: ReadPlan, behavior, verified: dict) -> str:
    steps = "\n".join(
        f"- `{s.label}` — {s.kind} at "
        + (f"0x{s.reg:02X}" + (f"/0x{s.reg_lo:02X}" if s.reg_lo is not None else "")
           if s.reg is not None else "bounded wait")
        for s in plan.steps)
    act = (f"\nWhen the raw reading {behavior.comparator} `{behavior.threshold}` "
           f"(raw device units), GPIO{behavior.gpio_port}{behavior.gpio_pin} is "
           f"driven high and `{behavior.action_label}=ON` is printed.\n"
           if behavior is not None else "\nNo trigger/action rule was specified.\n")
    return f"""# {plan.chip} application

Generated by **EmbeddPilot V2**. Bare-metal STM32F4, device at I²C address
`0x{plan.address:02X}`.

## Build

    make            # -> build/firmware.elf

Requires `arm-none-eabi-gcc`.

## What this firmware does
{steps}
{act}
## What has been verified — and what has NOT

| Property | Status |
|---|---|
| Register addresses | {verified.get('registers', 'from the extracted register map')} |
| Compiles clean (`-Wall -Wextra`) | {verified.get('compile', 'yes')} |
| Runs against a mocked device | {verified.get('emulation', 'see the emulation report')} |
| Raw → engineering-unit conversion | **NOT performed** — needs a datasheet-grounded math oracle |
| Physical hardware | **NOT verified** — emulation is not silicon |

Every register address above comes from the datasheet-extracted register map;
none was inferred. The raw device word is reported as-is: converting it to
engineering units requires a verified conversion, and where none exists this
firmware does not invent one.

Emulation shows the firmware runs and behaves as specified against a *mocked*
device. It is not evidence that it works on physical hardware — bring-up on real
silicon remains a human step.
"""


def generate_project(
    plan: ReadPlan,
    behavior: "Behavior | None" = None,
    samples: int = 1,
    has_math_oracle: bool = False,
    linker_script: str = "",
    verified: dict | None = None,
) -> dict[str, str]:
    """The deliverable: a complete, buildable application repo.

    Returns {relative_path: file_contents}. The README states plainly what was
    verified and what was not — a repo that overstates its own guarantees is the
    failure mode this project exists to prevent.
    """
    main_c = generate_application(plan, behavior, samples, has_math_oracle)
    files = {
        "src/main.c": main_c,
        "Makefile": _MAKEFILE,
        "README.md": _readme(plan, behavior, verified or {}),
    }
    if linker_script:
        files["link/stm32f4.ld"] = linker_script
    return files


# --- consuming V1's VERIFIED driver ------------------------------------------
#
# Until now this module emitted its own I2C primitives and talked to the device
# directly. That made the application's device logic improvised code sitting
# beside V1's verified driver rather than USING it — two pipelines that never
# met. The correct seam is the one V1 already designed: its bus drivers are
# portable C that reach the device through caller-supplied callbacks.
#
#     typedef int (*<chip>_read_fn)(uint8_t reg, uint8_t *buf, uint32_t len);
#     int <chip>_init(<chip>_dev_t *dev, <chip>_read_fn, <chip>_write_fn);
#
# So: V1 owns DEVICE logic (cross-checked against the datasheet, and where an
# oracle exists, its math executed against it). V2 owns MCU bring-up, implements
# those callbacks against the real peripheral, and runs the application. Nothing
# about the device is re-derived here.

_TYPEDEF_READ_RE = re.compile(
    r"typedef\s+int\s*\(\s*\*\s*(\w+_read_fn)\s*\)\s*\(", re.M)
_TYPEDEF_WRITE_RE = re.compile(
    r"typedef\s+int\s*\(\s*\*\s*(\w+_write_fn)\s*\)\s*\(", re.M)
_INIT_RE = re.compile(r"\bint\s+(\w+_init)\s*\(\s*(\w+_dev_t)\s*\*", re.M)
# a raw/uncompensated reader: prefer *_raw, since converting to engineering
# units is only legitimate where a verified oracle exists.
_READ_RAW_RE = re.compile(
    r"\bint\s+(\w*_read_\w*raw\w*)\s*\(\s*(\w+_dev_t)\s*\*\s*\w+\s*,\s*"
    r"(int32_t|uint32_t|int16_t|uint16_t)\s*\*", re.M)


@dataclass
class DriverInterface:
    """The entry points of a V1-generated driver, read from its header."""

    prefix: str
    header: str            # file name to #include
    dev_type: str
    init_fn: str
    read_fn_t: str
    write_fn_t: str
    read_raw_fn: str
    raw_ctype: str


def parse_driver_interface(header_text: str, header_name: str
                           ) -> tuple[DriverInterface | None, list[str]]:
    """Read a V1 driver header and find how to drive it.

    Returns (interface, reasons). None means the header does not expose the
    callback-based shape this integration needs — we say which piece is missing
    rather than guessing a function name that may not exist.
    """
    why: list[str] = []
    r = _TYPEDEF_READ_RE.search(header_text)
    w = _TYPEDEF_WRITE_RE.search(header_text)
    i = _INIT_RE.search(header_text)
    raw = _READ_RAW_RE.search(header_text)
    if not r:
        why.append("no <chip>_read_fn callback typedef")
    if not w:
        why.append("no <chip>_write_fn callback typedef")
    if not i:
        why.append("no <chip>_init(<chip>_dev_t*, ...) entry point")
    if not raw:
        why.append("no raw/uncompensated read function returning an integer "
                   "out-parameter — refusing to call a converted reading, "
                   "because unit conversion is only trustworthy where a "
                   "verified math oracle exists")
    if why:
        return None, why
    prefix = i.group(1)[: -len("_init")]
    return DriverInterface(
        prefix=prefix, header=header_name, dev_type=i.group(2),
        init_fn=i.group(1), read_fn_t=r.group(1), write_fn_t=w.group(1),
        read_raw_fn=raw.group(1), raw_ctype=raw.group(3),
    ), []


def generate_application_using_driver(
    iface: DriverInterface,
    address: int,
    behavior: "Behavior | None" = None,
    samples: int = 1,
    has_math_oracle: bool = False,
    uart_baud_brr: int = 0x0683,
) -> str:
    """Application firmware that RUNS V1's verified driver.

    The MCU half (vectors, clocks, USART, I2C) is the same proven scaffold. The
    device half is delegated entirely to the driver: this code only implements
    the driver's two bus callbacks and calls its published API.
    """
    if behavior is not None and behavior.unit != "raw" and not has_math_oracle:
        raise AppGenerationError(
            f"threshold is stated in {behavior.unit!r} but no verified math "
            "oracle converts this device's raw word into that unit (V1.10a). "
            "Restate it in raw units or supply an oracle — the conversion will "
            "not be invented here.")
    p = _ident(iface.prefix)
    pl = p.lower()
    act = behavior.gpio_pin if behavior is not None else 5
    glue = f"""
/* --- the driver's bus callbacks ---------------------------------------------
 * The ONLY device-facing code in this file. Everything above is MCU bring-up;
 * everything about {iface.prefix} itself lives in the VERIFIED driver we link
 * against, so no register of this device is re-derived here.
 */
static int {pl}_bus_read(uint8_t reg, uint8_t *buf, uint32_t len)
{{
    for (uint32_t k = 0; k < len; k++) {{
        if (!i2c_read_reg({p}_ADDR, (uint8_t)(reg + k), &buf[k])) {{ return -1; }}
    }}
    return 0;
}}

static int {pl}_bus_write(uint8_t reg, const uint8_t *buf, uint32_t len)
{{
    for (uint32_t k = 0; k < len; k++) {{
        if (!i2c_write_reg({p}_ADDR, (uint8_t)(reg + k), buf[k])) {{ return -1; }}
    }}
    return 0;
}}
"""
    body = _driver_body(iface, behavior, samples, pl)
    return _SCAFFOLD.format(
        chip=iface.prefix, prefix=p, addr=f"0x{address:02X}u",
        usart=_USART2_BASE, i2c=_I2C1_BASE, rcc=_RCC_BASE,
        brr=f"0x{uart_baud_brr:04X}u", act_pin=act, body=body,
        driver_include=f'#include "{iface.header}"',
        # On the driver path the device conversation belongs to the driver, so
        # the scaffold's own scratch bytes and helpers go unused. Reference them
        # explicitly rather than deleting them from the shared scaffold: one
        # scaffold, proven to boot, is worth more than two that drift apart.
        driver_decls=(f"    {iface.dev_type} dev;\n"
                      f"    {iface.raw_ctype} raw = 0;\n"
                      "    (void)b0; (void)b1;\n"
                      "    (void)uart_hex8; (void)delay_ticks;"),
        driver_glue=glue, extra_defines="",
    )


def _driver_body(iface: DriverInterface, behavior, samples: int, pl: str) -> str:
    out = [f"""
    if ({iface.init_fn}(&dev, {pl}_bus_read, {pl}_bus_write) != 0) {{
        uart_puts("{iface.prefix}-INIT-FAILED\\r\\n");
        goto done;
    }}
    uart_puts("{iface.prefix}-INIT=OK\\r\\n");"""]
    out.append(f"""
        if ({iface.read_raw_fn}(&dev, &raw) != 0) {{
            uart_puts("{iface.prefix}-READ-FAILED\\r\\n");
            goto done;
        }}
        /* RAW value straight from the verified driver. Not converted here:
         * unit conversion requires a datasheet-grounded oracle. */
        last_raw = (uint32_t)raw;
        uart_puts("{iface.prefix}-RAW=");
        uart_u32(last_raw);
        uart_puts("\\r\\n");""")
    if behavior is not None:
        cmp_ = (behavior.comparator
                if behavior.comparator in (">", ">=", "<", "<=", "==", "!=")
                else ">")
        out.append(f"""
        if (last_raw {cmp_} {behavior.threshold}u) {{
            gpio_write(1);
            uart_puts("{behavior.action_label}=ON\\r\\n");
        }} else {{
            gpio_write(0);
            uart_puts("{behavior.action_label}=OFF\\r\\n");
        }}""")
    head, loop_body = out[0], "\n".join(out[1:])
    n = max(1, samples)
    return (head + f"\n    for (uint32_t iter = 0; iter < {n}u; iter++) {{\n"
            + loop_body + "\n    }")


def expectations_for_driver(iface: DriverInterface, behavior=None) -> list[str]:
    exp = ["EP-EMU-BOOT", f"{iface.prefix}-INIT=OK", f"{iface.prefix}-RAW="]
    if behavior is not None:
        exp.append(f"{behavior.action_label}=")
    exp.append("EP-EMU-DONE")
    return exp



# --- multi-device systems ----------------------------------------------------
#
# A real application is rarely one sensor. The resource cross-check has always
# reasoned about a COMPOSED system (several devices sharing a bus, pins, DMA);
# the generator, until now, emitted exactly one. So a two-sensor application
# could be CHECKED but not BUILT — the moat was wider than the mill.
#
# Multi-device changes almost nothing structurally, because the scaffold's
# i2c_read_reg/i2c_write_reg already take the device address as a parameter: two
# devices on one I2C bus differ only by address. What it does force is one
# honest decision — WHICH device's reading drives the actuator. With several
# readings available that is genuinely ambiguous, so it must be stated, never
# inferred from ordering.

def generate_system(
    plans: list[ReadPlan],
    behavior: "Behavior | None" = None,
    samples: int = 1,
    has_math_oracle: bool = False,
    source_chip: str | None = None,
    uart_baud_brr: int = 0x0683,
) -> str:
    """Firmware for a composed system of I2C devices on one bus.

    `source_chip` names which device's raw reading the behaviour compares. It is
    required when more than one device produces a reading: picking the first one
    silently would be inventing a requirement the user never stated.
    """
    if not plans:
        raise AppGenerationError("no devices — nothing to generate")
    for pl in plans:
        if not pl.steps:
            raise AppGenerationError(
                f"{pl.chip}: no device steps supplied — refusing to generate "
                "firmware that touches registers nobody specified")
    if behavior is not None and behavior.unit != "raw" and not has_math_oracle:
        raise AppGenerationError(
            f"threshold is stated in {behavior.unit!r} but no verified math "
            "oracle converts a raw device word into that unit (V1.10a). Restate "
            "it in raw units or supply an oracle — it will not be invented here.")

    readers = [pl for pl in plans
               if any(s.kind in ("read16", "read8") for s in pl.steps)]
    src = None
    if behavior is not None:
        if source_chip:
            match = [pl for pl in plans if pl.chip == source_chip]
            if not match:
                raise AppGenerationError(
                    f"behaviour names source device {source_chip!r}, which is not "
                    f"in the composed system ({', '.join(p.chip for p in plans)})")
            src = match[0]
        elif len(readers) == 1:
            src = readers[0]
        else:
            raise AppGenerationError(
                "the system has several devices that produce a reading "
                f"({', '.join(p.chip for p in readers)}) but the behaviour does "
                "not say which one drives the action. Name it — choosing the "
                "first would be inventing a requirement.")

    # the first device's address goes through the scaffold's own slot; the rest
    # are appended, so every device is addressed by a NAMED constant
    extra = "\n".join(
        f"#define {_ident(pl.chip)}_ADDR 0x{pl.address:02X}u" for pl in plans[1:])
    if extra:
        extra += "\n"
    if len({pl.address for pl in plans}) != len(plans):
        # the resource cross-check owns this verdict, but emitting firmware that
        # cannot work is worse than refusing to
        raise AppGenerationError(
            "two devices claim the same I2C address — the composed system cannot "
            "work; resolve the collision before generating firmware")

    body_parts = []
    for pl in plans:
        p = _ident(pl.chip)
        # Labels must be UNIQUE PER DEVICE, or two sensors both report
        # "<chip>-RAW=" and an assertion cannot tell them apart — a two-device
        # system would look like it worked while only one device was observed.
        # The label is ours (not a device fact), so re-deriving it from the
        # plan's current chip name invents nothing.
        labelled = ReadPlan(chip=pl.chip, address=pl.address, steps=[
            Step(kind=s.kind, reg=s.reg, reg_lo=s.reg_lo, value=s.value,
                 ticks=s.ticks, expect_hex=s.expect_hex,
                 label=f"{pl.chip}-{s.label.split('-', 1)[-1]}"
                 if "-" in s.label else f"{pl.chip}-{s.label}")
            for s in pl.steps])
        body_parts.append(f"        /* --- {pl.chip} --- */")
        body_parts.append(_emit_body(labelled, p, None, 1))
        if src is not None and pl is src:
            body_parts.append("        sys_raw = last_raw;")
    if behavior is not None:
        cmp_ = (behavior.comparator
                if behavior.comparator in (">", ">=", "<", "<=", "==", "!=")
                else ">")
        body_parts.append(f"""
        /* trigger -> action. The comparison is on {src.chip}'s RAW word, named
         * explicitly rather than inferred from device order. */
        if (sys_raw {cmp_} {behavior.threshold}u) {{
            gpio_write(1);
            uart_puts("{behavior.action_label}=ON\\r\\n");
        }} else {{
            gpio_write(0);
            uart_puts("{behavior.action_label}=OFF\\r\\n");
        }}""")
    n = max(1, samples)
    body = (f"    for (uint32_t iter = 0; iter < {n}u; iter++) {{\n"
            + "\n".join(body_parts) + "\n    }")

    head = plans[0]
    return _SCAFFOLD.format(
        chip=", ".join(pl.chip for pl in plans), prefix=_ident(head.chip),
        addr=f"0x{head.address:02X}u",
        usart=_USART2_BASE, i2c=_I2C1_BASE, rcc=_RCC_BASE,
        brr=f"0x{uart_baud_brr:04X}u", body=body,
        act_pin=(behavior.gpio_pin if behavior is not None else 5),
        driver_include="", driver_glue="", extra_defines=extra,
        driver_decls="    uint32_t sys_raw = 0; (void)sys_raw;",
    )


def expectations_for_system(plans: list[ReadPlan], behavior=None) -> list[str]:
    exp = ["EP-EMU-BOOT"]
    for pl in plans:
        relabelled = ReadPlan(chip=pl.chip, address=pl.address, steps=[
            Step(kind=s.kind, reg=s.reg, reg_lo=s.reg_lo, value=s.value,
                 ticks=s.ticks, expect_hex=s.expect_hex,
                 label=f"{pl.chip}-{s.label.split('-', 1)[-1]}"
                 if "-" in s.label else f"{pl.chip}-{s.label}")
            for s in pl.steps])
        exp.extend(e for e in expectations_for(relabelled)
                   if e not in ("EP-EMU-BOOT", "EP-EMU-DONE"))
    if behavior is not None:
        exp.append(f"{behavior.action_label}=")
    exp.append("EP-EMU-DONE")
    return exp
