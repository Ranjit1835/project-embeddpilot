# Verification Harness — Limitations & Blind Spots

## What the harness DOES verify
- I2C bus initialization succeeds
- Correct slave address targeting (0x77 for BMP180)
- Single-register read (chip ID = 0x55)
- Single-register write + read-back (ctrl_meas configuration)
- Burst read of 3 bytes (temperature raw data)
- Soft reset and post-reset state verification

## What the harness does NOT verify
- **Timing-precise behavior**: Wokwi simulates functional I2C, not cycle-accurate timing. SCL frequency, hold times, setup times are NOT validated against the ESP32 TRM timing registers.
- **Hard real-time constraints**: ISR latency, RTOS task priorities, and DMA transfers are not tested.
- **Electrical characteristics**: Pull-up resistor behavior, bus capacitance, signal integrity are not modeled.
- **Multi-master arbitration**: Only single-master mode is tested.
- **Error injection**: Bus contention, NACK storms, clock stretching edge cases are not covered in V1.
- **Power management**: Sleep/wake behavior of the I2C peripheral is not tested.

## Simulation ≠ Hardware
A PASS in this harness means the driver's LOGIC is correct — it reads/writes the right registers with the right values in the right sequence. It does NOT guarantee the driver will work on physical hardware without timing adjustments.

Do not over-trust a green sim run. Always validate on real hardware before production use.
