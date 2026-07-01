#!/usr/bin/env python3
"""
EmbeddPilot Verification Harness Runner.

Compiles firmware via PlatformIO, runs in Wokwi sim, and parses serial
output for [PASS]/[FAIL] assertions. Returns exit code 0 if all tests
pass, 1 if any test fails or harness doesn't complete.

Usage:
    python scripts/run_harness.py                    # run reference driver
    python scripts/run_harness.py --broken           # run corrupted driver (should FAIL)
    python scripts/run_harness.py --driver path.cpp  # run a specific driver file
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).parent.parent / "harness"
SRC_MAIN = HARNESS_DIR / "src" / "main.cpp"
REFERENCE_DRIVER = HARNESS_DIR / "src" / "main.cpp"
BROKEN_DRIVER = HARNESS_DIR / "reference" / "driver_broken.cpp"
WOKWI_CLI = shutil.which("wokwi-cli") or str(
    Path.home() / ".wokwi" / "bin" / "wokwi-cli.exe"
)
TIMEOUT_MS = 15000


def compile_firmware() -> bool:
    print("=== Compiling firmware ===")
    result = subprocess.run(
        ["pio", "run"],
        cwd=str(HARNESS_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        print("COMPILE FAILED:")
        print(result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr)
        return False
    print("Compile OK")
    return True


def run_simulation() -> str:
    print("=== Running Wokwi simulation ===")
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
    print(output[-3000:] if len(output) > 3000 else output)
    return output


def parse_results(output: str) -> dict:
    results = {"tests": [], "passed": 0, "failed": 0, "complete": False}

    for line in output.split("\n"):
        line = line.strip()
        match = re.match(r"\[(PASS|FAIL)\]\s+(.+)", line)
        if match:
            status = match.group(1)
            name = match.group(2)
            results["tests"].append({"name": name, "status": status})
            if status == "PASS":
                results["passed"] += 1
            else:
                results["failed"] += 1

        if "HARNESS_COMPLETE" in line:
            results["complete"] = True

    return results


def swap_driver(driver_path: Path):
    """Replace src/main.cpp with the specified driver file."""
    backup = SRC_MAIN.with_suffix(".cpp.bak")
    if not backup.exists():
        shutil.copy2(SRC_MAIN, backup)
    shutil.copy2(driver_path, SRC_MAIN)
    print(f"Swapped driver: {driver_path.name}")


def restore_driver():
    """Restore original src/main.cpp from backup."""
    backup = SRC_MAIN.with_suffix(".cpp.bak")
    if backup.exists():
        shutil.copy2(backup, SRC_MAIN)
        backup.unlink()
        print("Restored original driver")


def main():
    parser = argparse.ArgumentParser(description="EmbeddPilot Verification Runner")
    parser.add_argument("--broken", action="store_true", help="Run the corrupted driver")
    parser.add_argument("--driver", type=str, help="Path to a custom driver .cpp file")
    args = parser.parse_args()

    custom_driver = None
    if args.broken:
        custom_driver = BROKEN_DRIVER
    elif args.driver:
        custom_driver = Path(args.driver)
        if not custom_driver.exists():
            print(f"ERROR: Driver file not found: {custom_driver}")
            sys.exit(1)

    try:
        if custom_driver:
            swap_driver(custom_driver)

        if not compile_firmware():
            sys.exit(1)

        output = run_simulation()
        results = parse_results(output)

        print("\n=== Verification Report ===")
        for test in results["tests"]:
            marker = "OK" if test["status"] == "PASS" else "XX"
            print(f"  [{marker}] {test['name']}")

        print(f"\nPassed: {results['passed']}, Failed: {results['failed']}")
        print(f"Harness complete: {results['complete']}")

        if results["failed"] > 0 or not results["complete"]:
            print("\nVERDICT: FAIL")
            sys.exit(1)
        else:
            print("\nVERDICT: PASS")
            sys.exit(0)

    finally:
        if custom_driver:
            restore_driver()


if __name__ == "__main__":
    main()
