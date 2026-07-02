# EmbeddPilot V1.1 — Failure Report

**Timestamp:** 2026-07-02T09:16:41.385167+00:00

## Failed Tests

- **test_i2c_init** (exercises: `bmp180_init()`)
  - Assertion: `[FAIL] test_i2c_init`

- **test_chip_id** (exercises: `bmp180_chip_id()`)
  - Assertion: `[FAIL] test_chip_id`

- **test_soft_reset** (exercises: `bmp180_soft_reset()`)
  - Assertion: `[FAIL] test_soft_reset`

## Raw Serial Output (last 2000 chars)

```
Wokwi CLI v0.26.1 (9d71b975b7eb)
Connected to Wokwi Simulation API 1.0.0-20260628-gda8378d0
Starting simulation...
ets Jul 29 2019 12:21:46

rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)
configsip: 0, SPIWP:0xee
clk_drv:0x00,q_drv:0x00,d_drv:0x00,cs0_drv:0x00,hd_drv:0x00,wp_drv:0x00
mode:DIO, clock div:2
load:0x3fff0030,len:1156
load:0x40078000,len:11456
ho 0 tail 12 room 4
load:0x40080400,len:2972
entry 0x400805dc
=== EmbeddPilot V1.1 Verification Harness ===
Target: ESP32 I2C0 + BMP180
---
[FAIL] test_i2c_init
  chip_id=0x0
[FAIL] test_chip_id
  ctrl_meas=0x20
[PASS] test_write_read_config
  raw_temp=29028
[PASS] test_burst_read
  soft_reset failed
[FAIL] test_soft_reset
---
HARNESS_COMPLETE


Expected text found: "HARNESS_COMPLETE"
TEST PASSED.

```