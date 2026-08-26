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


def generate_application(plan: ReadPlan, uart_baud_brr: int = 0x0683) -> str:
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
    p = _ident(plan.chip)
    body = _emit_body(plan, p)
    return _SCAFFOLD.format(
        chip=plan.chip, prefix=p, addr=f"0x{plan.address:02X}u",
        usart=_USART2_BASE, i2c=_I2C1_BASE, rcc=_RCC_BASE,
        brr=f"0x{uart_baud_brr:04X}u", body=body,
    )


def _emit_body(plan: ReadPlan, p: str) -> str:
    """The application half: the device conversation, in spec order."""
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
    uart_puts("{s.label}=");
    uart_u32(((uint32_t)b0 << 8) | (uint32_t)b1);
    uart_puts("\\r\\n");""")
        else:
            raise AppGenerationError(f"unknown step kind: {s.kind!r}")
    return "\n".join(out)


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
#define GUARD 200000u

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

void Reset_Handler(void)
{{
    uint32_t *src, *dst;
    uint8_t b0 = 0, b1 = 0;

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
{body}

done:
    uart_puts("EP-EMU-DONE\\r\\n");
    for (;;) {{ __asm__ volatile("wfi"); }}
}}
'''
