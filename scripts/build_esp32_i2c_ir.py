#!/usr/bin/env python3
"""Build the ESP32 I2C register-map IR from manually verified datasheet data.

Source: ESP32 Technical Reference Manual v5.7, Chapter 21 (pages 401-414).
Every value here is cross-checked against the register diagrams and descriptions.
"""

import json
from datetime import datetime, timezone

INT_FIELDS_13 = [
    ("I2C_TX_SEND_EMPTY_INT", 12),
    ("I2C_RX_REC_FULL_INT", 11),
    ("I2C_ACK_ERR_INT", 10),
    ("I2C_TRANS_START_INT", 9),
    ("I2C_TIME_OUT_INT", 8),
    ("I2C_TRANS_COMPLETE_INT", 7),
    ("I2C_MASTER_TRAN_COMP_INT", 6),
    ("I2C_ARBITRATION_LOST_INT", 5),
    ("I2C_SLAVE_TRAN_COMP_INT", 4),
    ("I2C_END_DETECT_INT", 3),
    ("I2C_RXFIFO_OVF_INT", 2),
    ("I2C_TXFIFO_EMPTY_INT", 1),
    ("I2C_RXFIFO_FULL_INT", 0),
]

INT_DESCRIPTIONS = {
    "I2C_TX_SEND_EMPTY_INT": "TX send empty",
    "I2C_RX_REC_FULL_INT": "RX receive full",
    "I2C_ACK_ERR_INT": "ACK error",
    "I2C_TRANS_START_INT": "Transaction start",
    "I2C_TIME_OUT_INT": "Timeout",
    "I2C_TRANS_COMPLETE_INT": "Transaction complete",
    "I2C_MASTER_TRAN_COMP_INT": "Master transaction complete",
    "I2C_ARBITRATION_LOST_INT": "Arbitration lost",
    "I2C_SLAVE_TRAN_COMP_INT": "Slave transaction complete",
    "I2C_END_DETECT_INT": "END command detected",
    "I2C_RXFIFO_OVF_INT": "RX FIFO overflow",
    "I2C_TXFIFO_EMPTY_INT": "TX FIFO empty threshold",
    "I2C_RXFIFO_FULL_INT": "RX FIFO full threshold",
}


def make_int_reg(name, offset, suffix, access, desc_template):
    fields = []
    for base_name, bit in INT_FIELDS_13:
        fname = f"{base_name}_{suffix}"
        fields.append({
            "name": fname,
            "bit_offset": bit,
            "width": 1,
            "access": access,
            "reset_value": 0,
            "description": desc_template.format(INT_DESCRIPTIONS[base_name]),
            "confidence": "high",
        })
    return {
        "name": name,
        "offset": offset,
        "size_bits": 32,
        "reset_value": "0x00000000",
        "description": f"I2C interrupt {suffix.lower().replace('_', ' ')} register.",
        "fields": sorted(fields, key=lambda f: f["bit_offset"]),
        "confidence": "high",
    }


def build_ir():
    registers = []

    # Register 21.1: I2C_SCL_LOW_PERIOD_REG (0x0000)
    registers.append({
        "name": "I2C_SCL_LOW_PERIOD_REG",
        "offset": "0x0000",
        "size_bits": 32,
        "reset_value": "0x00000000",
        "description": "Configures the low level width of the SCL clock.",
        "fields": [
            {
                "name": "I2C_SCL_LOW_PERIOD",
                "bit_offset": 0,
                "width": 14,
                "access": "RW",
                "reset_value": 0,
                "description": "Configures for how long SCL remains low in master mode, in APB clock cycles.",
                "confidence": "high",
            }
        ],
        "confidence": "high",
    })

    # Register 21.2: I2C_CTR_REG (0x0004)
    registers.append({
        "name": "I2C_CTR_REG",
        "offset": "0x0004",
        "size_bits": 32,
        "reset_value": "0x00000003",
        "description": "Transmission configuration register.",
        "fields": [
            {"name": "I2C_SDA_FORCE_OUT", "bit_offset": 0, "width": 1, "access": "RW", "reset_value": 1,
             "description": "0: direct output; 1: open drain output.", "confidence": "high"},
            {"name": "I2C_SCL_FORCE_OUT", "bit_offset": 1, "width": 1, "access": "RW", "reset_value": 1,
             "description": "0: direct output; 1: open drain output.", "confidence": "high"},
            {"name": "I2C_SAMPLE_SCL_LEVEL", "bit_offset": 2, "width": 1, "access": "RW", "reset_value": 0,
             "description": "1: sample SDA on SCL low level; 0: sample SDA on SCL high level.", "confidence": "high"},
            {"name": "I2C_MS_MODE", "bit_offset": 4, "width": 1, "access": "RW", "reset_value": 0,
             "description": "Set to configure as I2C Master. Clear to configure as I2C Slave.",
             "enum_values": {"0": "Slave", "1": "Master"}, "confidence": "high"},
            {"name": "I2C_TRANS_START", "bit_offset": 5, "width": 1, "access": "RW", "reset_value": 0,
             "description": "Set this bit to start sending the data in txfifo.", "confidence": "high"},
            {"name": "I2C_TX_LSB_FIRST", "bit_offset": 6, "width": 1, "access": "RW", "reset_value": 0,
             "description": "1: send data from LSB; 0: send data from MSB.", "confidence": "high"},
            {"name": "I2C_RX_LSB_FIRST", "bit_offset": 7, "width": 1, "access": "RW", "reset_value": 0,
             "description": "1: receive data from LSB; 0: receive data from MSB.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.3: I2C_SR_REG (0x0008)
    registers.append({
        "name": "I2C_SR_REG",
        "offset": "0x0008",
        "size_bits": 32,
        "reset_value": "0x00000000",
        "description": "Describes I2C work status.",
        "fields": [
            {"name": "I2C_ACK_REC", "bit_offset": 0, "width": 1, "access": "RO", "reset_value": 0,
             "description": "Stores the value of the received ACK bit.", "confidence": "high"},
            {"name": "I2C_SLAVE_RW", "bit_offset": 1, "width": 1, "access": "RO", "reset_value": 0,
             "description": "In slave mode, 1: master reads from slave; 0: master writes to slave.", "confidence": "high"},
            {"name": "I2C_TIME_OUT", "bit_offset": 2, "width": 1, "access": "RO", "reset_value": 0,
             "description": "When the I2C controller takes more than I2C_TIME_OUT clocks to receive a data bit, changes to 1.", "confidence": "high"},
            {"name": "I2C_ARB_LOST", "bit_offset": 3, "width": 1, "access": "RO", "reset_value": 0,
             "description": "When the I2C controller loses control of SCL line, changes to 1.", "confidence": "high"},
            {"name": "I2C_BUS_BUSY", "bit_offset": 4, "width": 1, "access": "RO", "reset_value": 0,
             "description": "1: I2C bus is busy transferring data; 0: I2C bus is idle.", "confidence": "high"},
            {"name": "I2C_SLAVE_ADDRESSED", "bit_offset": 5, "width": 1, "access": "RO", "reset_value": 0,
             "description": "High when configured as slave and address sent by master matches slave address.", "confidence": "high"},
            {"name": "I2C_BYTE_TRANS", "bit_offset": 6, "width": 1, "access": "RO", "reset_value": 0,
             "description": "Changes to 1 when one byte is transferred.", "confidence": "high"},
            {"name": "I2C_RXFIFO_CNT", "bit_offset": 8, "width": 6, "access": "RO", "reset_value": 0,
             "description": "Amount of data needed to be sent.", "confidence": "high"},
            {"name": "I2C_TXFIFO_CNT", "bit_offset": 18, "width": 6, "access": "RO", "reset_value": 0,
             "description": "Amount of received data in RAM.", "confidence": "high"},
            {"name": "I2C_SCL_MAIN_STATE_LAST", "bit_offset": 24, "width": 3, "access": "RO", "reset_value": 0,
             "description": "States of I2C module state machine.",
             "enum_values": {"0": "Idle", "1": "Address shift", "2": "ACK address", "3": "Rx data", "4": "Tx data", "5": "Send ACK", "6": "Wait ACK"},
             "confidence": "high"},
            {"name": "I2C_SCL_STATE_LAST", "bit_offset": 28, "width": 3, "access": "RO", "reset_value": 0,
             "description": "States of the state machine used to produce SCL.",
             "enum_values": {"0": "Idle", "1": "Start", "2": "Negative edge", "3": "Low", "4": "Positive edge", "5": "High", "6": "Stop"},
             "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.4: I2C_TO_REG (0x000C)
    registers.append({
        "name": "I2C_TO_REG",
        "offset": "0x000c",
        "size_bits": 32,
        "reset_value": "0x00000000",
        "description": "Timeout control register.",
        "fields": [
            {"name": "I2C_TIME_OUT_REG", "bit_offset": 0, "width": 20, "access": "RW", "reset_value": 0,
             "description": "Timeout for receiving a data bit in APB clock cycles.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.5: I2C_SLAVE_ADDR_REG (0x0010)
    registers.append({
        "name": "I2C_SLAVE_ADDR_REG",
        "offset": "0x0010",
        "size_bits": 32,
        "reset_value": "0x00000000",
        "description": "Configures the I2C slave address.",
        "fields": [
            {"name": "I2C_SLAVE_ADDR", "bit_offset": 0, "width": 15, "access": "RW", "reset_value": 0,
             "description": "When configured as I2C Slave, this field configures the slave address.", "confidence": "high"},
            {"name": "I2C_SLAVE_ADDR_10BIT_EN", "bit_offset": 31, "width": 1, "access": "RW", "reset_value": 0,
             "description": "Enables slave 10-bit addressing mode in master mode.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.6: I2C_RXFIFO_ST_REG (0x0014)
    registers.append({
        "name": "I2C_RXFIFO_ST_REG",
        "offset": "0x0014",
        "size_bits": 32,
        "reset_value": "0x00000000",
        "description": "FIFO status register.",
        "fields": [
            {"name": "I2C_RXFIFO_START_ADDR", "bit_offset": 0, "width": 5, "access": "RO", "reset_value": 0,
             "description": "Offset address of the last received data, as described in nonfifo_rx_thres register.", "confidence": "high"},
            {"name": "I2C_RXFIFO_END_ADDR", "bit_offset": 5, "width": 5, "access": "RO", "reset_value": 0,
             "description": "Offset address of the last received data. Refreshes when RX_REC_FULL_INT or TRANS_COMPLETE_INT is generated.", "confidence": "high"},
            {"name": "I2C_TXFIFO_START_ADDR", "bit_offset": 10, "width": 5, "access": "RO", "reset_value": 0,
             "description": "Offset address of the first sent data, as described in nonfifo_tx_thres register.", "confidence": "high"},
            {"name": "I2C_TXFIFO_END_ADDR", "bit_offset": 15, "width": 5, "access": "RO", "reset_value": 0,
             "description": "Offset address of the last sent data. Refreshes when TX_SEND_EMPTY_INT or TRANS_COMPLETE_INT is generated.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.7: I2C_FIFO_CONF_REG (0x0018)
    registers.append({
        "name": "I2C_FIFO_CONF_REG",
        "offset": "0x0018",
        "size_bits": 32,
        "reset_value": "0x01554000",
        "description": "FIFO configuration register.",
        "fields": [
            {"name": "I2C_RXFIFO_FULL_THRHD", "bit_offset": 0, "width": 5, "access": "RW", "reset_value": 0,
             "description": "RX FIFO threshold in non-FIFO mode. When RX FIFO count > this value, RXFIFO_FULL_INT_RAW is valid.", "confidence": "high"},
            {"name": "I2C_TXFIFO_EMPTY_THRHD", "bit_offset": 5, "width": 5, "access": "RW", "reset_value": 0,
             "description": "TX FIFO threshold in non-FIFO mode. When TX FIFO count > this value, TXFIFO_EMPTY_INT_RAW is valid.", "confidence": "high"},
            {"name": "I2C_NONFIFO_EN", "bit_offset": 10, "width": 1, "access": "RW", "reset_value": 0,
             "description": "Set to enable APB nonfifo access.", "confidence": "high"},
            {"name": "I2C_FIFO_ADDR_CFG_EN", "bit_offset": 11, "width": 1, "access": "RW", "reset_value": 0,
             "description": "When set, byte received after I2C address byte represents offset address in I2C Slave RAM.", "confidence": "high"},
            {"name": "I2C_NONFIFO_RX_THRES", "bit_offset": 14, "width": 6, "access": "RW", "reset_value": 21,
             "description": "When I2C receives more than this many bytes, rx_send_full_int_raw interrupt is generated.", "confidence": "high"},
            {"name": "I2C_NONFIFO_TX_THRES", "bit_offset": 20, "width": 6, "access": "RW", "reset_value": 21,
             "description": "When I2C sends more than this many bytes, tx_send_empty_int_raw interrupt is generated.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.8: I2C_INT_RAW_REG (0x0020)
    registers.append(make_int_reg(
        "I2C_INT_RAW_REG", "0x0020", "RAW", "RO",
        "Raw interrupt status bit for {} interrupt."
    ))

    # Register 21.9: I2C_INT_CLR_REG (0x0024)
    registers.append(make_int_reg(
        "I2C_INT_CLR_REG", "0x0024", "CLR", "WO",
        "Set this bit to clear the {} interrupt."
    ))

    # Register 21.10: I2C_INT_ENA_REG (0x0028)
    registers.append(make_int_reg(
        "I2C_INT_ENA_REG", "0x0028", "ENA", "RW",
        "Interrupt enable bit for {} interrupt."
    ))

    # Register 21.11: I2C_INT_STATUS_REG (0x002C)
    registers.append(make_int_reg(
        "I2C_INT_STATUS_REG", "0x002c", "ST", "RO",
        "Masked interrupt status bit for {} interrupt."
    ))

    # Register 21.12: I2C_SDA_HOLD_REG (0x0030)
    registers.append({
        "name": "I2C_SDA_HOLD_REG",
        "offset": "0x0030",
        "size_bits": 32,
        "reset_value": "0x00000000",
        "description": "Configures the hold time after a negative SCL edge.",
        "fields": [
            {"name": "I2C_SDA_HOLD_TIME", "bit_offset": 0, "width": 10, "access": "RW", "reset_value": 0,
             "description": "Time to hold data after the negative edge of SCL, in APB clock cycles.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.13: I2C_SDA_SAMPLE_REG (0x0034)
    registers.append({
        "name": "I2C_SDA_SAMPLE_REG",
        "offset": "0x0034",
        "size_bits": 32,
        "reset_value": "0x00000000",
        "description": "Configures the sample time after a positive SCL edge.",
        "fields": [
            {"name": "I2C_SDA_SAMPLE_TIME", "bit_offset": 0, "width": 10, "access": "RW", "reset_value": 0,
             "description": "Time to sample SDA after the positive edge of SCL, in APB clock cycles.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.14: I2C_SCL_HIGH_PERIOD_REG (0x0038)
    registers.append({
        "name": "I2C_SCL_HIGH_PERIOD_REG",
        "offset": "0x0038",
        "size_bits": 32,
        "reset_value": "0x00000000",
        "description": "Configures the high level width of the SCL clock.",
        "fields": [
            {"name": "I2C_SCL_HIGH_PERIOD", "bit_offset": 0, "width": 14, "access": "RW", "reset_value": 0,
             "description": "Configures for how long SCL remains high in master mode, in APB clock cycles.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Note: offset 0x003C is not documented — gap between 0x0038 and 0x0040

    # Register 21.15: I2C_SCL_START_HOLD_REG (0x0040)
    registers.append({
        "name": "I2C_SCL_START_HOLD_REG",
        "offset": "0x0040",
        "size_bits": 32,
        "reset_value": "0x00000008",
        "description": "Configures the delay between the SDA and SCL negative edge for a start condition.",
        "fields": [
            {"name": "I2C_SCL_START_HOLD_TIME", "bit_offset": 0, "width": 10, "access": "RW", "reset_value": 8,
             "description": "Time between negative edge of SDA and negative edge of SCL for START condition, in APB clock cycles.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.16: I2C_SCL_RSTART_SETUP_REG (0x0044)
    registers.append({
        "name": "I2C_SCL_RSTART_SETUP_REG",
        "offset": "0x0044",
        "size_bits": 32,
        "reset_value": "0x00000008",
        "description": "Configures the delay between the positive edge of SCL and the negative edge of SDA for a RESTART condition.",
        "fields": [
            {"name": "I2C_SCL_RSTART_SETUP_TIME", "bit_offset": 0, "width": 10, "access": "RW", "reset_value": 8,
             "description": "Time between positive edge of SCL and negative edge of SDA for RESTART condition, in APB clock cycles.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.17: I2C_SCL_STOP_HOLD_REG (0x0048)
    registers.append({
        "name": "I2C_SCL_STOP_HOLD_REG",
        "offset": "0x0048",
        "size_bits": 32,
        "reset_value": "0x00000000",
        "description": "Configures the delay after the SCL clock edge for a stop condition.",
        "fields": [
            {"name": "I2C_SCL_STOP_HOLD_TIME", "bit_offset": 0, "width": 14, "access": "RW", "reset_value": 0,
             "description": "Delay after the STOP condition, in APB clock cycles.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.18: I2C_SCL_STOP_SETUP_REG (0x004C)
    registers.append({
        "name": "I2C_SCL_STOP_SETUP_REG",
        "offset": "0x004c",
        "size_bits": 32,
        "reset_value": "0x00000000",
        "description": "Configures the delay between the SDA and SCL positive edge for a stop condition.",
        "fields": [
            {"name": "I2C_SCL_STOP_SETUP_TIME", "bit_offset": 0, "width": 10, "access": "RW", "reset_value": 0,
             "description": "Time between positive edge of SCL and positive edge of SDA, in APB clock cycles.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.19: I2C_SCL_FILTER_CFG_REG (0x0050)
    registers.append({
        "name": "I2C_SCL_FILTER_CFG_REG",
        "offset": "0x0050",
        "size_bits": 32,
        "reset_value": "0x00000008",
        "description": "SCL filter configuration register.",
        "fields": [
            {"name": "I2C_SCL_FILTER_THRES", "bit_offset": 0, "width": 3, "access": "RW", "reset_value": 0,
             "description": "Pulses on SCL shorter than this value in APB clock cycles are ignored.", "confidence": "high"},
            {"name": "I2C_SCL_FILTER_EN", "bit_offset": 3, "width": 1, "access": "RW", "reset_value": 1,
             "description": "Filter enable bit for SCL.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.20: I2C_SDA_FILTER_CFG_REG (0x0054)
    registers.append({
        "name": "I2C_SDA_FILTER_CFG_REG",
        "offset": "0x0054",
        "size_bits": 32,
        "reset_value": "0x00000008",
        "description": "SDA filter configuration register.",
        "fields": [
            {"name": "I2C_SDA_FILTER_THRES", "bit_offset": 0, "width": 3, "access": "RW", "reset_value": 0,
             "description": "Pulses on SDA shorter than this value in APB clock cycles are ignored.", "confidence": "high"},
            {"name": "I2C_SDA_FILTER_EN", "bit_offset": 3, "width": 1, "access": "RW", "reset_value": 1,
             "description": "Filter enable bit for SDA.", "confidence": "high"},
        ],
        "confidence": "high",
    })

    # Register 21.21: I2C_COMDn_REG (n: 0-15) at 0x0058 + 4*n
    # Sub-field layout confirmed via ESP-IDF v5.3 i2c_struct.h:
    #   byte_num[7:0], ack_en[8], ack_exp[9], ack_val[10], op_code[13:11], done[31]
    for n in range(16):
        offset = 0x0058 + 4 * n
        registers.append({
            "name": f"I2C_COMD{n}_REG",
            "offset": f"0x{offset:04x}",
            "size_bits": 32,
            "reset_value": "0x00000000",
            "description": f"I2C command register {n}.",
            "fields": [
                {"name": f"I2C_COMMAND{n}_BYTE_NUM", "bit_offset": 0, "width": 8, "access": "RW", "reset_value": 0,
                 "description": "Number of bytes to read or written. Max 255, min 1. Meaningless for RSTART/STOP/END.",
                 "confidence": "high"},
                {"name": f"I2C_COMMAND{n}_ACK_EN", "bit_offset": 8, "width": 1, "access": "RW", "reset_value": 0,
                 "description": "Enable ACK value checking for transmitter. 1: enabled, 0: disabled.",
                 "confidence": "high"},
                {"name": f"I2C_COMMAND{n}_ACK_EXP", "bit_offset": 9, "width": 1, "access": "RW", "reset_value": 0,
                 "description": "Expected ACK value for the transmitter.",
                 "confidence": "high"},
                {"name": f"I2C_COMMAND{n}_ACK_VAL", "bit_offset": 10, "width": 1, "access": "RW", "reset_value": 0,
                 "description": "When receiving data, indicates whether receiver sends ACK after this byte.",
                 "confidence": "high"},
                {"name": f"I2C_COMMAND{n}_OP_CODE", "bit_offset": 11, "width": 3, "access": "RW", "reset_value": 0,
                 "description": "Command opcode.",
                 "enum_values": {"0": "RSTART", "1": "WRITE", "2": "READ", "3": "STOP", "4": "END"},
                 "confidence": "high"},
                {"name": f"I2C_COMMAND{n}_DONE", "bit_offset": 31, "width": 1, "access": "RW", "reset_value": 0,
                 "description": "When command n is done in I2C Master mode, this bit changes to high level.",
                 "confidence": "high"},
            ],
            "confidence": "high",
        })

    ir = {
        "peripheral": "I2C0",
        "base_address": "0x3FF53000",
        "register_size_bits": 32,
        "registers": registers,
        "meta": {
            "datasheet_source": "esp32_technical_reference_manual_en.pdf",
            "datasheet_version": "V5.7",
            "mcu_family": "ESP32",
            "mcu_part": "ESP32-WROOM-32",
            "extraction_tool": "manual_extraction_with_pymupdf",
            "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
            "schema_version": "1.0.0",
        },
    }

    return ir


if __name__ == "__main__":
    ir = build_ir()
    out_path = r"C:\Users\perimilla charani\Desktop\project-embeddpilot\artifacts\register-ir.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ir, f, indent=2, ensure_ascii=False)

    reg_count = len(ir["registers"])
    field_count = sum(len(r["fields"]) for r in ir["registers"])
    print(f"Generated IR: {reg_count} registers, {field_count} fields")
    print(f"Written to: {out_path}")
