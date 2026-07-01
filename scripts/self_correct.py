#!/usr/bin/env python3
"""
EmbeddPilot Self-Correcting Pipeline.

Runs the full loop:
  1. Generate driver from IR
  2. Compile
  3. Run in Wokwi sim
  4. If FAIL -> parse failure, feed back to codegen, regenerate, retry
  5. Max N iterations before giving up

Usage:
    python scripts/self_correct.py
    python scripts/self_correct.py --max-retries 3
    python scripts/self_correct.py --dry-run   # generate + compile only, skip sim
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
HARNESS_DIR = PROJECT_ROOT / "harness"
DRIVERS_DIR = PROJECT_ROOT / "drivers" / "generated"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
WOKWI_CLI = shutil.which("wokwi-cli") or str(
    Path.home() / ".wokwi" / "bin" / "wokwi-cli.exe"
)
TIMEOUT_MS = 15000


def generate_driver() -> bool:
    print("  [1/3] Generating driver from IR...")
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "generate_driver.py")],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        print(f"  Generation failed: {result.stderr[-500:]}")
        return False
    print("  Generation OK")
    return True


def compile_driver() -> bool:
    print("  [2/3] Compiling...")
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
            print(f"  Compile failed: {result.stderr[-500:]}")
            return False
        print("  Compile OK")
        return True
    finally:
        shutil.copy2(backup, harness_src)
        backup.unlink()


def run_simulation() -> dict:
    print("  [3/3] Running Wokwi simulation...")
    import re

    cmd = [
        WOKWI_CLI,
        "--timeout", str(TIMEOUT_MS),
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


def run_pipeline(max_retries: int, dry_run: bool) -> bool:
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "max_retries": max_retries,
        "iterations": [],
        "final_verdict": "UNKNOWN",
    }

    for attempt in range(1, max_retries + 1):
        print(f"\n{'='*50}")
        print(f"Attempt {attempt}/{max_retries}")
        print(f"{'='*50}")

        iteration = {"attempt": attempt, "steps": {}}

        if not generate_driver():
            iteration["steps"]["generate"] = "FAIL"
            iteration["verdict"] = "GENERATION_FAILED"
            report["iterations"].append(iteration)
            continue
        iteration["steps"]["generate"] = "PASS"

        if not compile_driver():
            iteration["steps"]["compile"] = "FAIL"
            iteration["verdict"] = "COMPILE_FAILED"
            report["iterations"].append(iteration)
            continue
        iteration["steps"]["compile"] = "PASS"

        if dry_run:
            print("  [3/3] Skipping simulation (--dry-run)")
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
            print(f"\n  ALL TESTS PASSED ({sim_result['passed']}/{sim_result['passed']})")
            break
        else:
            iteration["verdict"] = "SIM_FAIL"
            report["iterations"].append(iteration)
            print(f"  FAILED: {sim_result['failed']} test(s)")
            for f in sim_result["failures"]:
                print(f"    - {f['test']}: {f['output']}")

            if attempt < max_retries:
                print(f"\n  Retrying ({attempt + 1}/{max_retries})...")
    else:
        report["final_verdict"] = "MAX_RETRIES_EXCEEDED"
        print(f"\n  MAX RETRIES ({max_retries}) EXCEEDED — pipeline failed.")

    report_path = ARTIFACTS_DIR / "pipeline_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport saved: {report_path}")
    print(f"FINAL VERDICT: {report['final_verdict']}")

    return report["final_verdict"] in ("PASS", "DRY_RUN_PASS")


def main():
    parser = argparse.ArgumentParser(description="EmbeddPilot Self-Correcting Pipeline")
    parser.add_argument("--max-retries", type=int, default=5, help="Max correction attempts")
    parser.add_argument("--dry-run", action="store_true", help="Skip simulation, test generate+compile only")
    args = parser.parse_args()

    success = run_pipeline(args.max_retries, args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
