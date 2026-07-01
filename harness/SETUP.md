# Wokwi Simulation Setup

## Get a Wokwi API Token

1. Go to https://wokwi.com/dashboard/ci
2. Sign in (GitHub OAuth)
3. Create a new CI token (free tier: limited sim minutes/month)
4. Set the token as an environment variable:

### Windows (PowerShell)
```powershell
$env:WOKWI_CLI_TOKEN = "your-token-here"
```

### Persist across sessions (PowerShell profile)
```powershell
[System.Environment]::SetEnvironmentVariable("WOKWI_CLI_TOKEN", "your-token-here", "User")
```

### Linux/macOS
```bash
export WOKWI_CLI_TOKEN="your-token-here"
```

## Run the Reference Driver

```bash
# Compile
cd harness
pio run

# Run in Wokwi (token must be set)
wokwi-cli --timeout 15000 --expect-text "HARNESS_COMPLETE"
```

## Run the Verification Script

```bash
# Test reference driver (should PASS)
python scripts/run_harness.py

# Test broken driver (should FAIL)
python scripts/run_harness.py --broken

# Test a custom/generated driver
python scripts/run_harness.py --driver path/to/driver.cpp
```

## Expected Serial Output (Reference Driver)

```
=== EmbeddPilot V1 Verification Harness ===
Target: ESP32 I2C0 + BMP280
---
[PASS] test_i2c_init
[PASS] test_chip_id
  chip_id=0x58
[PASS] test_write_read_config
  ctrl_meas=0x27
[PASS] test_burst_read
  raw_press=..., raw_temp=...
[PASS] test_soft_reset
  post-reset ctrl_meas=0x00 (sleep mode)
---
HARNESS_COMPLETE
```
