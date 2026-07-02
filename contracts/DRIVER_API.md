# BMP180 Driver Library API Contract

> Both the generator (Lane 1) and the harness (Lane 2) implement against this contract VERBATIM.
> Compilation is the contract check — if either side deviates, the build fails.

## Files

The generator emits exactly two files into `drivers/generated/`:
- `bmp180_driver.h` — public API declarations
- `bmp180_driver.cpp` — implementation

## Status Enum

```c
typedef enum {
    BMP180_OK = 0,
    BMP180_ERR_I2C,
    BMP180_ERR_BAD_CHIP_ID
} bmp180_status_t;
```

## Public API

```c
bmp180_status_t bmp180_init(TwoWire &wire, int sda_pin, int scl_pin, uint32_t freq);
```
- Calls `wire.begin(sda_pin, scl_pin, freq)`.
- Reads chip ID register (0xD0). If the read fails, returns `BMP180_ERR_I2C`. If the value is not the BMP180 chip ID (0x55), returns `BMP180_ERR_BAD_CHIP_ID`.
- On success, stores the Wire reference internally and returns `BMP180_OK`.

```c
uint8_t bmp180_chip_id(void);
```
- Returns the chip ID value read during `bmp180_init()`.
- If `bmp180_init()` was never called or failed, returns `0xFF`.

```c
bmp180_status_t bmp180_soft_reset(void);
```
- Writes reset command `0xB6` to register `0xE0`.
- Waits 10ms for reset to complete.
- Reads chip ID to verify the sensor is alive post-reset.
- Returns `BMP180_OK` on success, `BMP180_ERR_I2C` on I2C failure, `BMP180_ERR_BAD_CHIP_ID` if chip ID is wrong after reset.

```c
bmp180_status_t bmp180_read_raw_temperature(int32_t *raw_temp);
```
- Writes measurement command `0x2E` to control register `0xF4`.
- Waits 5ms for conversion.
- Reads 3 bytes starting at data register `0xF6` (burst read).
- Writes `(data[0] << 8) | data[1]` into `*raw_temp`.
- Returns `BMP180_OK` on success, `BMP180_ERR_I2C` on any I2C failure.

```c
bmp180_status_t bmp180_read_register(uint8_t reg, uint8_t *value);
```
- Reads a single register at address `reg` into `*value`.
- Returns `BMP180_OK` on success, `BMP180_ERR_I2C` on failure.

```c
bmp180_status_t bmp180_write_register(uint8_t reg, uint8_t value);
```
- Writes `value` to register at address `reg`.
- Returns `BMP180_OK` on success, `BMP180_ERR_I2C` on failure.

## Sensor Constants (template-defined)

| Constant | Value | Description |
|----------|-------|-------------|
| I2C address | 0x77 | BMP180 default address |
| Chip ID register | 0xD0 | Register address for chip identification |
| Expected chip ID | 0x55 | BMP180 chip ID value |
| Reset register | 0xE0 | Soft reset register |
| Reset command | 0xB6 | Value to trigger soft reset |
| Control register | 0xF4 | Measurement control register |
| Temperature command | 0x2E | Start temperature measurement |
| Data start register | 0xF6 | First data output register |
| Data burst length | 3 | Bytes to read for raw temperature |

## Hard Rules

1. The library contains NO `Serial.print` / `Serial.println` / `Serial.write` calls.
2. The library contains NO `setup()` or `loop()` functions.
3. The library contains NO test logic, NO `[PASS]`/`[FAIL]` strings, NO `HARNESS_COMPLETE`.
4. The library contains NO expected-value assertions — it reports status codes; the harness decides what "correct" means.
5. All I2C communication uses the `TwoWire` reference passed to `bmp180_init()`.
