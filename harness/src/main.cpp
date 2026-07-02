/*
 * EmbeddPilot V1.1 — Independent Verification Harness
 *
 * This file is the PERMANENT test harness. It is NEVER overwritten by
 * the pipeline. All expected values and test logic live here.
 * The generated driver library (bmp180_driver.h/.cpp) is tested
 * through its public API only.
 *
 * Target: ESP32-WROOM-32, I2C0, BMP180 sensor at address 0x77
 * Framework: Arduino (Wire library)
 */

#include <Arduino.h>
#include <Wire.h>
#include "bmp180_driver.h"

/* --- Harness-Owned Expected Values --- */
static const uint8_t EXPECTED_CHIP_ID = 0x55;
static const int SDA_PIN              = 21;
static const int SCL_PIN              = 22;
static const uint32_t I2C_FREQ        = 100000;

/* --- Test Infrastructure --- */
static int total_passed = 0;
static int total_failed = 0;

static void report(const char *test_name, bool passed) {
    if (passed) {
        Serial.print("[PASS] ");
        total_passed++;
    } else {
        Serial.print("[FAIL] ");
        total_failed++;
    }
    Serial.println(test_name);
}

/* --- Test Scenarios --- */

static bool test_i2c_init() {
    bmp180_status_t status = bmp180_init(Wire, SDA_PIN, SCL_PIN, I2C_FREQ);
    return status == BMP180_OK;
}

static bool test_chip_id() {
    uint8_t id = bmp180_chip_id();
    Serial.print("  chip_id=0x");
    Serial.println(id, HEX);
    return id == EXPECTED_CHIP_ID;
}

static bool test_write_read_config() {
    bmp180_status_t ws = bmp180_write_register(0xF4, 0x2E);
    if (ws != BMP180_OK) {
        Serial.println("  write failed");
        return false;
    }
    delay(5);
    uint8_t readback;
    bmp180_status_t rs = bmp180_read_register(0xF4, &readback);
    if (rs != BMP180_OK || readback == 0xFF) {
        Serial.println("  readback failed");
        return false;
    }
    Serial.print("  ctrl_meas=0x");
    Serial.println(readback, HEX);
    return true;
}

static bool test_burst_read() {
    int32_t raw_temp;
    bmp180_status_t status = bmp180_read_raw_temperature(&raw_temp);
    if (status != BMP180_OK) {
        Serial.println("  read_raw_temperature failed");
        return false;
    }
    Serial.print("  raw_temp=");
    Serial.println(raw_temp);
    return raw_temp > 0;
}

static bool test_soft_reset() {
    bmp180_status_t status = bmp180_soft_reset();
    if (status != BMP180_OK) {
        Serial.println("  soft_reset failed");
        return false;
    }
    uint8_t id = bmp180_chip_id();
    if (id == EXPECTED_CHIP_ID) {
        Serial.println("  post-reset chip_id OK");
        return true;
    }
    Serial.print("  post-reset chip_id=0x");
    Serial.println(id, HEX);
    return false;
}

/* --- Entry Point --- */

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("=== EmbeddPilot V1.1 Verification Harness ===");
    Serial.println("Target: ESP32 I2C0 + BMP180");
    Serial.println("---");

    report("test_i2c_init", test_i2c_init());
    report("test_chip_id", test_chip_id());
    report("test_write_read_config", test_write_read_config());
    report("test_burst_read", test_burst_read());
    report("test_soft_reset", test_soft_reset());

    Serial.println("---");
    Serial.println("HARNESS_COMPLETE");
}

void loop() {
}
