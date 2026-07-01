#!/usr/bin/env python3
"""Validate a register-map IR JSON file against the schema and internal consistency rules."""

import json
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:
    print("ERROR: jsonschema not installed. Run: pip install jsonschema")
    sys.exit(1)


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_schema(ir: dict, schema: dict) -> list[str]:
    errors = []
    validator = jsonschema.Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(ir), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"CRITICAL [schema] {path}: {error.message}")
    return errors


def validate_consistency(ir: dict) -> list[str]:
    issues = []
    seen_offsets = {}
    reg_size = ir.get("register_size_bits", 32)

    for i, reg in enumerate(ir.get("registers", [])):
        name = reg.get("name", f"register[{i}]")
        offset = reg.get("offset", "")
        size = reg.get("size_bits", reg_size)

        if offset in seen_offsets:
            issues.append(f"CRITICAL [overlap] Register '{name}' has same offset {offset} as '{seen_offsets[offset]}'")
        seen_offsets[offset] = name

        fields = reg.get("fields", [])
        occupied_bits = set()
        for field in fields:
            fname = field.get("name", "?")
            bit_off = field.get("bit_offset", 0)
            width = field.get("width", 1)

            if bit_off + width > size:
                issues.append(
                    f"CRITICAL [overflow] {name}.{fname}: bit_offset({bit_off}) + width({width}) = {bit_off + width} exceeds register size {size}"
                )

            field_bits = set(range(bit_off, bit_off + width))
            overlap = occupied_bits & field_bits
            if overlap:
                issues.append(
                    f"CRITICAL [bit-overlap] {name}.{fname}: bits {sorted(overlap)} already used by another field"
                )
            occupied_bits |= field_bits

        low_confidence = [f for f in fields if f.get("confidence") == "low"]
        if low_confidence:
            names = ", ".join(f.get("name", "?") for f in low_confidence)
            issues.append(f"WARNING [low-confidence] {name}: fields needing human review: {names}")

        if reg.get("confidence") == "low":
            issues.append(f"WARNING [low-confidence] Register '{name}' flagged low-confidence — needs human review")

    return issues


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <ir.json> [schema.json]")
        sys.exit(1)

    ir_path = Path(sys.argv[1])
    schema_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent.parent / "schema" / "register-ir.schema.json"

    if not ir_path.exists():
        print(f"ERROR: IR file not found: {ir_path}")
        sys.exit(1)
    if not schema_path.exists():
        print(f"ERROR: Schema file not found: {schema_path}")
        sys.exit(1)

    ir = load_json(ir_path)
    schema = load_json(schema_path)

    issues = []
    issues.extend(validate_schema(ir, schema))
    issues.extend(validate_consistency(ir))

    criticals = [i for i in issues if i.startswith("CRITICAL")]
    warnings = [i for i in issues if i.startswith("WARNING")]
    infos = [i for i in issues if i.startswith("INFO")]

    print("=" * 60)
    print("EmbeddPilot IR Validation Report")
    print("=" * 60)
    print(f"File: {ir_path}")
    print(f"Peripheral: {ir.get('peripheral', 'unknown')}")
    print(f"Registers: {len(ir.get('registers', []))}")
    print(f"Total fields: {sum(len(r.get('fields', [])) for r in ir.get('registers', []))}")
    print("-" * 60)

    for issue in issues:
        print(f"  {issue}")

    print("-" * 60)
    print(f"CRITICAL: {len(criticals)}  WARNING: {len(warnings)}  INFO: {len(infos)}")

    if criticals:
        print("\nVERDICT: FAIL — critical issues must be resolved before downstream use.")
        sys.exit(1)
    elif warnings:
        print("\nVERDICT: PASS WITH WARNINGS — review flagged items before proceeding.")
        sys.exit(0)
    else:
        print("\nVERDICT: PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
