#!/usr/bin/env python3
"""
EmbeddPilot — One-command pipeline.

Datasheet in -> Verified driver + proof out.

Stages:
  1. Validate IR (schema + consistency)
  2. Generate driver + register header from IR
  3. Compile via PlatformIO
  4. Simulate via Wokwi (unless --dry-run)
  5. Self-correct on failure (up to --max-retries)
  6. Package output: driver, header, report

Usage:
    python embeddpilot.py
    python embeddpilot.py --ir artifacts/register-ir.json
    python embeddpilot.py --dry-run
    python embeddpilot.py --max-retries 3 --output-dir build/
"""

import argparse
import json
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
DEFAULT_IR = ARTIFACTS_DIR / "register-ir.json"
SCHEMA_PATH = PROJECT_ROOT / "schema" / "register-ir.schema.json"


def banner(text: str):
    width = 60
    print(f"\n{'=' * width}")
    print(f"  {text}")
    print(f"{'=' * width}")


def step(n: int, total: int, text: str):
    print(f"\n  [{n}/{total}] {text}")


def run_ir_validation(ir_path: Path) -> bool:
    step(1, 6, "Validating IR against schema...")
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_ir.py"), str(ir_path)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    print(result.stdout[-2000:])
    if result.returncode != 0:
        print("  IR VALIDATION FAILED")
        return False
    print("  IR validation passed")
    return True


def run_generation(ir_path: Path) -> bool:
    step(2, 6, "Generating driver from IR...")
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "generate_driver.py"), "--ir", str(ir_path)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(result.stdout[-2000:])
    if result.returncode != 0:
        print(f"  GENERATION FAILED: {result.stderr[-500:]}")
        return False
    print("  Driver generation passed")
    return True


def run_compile() -> bool:
    step(3, 6, "Compiling driver via PlatformIO...")
    driver_path = DRIVERS_DIR / "driver.cpp"
    harness_src = HARNESS_DIR / "src" / "main.cpp"
    backup = harness_src.with_suffix(".cpp.bak")

    shutil.copy2(harness_src, backup)
    shutil.copy2(driver_path, harness_src)

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
            return False
        print("  Compilation passed")
        return True
    finally:
        shutil.copy2(backup, harness_src)
        backup.unlink()


def run_simulation() -> dict:
    import re

    step(4, 6, "Running Wokwi simulation...")
    wokwi_cli = shutil.which("wokwi-cli") or str(
        Path.home() / ".wokwi" / "bin" / "wokwi-cli.exe"
    )
    cmd = [
        wokwi_cli,
        "--timeout", "15000",
        "--expect-text", "HARNESS_COMPLETE",
        "--fail-text", "I2C_WRITE_ERROR",
    ]
    result = subprocess.run(
        cmd,
        cwd=str(HARNESS_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )
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

    return {
        "passed": passed,
        "failed": failed,
        "complete": complete,
        "tests": tests,
        "failures": failures,
        "raw_output": output[-2000:],
    }


def package_output(output_dir: Path, report: dict):
    step(6, 6, f"Packaging output to {output_dir}/...")
    output_dir.mkdir(parents=True, exist_ok=True)

    driver_src = DRIVERS_DIR / "driver.cpp"
    header_src = DRIVERS_DIR / "i2c0_regs.h"

    if driver_src.exists():
        shutil.copy2(driver_src, output_dir / "driver.cpp")
    if header_src.exists():
        shutil.copy2(header_src, output_dir / "i2c0_regs.h")

    report_path = output_dir / "pipeline_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    proof_path = output_dir / "proof.txt"
    lines = [
        f"EmbeddPilot V1 — Verification Proof",
        f"Generated: {report['timestamp']}",
        f"IR Source: {report.get('ir_path', 'unknown')}",
        f"Verdict: {report['final_verdict']}",
        f"Iterations: {len(report['iterations'])}",
        "",
    ]
    for it in report["iterations"]:
        lines.append(f"  Attempt {it['attempt']}:")
        for step_name, step_result in it["steps"].items():
            if isinstance(step_result, dict):
                lines.append(f"    {step_name}: {step_result.get('passed', '?')} passed, {step_result.get('failed', '?')} failed")
            else:
                lines.append(f"    {step_name}: {step_result}")
        lines.append(f"    verdict: {it['verdict']}")
        lines.append("")
    lines.append(f"FINAL VERDICT: {report['final_verdict']}")
    proof_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"  driver.cpp      -> {output_dir / 'driver.cpp'}")
    print(f"  i2c0_regs.h     -> {output_dir / 'i2c0_regs.h'}")
    print(f"  pipeline_report -> {report_path}")
    print(f"  proof.txt       -> {proof_path}")


def run_pipeline(ir_path: Path, max_retries: int, dry_run: bool, output_dir: Path) -> bool:
    banner("EmbeddPilot V1 Pipeline")
    print(f"  IR:          {ir_path}")
    print(f"  Max retries: {max_retries}")
    print(f"  Dry run:     {dry_run}")
    print(f"  Output:      {output_dir}")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ir_path": str(ir_path),
        "max_retries": max_retries,
        "dry_run": dry_run,
        "iterations": [],
        "final_verdict": "UNKNOWN",
    }

    if not run_ir_validation(ir_path):
        report["final_verdict"] = "IR_VALIDATION_FAILED"
        package_output(output_dir, report)
        return False

    for attempt in range(1, max_retries + 1):
        banner(f"Attempt {attempt}/{max_retries}")
        iteration = {"attempt": attempt, "steps": {}}

        if not run_generation(ir_path):
            iteration["steps"]["generate"] = "FAIL"
            iteration["verdict"] = "GENERATION_FAILED"
            report["iterations"].append(iteration)
            continue
        iteration["steps"]["generate"] = "PASS"

        if not run_compile():
            iteration["steps"]["compile"] = "FAIL"
            iteration["verdict"] = "COMPILE_FAILED"
            report["iterations"].append(iteration)
            continue
        iteration["steps"]["compile"] = "PASS"

        if dry_run:
            step(4, 6, "Skipping simulation (--dry-run)")
            iteration["steps"]["simulate"] = "SKIPPED"
            iteration["verdict"] = "DRY_RUN_PASS"
            report["iterations"].append(iteration)
            report["final_verdict"] = "DRY_RUN_PASS"
            break

        sim_result = run_simulation()
        iteration["steps"]["simulate"] = sim_result

        if sim_result["failed"] == 0 and sim_result["complete"]:
            iteration["verdict"] = "PASS"
            report["iterations"].append(iteration)
            report["final_verdict"] = "PASS"
            step(5, 6, f"ALL TESTS PASSED ({sim_result['passed']}/{sim_result['passed']})")
            break
        else:
            iteration["verdict"] = "SIM_FAIL"
            report["iterations"].append(iteration)
            print(f"\n  SIM FAILED: {sim_result['failed']} test(s)")
            for f in sim_result["failures"]:
                print(f"    - {f['test']}")
            if attempt < max_retries:
                step(5, 6, f"Self-correcting... retry {attempt + 1}/{max_retries}")
    else:
        report["final_verdict"] = "MAX_RETRIES_EXCEEDED"

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
        description="EmbeddPilot — Datasheet to verified driver in one command",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python embeddpilot.py                          # full pipeline with defaults
  python embeddpilot.py --dry-run                # generate + compile only
  python embeddpilot.py --ir my_ir.json          # use custom IR
  python embeddpilot.py --output-dir build/v1    # custom output location
  python embeddpilot.py --max-retries 3          # limit correction attempts
""",
    )
    parser.add_argument("--ir", type=str, default=str(DEFAULT_IR), help="Path to register-map IR JSON")
    parser.add_argument("--max-retries", type=int, default=5, help="Max self-correction attempts (default: 5)")
    parser.add_argument("--dry-run", action="store_true", help="Skip simulation, test generate+compile only")
    parser.add_argument("--output-dir", type=str, default=str(PROJECT_ROOT / "build" / "output"), help="Directory for output artifacts")
    args = parser.parse_args()

    ir_path = Path(args.ir)
    if not ir_path.exists():
        print(f"ERROR: IR file not found: {ir_path}")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    success = run_pipeline(ir_path, args.max_retries, args.dry_run, output_dir)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
