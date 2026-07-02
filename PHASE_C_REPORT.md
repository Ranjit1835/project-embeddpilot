# PHASE C — INDEPENDENT JUDGE + LIBRARY FORM FACTOR Report

> EmbeddPilot V1.1 — The generator is never the judge. Now proven by architecture.

**Date:** 2026-07-02
**Verdict:** PASS (all 3 proof runs successful)

---

## STEP 0 — API CONTRACT

Created `contracts/DRIVER_API.md` defining the exact C API boundary:

```c
typedef enum { BMP180_OK = 0, BMP180_ERR_I2C, BMP180_ERR_BAD_CHIP_ID } bmp180_status_t;

bmp180_status_t bmp180_init(TwoWire &wire, int sda_pin, int scl_pin, uint32_t freq);
uint8_t         bmp180_chip_id(void);
bmp180_status_t bmp180_soft_reset(void);
bmp180_status_t bmp180_read_raw_temperature(int32_t *raw_temp);
bmp180_status_t bmp180_read_register(uint8_t reg, uint8_t *value);
bmp180_status_t bmp180_write_register(uint8_t reg, uint8_t value);
```

**Hard rules in contract:** no Serial prints, no setup()/loop(), no test logic, no PASS/FAIL strings, no expected-value assertions. Both the generator and harness implement against this contract. Compilation is the contract check.

---

## LANE 1 — LIBRARY TEMPLATE

**File changed:** `codegen/driver_gen.py`

| Before (V1) | After (V1.1) |
|-------------|-------------|
| Returns single `str` (driver.cpp monolith) | Returns `dict` with `"header"` and `"source"` keys |
| Embedded test functions (test_i2c_init, etc.) | Zero test functions — pure driver library |
| `Serial.print` throughout | Zero Serial usage |
| `setup()` + `loop()` entry points | No entry points — library API only |
| `[PASS]`/`[FAIL]` strings | None |
| Expected values (EXPECTED_CHIP_ID) | Status codes only — harness decides correctness |

**Generated files:**
- `bmp180_driver.h` (36 lines) — status enum + 6 function prototypes
- `bmp180_driver.cpp` (136 lines) — implementation using Wire library, static module state

---

## LANE 2 — HARNESS OWNS THE JUDGE

**File changed:** `harness/src/main.cpp`

This file is now **permanent** — never overwritten by the pipeline.

**Harness-owned expected values:**
```c
static const uint8_t EXPECTED_CHIP_ID = 0x55;  // harness decides what "correct" means
static const int SDA_PIN = 21;
static const int SCL_PIN = 22;
static const uint32_t I2C_FREQ = 100000;
```

**5 test scenarios — all call only the contract API:**

| Scenario | API Called | PASS Condition (harness-owned) |
|----------|-----------|-------------------------------|
| test_i2c_init | `bmp180_init()` | Returns BMP180_OK |
| test_chip_id | `bmp180_chip_id()` | Returns 0x55 (harness constant) |
| test_write_read_config | `bmp180_write_register()` + `bmp180_read_register()` | Write succeeds, readback != 0xFF |
| test_burst_read | `bmp180_read_raw_temperature()` | Returns BMP180_OK, value > 0 |
| test_soft_reset | `bmp180_soft_reset()` + `bmp180_chip_id()` | Returns BMP180_OK, chip_id == 0x55 |

---

## LANE 3 — PIPELINE INTEGRATION + GUARD + PACKAGING

**Files changed:** `embeddpilot.py`, `scripts/generate_driver.py`

### New pipeline flow (6 steps)

```
1. Validate IR
2. Generate library (bmp180_driver.h + .cpp + i2c0_regs.h)
3. Contamination guard (scan for forbidden tokens)
4. Install library → Compile via PlatformIO
5. Simulate via Wokwi
6. Uninstall library → Package output
```

### Key changes

| Change | Detail |
|--------|--------|
| **Library install/uninstall** | `install_library()` copies .h/.cpp to `harness/lib/bmp180/`; `uninstall_library()` removes it. `harness/src/main.cpp` is NEVER touched. |
| **Contamination guard** | Scans both generated files for `[PASS]`, `[FAIL]`, `Serial.`, `setup(`, `loop(`, `HARNESS_COMPLETE`. Any hit → `GENERATION_CONTAMINATED` with file:line. |
| **Packaging** | Output: `bmp180_driver.h`, `bmp180_driver.cpp`, `i2c0_regs.h`, `pipeline_report.json`, `proof.txt`, `INTEGRATION.md` |
| **proof.txt** | New line: "Tests are harness-owned and independent of generation (contamination guard active)." |
| **failure_report.md** | Now maps failed scenario → exercised API function |
| **generate_driver.py** | Handles new dict return; writes `bmp180_driver.h` + `bmp180_driver.cpp` instead of `driver.cpp` |

---

## VERIFICATION RESULTS

### Run 1 — Full Pipeline (correct library)

```
VERDICT: PASS
Timestamp: 2026-07-02T07:39:55.279756+00:00
Steps:
  validate_ir: PASS
  generate: PASS
  contamination_guard: PASS
  compile: PASS
  simulate: 5 passed, 0 failed
    [PASS] test_i2c_init
    [PASS] test_chip_id     (chip_id=0x55)
    [PASS] test_write_read_config  (ctrl_meas=0x20)
    [PASS] test_burst_read  (raw_temp=29028)
    [PASS] test_soft_reset  (post-reset chip_id OK)
FINAL VERDICT: PASS
```

### Run 2 — Guard Proof (Serial.print injected into template)

```
VERDICT: GENERATION_CONTAMINATED
Injected: static void debug_log() { Serial.println("DEBUG"); }
Guard output:
  bmp180_driver.cpp:35 — found 'Serial.': static void debug_log() { Serial.println("DEBUG"); }
Pipeline halted at step 3/6. Compile and simulate never ran.
Reverted. Re-run → PASS.
```

### Run 3 — Judge Proof (broken library: REG_CHIP_ID 0xD0 → 0xD1)

```
Manually installed broken bmp180_driver.cpp into harness/lib/bmp180/
Compiled: SUCCESS
Simulation output:
  [FAIL] test_i2c_init       (bmp180_init returns BAD_CHIP_ID — library reads wrong register)
    chip_id=0x0
  [FAIL] test_chip_id        (harness expects 0x55, library stored 0x0)
    ctrl_meas=0x20
  [PASS] test_write_read_config
    raw_temp=29028
  [PASS] test_burst_read
    soft_reset failed
  [FAIL] test_soft_reset     (library reads wrong register post-reset)

Result: 2 PASS, 3 FAIL — harness independently detected the broken library.
The harness NEVER saw the broken constant (0xD1) — it only saw the library's
behavior through the API. The expected value 0x55 lives in main.cpp, not in
the library. This is what "generator is never the judge" looks like.
Restored. Re-run → PASS.
```

---

## DELIVERABLE TREE

```
build/output/
├── bmp180_driver.h        # Public API (status enum + prototypes)
├── bmp180_driver.cpp      # Implementation (Wire I2C, no Serial, no tests)
├── i2c0_regs.h            # ESP32 I2C0 register definitions from IR
├── pipeline_report.json   # Machine-readable verification report
├── proof.txt              # Human-readable proof with independence attestation
└── INTEGRATION.md         # 4-step integration guide for PlatformIO projects
```

---

## DOC UPDATES

| File | Change |
|------|--------|
| `CLAUDE.md` | "generator is never the judge" → **RESTORED (Phase C)**, guard active. Added library file conventions and contract reference. |
| `DONE.md` | Known gap (a) [generator-embedded tests] → **checked off**. Gap (b) [IR not driving code] remains for Phase D. |
| `contracts/DRIVER_API.md` | NEW — the exact C API contract both sides implement against. |

---

## ARCHITECTURAL PROOF SUMMARY

| Finding from Phase A | Status after Phase C |
|---------------------|---------------------|
| Finding 2: Generator judges itself | **FIXED.** Library has zero test logic. Harness owns all assertions. Contamination guard prevents regression. Proven by broken-library judge test. |
| Finding 4: IR is decorative | **Unchanged.** Scheduled for Phase D. |
