/* EmbeddPilot compile-judge STUB — not the real CMSIS stm32f4xx.h.
 * Provides just enough of the STM32F4 peripheral surface (RCC, GPIO, I2C
 * register structs + base pointers) for generated bring-up code to compile
 * clean under -Wall -Wextra -Werror with arm-none-eabi-gcc. The judge only
 * COMPILES (-c), never links, so real base addresses are irrelevant here —
 * on real hardware this code builds against the vendor CMSIS header instead.
 * The BIT POSITIONS the driver uses are NOT defined here on purpose: the worker
 * defines them from the MCU map and mcu_crosscheck verifies them. */
#ifndef EMBEDDPILOT_STUB_STM32F4XX_H
#define EMBEDDPILOT_STUB_STM32F4XX_H

#include <stdint.h>

typedef struct {
    volatile uint32_t CR;
    volatile uint32_t PLLCFGR;
    volatile uint32_t CFGR;
    volatile uint32_t CIR;
    volatile uint32_t AHB1RSTR;
    volatile uint32_t AHB2RSTR;
    volatile uint32_t AHB3RSTR;
    uint32_t RESERVED0;
    volatile uint32_t APB1RSTR;
    volatile uint32_t APB2RSTR;
    uint32_t RESERVED1[2];
    volatile uint32_t AHB1ENR;
    volatile uint32_t AHB2ENR;
    volatile uint32_t AHB3ENR;
    uint32_t RESERVED2;
    volatile uint32_t APB1ENR;
    volatile uint32_t APB2ENR;
} RCC_TypeDef;

typedef struct {
    volatile uint32_t MODER;
    volatile uint32_t OTYPER;
    volatile uint32_t OSPEEDR;
    volatile uint32_t PUPDR;
    volatile uint32_t IDR;
    volatile uint32_t ODR;
    volatile uint32_t BSRR;
    volatile uint32_t LCKR;
    volatile uint32_t AFR[2];
} GPIO_TypeDef;

typedef struct {
    volatile uint32_t CR1;
    volatile uint32_t CR2;
    volatile uint32_t OAR1;
    volatile uint32_t OAR2;
    volatile uint32_t DR;
    volatile uint32_t SR1;
    volatile uint32_t SR2;
    volatile uint32_t CCR;
    volatile uint32_t TRISE;
    volatile uint32_t FLTR;
} I2C_TypeDef;

#define RCC   ((RCC_TypeDef *)  0x40023800UL)
#define GPIOA ((GPIO_TypeDef *) 0x40020000UL)
#define GPIOB ((GPIO_TypeDef *) 0x40020400UL)
#define GPIOC ((GPIO_TypeDef *) 0x40020800UL)
#define GPIOD ((GPIO_TypeDef *) 0x40020C00UL)
#define GPIOE ((GPIO_TypeDef *) 0x40021000UL)
#define GPIOF ((GPIO_TypeDef *) 0x40021400UL)
#define GPIOG ((GPIO_TypeDef *) 0x40021800UL)
#define GPIOH ((GPIO_TypeDef *) 0x40021C00UL)
#define GPIOI ((GPIO_TypeDef *) 0x40022000UL)
#define I2C1  ((I2C_TypeDef *)  0x40005400UL)
#define I2C2  ((I2C_TypeDef *)  0x40005800UL)
#define I2C3  ((I2C_TypeDef *)  0x40005C00UL)

#endif
