#!/usr/bin/env python3
"""Spot-check 5 registers in the IR against known datasheet values."""

import json
import sys

IR_PATH = r"C:\Users\perimilla charani\Desktop\project-embeddpilot\artifacts\register-ir.json"

CHECKS = [
    {
        "name": "I2C_CTR_REG",
        "offset": "0x0004",
        "reset": "0x00000003",
        "fields": [
            ("I2C_SDA_FORCE_OUT", 0, 1, "RW"),
            ("I2C_MS_MODE", 4, 1, "RW"),
            ("I2C_RX_LSB_FIRST", 7, 1, "RW"),
        ],
    },
    {
        "name": "I2C_SR_REG",
        "offset": "0x0008",
        "reset": "0x00000000",
        "fields": [
            ("I2C_ACK_REC", 0, 1, "RO"),
            ("I2C_RXFIFO_CNT", 8, 6, "RO"),
            ("I2C_SCL_STATE_LAST", 28, 3, "RO"),
        ],
    },
    {
        "name": "I2C_FIFO_CONF_REG",
        "offset": "0x0018",
        "reset": "0x01554000",
        "fields": [
            ("I2C_NONFIFO_TX_THRES", 20, 6, "RW"),
            ("I2C_NONFIFO_RX_THRES", 14, 6, "RW"),
        ],
    },
    {
        "name": "I2C_SCL_FILTER_CFG_REG",
        "offset": "0x0050",
        "reset": "0x00000008",
        "fields": [
            ("I2C_SCL_FILTER_EN", 3, 1, "RW"),
            ("I2C_SCL_FILTER_THRES", 0, 3, "RW"),
        ],
    },
    {
        "name": "I2C_COMD0_REG",
        "offset": "0x0058",
        "reset": "0x00000000",
        "fields": [
            ("I2C_COMMAND0_BYTE_NUM", 0, 8, "RW"),
            ("I2C_COMMAND0_ACK_EN", 8, 1, "RW"),
            ("I2C_COMMAND0_ACK_EXP", 9, 1, "RW"),
            ("I2C_COMMAND0_ACK_VAL", 10, 1, "RW"),
            ("I2C_COMMAND0_OP_CODE", 11, 3, "RW"),
            ("I2C_COMMAND0_DONE", 31, 1, "RW"),
        ],
    },
]


def main():
    with open(IR_PATH) as f:
        ir = json.load(f)

    regs_by_name = {r["name"]: r for r in ir["registers"]}
    all_pass = True

    for check in CHECKS:
        reg = regs_by_name.get(check["name"])
        if not reg:
            print(f"FAIL: {check['name']} not found in IR")
            all_pass = False
            continue

        issues = []
        if reg["offset"] != check["offset"]:
            issues.append(f"offset: got {reg['offset']}, expected {check['offset']}")
        if reg["reset_value"] != check["reset"]:
            issues.append(f"reset: got {reg['reset_value']}, expected {check['reset']}")

        fields_by_name = {f["name"]: f for f in reg["fields"]}
        for fname, exp_bit, exp_width, exp_access in check["fields"]:
            field = fields_by_name.get(fname)
            if not field:
                issues.append(f"field {fname} missing")
            else:
                if field["bit_offset"] != exp_bit:
                    issues.append(f"{fname} bit_offset: got {field['bit_offset']}, expected {exp_bit}")
                if field["width"] != exp_width:
                    issues.append(f"{fname} width: got {field['width']}, expected {exp_width}")
                if field["access"] != exp_access:
                    issues.append(f"{fname} access: got {field['access']}, expected {exp_access}")

        if issues:
            print(f"FAIL: {check['name']}")
            for i in issues:
                print(f"  - {i}")
            all_pass = False
        else:
            n_fields = len(check["fields"])
            print(f"PASS: {check['name']} (offset={check['offset']}, reset={check['reset']}, {n_fields} fields OK)")

    print()
    if all_pass:
        print("SPOT-CHECK VERDICT: ALL 5 REGISTERS PASS")
    else:
        print("SPOT-CHECK VERDICT: FAILURES DETECTED")
        sys.exit(1)


if __name__ == "__main__":
    main()
