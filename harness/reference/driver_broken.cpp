/*
 * DELIBERATELY CORRUPTED reference driver.
 * Used to verify the harness catches broken firmware.
 *
 * Corruptions:
 * 1. Wrong sensor address (0x76 instead of 0x77)
 * 2. Wrong chip ID expectation (0x60 instead of 0x55)
 * 3. Swapped SDA/SCL pins (22/21 instead of 21/22)
 */

#include <Arduino.h>
#include <Wire.h>

static const uint8_t SENSOR_ADDR      = 0x76;  // BUG: wrong address
static const uint8_t REG_CHIP_ID      = 0xD0;
static const uint8_t REG_RESET        = 0xE0;
static const uint8_t REG_CTRL_MEAS    = 0xF4;
static const uint8_t REG_DATA_START   = 0xF6;
static const uint8_t EXPECTED_CHIP_ID = 0x60;  // BUG: wrong expected ID
static const uint8_t RESET_CMD        = 0xB6;
static const uint8_t TEMP_CMD         = 0x2E;
static const uint8_t DATA_BURST_LEN   = 3;

static const int SDA_PIN = 22;  // BUG: swapped with SCL
static const int SCL_PIN = 21;  // BUG: swapped with SDA
static const uint32_t I2C_FREQ = 100000;

enum TestResult { TEST_PASS, TEST_FAIL };

static void print_result(const char* test_name, TestResult result) {
    if (result == TEST_PASS) {
        Serial.print("[PASS] ");
    } else {
        Serial.print("[FAIL] ");
    }
    Serial.println(test_name);
}

static uint8_t read_register(uint8_t reg) {
    Wire.beginTransmission(SENSOR_ADDR);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) {
        Serial.println("[FAIL] I2C_WRITE_ERROR");
        return 0xFF;
    }
    Wire.requestFrom(SENSOR_ADDR, (uint8_t)1);
    if (Wire.available()) {
        return Wire.read();
    }
    return 0xFF;
}

static bool write_register(uint8_t reg, uint8_t value) {
    Wire.beginTransmission(SENSOR_ADDR);
    Wire.write(reg);
    Wire.write(value);
    return Wire.endTransmission() == 0;
}

static bool read_burst(uint8_t start_reg, uint8_t* buf, uint8_t len) {
    Wire.beginTransmission(SENSOR_ADDR);
    Wire.write(start_reg);
    if (Wire.endTransmission(false) != 0) {
        return false;
    }
    Wire.requestFrom(SENSOR_ADDR, len);
    for (uint8_t i = 0; i < len; i++) {
        if (!Wire.available()) return false;
        buf[i] = Wire.read();
    }
    return true;
}

static TestResult test_i2c_init() {
    Wire.begin(SDA_PIN, SCL_PIN, I2C_FREQ);
    return TEST_PASS;
}

static TestResult test_chip_id() {
    uint8_t id = read_register(REG_CHIP_ID);
    if (id == EXPECTED_CHIP_ID) {
        Serial.print("  chip_id=0x");
        Serial.println(id, HEX);
        return TEST_PASS;
    }
    Serial.print("  expected=0x55, got=0x");
    Serial.println(id, HEX);
    return TEST_FAIL;
}

static TestResult test_write_read_config() {
    if (!write_register(REG_CTRL_MEAS, TEMP_CMD)) {
        Serial.println("  write failed");
        return TEST_FAIL;
    }
    delay(5);
    uint8_t readback = read_register(REG_CTRL_MEAS);
    if (readback != 0xFF) {
        Serial.print("  ctrl_meas=0x");
        Serial.println(readback, HEX);
        return TEST_PASS;
    }
    Serial.println("  readback returned 0xFF");
    return TEST_FAIL;
}

static TestResult test_burst_read() {
    if (!write_register(REG_CTRL_MEAS, TEMP_CMD)) {
        Serial.println("  trigger measurement failed");
        return TEST_FAIL;
    }
    delay(5);
    uint8_t data[DATA_BURST_LEN];
    if (!read_burst(REG_DATA_START, data, DATA_BURST_LEN)) {
        Serial.println("  burst read failed");
        return TEST_FAIL;
    }
    int32_t raw_temp = ((int32_t)data[0] << 8) | (int32_t)data[1];
    Serial.print("  raw_temp=");
    Serial.println(raw_temp);
    return TEST_PASS;
}

static TestResult test_soft_reset() {
    if (!write_register(REG_RESET, RESET_CMD)) {
        Serial.println("  reset write failed");
        return TEST_FAIL;
    }
    delay(10);
    uint8_t id = read_register(REG_CHIP_ID);
    if (id == EXPECTED_CHIP_ID) {
        Serial.println("  post-reset chip_id OK");
        return TEST_PASS;
    }
    Serial.print("  post-reset chip_id=0x");
    Serial.println(id, HEX);
    return TEST_FAIL;
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("=== EmbeddPilot V1 Verification Harness ===");
    Serial.println("Target: ESP32 I2C0 + BMP180");
    Serial.println("---");

    print_result("test_i2c_init", test_i2c_init());
    print_result("test_chip_id", test_chip_id());
    print_result("test_write_read_config", test_write_read_config());
    print_result("test_burst_read", test_burst_read());
    print_result("test_soft_reset", test_soft_reset());

    Serial.println("---");
    Serial.println("HARNESS_COMPLETE");
}

void loop() {}
