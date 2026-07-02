#!/usr/bin/env python3
"""
EmbeddPilot V1.1 — One-command pipeline.

Datasheet in -> Verified driver library + proof out.

Stages:
  1. Validate IR (schema + consistency)
  2. Generate driver library from IR (deterministic, single attempt)
  3. Contamination guard (verify library has no test logic)
  4. Compile via PlatformIO (single attempt)
  5. Simulate via Wokwi (unless --dry-run); one infrastructure retry allowed
  6. Package output: library, header, report, integration guide

Usage:
    python embeddpilot.py
    python embeddpilot.py --ir artifacts/controller-ir.json
    python embeddpilot.py --dry-run
    python embeddpilot.py --no-sim-retry --output-dir build/
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
DRIVERS_DIR = PROJECT_ROOT / "drivers" / "generated"
HARNESS_DIR = PROJECT_ROOT / "harness"
HARNESS_LIB_DIR = HARNESS_DIR / "lib" / "bmp180"
DEFAULT_CONTROLLER_IR = ARTIFACTS_DIR / "controller-ir.json"
DEFAULT_SENSOR_IR = ARTIFACTS_DIR / "sensor-ir.json"
CONTROLLER_SCHEMA = PROJECT_ROOT / "schema" / "register-ir.schema.json"
SENSOR_SCHEMA = PROJECT_ROOT / "schema" / "sensor-ir.schema.json"

TOTAL_STEPS = 7

SCENARIO_TO_FUNCTION = {
    "test_i2c_init": "bmp180_init()",
    "test_chip_id": "bmp180_chip_id()",
    "test_write_read_config": "bmp180_write_register() + bmp180_read_register()",
    "test_burst_read": "bmp180_read_raw_temperature()",
    "test_soft_reset": "bmp180_soft_reset()",
}


def banner(text: str):
    width = 60
    print(f"\n{'=' * width}")
    print(f"  {text}")
    print(f"{'=' * width}")


def step(n: int, total: int, text: str):
    print(f"\n  [{n}/{total}] {text}")


def run_ir_validation(ir_path: Path) -> bool:
    step(1, TOTAL_STEPS, "Validating controller IR against schema...")
    try:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_ir.py"), str(ir_path)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print("  Controller IR validation timed out")
        return False
    except FileNotFoundError:
        print("  ERROR: validate_ir.py not found")
        return False
    print(result.stdout[-2000:])
    if result.returncode != 0:
        print("  CONTROLLER IR VALIDATION FAILED")
        return False
    print("  Controller IR validation passed")
    return True


def run_sensor_ir_validation(sensor_ir_path: Path) -> bool:
    step(2, TOTAL_STEPS, "Validating sensor IR against schema...")
    try:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_ir.py"),
             str(sensor_ir_path), str(SENSOR_SCHEMA)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print("  Sensor IR validation timed out")
        return False
    except FileNotFoundError:
        print("  ERROR: validate_ir.py not found")
        return False
    print(result.stdout[-2000:])
    if result.returncode != 0:
        print("  SENSOR IR VALIDATION FAILED")
        return False
    print("  Sensor IR validation passed")
    return True


def run_generation(ir_path: Path, sensor_ir_path: Path) -> bool:
    step(3, TOTAL_STEPS, "Generating driver library from controller IR + sensor IR (deterministic template)...")
    try:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "generate_driver.py"),
             "--ir", str(ir_path), "--sensor-ir", str(sensor_ir_path)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        print("  Generation timed out")
        return False
    except FileNotFoundError:
        print("  ERROR: generate_driver.py not found")
        return False
    print(result.stdout[-2000:])
    if result.returncode != 0:
        print(f"  GENERATION FAILED: {result.stderr[-500:]}")
        return False
    print("  Driver library generation passed")
    return True


def run_contamination_guard() -> str:
    """Scan generated library files for forbidden tokens.
    Returns "PASS" or "GENERATION_CONTAMINATED".
    """
    step(4, TOTAL_STEPS, "Running contamination guard...")

    forbidden = ["[PASS]", "[FAIL]", "Serial.", "setup(", "loop(", "HARNESS_COMPLETE"]
    files_to_scan = [
        DRIVERS_DIR / "bmp180_driver.h",
        DRIVERS_DIR / "bmp180_driver.cpp",
    ]

    violations = []
    for fpath in files_to_scan:
        if not fpath.exists():
            print(f"  WARNING: {fpath.name} not found")
            continue
        lines = fpath.read_text(encoding="utf-8").splitlines()
        for line_num, line in enumerate(lines, 1):
            for token in forbidden:
                if token in line:
                    violations.append((fpath.name, line_num, token, line.strip()))

    if violations:
        print("  GENERATION_CONTAMINATED — library contains test/harness tokens:")
        for fname, lnum, token, text in violations:
            print(f"    {fname}:{lnum} — found '{token}': {text}")
        return "GENERATION_CONTAMINATED"

    print("  Contamination guard passed (no forbidden tokens in library)")
    return "PASS"


def install_library():
    """Copy generated library files into harness/lib/bmp180/ for PlatformIO build."""
    HARNESS_LIB_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DRIVERS_DIR / "bmp180_driver.h", HARNESS_LIB_DIR / "bmp180_driver.h")
    shutil.copy2(DRIVERS_DIR / "bmp180_driver.cpp", HARNESS_LIB_DIR / "bmp180_driver.cpp")


def uninstall_library():
    """Remove harness/lib/bmp180/ directory."""
    if HARNESS_LIB_DIR.exists():
        shutil.rmtree(HARNESS_LIB_DIR)


def run_compile() -> str:
    """Compile via PlatformIO. Returns verdict string."""
    step(5, TOTAL_STEPS, "Compiling driver via PlatformIO...")
    try:
        result = subprocess.run(
            ["pio", "run"],
            cwd=str(HARNESS_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            print(f"  COMPILE FAILED:\n{result.stderr[-1000:]}")
            return "COMPILE_FAILED"
        print("  Compilation passed")
        return "PASS"
    except subprocess.TimeoutExpired:
        print("  COMPILE TIMEOUT: PlatformIO build exceeded 300s")
        return "COMPILE_TIMEOUT"
    except FileNotFoundError:
        print("  PlatformIO CLI (pio) not found. Install: pip install platformio")
        return "PIO_NOT_FOUND"


def _resolve_wokwi_cli() -> str:
    env_path = os.environ.get("WOKWI_CLI_PATH")
    if env_path:
        return env_path
    found = shutil.which("wokwi-cli")
    if found:
        return found
    raise FileNotFoundError("wokwi-cli")


def _run_sim_once() -> dict:
    try:
        wokwi_cli = _resolve_wokwi_cli()
    except FileNotFoundError:
        return {
            "passed": 0, "failed": 0, "complete": False,
            "tests": [], "failures": [], "raw_output": "",
            "exit_code": -1, "is_infra_failure": True, "is_test_failure": False,
            "error": "wokwi-cli not found. Install: npx wokwi-cli or see https://docs.wokwi.com/wokwi-ci/getting-started",
        }

    cmd = [
        wokwi_cli,
        "--timeout", "15000",
        "--expect-text", "HARNESS_COMPLETE",
        "--fail-text", "I2C_WRITE_ERROR",
    ]

    try:
        result = subprocess.run(
            cmd, cwd=str(HARNESS_DIR),
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {
            "passed": 0, "failed": 0, "complete": False,
            "tests": [], "failures": [], "raw_output": "(simulation timed out after 60s)",
            "exit_code": -1, "is_infra_failure": True, "is_test_failure": False,
            "error": "SIM_TIMEOUT",
        }
    except FileNotFoundError:
        return {
            "passed": 0, "failed": 0, "complete": False,
            "tests": [], "failures": [], "raw_output": "",
            "exit_code": -1, "is_infra_failure": True, "is_test_failure": False,
            "error": "wokwi-cli not found. Install: npx wokwi-cli or see https://docs.wokwi.com/wokwi-ci/getting-started",
        }

    output = result.stdout + result.stderr
    tests = []
    passed = 0
    failed = 0
    complete = False
    failures = []

    for line in output.split("\n"):
        line = line.strip()
        match = re.match(r"\[(PASS|FAIL)\]\s+(.+)", line)
        if match:
            status = match.group(1)
            name = match.group(2)
            tests.append({"name": name, "status": status})
            if status == "PASS":
                passed += 1
            else:
                failed += 1
                failures.append({"test": name, "output": line})
        if "HARNESS_COMPLETE" in line:
            complete = True

    has_fail_lines = failed > 0
    is_infra = (result.returncode != 0 and not complete and not has_fail_lines)
    is_test_fail = has_fail_lines

    return {
        "passed": passed, "failed": failed, "complete": complete,
        "tests": tests, "failures": failures,
        "raw_output": output[-2000:],
        "exit_code": result.returncode,
        "is_infra_failure": is_infra, "is_test_failure": is_test_fail,
    }


def run_simulation(sim_retry: bool) -> dict:
    step(6, TOTAL_STEPS, "Running Wokwi simulation...")
    sim_result = _run_sim_once()
    if "error" in sim_result:
        print(f"  {sim_result['error']}")
    if sim_result["is_infra_failure"] and sim_retry:
        print("  Retrying simulation (infrastructure)...")
        sim_result = _run_sim_once()
        if "error" in sim_result:
            print(f"  {sim_result['error']}")
    return sim_result


def write_failure_report(sim_result: dict):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = ARTIFACTS_DIR / "failure_report.md"

    lines = [
        "# EmbeddPilot V1.1 — Failure Report",
        "",
        f"**Timestamp:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Failed Tests",
        "",
    ]

    for f in sim_result["failures"]:
        test_name = f["test"]
        api_fn = SCENARIO_TO_FUNCTION.get(test_name, "unknown")
        lines.append(f"- **{test_name}** (exercises: `{api_fn}`)")
        lines.append(f"  - Assertion: `{f['output']}`")
        lines.append("")

    lines.append("## Raw Serial Output (last 2000 chars)")
    lines.append("")
    lines.append("```")
    lines.append(sim_result.get("raw_output", "(no output)"))
    lines.append("```")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Failure report written: {report_path}")


def package_output(output_dir: Path, report: dict):
    step(7, TOTAL_STEPS, f"Packaging output to {output_dir}/...")
    output_dir.mkdir(parents=True, exist_ok=True)

    for fname in ("bmp180_driver.h", "bmp180_driver.cpp", "i2c0_regs.h"):
        src = DRIVERS_DIR / fname
        if src.exists():
            shutil.copy2(src, output_dir / fname)

    report_path = output_dir / "pipeline_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    sensor_info = report.get("sensor_ir", {})
    proof_lines = [
        "EmbeddPilot V1.1 — Verification Proof",
        f"Generated: {report['timestamp']}",
        f"Controller IR: {report.get('ir_path', 'unknown')}",
        f"Sensor IR: {report.get('sensor_ir_path', 'unknown')}",
        f"Verdict: {report['final_verdict']}",
        f"Driver generated from sensor IR: {sensor_info.get('name', '?')} @ {sensor_info.get('i2c_address', '?')}",
        f"  Extraction: {sensor_info.get('extraction_method', 'unknown')}",
        "Two-layer IR: controller (ESP32 I2C0) + sensor (BMP180). All constants IR-driven.",
        "Tests are harness-owned and independent of generation (contamination guard active).",
        "",
    ]
    for step_name, step_result in report["steps"].items():
        if isinstance(step_result, dict):
            proof_lines.append(f"  {step_name}: {step_result.get('passed', '?')} passed, {step_result.get('failed', '?')} failed")
        else:
            proof_lines.append(f"  {step_name}: {step_result}")
    proof_lines.append("")
    proof_lines.append(f"FINAL VERDICT: {report['final_verdict']}")
    (output_dir / "proof.txt").write_text("\n".join(proof_lines), encoding="utf-8")

    integration = """# BMP180 Driver — Integration Guide

## Files

| File | Purpose |
|------|---------|
| `bmp180_driver.h` | Public API: status enum + 6 function prototypes |
| `bmp180_driver.cpp` | Implementation: I2C via Wire library |
| `i2c0_regs.h` | ESP32 I2C0 register reference (extraction artifact, not consumed by this driver) |

## Steps

1. Copy `bmp180_driver.h` and `bmp180_driver.cpp` into your PlatformIO project's `lib/bmp180/` folder.
2. `#include "bmp180_driver.h"` in your main source file.
3. Call the API:
   ```c
   bmp180_status_t status = bmp180_init(Wire, 21, 22, 100000);
   if (status == BMP180_OK) {
       int32_t raw_temp;
       bmp180_read_raw_temperature(&raw_temp);
   }
   ```
4. Build with `pio run`. The library is self-contained — no additional dependencies.

## Note on i2c0_regs.h

`i2c0_regs.h` is a validated ESP32 I2C0 register reference generated from the controller IR.
It is an extraction artifact provided for reference — this driver does not `#include` it.
"""
    (output_dir / "INTEGRATION.md").write_text(integration, encoding="utf-8")

    print(f"  bmp180_driver.h   -> {output_dir / 'bmp180_driver.h'}")
    print(f"  bmp180_driver.cpp -> {output_dir / 'bmp180_driver.cpp'}")
    print(f"  i2c0_regs.h       -> {output_dir / 'i2c0_regs.h'}")
    print(f"  pipeline_report   -> {report_path}")
    print(f"  proof.txt         -> {output_dir / 'proof.txt'}")
    print(f"  INTEGRATION.md    -> {output_dir / 'INTEGRATION.md'}")


def run_pipeline(ir_path: Path, sensor_ir_path: Path, sim_retry: bool, dry_run: bool, output_dir: Path) -> bool:
    banner("EmbeddPilot V1.1 Pipeline")
    print(f"  Controller IR: {ir_path}")
    print(f"  Sensor IR:     {sensor_ir_path}")
    print(f"  Sim retry:     {sim_retry}")
    print(f"  Dry run:       {dry_run}")
    print(f"  Output:        {output_dir}")

    sensor_ir_data = json.loads(sensor_ir_path.read_text(encoding="utf-8"))
    controller_ir_data = json.loads(ir_path.read_text(encoding="utf-8"))

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ir_path": str(ir_path),
        "sensor_ir_path": str(sensor_ir_path),
        "sim_retry": sim_retry,
        "dry_run": dry_run,
        "controller_ir": {
            "peripheral": controller_ir_data.get("peripheral", "unknown"),
            "registers": len(controller_ir_data.get("registers", [])),
            "fields": sum(len(r.get("fields", [])) for r in controller_ir_data.get("registers", [])),
        },
        "sensor_ir": {
            "name": sensor_ir_data.get("device", {}).get("name", "unknown"),
            "manufacturer": sensor_ir_data.get("device", {}).get("manufacturer", ""),
            "i2c_address": sensor_ir_data.get("device", {}).get("i2c_address", ""),
            "registers": len(sensor_ir_data.get("registers", [])),
            "commands": len(sensor_ir_data.get("commands", [])),
            "coefficients": len(sensor_ir_data.get("calibration", {}).get("coefficients", [])),
            "timings": len(sensor_ir_data.get("timings", [])),
            "extraction_method": sensor_ir_data.get("meta", {}).get("extraction_method", ""),
            "extraction_date": sensor_ir_data.get("meta", {}).get("extraction_date", ""),
        },
        "steps": {},
        "final_verdict": "UNKNOWN",
    }

    # Step 1: Validate controller IR
    if not run_ir_validation(ir_path):
        report["final_verdict"] = "IR_VALIDATION_FAILED"
        report["steps"]["validate_controller_ir"] = "FAIL"
        package_output(output_dir, report)
        return False
    report["steps"]["validate_controller_ir"] = "PASS"

    # Step 2: Validate sensor IR
    if not run_sensor_ir_validation(sensor_ir_path):
        report["final_verdict"] = "SENSOR_IR_VALIDATION_FAILED"
        report["steps"]["validate_sensor_ir"] = "FAIL"
        package_output(output_dir, report)
        return False
    report["steps"]["validate_sensor_ir"] = "PASS"

    # Step 3: Generate library
    if not run_generation(ir_path, sensor_ir_path):
        report["final_verdict"] = "GENERATION_FAILED"
        report["steps"]["generate"] = "FAIL"
        package_output(output_dir, report)
        return False
    report["steps"]["generate"] = "PASS"

    # Step 4: Contamination guard
    guard_verdict = run_contamination_guard()
    report["steps"]["contamination_guard"] = guard_verdict
    if guard_verdict != "PASS":
        report["final_verdict"] = guard_verdict
        package_output(output_dir, report)
        return False

    # Steps 4-5: Install library, compile, simulate, uninstall
    try:
        install_library()

        # Step 4: Compile
        compile_verdict = run_compile()
        if compile_verdict != "PASS":
            report["final_verdict"] = compile_verdict
            report["steps"]["compile"] = compile_verdict
            package_output(output_dir, report)
            return False
        report["steps"]["compile"] = "PASS"

        # Step 5: Simulate
        if dry_run:
            step(6, TOTAL_STEPS, "Skipping simulation (--dry-run)")
            report["steps"]["simulate"] = "SKIPPED"
            report["final_verdict"] = "DRY_RUN_PASS"
            package_output(output_dir, report)
            banner("Pipeline Complete")
            print(f"  VERDICT: DRY_RUN_PASS")
            print(f"  Output:  {output_dir}")
            return True

        sim_result = run_simulation(sim_retry)
        report["steps"]["simulate"] = sim_result

        if sim_result["failed"] == 0 and sim_result["complete"]:
            report["final_verdict"] = "PASS"
            print(f"\n  ALL TESTS PASSED ({sim_result['passed']}/{sim_result['passed']})")
        elif sim_result.get("is_test_failure"):
            report["final_verdict"] = "SIM_FAIL"
            print(f"\n  SIM FAILED: {sim_result['failed']} test(s)")
            for f in sim_result["failures"]:
                print(f"    - {f['test']}")
            write_failure_report(sim_result)
        else:
            report["final_verdict"] = "SIM_INFRA_FAIL"
            print("\n  SIM INFRASTRUCTURE FAILURE: simulation did not complete")

    finally:
        uninstall_library()

    # Step 6: Package
    package_output(output_dir, report)

    banner("Pipeline Complete")
    verdict = report["final_verdict"]
    if verdict in ("PASS", "DRY_RUN_PASS"):
        print(f"  VERDICT: {verdict}")
        print(f"  Output:  {output_dir}")
        return True
    else:
        print(f"  VERDICT: {verdict}")
        print(f"  The pipeline did not produce a verified driver.")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="EmbeddPilot V1.1 — Datasheet to verified driver library in one command",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python embeddpilot.py                          # full pipeline with defaults
  python embeddpilot.py --dry-run                # generate + compile only
  python embeddpilot.py --ir my_ir.json          # use custom IR
  python embeddpilot.py --output-dir build/v1    # custom output location
  python embeddpilot.py --no-sim-retry           # disable sim infrastructure retry
""",
    )
    parser.add_argument("--ir", type=str, default=str(DEFAULT_CONTROLLER_IR), help="Path to controller IR JSON")
    parser.add_argument("--sensor-ir", type=str, default=str(DEFAULT_SENSOR_IR), help="Path to sensor IR JSON")
    parser.add_argument(
        "--sim-retry",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Allow one infrastructure retry for simulation (default: enabled). Use --no-sim-retry to disable.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip simulation, test generate+compile only")
    parser.add_argument("--output-dir", type=str, default=str(PROJECT_ROOT / "build" / "output"), help="Directory for output artifacts")
    args = parser.parse_args()

    ir_path = Path(args.ir)
    if not ir_path.exists():
        print(f"ERROR: Controller IR file not found: {ir_path}")
        sys.exit(1)

    sensor_ir_path = Path(args.sensor_ir)
    if not sensor_ir_path.exists():
        print(f"ERROR: Sensor IR file not found: {sensor_ir_path}")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    success = run_pipeline(ir_path, sensor_ir_path, args.sim_retry, args.dry_run, output_dir)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
