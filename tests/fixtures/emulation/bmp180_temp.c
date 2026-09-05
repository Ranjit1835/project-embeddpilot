/* Hand-written bare-metal STM32F4: BMP180 RAW TEMPERATURE read over I2C1,
 * reported on USART2. RM0090 offsets only. Every wait is bounded -- nothing
 * may spin forever.
 *
 * WHY THIS FIXTURE EXISTS (it is not a bigger `bmp180_probe.c`)
 * ------------------------------------------------------------
 * `bmp180_probe.c` reads the chip ID at 0xD0. The ID is a CONSTANT: the same
 * 0x55 comes back no matter what the mocked device was told to measure. So a
 * green run over that fixture proves "firmware runs and talks to a mocked
 * device" -- it does NOT prove that a value injected into the mock reaches the
 * assertion. Change the emulator's `Temperature` stimulus and the verdict does
 * not move, which means the stimulus is plumbed but not load-bearing.
 *
 * This fixture closes that gap. It performs the datasheet's raw-temperature
 * sequence -- write 0x2E to the control register 0xF4, wait the conversion
 * time, read the 16-bit uncompensated value UT from 0xF6 (MSB) / 0xF7 (LSB) --
 * and prints UT in decimal. UT is DERIVED FROM the mocked device's temperature,
 * so an assertion on it can only hold for the stimulus that produced it.
 *
 * WHAT THIS FIXTURE DELIBERATELY DOES NOT DO
 * ------------------------------------------
 * It does NOT compensate. The BMP180 compensation algorithm lives in a FIGURE
 * in the datasheet and V1.10a established it is not extractable, so this
 * project has NO oracle for it. Writing that math from memory would be exactly
 * the "unverified presented as verified" failure the product exists to prevent.
 * UT is emitted raw, and every claim made about it is a claim about raw
 * register flow-through and nothing more. No degrees Celsius appear anywhere.
 */
#include <stdint.h>

#define USART2_BASE 0x40004400u
#define USART_SR    (*(volatile uint32_t *)(USART2_BASE + 0x00u))
#define USART_DR    (*(volatile uint32_t *)(USART2_BASE + 0x04u))
#define USART_BRR   (*(volatile uint32_t *)(USART2_BASE + 0x08u))
#define USART_CR1   (*(volatile uint32_t *)(USART2_BASE + 0x0Cu))
#define SR_TXE      (1u << 7)
#define UCR1_UE     (1u << 13)
#define UCR1_TE     (1u << 3)

#define I2C1_BASE   0x40005400u
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
#define SR1_BTF     (1u << 2)
#define SR1_RXNE    (1u << 6)
#define SR1_TXE     (1u << 7)

#define RCC_AHB1ENR (*(volatile uint32_t *)(0x40023800u + 0x30u))
#define RCC_APB1ENR (*(volatile uint32_t *)(0x40023800u + 0x40u))

/* ARMv7-M SysTick (ARM DDI 0403, B3.3) -- architectural, not RM0090. */
#define SYST_CSR    (*(volatile uint32_t *)0xE000E010u)
#define SYST_RVR    (*(volatile uint32_t *)0xE000E014u)
#define SYST_CVR    (*(volatile uint32_t *)0xE000E018u)
#define SYST_ENABLE     (1u << 0)
#define SYST_CLKSOURCE  (1u << 2)
#define SYST_COUNTFLAG  (1u << 16)

#define BMP180_ADDR     0x77u
#define BMP180_ID_REG   0xD0u
#define BMP180_CTRL_REG 0xF4u   /* measurement control */
#define BMP180_OUT_MSB  0xF6u   /* raw result, high byte */
#define BMP180_OUT_LSB  0xF7u   /* raw result, low byte  */
#define BMP180_CMD_TEMP 0x2Eu   /* start a temperature conversion */

/* Datasheet: max temperature conversion time is 4.5 ms. Wait 5 ms.
 * The platform models SysTick at 72 MHz (`nvic systickFrequency` in the
 * shipped platforms/cpus/stm32f4.repl), so 5 ms = 360000 ticks -- inside the
 * 24-bit reload register. */
#define CONV_TICKS  360000u

#define GUARD       200000u
/* Ceiling on the SysTick poll. Sized well above the instruction count the
 * emulated core needs to cover 5 ms, so it only trips if SysTick is not
 * counting at all -- a condition the firmware REPORTS rather than hides. */
#define WAIT_GUARD  8000000u

extern uint32_t _estack;
extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss;

void Reset_Handler(void);
static void Default_Handler(void) { for (;;) { } }

__attribute__((section(".isr_vector"), used))
void (*const g_vectors[])(void) = {
    (void (*)(void))(&_estack),
    Reset_Handler,
    Default_Handler,
    Default_Handler,
};

static void uart_putc(char c)
{
    uint32_t g = GUARD;
    while (!(USART_SR & SR_TXE) && g) { g--; }
    USART_DR = (uint32_t)(uint8_t)c;
}

static void uart_puts(const char *s) { while (*s) { uart_putc(*s++); } }

static void uart_hex8(uint8_t v)
{
    static const char hx[] = "0123456789ABCDEF";
    uart_putc('0'); uart_putc('x');
    uart_putc(hx[(v >> 4) & 0xF]); uart_putc(hx[v & 0xF]);
}

/* Unsigned decimal. Fixed-size stack buffer -- no allocation anywhere. */
static void uart_u32(uint32_t v)
{
    char buf[10];
    int i = 0;
    if (v == 0u) { uart_putc('0'); return; }
    while (v && i < (int)sizeof(buf)) { buf[i++] = (char)('0' + (v % 10u)); v /= 10u; }
    while (i) { uart_putc(buf[--i]); }
}

/* returns 1 on success, 0 on timeout */
static int wait_flag(volatile uint32_t *reg, uint32_t mask)
{
    uint32_t g = GUARD;
    while (!(*reg & mask)) {
        if (--g == 0u) { return 0; }
    }
    return 1;
}

/* Bounded busy-wait on SysTick. Returns 1 if the interval actually elapsed on
 * the timer, 0 if the guard expired first. The caller must not silently treat
 * a guard expiry as a completed wait. */
static int delay_ticks(uint32_t ticks)
{
    uint32_t g = WAIT_GUARD;

    SYST_CSR = 0u;                       /* stop before reprogramming */
    SYST_RVR = ticks - 1u;
    SYST_CVR = 0u;                       /* writing any value clears COUNTFLAG */
    SYST_CSR = SYST_ENABLE | SYST_CLKSOURCE;

    while (!(SYST_CSR & SYST_COUNTFLAG)) {
        if (--g == 0u) { SYST_CSR = 0u; return 0; }
    }
    SYST_CSR = 0u;
    return 1;
}

/* Read one byte from `reg` of the 7-bit device `addr`. Returns 1 on success. */
static int i2c_read_reg(uint8_t addr, uint8_t reg, uint8_t *out)
{
    volatile uint32_t dummy;

    I2C_CR1 |= CR1_START;
    if (!wait_flag(&I2C_SR1, SR1_SB)) { uart_puts("ERR:SB1\r\n"); return 0; }

    I2C_DR = (uint32_t)(addr << 1);                 /* write */
    if (!wait_flag(&I2C_SR1, SR1_ADDR)) { uart_puts("ERR:ADDR-W\r\n"); return 0; }
    dummy = I2C_SR1; dummy = I2C_SR2; (void)dummy;  /* clear ADDR */

    if (!wait_flag(&I2C_SR1, SR1_TXE)) { uart_puts("ERR:TXE\r\n"); return 0; }
    I2C_DR = (uint32_t)reg;
    if (!wait_flag(&I2C_SR1, SR1_TXE)) { uart_puts("ERR:TXE2\r\n"); return 0; }

    I2C_CR1 |= CR1_START;                           /* repeated START */
    if (!wait_flag(&I2C_SR1, SR1_SB)) { uart_puts("ERR:SB2\r\n"); return 0; }

    I2C_CR1 &= ~CR1_ACK;                            /* NACK the single byte */
    I2C_DR = (uint32_t)((addr << 1) | 1u);          /* read */
    if (!wait_flag(&I2C_SR1, SR1_ADDR)) { uart_puts("ERR:ADDR-R\r\n"); return 0; }
    dummy = I2C_SR1; dummy = I2C_SR2; (void)dummy;

    I2C_CR1 |= CR1_STOP;
    if (!wait_flag(&I2C_SR1, SR1_RXNE)) { uart_puts("ERR:RXNE\r\n"); return 0; }
    *out = (uint8_t)(I2C_DR & 0xFFu);

    I2C_CR1 |= CR1_ACK;
    return 1;
}

/* Write one byte to `reg` of the 7-bit device `addr`. Returns 1 on success. */
static int i2c_write_reg(uint8_t addr, uint8_t reg, uint8_t val)
{
    volatile uint32_t dummy;

    I2C_CR1 |= CR1_START;
    if (!wait_flag(&I2C_SR1, SR1_SB)) { uart_puts("ERR:W-SB\r\n"); return 0; }

    I2C_DR = (uint32_t)(addr << 1);                 /* write */
    if (!wait_flag(&I2C_SR1, SR1_ADDR)) { uart_puts("ERR:W-ADDR\r\n"); return 0; }
    dummy = I2C_SR1; dummy = I2C_SR2; (void)dummy;  /* clear ADDR */

    if (!wait_flag(&I2C_SR1, SR1_TXE)) { uart_puts("ERR:W-TXE\r\n"); return 0; }
    I2C_DR = (uint32_t)reg;
    if (!wait_flag(&I2C_SR1, SR1_TXE)) { uart_puts("ERR:W-TXE2\r\n"); return 0; }

    I2C_DR = (uint32_t)val;
    if (!wait_flag(&I2C_SR1, SR1_BTF)) { uart_puts("ERR:W-BTF\r\n"); return 0; }

    I2C_CR1 |= CR1_STOP;
    return 1;
}

void Reset_Handler(void)
{
    uint32_t *src, *dst;
    uint8_t id = 0, msb = 0, lsb = 0;

    for (src = &_sidata, dst = &_sdata; dst < &_edata; ) { *dst++ = *src++; }
    for (dst = &_sbss; dst < &_ebss; ) { *dst++ = 0u; }

    RCC_AHB1ENR |= (1u << 0) | (1u << 1);
    RCC_APB1ENR |= (1u << 17) | (1u << 21);   /* USART2, I2C1 */

    USART_BRR = 0x0683u;
    USART_CR1 = UCR1_UE | UCR1_TE;
    uart_puts("EP-EMU-BOOT\r\n");

    I2C_CR2   = 42u;        /* APB1 = 42 MHz */
    I2C_CCR   = 210u;       /* 100 kHz standard mode */
    I2C_TRISE = 43u;
    I2C_CR1   = CR1_PE | CR1_ACK;

    /* 1. identify the part -- a constant, and therefore NOT the proof */
    if (i2c_read_reg(BMP180_ADDR, BMP180_ID_REG, &id)) {
        uart_puts("BMP180-ID=");
        uart_hex8(id);
        uart_puts("\r\n");
    } else {
        uart_puts("BMP180-READ-FAILED\r\n");
        goto done;
    }

    /* 2. start a temperature conversion */
    if (!i2c_write_reg(BMP180_ADDR, BMP180_CTRL_REG, BMP180_CMD_TEMP)) {
        uart_puts("BMP180-START-FAILED\r\n");
        goto done;
    }

    /* 3. wait it out -- and say so if the wait did not really happen */
    if (delay_ticks(CONV_TICKS)) {
        uart_puts("BMP180-WAIT=OK\r\n");
    } else {
        uart_puts("BMP180-WAIT=GUARD\r\n");
    }

    /* 4. read the uncompensated value, MSB then LSB. Two addressed single-byte
     * reads rather than one auto-incrementing burst: the register pointer is
     * set explicitly each time, so nothing depends on the mock's auto-increment
     * behaviour. */
    if (!i2c_read_reg(BMP180_ADDR, BMP180_OUT_MSB, &msb) ||
        !i2c_read_reg(BMP180_ADDR, BMP180_OUT_LSB, &lsb)) {
        uart_puts("BMP180-UT-FAILED\r\n");
        goto done;
    }

    uart_puts("BMP180-UT=");
    uart_u32(((uint32_t)msb << 8) | (uint32_t)lsb);   /* RAW. Not compensated. */
    uart_puts("\r\n");

    /* the bytes too, so a mismatch can be debugged without a rebuild */
    uart_puts("BMP180-UT-BYTES=");
    uart_hex8(msb); uart_putc(','); uart_hex8(lsb);
    uart_puts("\r\n");

done:
    uart_puts("EP-EMU-DONE\r\n");
    for (;;) { __asm__ volatile("wfi"); }
}
