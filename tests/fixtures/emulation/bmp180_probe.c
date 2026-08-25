/* Hand-written bare-metal STM32F4: read BMP180 chip-ID over I2C1, report on USART2.
 * RM0090 offsets only. Every wait is bounded -- nothing may spin forever.
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

#define BMP180_ADDR 0x77u
#define BMP180_ID_REG 0xD0u

#define GUARD 200000u

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

/* returns 1 on success, 0 on timeout */
static int wait_flag(volatile uint32_t *reg, uint32_t mask)
{
    uint32_t g = GUARD;
    while (!(*reg & mask)) {
        if (--g == 0u) { return 0; }
    }
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

void Reset_Handler(void)
{
    uint32_t *src, *dst;
    uint8_t id = 0;

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

    if (i2c_read_reg(BMP180_ADDR, BMP180_ID_REG, &id)) {
        uart_puts("BMP180-ID=");
        uart_hex8(id);
        uart_puts("\r\n");
    } else {
        uart_puts("BMP180-READ-FAILED\r\n");
    }

    uart_puts("EP-EMU-DONE\r\n");
    for (;;) { __asm__ volatile("wfi"); }
}
