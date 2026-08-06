/* EmbeddPilot compile-judge STUB — not the real ESP-IDF driver/i2c.h.
 * Declarations only; enough for generated I2C driver examples to compile
 * clean under -Wall -Wextra -Werror. See esp_err.h for the rationale. */
#ifndef EMBEDDPILOT_STUB_DRIVER_I2C_H
#define EMBEDDPILOT_STUB_DRIVER_I2C_H

#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

typedef int i2c_port_t;
typedef int gpio_num_t;

typedef enum { I2C_MODE_SLAVE = 0, I2C_MODE_MASTER = 1 } i2c_mode_t;
typedef enum { I2C_MASTER_READ = 1, I2C_MASTER_WRITE = 0 } i2c_rw_t;

#define I2C_NUM_0 0
#define I2C_NUM_1 1

typedef struct {
    uint32_t clk_speed;
} i2c_master_clk_cfg_t;

typedef struct {
    i2c_mode_t mode;
    int sda_io_num;
    int scl_io_num;
    int sda_pullup_en;
    int scl_pullup_en;
    union { i2c_master_clk_cfg_t master; } m;
    uint32_t clk_flags;
} i2c_config_t;

esp_err_t i2c_param_config(i2c_port_t i2c_num, const i2c_config_t *i2c_conf);
esp_err_t i2c_driver_install(i2c_port_t i2c_num, i2c_mode_t mode,
                             size_t slv_rx_buf_len, size_t slv_tx_buf_len,
                             int intr_alloc_flags);
esp_err_t i2c_driver_delete(i2c_port_t i2c_num);
esp_err_t i2c_master_write_to_device(i2c_port_t i2c_num, uint8_t address,
                                     const uint8_t *write_buffer, size_t write_size,
                                     int ticks_to_wait);
esp_err_t i2c_master_read_from_device(i2c_port_t i2c_num, uint8_t address,
                                      uint8_t *read_buffer, size_t read_size,
                                      int ticks_to_wait);
esp_err_t i2c_master_write_read_device(i2c_port_t i2c_num, uint8_t address,
                                       const uint8_t *write_buffer, size_t write_size,
                                       uint8_t *read_buffer, size_t read_size,
                                       int ticks_to_wait);

#endif
