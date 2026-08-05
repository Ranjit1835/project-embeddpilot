/* Mirrors schema/register-map.schema.json and the WS2 pipeline payloads. */

export interface BitField {
  name: string;
  bits: string; // "[msb:lsb]"
  description?: string;
}

export interface Register {
  name: string;
  offset: string; // "0x.."
  reset_value?: string | null;
  access?: "RW" | "RO" | "WO" | null;
  fields: BitField[];
  confidence?: "high" | "medium" | "low";
  source_pages: number[];
}

export interface Command {
  name: string;
  opcode: string;
  description?: string;
  address_bytes?: number | null;
  dummy_cycles?: number | null;
  data_direction?: "read" | "write" | "none" | null;
  source_pages: number[];
}

export interface DetectedValue {
  value: string;
  confidence: "high" | "medium" | "low";
  source_pages: number[];
}

/** Origin of an input field. 'user' or 'detected' generate; 'detected_unconfirmed'
    or null are blocked until the user confirms/corrects on the review screen. */
export type Provenance = "user" | "detected" | "detected_unconfirmed" | null;

export interface RegisterMap {
  peripheral: string;
  chip: string;
  base_address?: string | null;
  registers: Register[];
  commands?: Command[];
  extraction_confidence: "high" | "medium" | "low";
  source_pages: number[];
  warnings?: string[];
  low_confidence_pages?: number[];
  detected?: {
    chip?: DetectedValue;
    vendor?: DetectedValue;
    shape_hint?: DetectedValue;
    interfaces?: DetectedValue[];
  };
  provenance?: { chip?: Provenance; peripheral?: Provenance };
}

/** Canonical target platforms (Priority 3). Value is the token sent to the
    backend; the validator maps each to a toolchain + HAL convention. */
export const PLATFORMS: { value: string; label: string }[] = [
  { value: "stm32", label: "STM32" },
  { value: "esp32", label: "ESP32" },
  { value: "nxp", label: "NXP" },
  { value: "ti", label: "TI" },
  { value: "raspberry-pi", label: "Raspberry Pi" },
  { value: "avr", label: "AVR / Arduino" },
  { value: "cortex-m", label: "Generic ARM Cortex-M" },
  { value: "other", label: "Other (specify)" },
];

export interface RouteDecision {
  path: "template" | "llm";
  framing: "register" | "command" | null;
  template_id: string | null;
  reason: string;
  user_label: string;
}

export interface Failure {
  check: string;
  file: string;
  line: number | null;
  message: string;
}

export interface UnverifiedField {
  file: string;
  line: number;
  register: string;
  define: string;
  claimed_bits: string;
  has_unverified_comment: boolean;
  source_pages: number[];
}

export type CheckState = "pass" | "fail" | "skipped";

export interface ValidationReport {
  status: "validated" | "validated-with-unverified-fields" | "failed";
  checks: Record<string, CheckState>;
  failures: Failure[];
  unverified_fields: UnverifiedField[];
  notes: string[];
}

export interface GenerationResult {
  status:
    | "validated"
    | "validated-with-unverified-fields"
    | "unvalidated"
    | "template-path";
  decision: RouteDecision;
  files?: Record<string, string>;
  attempts?: number;
  reports?: ValidationReport[];
  unverified_fields?: UnverifiedField[];
  validation_failures?: Failure[];
  register_map?: RegisterMap;
  provider?: string;
  message?: string;
  user_edits?: string[];
}

export type JobEvent =
  | { ts: number; type: "stage"; stage: string }
  | { ts: number; type: "route"; decision: RouteDecision }
  | { ts: number; type: "attempt_start"; attempt: number }
  | { ts: number; type: "attempt_report"; attempt: number; report: ValidationReport }
  | { ts: number; type: "job_done"; status: "done" | "error"; error: string | null };

export interface Sample {
  id: string;
  platform: string;
  label: string;
}
