# V1 Target Lock

## MCU Family
**ESP32** (Xtensa LX6 dual-core, ESP-IDF framework)

## Specific Part
**ESP32-WROOM-32** (most common module, widest Wokwi support)

## Peripheral
**I2C** (Inter-Integrated Circuit controller)
- ESP32 has two I2C controllers: I2C0 and I2C1
- V1 targets **I2C0** (the default, most commonly used)
- Covers: master mode init, slave address configuration, read/write transactions, FIFO management, error handling (NACK, timeout, arbitration loss)

## Simulated Sensor
**BMP180** (temperature/pressure sensor, I2C address 0x77, chip ID 0x55)
- Supported in Wokwi as `board-bmp180`
- Simple register interface for read verification
- Industry-standard I2C peripheral for testing

## Simulator
**Wokwi** (wokwi-cli for headless CI)
- diagram.json defines ESP32 + BMP180 wiring
- `$serialMonitor` connections required for serial capture
- Serial assertions for pass/fail (--expect-text / --fail-text)
- GitHub Actions integration via wokwi-ci-action

## Datasheet Source
- ESP32 Technical Reference Manual (esp32_technical_reference_manual_en.pdf)
- Chapter 11: I2C Controller
- Bosch BMP180 datasheet for sensor-side register map

## What V1 does NOT cover
- I2C slave mode
- Multi-master arbitration
- DMA-based I2C transfers
- Any peripheral other than I2C
- Any MCU other than ESP32
- Cross-family porting (that's V2)
