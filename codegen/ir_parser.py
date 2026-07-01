"""
Parse the register-map IR JSON into Python objects for code generation.

This module is the ONLY place the IR is read. All downstream codegen
consumes these dataclasses, never the raw JSON.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BitField:
    name: str
    bit_offset: int
    width: int
    access: str
    reset_value: int = 0
    description: str = ""
    enum_values: dict[str, str] = field(default_factory=dict)
    confidence: str = "high"
    notes: str = ""

    @property
    def mask(self) -> int:
        return ((1 << self.width) - 1) << self.bit_offset

    @property
    def max_value(self) -> int:
        return (1 << self.width) - 1

    @property
    def is_single_bit(self) -> bool:
        return self.width == 1

    @property
    def is_writable(self) -> bool:
        return self.access in ("RW", "WO", "RW1C", "RW1S", "W1")

    @property
    def is_readable(self) -> bool:
        return self.access in ("RO", "RW", "RW1C", "RW1S")


@dataclass
class Register:
    name: str
    offset: str
    size_bits: int
    fields: list[BitField]
    reset_value: str = "0x00000000"
    description: str = ""
    confidence: str = "high"
    notes: str = ""

    @property
    def offset_int(self) -> int:
        return int(self.offset, 16)

    @property
    def reset_value_int(self) -> int:
        return int(self.reset_value, 16)

    def field_by_name(self, name: str) -> BitField | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None


@dataclass
class PeripheralIR:
    peripheral: str
    base_address: str
    register_size_bits: int
    registers: list[Register]
    datasheet_source: str = ""
    mcu_family: str = ""
    mcu_part: str = ""

    @property
    def base_address_int(self) -> int:
        return int(self.base_address, 16)

    def reg_by_name(self, name: str) -> Register | None:
        for r in self.registers:
            if r.name == name:
                return r
        return None


def parse_ir(path: str | Path) -> PeripheralIR:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    registers = []
    for rdata in data["registers"]:
        fields = []
        for fdata in rdata.get("fields", []):
            fields.append(BitField(
                name=fdata["name"],
                bit_offset=fdata["bit_offset"],
                width=fdata["width"],
                access=fdata["access"],
                reset_value=fdata.get("reset_value", 0),
                description=fdata.get("description", ""),
                enum_values=fdata.get("enum_values", {}),
                confidence=fdata.get("confidence", "high"),
                notes=fdata.get("notes", ""),
            ))
        registers.append(Register(
            name=rdata["name"],
            offset=rdata["offset"],
            size_bits=rdata.get("size_bits", data.get("register_size_bits", 32)),
            fields=fields,
            reset_value=rdata.get("reset_value", "0x00000000"),
            description=rdata.get("description", ""),
            confidence=rdata.get("confidence", "high"),
            notes=rdata.get("notes", ""),
        ))

    meta = data.get("meta", {})
    return PeripheralIR(
        peripheral=data["peripheral"],
        base_address=data["base_address"],
        register_size_bits=data.get("register_size_bits", 32),
        registers=registers,
        datasheet_source=meta.get("datasheet_source", ""),
        mcu_family=meta.get("mcu_family", ""),
        mcu_part=meta.get("mcu_part", ""),
    )
