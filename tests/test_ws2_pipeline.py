"""WS2 tests: router decisions, three-state cross-check, retry loop,
graceful fallback, base-address parameterization, command-device end-to-end,
and the contamination guard. All LLM calls are mocked (MockProvider)."""

import glob
import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from generation.pipeline import generate_validated_driver
from generation.provider import MockProvider
from generation.router import route
from generation.worker import build_worker_prompt, generate_driver
from validator.crosscheck import crosscheck
from validator.report import ValidationReport

# --- fixtures -------------------------------------------------------------------

REGISTER_MAP = {
    "peripheral": "I2C0",
    "chip": "ESP32",
    "provenance": {"chip": "user", "peripheral": "user"},
    "base_address": "0x3FF53000",
    "registers": [
        {"name": "I2C_CTR_REG", "offset": "0x0004", "reset_value": "0x00",
         "access": "RW",
         "fields": [{"name": "TRANS_START", "bits": "[5:5]", "description": ""}],
         "confidence": "high", "source_pages": [401]},
        {"name": "I2C_SR_REG", "offset": "0x0008", "reset_value": None,
         "access": "RO", "fields": [],  # unknown layout -> unverified territory
         "confidence": "high", "source_pages": [404]},
    ],
    "commands": [],
    "extraction_confidence": "high", "source_pages": [401], "warnings": [],
}

COMMAND_MAP = {
    "peripheral": "spi-flash",
    "chip": "W25Q64JV",
    "provenance": {"chip": "user", "peripheral": "user"},
    "base_address": None,
    "registers": [],
    "commands": [
        {"name": "Write Enable", "opcode": "0x06", "description": "",
         "address_bytes": None, "dummy_cycles": None, "data_direction": "none",
         "source_pages": [23]},
        {"name": "Read Data", "opcode": "0x03", "description": "",
         "address_bytes": 3, "dummy_cycles": None, "data_direction": "read",
         "source_pages": [23]},
    ],
    "extraction_confidence": "medium", "source_pages": [23], "warnings": [],
}

BMP180_MAP = {"peripheral": "pressure-sensor", "chip": "BMP180",
              "provenance": {"chip": "user", "peripheral": "user"},
              "registers": [{"name": "CHIP_ID", "offset": "0xD0",
                             "fields": [], "source_pages": [18]}],
              "commands": [], "warnings": []}


def check_lines(text: str) -> dict:
    return {"gen.h": text.splitlines()}


def run_crosscheck(source: str, register_map: dict) -> ValidationReport:
    report = ValidationReport()
    crosscheck(check_lines(source), register_map, report)
    # unit tests target the cross-check only; mark the other checks green
    report.checks.setdefault("compile", "pass")
    report.checks.setdefault("static_analysis", "pass")
    return report.finalize()


# --- router ---------------------------------------------------------------------

def test_router_template_path():
    d = route(BMP180_MAP, "esp32", log=False)
    assert d.path == "template" and d.template_id == "bmp180-esp32-i2c"
    assert d.user_label == "Generated via validated template"


def test_router_llm_register_path():
    d = route(REGISTER_MAP, "stm32", log=False)
    assert (d.path, d.framing) == ("llm", "register")
    assert d.user_label == "Generated via AI with validation"


def test_router_llm_command_path():
    d = route(COMMAND_MAP, "esp32", log=False)
    assert (d.path, d.framing) == ("llm", "command")


def test_router_template_needs_platform_match():
    # BMP180 on an unsupported platform must NOT take the template path
    d = route(BMP180_MAP, "stm32", log=False)
    assert d.path == "llm"


# --- cross-check: three-state field logic (Amendment 1) --------------------------

def test_field_matching_map_is_validated():
    src = "#define I2C_CTR_TRANS_START_MASK (0x1 << 5)\n"
    r = run_crosscheck(src, REGISTER_MAP)
    assert r.status == "validated"
    assert not r.failures and not r.unverified_fields


def test_field_contradicting_map_is_hard_failure():
    src = "#define I2C_CTR_TRANS_START_MASK (0x1 << 7)\n"  # map says bit 5
    r = run_crosscheck(src, REGISTER_MAP)
    assert r.status == "failed"
    assert any("TRANS_START" in f.message for f in r.failures)


def test_field_absent_with_comment_is_unverified_not_failed():
    src = (
        "/* UNVERIFIED: bit positions not confirmed against datasheet — "
        "verify manually (see p.404) */\n"
        "#define I2C_SR_BUS_BUSY_MASK (0x1 << 4)\n"
    )
    r = run_crosscheck(src, REGISTER_MAP)
    assert r.status == "validated-with-unverified-fields"
    assert len(r.unverified_fields) == 1
    uf = r.unverified_fields[0]
    assert uf.register == "I2C_SR_REG" and uf.has_unverified_comment
    assert uf.claimed_bits == "[4:4]"


def test_field_absent_without_comment_is_hard_failure():
    src = "#define I2C_SR_BUS_BUSY_MASK (0x1 << 4)\n"
    r = run_crosscheck(src, REGISTER_MAP)
    assert r.status == "failed"
    assert any("UNVERIFIED" in f.message for f in r.failures)


def test_never_collapse_unverified_into_validated():
    src = (
        "#define I2C_CTR_TRANS_START_MASK (0x1 << 5)\n"
        "/* UNVERIFIED: bit positions not confirmed against datasheet */\n"
        "#define I2C_SR_BUS_BUSY_MASK (0x1 << 4)\n"
    )
    r = run_crosscheck(src, REGISTER_MAP)
    assert r.status == "validated-with-unverified-fields"  # not "validated"


# --- cross-check: offsets, opcodes, base parameterization ------------------------

def test_offset_not_in_map_is_hard_failure():
    src = "#define I2C_BOGUS_REG_OFFSET 0x0044\n"
    r = run_crosscheck(src, REGISTER_MAP)
    assert r.status == "failed"


def test_device_bus_address_is_not_a_register_offset():
    # BME280_I2C_ADDR = 0x76 is the I2C device (bus) address, not a register
    # offset — the _ADDR suffix must not get it cross-checked against the
    # register-offset table (regression: this false-failed a valid BME280 run).
    for name in ("BME280_I2C_ADDR", "BME280_DEV_ADDR", "BME280_SLAVE_ADDR"):
        r = run_crosscheck(f"#define {name} 0x76\n", REGISTER_MAP)
        assert r.status == "validated", (name, [f.message for f in r.failures])


def test_opcode_not_in_commands_is_hard_failure():
    src = "#define W25Q_CHIP_ERASE_CMD 0xC8\n"  # not in the commands array
    r = run_crosscheck(src, COMMAND_MAP)
    assert r.status == "failed"


def test_known_opcode_passes():
    src = "#define W25Q_WRITE_ENABLE_CMD 0x06\n#define W25Q_READ_DATA_CMD 0x03\n"
    r = run_crosscheck(src, COMMAND_MAP)
    assert r.status == "validated"


def test_hardcoded_absolute_address_fails_when_addressing_is_relative():
    # addendum-required case: absolute register address instead of BASE+offset
    src = "#define I2C_CTR_REG_ADDR 0x3FF53004\n"
    r = run_crosscheck(src, REGISTER_MAP)
    assert r.status == "failed"
    assert any("absolute" in f.message for f in r.failures)


def test_base_define_is_allowed_and_checked():
    ok = run_crosscheck("#define ESP32_I2C0_BASE 0x3FF53000\n", REGISTER_MAP)
    assert ok.status == "validated"
    bad = run_crosscheck("#define ESP32_I2C0_BASE 0x3FF67000\n", REGISTER_MAP)
    assert bad.status == "failed"


# --- worker prompt contract (Amendments 1 & 3) ------------------------------------

def test_prompt_declares_unknown_fields_and_addressing():
    d = route(REGISTER_MAP, "stm32", log=False)
    p = build_worker_prompt(REGISTER_MAP, d, "stm32")
    assert "I2C_SR_REG" in p and "fields are UNKNOWN" in p
    assert "UNVERIFIED" in p
    assert "base_address: 0x3FF53000" in p
    assert "never hard-code absolute addresses" in p


def test_prompt_command_framing():
    d = route(COMMAND_MAP, "esp32", log=False)
    p = build_worker_prompt(COMMAND_MAP, d, "esp32")
    assert "command-based device" in p and "opcode constants" in p


def test_retry_feedback_lands_in_prompt():
    d = route(REGISTER_MAP, "stm32", log=False)
    p = build_worker_prompt(REGISTER_MAP, d, "stm32", feedback="- [compile] x.c: boom")
    assert "PREVIOUS ATTEMPT FAILED VALIDATION" in p and "boom" in p


# --- retry loop and graceful fallback ---------------------------------------------

GOOD_RESPONSE = {
    "header_c": "#define I2C_CTR_TRANS_START_MASK (0x1 << 5)\n",
    "source_c": "int esp32_driver_ok(void);\nint esp32_driver_ok(void) { return 0; }\n",
    "example_c": "int esp32_example(void);\nint esp32_example(void) { return 0; }\n",
    "notes": "",
}
BAD_RESPONSE = dict(GOOD_RESPONSE, header_c="#define I2C_CTR_TRANS_START_MASK (0x1 << 7)\n")


def fake_validator(sequence):
    """Yields canned reports in order, so retry mechanics are tested without
    the real toolchain."""
    seq = list(sequence)

    def _validate(workdir, map_path, platform):
        return seq.pop(0) if seq else seq_final
    seq_final = {"status": "failed", "checks": {}, "failures": [
        {"check": "compile", "file": "x.c", "line": 1, "message": "seeded failure"}
    ], "unverified_fields": [], "notes": []}
    return _validate


FAILED_REPORT = {"status": "failed", "checks": {}, "failures": [
    {"check": "register_crosscheck", "file": "gen.h", "line": 1,
     "message": "seeded mismatch"}], "unverified_fields": [], "notes": []}
OK_REPORT = {"status": "validated", "checks": {"compile": "pass"},
             "failures": [], "unverified_fields": [], "notes": []}


def test_retry_then_success(tmp_path):
    provider = MockProvider([BAD_RESPONSE, GOOD_RESPONSE])
    result = generate_validated_driver(
        REGISTER_MAP, "stm32", provider, workdir_root=str(tmp_path),
        validate_fn=fake_validator([FAILED_REPORT, OK_REPORT]),
    )
    assert result["status"] == "validated"
    assert result["attempts"] == 2
    # the retry prompt carried the validator's failure artifact
    assert "seeded mismatch" in provider.calls[1][1]


def test_three_failures_then_graceful_fallback(tmp_path):
    provider = MockProvider([BAD_RESPONSE] * 4)
    result = generate_validated_driver(
        REGISTER_MAP, "stm32", provider, workdir_root=str(tmp_path),
        validate_fn=fake_validator([FAILED_REPORT] * 4),
    )
    assert result["status"] == "unvalidated"
    assert result["attempts"] == 4  # 1 initial + 3 retries, never more
    assert result["validation_failures"]          # exact failures attached
    assert result["register_map"] == REGISTER_MAP  # map attached for manual work
    assert "UNVALIDATED" in result["message"]


def test_template_route_short_circuits(tmp_path):
    provider = MockProvider([])
    result = generate_validated_driver(
        BMP180_MAP, "esp32", provider, workdir_root=str(tmp_path),
        validate_fn=fake_validator([]),
    )
    assert result["status"] == "template-path"
    assert provider.calls == []  # LLM never invoked for template families


# --- command-device end-to-end (W25Q64 map, real validator subprocess) ------------

W25Q_DRIVER = {
    "header_c": (
        "#ifndef W25Q64JV_DRIVER_H\n#define W25Q64JV_DRIVER_H\n"
        "#include <stdint.h>\n"
        "#define W25Q_WRITE_ENABLE_CMD 0x06\n"
        "#define W25Q_READ_DATA_CMD 0x03\n"
        "typedef int (*w25q_xfer_fn)(const uint8_t *tx, uint8_t *rx, uint32_t len);\n"
        "int w25q_write_enable(w25q_xfer_fn xfer);\n"
        "#endif\n"
    ),
    "source_c": (
        '#include "w25q64jv_driver.h"\n'
        "int w25q_write_enable(w25q_xfer_fn xfer) {\n"
        "    uint8_t op = W25Q_WRITE_ENABLE_CMD;\n"
        "    return xfer(&op, 0, 1u);\n}\n"
    ),
    "example_c": (
        '#include "w25q64jv_driver.h"\n'
        "static int null_xfer(const uint8_t *tx, uint8_t *rx, uint32_t len) {\n"
        "    (void)tx; (void)rx; (void)len; return 0;\n}\n"
        "int w25q_example(void);\n"
        "int w25q_example(void) { return w25q_write_enable(null_xfer); }\n"
    ),
    "notes": "",
}


def test_command_device_end_to_end_with_real_validator(tmp_path):
    provider = MockProvider([W25Q_DRIVER])
    result = generate_validated_driver(
        COMMAND_MAP, "esp32", provider, workdir_root=str(tmp_path)
    )  # default validate_fn -> real subprocess validator
    assert result["decision"]["framing"] == "command"
    assert result["status"] in ("validated", "validated-with-unverified-fields"), (
        result["reports"][-1]
    )
    checks = result["reports"][-1]["checks"]
    assert checks["register_crosscheck"] == "pass"
    assert checks["compile"] in ("pass", "skipped")


# --- contamination guard -----------------------------------------------------------

def _imported_modules(package_dir: str) -> set:
    import ast

    mods = set()
    for path in glob.glob(os.path.join(PROJECT_ROOT, package_dir, "*.py")):
        tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
    return mods


def test_validator_never_imports_generation():
    assert "generation" not in _imported_modules("validator")


def test_generation_never_imports_validator():
    assert "validator" not in _imported_modules("generation")


def test_pipeline_runs_validator_as_subprocess():
    text = open(os.path.join(PROJECT_ROOT, "generation", "pipeline.py"),
                encoding="utf-8").read()
    assert "subprocess" in text and '"-m", "validator"' in text
