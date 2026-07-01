#!/usr/bin/env python3
"""
EmbeddPilot Driver Generator — Main Entry Point.

Reads the validated IR, generates:
1. Register header file (i2c0_regs.h)
2. Driver source file (driver.cpp)
3. Copies them into drivers/generated/

Then compiles the driver against the harness to verify it builds.

Usage:
    python scripts/generate_driver.py
    python scripts/generate_driver.py --compile   # also compile via PlatformIO
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from codegen.ir_parser import parse_ir
from codegen.header_gen import generate_header
from codegen.driver_gen import generate_driver

IR_PATH = PROJECT_ROOT / "artifacts" / "register-ir.json"
OUTPUT_DIR = PROJECT_ROOT / "drivers" / "generated"
HARNESS_DIR = PROJECT_ROOT / "harness"

SENSOR_CONFIG = {
    "sensor_addr": "0x77",
    "sensor_name": "BMP180",
    "chip_id_reg": "0xD0",
    "chip_id_value": "0x55",
    "reset_reg": "0xE0",
    "reset_cmd": "0xB6",
    "ctrl_reg": "0xF4",
    "ctrl_value": "0x2E",
    "data_start_reg": "0xF6",
    "data_len": "3",
    "sda_pin": "21",
    "scl_pin": "22",
    "i2c_freq": "100000",
}


def main():
    parser = argparse.ArgumentParser(description="EmbeddPilot Driver Generator")
    parser.add_argument("--compile", action="store_true", help="Compile after generation")
    parser.add_argument("--ir", type=str, default=str(IR_PATH), help="Path to IR JSON")
    args = parser.parse_args()

    ir_path = Path(args.ir)
    if not ir_path.exists():
        print(f"ERROR: IR file not found: {ir_path}")
        sys.exit(1)

    print(f"=== EmbeddPilot Driver Generator ===")
    print(f"IR: {ir_path}")
    print()

    # Parse IR
    ir = parse_ir(ir_path)
    print(f"Parsed: {ir.peripheral} @ {ir.base_address}")
    print(f"  {len(ir.registers)} registers, {sum(len(r.fields) for r in ir.registers)} fields")
    print()

    # Generate header
    header_content = generate_header(ir)
    header_path = OUTPUT_DIR / "i2c0_regs.h"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    header_path.write_text(header_content, encoding="utf-8")
    header_lines = header_content.count("\n")
    print(f"Generated: {header_path.name} ({header_lines} lines)")

    # Generate driver
    driver_content = generate_driver(ir, SENSOR_CONFIG)
    driver_path = OUTPUT_DIR / "driver.cpp"
    driver_path.write_text(driver_content, encoding="utf-8")
    driver_lines = driver_content.count("\n")
    print(f"Generated: {driver_path.name} ({driver_lines} lines)")

    # Validation gate: check that driver doesn't reference any register
    # address not in the IR (training-memory leak detection)
    _validate_no_hallucinated_registers(driver_content, ir)

    print()
    print(f"Output directory: {OUTPUT_DIR}")

    if args.compile:
        print()
        print("=== Compiling generated driver ===")
        success = _compile_driver(driver_path)
        if not success:
            print("COMPILE FAILED")
            sys.exit(1)
        print("COMPILE OK")

    print()
    print("GENERATION COMPLETE")


def _validate_no_hallucinated_registers(code: str, ir):
    """Ensure the generated code doesn't contain register addresses not in the IR."""
    import re
    hex_refs = re.findall(r"0x[0-9A-Fa-f]{4,8}", code)

    ir_addresses = set()
    ir_addresses.add(ir.base_address.lower())
    for reg in ir.registers:
        abs_addr = ir.base_address_int + reg.offset_int
        ir_addresses.add(f"0x{abs_addr:08x}")
        ir_addresses.add(reg.offset.lower())

    sensor_addrs = {"0x76", "0x77", "0xd0", "0xe0", "0xf4", "0xf5", "0xf6", "0xf7", "0xfa", "0xb6", "0x55", "0x58", "0x2e"}

    for href in hex_refs:
        h = href.lower()
        if h in ir_addresses or h in sensor_addrs:
            continue
        if int(h, 16) <= 0xFF:
            continue
        print(f"  WARNING: Code references {href} which is not in the IR or sensor config")


def _compile_driver(driver_path: Path) -> bool:
    """Copy driver into harness and compile via PlatformIO."""
    harness_src = HARNESS_DIR / "src" / "main.cpp"
    backup = harness_src.with_suffix(".cpp.bak")

    try:
        shutil.copy2(harness_src, backup)
        shutil.copy2(driver_path, harness_src)

        result = subprocess.run(
            ["pio", "run"],
            cwd=str(HARNESS_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            print(result.stderr[-2000:])
            return False
        return True
    finally:
        if backup.exists():
            shutil.copy2(backup, harness_src)
            backup.unlink()


if __name__ == "__main__":
    main()
