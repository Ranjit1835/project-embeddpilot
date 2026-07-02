#!/usr/bin/env python3
"""
EmbeddPilot Driver Generator — Main Entry Point.

Reads BOTH validated IRs (controller + sensor), generates:
1. Register header file (i2c0_regs.h)
2. Driver library: bmp180_driver.h + bmp180_driver.cpp

All sensor constants come from the sensor IR. Zero hardcoded hex.

Usage:
    python scripts/generate_driver.py
    python scripts/generate_driver.py --ir path/to/controller-ir.json --sensor-ir path/to/sensor-ir.json
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from codegen.ir_parser import parse_ir
from codegen.sensor_ir_parser import parse_sensor_ir
from codegen.header_gen import generate_header
from codegen.driver_gen import generate_driver

CONTROLLER_IR_PATH = PROJECT_ROOT / "artifacts" / "controller-ir.json"
SENSOR_IR_PATH = PROJECT_ROOT / "artifacts" / "sensor-ir.json"
OUTPUT_DIR = PROJECT_ROOT / "drivers" / "generated"


def main():
    parser = argparse.ArgumentParser(description="EmbeddPilot Driver Generator")
    parser.add_argument("--ir", type=str, default=str(CONTROLLER_IR_PATH), help="Path to controller IR JSON")
    parser.add_argument("--sensor-ir", type=str, default=str(SENSOR_IR_PATH), help="Path to sensor IR JSON")
    args = parser.parse_args()

    ir_path = Path(args.ir)
    sensor_ir_path = Path(args.sensor_ir)

    if not ir_path.exists():
        print(f"ERROR: Controller IR file not found: {ir_path}")
        sys.exit(1)
    if not sensor_ir_path.exists():
        print(f"ERROR: Sensor IR file not found: {sensor_ir_path}")
        sys.exit(1)

    print("=== EmbeddPilot Driver Generator ===")
    print(f"Controller IR: {ir_path}")
    print(f"Sensor IR:     {sensor_ir_path}")
    print()

    ir = parse_ir(ir_path)
    print(f"Controller: {ir.peripheral} @ {ir.base_address}")
    print(f"  {len(ir.registers)} registers, {sum(len(r.fields) for r in ir.registers)} fields")

    sensor_ir = parse_sensor_ir(sensor_ir_path)
    print(f"Sensor: {sensor_ir.name} ({sensor_ir.manufacturer}) @ {sensor_ir.i2c_address}")
    print(f"  {len(sensor_ir.registers)} registers, {len(sensor_ir.commands)} commands, {len(sensor_ir.coefficients)} calibration coefficients")
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    header_content = generate_header(ir)
    header_path = OUTPUT_DIR / "i2c0_regs.h"
    header_path.write_text(header_content, encoding="utf-8")
    header_lines = header_content.count("\n")
    print(f"Generated: {header_path.name} ({header_lines} lines)")

    result = generate_driver(ir, sensor_ir)

    drv_header_path = OUTPUT_DIR / "bmp180_driver.h"
    drv_header_path.write_text(result["header"], encoding="utf-8")
    print(f"Generated: {drv_header_path.name} ({result['header'].count(chr(10))} lines)")

    drv_source_path = OUTPUT_DIR / "bmp180_driver.cpp"
    drv_source_path.write_text(result["source"], encoding="utf-8")
    print(f"Generated: {drv_source_path.name} ({result['source'].count(chr(10))} lines)")

    _validate_no_hallucinated_registers(result["header"] + result["source"], ir, sensor_ir)

    print()
    print(f"Output directory: {OUTPUT_DIR}")
    print()
    print("GENERATION COMPLETE")


def _validate_no_hallucinated_registers(code: str, ir, sensor_ir):
    import re
    hex_refs = re.findall(r"0x[0-9A-Fa-f]{4,8}", code)

    ir_addresses = set()
    ir_addresses.add(ir.base_address.lower())
    for reg in ir.registers:
        abs_addr = ir.base_address_int + reg.offset_int
        ir_addresses.add(f"0x{abs_addr:08x}")
        ir_addresses.add(reg.offset.lower())

    sensor_addrs = set()
    sensor_addrs.add(sensor_ir.i2c_address.lower())
    sensor_addrs.add(sensor_ir.chip_id_register.lower())
    sensor_addrs.add(sensor_ir.chip_id_expected.lower())
    for reg in sensor_ir.registers:
        sensor_addrs.add(reg.address.lower())
    for cmd in sensor_ir.commands:
        sensor_addrs.add(cmd.target_register.lower())
        sensor_addrs.add(cmd.value.lower())

    for href in hex_refs:
        h = href.lower()
        if h in ir_addresses or h in sensor_addrs:
            continue
        if int(h, 16) <= 0xFF:
            continue
        print(f"  WARNING: Code references {href} which is not in the IR or sensor config")


if __name__ == "__main__":
    main()
