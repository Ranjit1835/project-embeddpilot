/* Mock data for the V2 "Resource Map" hero screen (V2_PLAN §7).
   Pure fixtures — this module makes no network calls and is safe to import
   from a client component. Geometry lives here alongside the semantics so the
   board view stays a renderer, not a source of truth.

   Coordinate space is the board SVG viewBox: 0 0 860 480.
   Pin rows sit on a 34px grid so every stub can be a straight line — the
   "instrument precision" the panel aesthetic depends on. */

export type Mode = "conflict" | "resolved";

/* ---------------------------------------------------------------- target */

export const TARGET = {
  family: "STM32F4",
  mcu: "STM32F411RET6",
  board: "NUCLEO-F411RE",
  pkg: "LQFP64",
  core: "CORTEX-M4F · 100 MHz",
  project: "greenhouse",
} as const;

/* ------------------------------------------------------------------ pins */

export type PinKind = "bus" | "uart" | "gpio" | "free" | "power" | "reserved";

export interface Pin {
  /** silkscreen designator */
  id: string;
  /** SVG row centre */
  y: number;
  kind: PinKind;
  /** alternate-function label printed on the silkscreen */
  fn: string;
  /** who claims this pin, printed under the trace */
  owner?: string;
  /** true when two nets are booked onto the same pad */
  conflict?: boolean;
  /** the net physically reaches the die */
  wired: boolean;
}

const PIN_Y = [78, 112, 146, 180, 214, 248, 282, 316, 350, 384] as const;

export function pins(mode: Mode): Pin[] {
  const conflict = mode === "conflict";
  return [
    {
      id: "PB6",
      y: PIN_Y[0],
      kind: conflict ? "gpio" : "bus",
      fn: "I²C1_SCL",
      owner: conflict ? "BME280 · SSD1306  ✕  RELAY" : "BME280 · SSD1306",
      conflict,
      wired: true,
    },
    {
      id: "PB7",
      y: PIN_Y[1],
      kind: "bus",
      fn: "I²C1_SDA",
      owner: "BME280 · SSD1306",
      wired: true,
    },
    {
      id: "PB5",
      y: PIN_Y[2],
      kind: conflict ? "free" : "gpio",
      fn: conflict ? "— available" : "RELAY_CTRL",
      owner: conflict ? undefined : "RELAY  (push-pull)",
      wired: !conflict,
    },
    { id: "PA2", y: PIN_Y[3], kind: "uart", fn: "USART2_TX", owner: "CONSOLE", wired: true },
    { id: "PA3", y: PIN_Y[4], kind: "uart", fn: "USART2_RX", owner: "CONSOLE", wired: true },
    { id: "PA5", y: PIN_Y[5], kind: "free", fn: "— available", wired: false },
    { id: "PA0", y: PIN_Y[6], kind: "free", fn: "— available", wired: false },
    { id: "PC13", y: PIN_Y[7], kind: "reserved", fn: "USER_BTN", owner: "reserved by board", wired: true },
    { id: "3V3", y: PIN_Y[8], kind: "power", fn: "VDD", wired: true },
    { id: "GND", y: PIN_Y[9], kind: "power", fn: "VSS", wired: true },
  ];
}

/* -------------------------------------------------------- die sub-blocks */

export interface DieBlock {
  label: string;
  note: string;
  y: number;
  h: number;
  /** lit = peripheral is claimed by the composed system */
  lit: boolean;
}

export const DIE_BLOCKS: DieBlock[] = [
  { label: "I²C1", note: "400 kHz · FM", y: 66, h: 40, lit: true },
  { label: "USART2", note: "115200 8N1", y: 118, h: 40, lit: true },
  { label: "GPIOB", note: "PP · no PU", y: 170, h: 40, lit: true },
  { label: "DMA1", note: "0/8 streams", y: 222, h: 40, lit: false },
  { label: "RCC · APB1", note: "42 MHz", y: 274, h: 40, lit: true },
  { label: "PWR · VDD", note: "3.3 V", y: 326, h: 40, lit: true },
  { label: "NVIC", note: "2/60 IRQ", y: 378, h: 34, lit: false },
];

/* --------------------------------------------------------------- devices */

export interface DeviceNode {
  id: string;
  name: string;
  role: string;
  iface: string;
  addr?: string;
  /** SVG block geometry */
  y: number;
  h: number;
  /** per-device oracle checks carried up from V1 */
  checks: { label: string; ok: boolean }[];
  status: "ok" | "conflict";
}

export function devices(mode: Mode): DeviceNode[] {
  const conflict = mode === "conflict";
  return [
    {
      id: "bme280",
      name: "BME280",
      role: "temp · humidity · pressure",
      iface: "I²C1",
      addr: "0x76",
      y: 52,
      h: 86,
      checks: [
        { label: "reg", ok: true },
        { label: "readout", ok: true },
        { label: "math", ok: true },
      ],
      status: "ok",
    },
    {
      id: "ssd1306",
      name: "SSD1306",
      role: "128×64 OLED",
      iface: "I²C1",
      addr: "0x3C",
      y: 170,
      h: 86,
      checks: [
        { label: "reg", ok: true },
        { label: "readout", ok: true },
      ],
      status: "ok",
    },
    {
      id: "console",
      name: "CONSOLE",
      role: "virtual UART · host",
      iface: "USART2",
      y: 280,
      h: 80,
      checks: [],
      status: "ok",
    },
    {
      id: "relay",
      name: "RELAY",
      role: conflict ? "vent actuator — unplaced" : "vent actuator",
      iface: conflict ? "GPIO PB6" : "GPIO PB5",
      y: 400,
      h: 56,
      checks: [],
      status: conflict ? "conflict" : "ok",
    },
  ];
}

/* ------------------------------------------------------------- net paths */

/* Two-layer copper. Top layer carries the buses (phosphor); the relay control
   net rides the bottom layer (cool cyan) so its crossings read as intentional
   layer changes rather than shorts. Both relay paths share an identical
   command sequence so the `d` attribute can be tweened between states. */

export const NETS = {
  scl: "M 410 78 H 570",
  sda: "M 410 112 H 570",
  daisyScl: "M 598 138 V 170",
  daisySda: "M 632 138 V 170",
  uartTx: "M 410 180 H 452 L 570 298",
  uartRx: "M 410 214 H 452 L 570 332",
  /** relay control — booked onto PB6 (collision) */
  relayConflict: "M 108 78 L 132 102 V 404 L 156 428 H 570",
  /** relay control — reassigned to PB5 */
  relayResolved: "M 108 146 L 132 170 V 404 L 156 428 H 570",
} as const;

export function relayNet(mode: Mode) {
  return mode === "conflict" ? NETS.relayConflict : NETS.relayResolved;
}

/* ------------------------------------------------------------- conflicts */

export interface ConflictRecord {
  pin: string;
  headline: string;
  claimants: { net: string; owners: string; kind: "bus" | "gpio" }[];
  rule: string;
  remedy: string;
  suggestion: string;
}

export const CONFLICT: ConflictRecord = {
  pin: "PB6",
  headline: "PB6 double-booked",
  claimants: [
    { net: "I²C1_SCL", owners: "BME280 · SSD1306", kind: "bus" },
    { net: "GPIO out", owners: "RELAY", kind: "gpio" },
  ],
  rule: "AF04 (I2C1_SCL) and GPIO output cannot share one pad",
  remedy: "reassign RELAY",
  suggestion: "PB5",
};

/* --------------------------------------------------------- verdict rail */

export type CheckState = "pass" | "warn" | "pending" | "fail";

export interface RailCheck {
  id: string;
  label: string;
  state: CheckState;
  note: string;
}

export function rail(mode: Mode): RailCheck[] {
  if (mode === "conflict") {
    return [
      { id: "register", label: "register", state: "pass", note: "3/3 maps cross-checked" },
      { id: "readout", label: "readout", state: "pass", note: "5/5 vectors" },
      { id: "math", label: "math", state: "pass", note: "compensation ±0.01" },
      { id: "resource", label: "resource", state: "warn", note: "1 collision" },
      { id: "emulation", label: "emulation", state: "pending", note: "blocked" },
    ];
  }
  return [
    { id: "register", label: "register", state: "pass", note: "3/3 maps cross-checked" },
    { id: "readout", label: "readout", state: "pass", note: "5/5 vectors" },
    { id: "math", label: "math", state: "pass", note: "compensation ±0.01" },
    { id: "resource", label: "resource", state: "pass", note: "0 collisions" },
    { id: "emulation", label: "emulation", state: "pass", note: "6/6 assertions" },
  ];
}

export function verdict(mode: Mode) {
  return mode === "conflict"
    ? { label: "BLOCKED — 1 RESOURCE COLLISION", tone: "bad" as const }
    : { label: "WORKING (EMULATED)", tone: "good" as const };
}

/* --------------------------------------------------- emulated UART trace */

export type LineTone = "dim" | "ink" | "good" | "warn" | "bad";

export interface UartLine {
  t: string;
  text: string;
  tone: LineTone;
}

export const UART: UartLine[] = [
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
export const TEMP_TRACE = [
  23.9, 24.2, 24.81, 25.6, 26.4, 27.44, 28.6, 29.5, 30.2, 31.05, 31.4, 31.62,
  31.5, 31.55, 31.4, 31.48,
];

export const THRESHOLD_C = 30;
