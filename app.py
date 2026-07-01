"""
EmbeddPilot V1 — Web Demo

Interactive demo of the AI pipeline that turns MCU datasheets
into simulation-verified C drivers.
"""

import json
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).parent
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
DRIVERS_DIR = PROJECT_ROOT / "drivers" / "generated"
SCHEMA_DIR = PROJECT_ROOT / "schema"

st.set_page_config(
    page_title="EmbeddPilot V1",
    page_icon="🔧",
    layout="wide",
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- Header ---
st.title("EmbeddPilot V1")
st.markdown("**AI pipeline that turns MCU datasheets into simulation-verified C drivers.**")
st.markdown("---")

# --- Pipeline Overview ---
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Registers", "36")
col2.metric("Bit Fields", "191")
col3.metric("Header Lines", "1,039")
col4.metric("Driver Lines", "174")
col5.metric("Determinism", "10/10")

st.markdown("---")

# --- Tabs ---
tab_pipeline, tab_ir, tab_driver, tab_header, tab_proof = st.tabs([
    "Pipeline", "Register Map IR", "Generated Driver", "Register Header", "Verification Proof",
])

# --- Pipeline Tab ---
with tab_pipeline:
    st.subheader("How It Works")
    st.markdown("""
    ```
    ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
    │  Datasheet   │────▶│  Register    │────▶│    Code      │────▶│   Wokwi      │────▶│  Verified    │
    │  (PDF)       │     │  Map IR      │     │  Generation  │     │  Simulation  │     │  Driver      │
    └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
    ESP32 TRM             36 registers         driver.cpp           5/5 tests PASS       + proof.txt
    Chapter 11            191 fields           i2c0_regs.h          BMP180 I2C           + report.json
    ```
    """)

    st.subheader("V1 Exit Criteria — All Passed")
    checks = [
        ("Extraction", "IR JSON produced from datasheet, schema-valid, validator verdict PASS"),
        ("Harness", "Wokwi sim discriminates correct vs broken drivers (reference 5/5, corrupted 4/5 FAIL)"),
        ("Codegen", "Generated driver compiles under PlatformIO without errors"),
        ("Verification", "Generated driver passes all 5 harness scenarios in Wokwi sim"),
        ("Self-correction", "Pipeline completes on first attempt (5/5 PASS)"),
        ("Determinism", "10/10 identical passing runs confirmed"),
        ("Wrapper", "One-command interface: python embeddpilot.py"),
    ]
    for name, desc in checks:
        st.checkbox(f"**{name}**: {desc}", value=True, disabled=True)

    st.subheader("Target Configuration")
    c1, c2, c3 = st.columns(3)
    c1.info("**MCU**: ESP32-WROOM-32\n\n**Peripheral**: I2C0 (master mode)")
    c2.info("**Sensor**: BMP180 (0x77)\n\n**Simulator**: Wokwi CLI")
    c3.info("**Framework**: Arduino (Wire)\n\n**Build**: PlatformIO")

# --- IR Tab ---
with tab_ir:
    st.subheader("ESP32 I2C0 Register Map — Extracted from Datasheet")

    ir_path = ARTIFACTS_DIR / "register-ir.json"
    if ir_path.exists():
        ir = load_json(ir_path)
        st.markdown(f"**Peripheral**: `{ir['peripheral']}` | **Base Address**: `{ir['base_address']}` | **Registers**: {len(ir['registers'])}")

        search = st.text_input("Filter registers", placeholder="e.g. CTR, FIFO, INT...")
        regs = ir["registers"]
        if search:
            regs = [r for r in regs if search.upper() in r["name"].upper()]

        for reg in regs:
            with st.expander(f"`{reg['offset']}` — **{reg['name']}** ({len(reg.get('fields', []))} fields, reset: {reg.get('reset_value', 'N/A')})"):
                st.markdown(f"*{reg.get('description', 'No description')}*")
                if reg.get("fields"):
                    field_data = []
                    for f in reg["fields"]:
                        field_data.append({
                            "Name": f["name"],
                            "Bits": f"[{f['bit_offset'] + f['width'] - 1}:{f['bit_offset']}]",
                            "Width": f["width"],
                            "Access": f["access"],
                            "Reset": f.get("reset_value", 0),
                            "Description": f.get("description", "")[:80],
                        })
                    st.dataframe(field_data, use_container_width=True, hide_index=True)
    else:
        st.warning("IR file not found. Run the pipeline locally first.")

# --- Driver Tab ---
with tab_driver:
    st.subheader("AI-Generated Driver — driver.cpp")
    driver_path = DRIVERS_DIR / "driver.cpp"
    if driver_path.exists():
        code = load_text(driver_path)
        st.code(code, language="cpp", line_numbers=True)
        st.download_button("Download driver.cpp", code, file_name="driver.cpp", mime="text/x-c")
    else:
        st.warning("Driver not generated yet.")

# --- Header Tab ---
with tab_header:
    st.subheader("Register Definitions — i2c0_regs.h")
    header_path = DRIVERS_DIR / "i2c0_regs.h"
    if header_path.exists():
        code = load_text(header_path)
        st.code(code, language="c", line_numbers=True)
        st.download_button("Download i2c0_regs.h", code, file_name="i2c0_regs.h", mime="text/x-c")
    else:
        st.warning("Header not generated yet.")

# --- Proof Tab ---
with tab_proof:
    st.subheader("Pipeline Verification Report")
    report_path = ARTIFACTS_DIR / "pipeline_report.json"
    if report_path.exists():
        report = load_json(report_path)
        st.markdown(f"**Timestamp**: {report.get('timestamp', 'N/A')}")
        st.markdown(f"**Final Verdict**: `{report.get('final_verdict', 'UNKNOWN')}`")

        for it in report.get("iterations", []):
            st.markdown(f"### Attempt {it['attempt']}")
            for step_name, step_result in it.get("steps", {}).items():
                if isinstance(step_result, dict):
                    passed = step_result.get("passed", 0)
                    failed = step_result.get("failed", 0)
                    if failed == 0:
                        st.success(f"**{step_name}**: {passed} passed, {failed} failed")
                    else:
                        st.error(f"**{step_name}**: {passed} passed, {failed} failed")
                    if step_result.get("tests"):
                        for t in step_result["tests"]:
                            icon = "✅" if t["status"] == "PASS" else "❌"
                            st.markdown(f"  {icon} `{t['name']}`")
                else:
                    if step_result == "PASS":
                        st.success(f"**{step_name}**: {step_result}")
                    elif step_result == "SKIPPED":
                        st.info(f"**{step_name}**: {step_result}")
                    else:
                        st.error(f"**{step_name}**: {step_result}")

        st.markdown("---")
        st.json(report)
    else:
        st.warning("No pipeline report found.")

# --- Footer ---
st.markdown("---")
st.markdown(
    "**EmbeddPilot V1** — "
    "[GitHub](https://github.com/Ranjit1835/project-embeddpilot) · "
    "Built with Claude Code"
)
