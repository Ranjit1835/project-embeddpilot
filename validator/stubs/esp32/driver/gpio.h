/* EmbeddPilot compile-judge STUB — not the real ESP-IDF driver/gpio.h.
 * Declarations only; see esp_err.h for the rationale. */
#ifndef EMBEDDPILOT_STUB_DRIVER_GPIO_H
#define EMBEDDPILOT_STUB_DRIVER_GPIO_H

#include "esp_err.h"

typedef int gpio_num_t;
typedef enum { GPIO_MODE_INPUT = 1, GPIO_MODE_OUTPUT = 2 } gpio_mode_t;

esp_err_t gpio_set_direction(gpio_num_t gpio_num, gpio_mode_t mode);
esp_err_t gpio_set_level(gpio_num_t gpio_num, uint32_t level);
int gpio_get_level(gpio_num_t gpio_num);

#endif
