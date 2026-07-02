"""
Parse the sensor-ir.json into Python objects for driver generation.

This is the ONLY place the sensor IR is read. All downstream codegen
consumes these dataclasses, never the raw JSON.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SensorRegister:
    name: str
    address: str
    size_bytes: int
    access: str
    description: str = ""
    confidence: str = "high"
    notes: str = ""

    @property
    def address_int(self) -> int:
        return int(self.address, 16)


@dataclass
class SensorCommand:
    name: str
    target_register: str
    value: str
    purpose: str = ""

    @property
    def target_register_int(self) -> int:
        return int(self.target_register, 16)

    @property
    def value_int(self) -> int:
        return int(self.value, 16)


@dataclass
class CalibrationCoefficient:
    name: str
    address_msb: str
    address_lsb: str
    signed: bool


@dataclass
class Timing:
    name: str
    microseconds: int
    description: str = ""


@dataclass
class SensorIR:
    name: str
    manufacturer: str
    i2c_address: str
    chip_id_register: str
    chip_id_expected: str
    datasheet_source: str
    registers: list[SensorRegister]
    commands: list[SensorCommand]
    coefficients: list[CalibrationCoefficient]
    timings: list[Timing]

    @property
    def i2c_address_int(self) -> int:
        return int(self.i2c_address, 16)

    @property
    def chip_id_register_int(self) -> int:
        return int(self.chip_id_register, 16)

    @property
    def chip_id_expected_int(self) -> int:
        return int(self.chip_id_expected, 16)

    def reg_by_name(self, name: str) -> SensorRegister | None:
        for r in self.registers:
            if r.name == name:
                return r
        return None

    def cmd_by_name(self, name: str) -> SensorCommand | None:
        for c in self.commands:
            if c.name == name:
                return c
        return None

    def timing_by_name(self, name: str) -> Timing | None:
        for t in self.timings:
            if t.name == name:
                return t
        return None


def parse_sensor_ir(path: str | Path) -> SensorIR:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    device = data["device"]

    registers = [
        SensorRegister(
            name=r["name"],
            address=r["address"],
            size_bytes=r["size_bytes"],
            access=r["access"],
            description=r.get("description", ""),
            confidence=r.get("confidence", "high"),
            notes=r.get("notes", ""),
        )
        for r in data.get("registers", [])
    ]

    commands = [
        SensorCommand(
            name=c["name"],
            target_register=c["target_register"],
            value=c["value"],
            purpose=c.get("purpose", ""),
        )
        for c in data.get("commands", [])
    ]

    coefficients = [
        CalibrationCoefficient(
            name=c["name"],
            address_msb=c["address_msb"],
            address_lsb=c["address_lsb"],
            signed=c["signed"],
        )
        for c in data.get("calibration", {}).get("coefficients", [])
    ]

    timings = [
        Timing(
            name=t["name"],
            microseconds=t["microseconds"],
            description=t.get("description", ""),
        )
        for t in data.get("timings", [])
    ]

    return SensorIR(
        name=device["name"],
        manufacturer=device.get("manufacturer", ""),
        i2c_address=device["i2c_address"],
        chip_id_register=device["chip_id_register"],
        chip_id_expected=device["chip_id_expected"],
        datasheet_source=device.get("datasheet_source", ""),
        registers=registers,
        commands=commands,
        coefficients=coefficients,
        timings=timings,
    )
