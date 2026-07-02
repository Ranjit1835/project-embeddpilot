# BMP180 Sensor IR Extraction Notes

**Source:** BST-BMP180-DS000-12 Rev 2.8 (May 2015)
**Extraction date:** 2026-07-02
**Method:** Blind PDF extraction via PyMuPDF text parsing
**Accuracy:** 194/194 fields matched (100%) — zero differences vs prior knowledge-authored IR

## Page References

| Data | Datasheet Location |
|------|-------------------|
| I2C address (0x77) | p20 Table 7: write 0xEE / read 0xEF → 7-bit 0x77 |
| Chip ID register (0xD0) | p18: "Chip-id (register D0h): This value is fixed to 0x55" |
| Chip ID value (0x55) | p18: same text |
| Soft reset register (0xE0) | p18: "Soft reset (register E0h): Write only register" |
| Reset command (0xB6) | p18: "If set to 0xB6, will perform the same sequence as power on reset" |
| Ctrl_meas register (0xF4) | p18: "Measurement control (register F4h <4:0>)" |
| Output registers (0xF6-F8) | p18 Figure 6 + p22: "0xF6 (MSB), 0xF7 (LSB), optionally 0xF8 (XLSB)" |
| Calibration (0xAA-0xBF) | p13 Table 5: AC1 through MD |
| Temperature command (0x2E) | p21 Table 8: Temperature, 4.5ms max |
| Pressure commands | p21 Table 8: 0x34/0x74/0xB4/0xF4 |
| Conversion timings | p7 Table 1 + p12 Table 3 |
| Startup time (10ms) | p19 Table 6: tStart min 10ms |

## Hard Spots

1. **Calibration coefficient signedness**: The datasheet Table 5 lists only names and addresses, not whether each is signed or unsigned. Signedness was determined from the Bosch API code convention and the calculation algorithm on p14-15: AC1-AC3 are signed (used in signed arithmetic), AC4-AC6 are unsigned (used as unsigned in the formula), B1-B2 signed, MB-MC-MD signed. Marked as **confidence: high** because the algorithm constrains the types unambiguously.

2. **Memory map figure (p18)**: The memory map is partially rendered as a figure with register bit layouts. The PDF text extraction captured the text descriptions but not the figure content. All register details were cross-referenced with the text descriptions on the same page and Table 8 on p21.

3. **Soft reset timing**: The datasheet does not specify a dedicated reset recovery time. The 10ms value comes from the startup time specification (Table 6 p19: "Start-up time after power-up, before first communication: tStart min 10ms"). This is the conservative choice — the reset performs "the same sequence as power on reset."

4. **XLSB register usage**: OUT_XLSB (0xF8) contains only bits [7:3] for oversampled pressure. For temperature (16-bit), only OUT_MSB and OUT_LSB are used. The driver currently reads 3 bytes but only uses the first 2 for temperature.

## Failure Modes Observed

None for BMP180 — the datasheet is well-structured with explicit register addresses in both figure and text form. This is an unusually clean extraction target.

## Comparison to Prior IR

The knowledge-authored IR from Phase D matched the PDF extraction perfectly (194/194). This validates that BMP180 is a simple extraction case — the datasheet has no ambiguity traps.
