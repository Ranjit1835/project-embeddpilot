/* Demo fixtures for the V2 Resource Map — the offline fallback.

   Precedent: lib/demo.ts + demo-data.json do this for the V1 wizard, so a
   hosted case study still demonstrates the product with no Python backend.

   WHAT MAKES THIS SAFE
   --------------------
   These are `AnalyzeResponse` / `BuildResult` values in the SAME shape the real
   API returns, so demo mode goes through the identical adapters and renderer
   (lib/v2-view.ts). There is no demo-only rendering path, which means the demo
   cannot show a capability the live pipeline lacks — the worst way to lie with
   a fixture.

   WHAT MAKES IT HONEST
   --------------------
   Demo mode is never entered automatically. `api.ts`'s V1 client falls back to
   recorded runs when the backend is unreachable; the V2 client deliberately
   does NOT (see lib/v2-api.ts) — it raises, and the screen says the backend is
   down. Demo is an explicit switch, and while it is on the chassis carries a
   permanent hazard banner naming it as fixture data.

   The wording of every message, note and verdict below is copied from what the
   Python actually emits (validator/resource_crosscheck.py::_check_pins,
   orchestration/v2_pipeline.py), so the demo does not teach a viewer to expect
   phrasing the real system never produces. */

import type {
  AnalyzeResponse,
  BuildResult,
  ConsoleLine,
} from "./v2-types";

export type DemoState = "conflict" | "resolved";

/* -------------------------------------------------------------- the target */

const SPEC_TARGET = {
  board: {
    value: "NUCLEO-F411RE",
    provenance: "user" as const,
    evidence: "on a NUCLEO-F411RE",
  },
  mcu: {
    value: "STM32F411RET6",
    provenance: "user" as const,
    evidence: "STM32F411RET6",
  },
};

const SPEC_DEVICES = [
  { role: { value: "temp · humidity · pressure", provenance: "user" as const, evidence: "temperature, humidity and pressure" } },
  { role: { value: "128×64 OLED", provenance: "user" as const, evidence: "128x64 OLED" } },
  { role: { value: "virtual UART · host console", provenance: "user" as const, evidence: "print over UART" } },
  { role: { value: "vent actuator", provenance: "asked" as const, evidence: "answer to q:devices[3].role: vent actuator" } },
];

const SPEC = {
  requirement_text:
    "On a NUCLEO-F411RE with an STM32F411RET6, read temperature, humidity and " +
    "pressure from a BME280 on I2C1 at 0x76, show them on a 128x64 OLED at " +
    "0x3C, print over UART, and switch a vent relay when the temperature rises " +
    "above 30 C. Sample every 500 ms and retry on a failed read.",
  target: SPEC_TARGET,
  devices: SPEC_DEVICES,
  behaviors: [],
  constraints: [],
  failure_behavior: { value: "retry", provenance: "user" as const, evidence: "retry on a failed read" },
  output_target: { value: "cmake-project", provenance: "asked" as const, evidence: "answer to q:output_target: cmake-project" },
  notes: [],
  dropped: [],
};

/* ------------------------------------------------------------- the devices */

const BME280 = {
  name: "BME280",
  bus: { kind: "i2c", instance: "I2C1", address: "0x76" },
  pins: [
    { pin: "PB6", function: "I2C1_SCL" },
    { pin: "PB7", function: "I2C1_SDA" },
  ],
};

const SSD1306 = {
  name: "SSD1306",
  bus: { kind: "i2c", instance: "I2C1", address: "0x3C" },
  pins: [
    { pin: "PB6", function: "I2C1_SCL" },
    { pin: "PB7", function: "I2C1_SDA" },
  ],
};

const CONSOLE = {
  name: "CONSOLE",
  bus: { kind: "uart", instance: "USART2" },
  pins: [
    { pin: "PA2", function: "USART2_TX" },
    { pin: "PA3", function: "USART2_RX" },
  ],
};

const relay = (pin: string) => ({
  name: "RELAY",
  pins: [{ pin, function: "GPIO_OUT" }],
});

/* ------------------------------------------------------------ resource map */

const claim = (
  device: string,
  resource: string,
  fn: string,
  signal: string,
  instance: string,
) => ({ device, resource, function: fn, signal, instance, shared: null });

function resourceMap(relayPin: string) {
  const pins: Record<string, ReturnType<typeof claim>[]> = {
    PA2: [claim("CONSOLE", "PA2", "USART2_TX", "TX", "USART2")],
    PA3: [claim("CONSOLE", "PA3", "USART2_RX", "RX", "USART2")],
    PB6: [
      claim("BME280", "PB6", "I2C1_SCL", "SCL", "I2C1"),
      claim("SSD1306", "PB6", "I2C1_SCL", "SCL", "I2C1"),
    ],
    PB7: [
      claim("BME280", "PB7", "I2C1_SDA", "SDA", "I2C1"),
      claim("SSD1306", "PB7", "I2C1_SDA", "SDA", "I2C1"),
    ],
  };
  pins[relayPin] = [
    ...(pins[relayPin] ?? []),
    claim("RELAY", relayPin, "GPIO_OUT", "OUT", ""),
  ];
  return {
    pins,
    buses: {
      I2C1: [
        { device: "BME280", kind: "i2c", instance: "I2C1", address: "0x76" },
        { device: "SSD1306", kind: "i2c", instance: "I2C1", address: "0x3C" },
      ],
      USART2: [{ device: "CONSOLE", kind: "uart", instance: "USART2" }],
    },
    dma: {},
    irq: {},
    device_count: 4,
  };
}

/* ------------------------------------------------------ analyze: conflict */

/** Wording copied from validator/resource_crosscheck.py::_check_pins. */
const PIN_CONFLICT_MESSAGE =
  'pin PB6 double-booked: I2C1_SCL (BME280, SSD1306) vs GPIO_OUT (RELAY) — ' +
  "these claims cannot coexist on one pin. Reassign one device to a free pin, " +
  'or, if this pin really is a shared bus signal here, declare it with ' +
  '"shared": true so the intent is stated rather than assumed';

export const DEMO_ANALYZE_CONFLICT: AnalyzeResponse = {
  status: "blocked-resource-conflict",
  questions: [],
  devices: [BME280, SSD1306, CONSOLE, relay("PB6")],
  resource_map: resourceMap("PB6"),
  stages: [
    { stage: "spec", state: "pass", detail: "every field traces to something the user stated" },
    { stage: "compose", state: "pass", detail: "4 device(s) composed" },
    { stage: "resource", state: "fail", detail: PIN_CONFLICT_MESSAGE },
  ],
  checks: { resource_crosscheck: "fail" },
  failures: [{ check: "resource_crosscheck", message: PIN_CONFLICT_MESSAGE }],
  spec: SPEC,
};

/* ------------------------------------------------------ analyze: resolved */

export const DEMO_ANALYZE_RESOLVED: AnalyzeResponse = {
  status: "no-firmware",
  questions: [],
  devices: [BME280, SSD1306, CONSOLE, relay("PB5")],
  resource_map: resourceMap("PB5"),
  stages: [
    { stage: "spec", state: "pass", detail: "every field traces to something the user stated" },
    { stage: "compose", state: "pass", detail: "4 device(s) composed" },
    { stage: "resource", state: "pass", detail: "" },
    {
      stage: "firmware",
      state: "skipped",
      detail:
        "no firmware source and no read plan — the pipeline does not fabricate one",
    },
  ],
  checks: { resource_crosscheck: "pass", emulation_check: "skipped" },
  failures: [],
  spec: SPEC,
};

/* ----------------------------------------------------------------- build */

/** The recorded build for the resolved system. `firmware_origin: "fixture"` is
    the truth about this artifact and is displayed as such — the pipeline treats
    that distinction as load-bearing and so does the screen. */
export const DEMO_BUILD: BuildResult = {
  status: "working-emulated",
  firmware_origin: "fixture",
  stages: [
    { stage: "spec", state: "pass", detail: "every field traces to something the user stated" },
    { stage: "compose", state: "pass", detail: "4 device(s) composed" },
    { stage: "resource", state: "pass", detail: "" },
    { stage: "compile", state: "pass", detail: "firmware.elf built (fixture source)" },
    { stage: "emulate", state: "pass", detail: "" },
  ],
  devices: [BME280, SSD1306, CONSOLE, relay("PB5")],
  // verbatim from orchestration/v2_pipeline.py
  verdict_note:
    "ran on an emulated MCU against mocked devices and matched the spec's " +
    "expectations — NOT evidence it works on physical hardware",
  checks: { resource_crosscheck: "pass", emulation_check: "pass" },
  failures: [],
  notes: [
    "resource cross-check: 4 composed devices, 5 pin(s), 2 bus instance(s), " +
      "0 DMA claim(s), 0 IRQ line(s) — no pin-mux, bus-address, bus-config, DMA " +
      "or IRQ conflicts",
    "pin alternate-function capability was NOT verified: the supplied MCU map " +
      "has no pin_alternate_functions table (the V1.7 MCU map extracts " +
      "clock/GPIO/peripheral registers only). Conflicts BETWEEN claims were " +
      "checked; whether each pin can actually provide its claimed function was " +
      "not — that mapping is unavailable and is not guessed here",
    "emulation: 6/6 assertions held over a 4.00 s run on stm32f4.repl",
  ],
};

export const DEMO_ANALYZE: Record<DemoState, AnalyzeResponse> = {
  conflict: DEMO_ANALYZE_CONFLICT,
  resolved: DEMO_ANALYZE_RESOLVED,
};

/* ------------------------------------------ recorded emulation transcript */

/* Only demo mode has this. A live V2 build reports stages, checks, failures and
   notes — it returns no UART capture — so the live emulation bay renders those
   instead and never a transcript. If this array ever showed up in a live run it
   would be a fabricated console. */

export const DEMO_UART: ConsoleLine[] = [
  { t: "0.000", text: "rcc   SYSCLK 100 MHz · APB1 42 MHz", tone: "dim" },
  { t: "0.004", text: "i2c1  init 400 kHz  PB6/PB7        ok", tone: "dim" },
  { t: "0.011", text: "bme280  chip_id=0x60               ok", tone: "good" },
  { t: "0.013", text: "ssd1306 init 128x64                ok", tone: "good" },
  { t: "0.016", text: "gpio  PB5 output push-pull  relay  ok", tone: "good" },
  { t: "0.500", text: "t=24.81 °C  rh=41.2 %  p=1006.2 hPa", tone: "ink" },
  { t: "1.000", text: "t=27.44 °C  rh=40.8 %  p=1006.1 hPa", tone: "ink" },
  { t: "1.500", text: "t=31.05 °C  ▶ THRESHOLD 30.0  relay=ON", tone: "warn" },
  { t: "2.000", text: "t=31.62 °C  oled: “ALERT 31.6C”", tone: "ink" },
  { t: "", text: "── assertions ─────────────────────────", tone: "dim" },
  { t: "", text: "1  i2c1 clock == 400000            PASS", tone: "good" },
  { t: "", text: "2  bme280 id == 0x60               PASS", tone: "good" },
  { t: "", text: "3  t within ±0.2 of math oracle    PASS", tone: "good" },
  { t: "", text: "4  relay LOW while t < 30.0        PASS", tone: "good" },
  { t: "", text: "5  relay HIGH ≤ 50 ms after t > 30 PASS", tone: "good" },
  { t: "", text: "6  zero bus NAK over 4.00 s        PASS", tone: "good" },
];

/** °C samples, 4 s window, 250 ms apart — feeds the scope trace. */
export const DEMO_TRACE = [
  23.9, 24.2, 24.81, 25.6, 26.4, 27.44, 28.6, 29.5, 30.2, 31.05, 31.4, 31.62,
  31.5, 31.55, 31.4, 31.48,
];

export const DEMO_THRESHOLD_C = 30;
