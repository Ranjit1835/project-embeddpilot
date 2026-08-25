"use client";

/* The board IS the screen. A two-layer copper render of the composed system:
   header pads on the left, the die as a peripheral inventory in the middle,
   devices hanging off the right. Top copper is phosphor (the I²C bus), bottom
   copper is bronze (the relay control net) — so crossings read as deliberate
   layer changes, and a genuine double-booking reads as an alarm. */

import { motion } from "framer-motion";
import { DIE_BLOCKS, devices, pins, relayNet, NETS, TARGET, type Mode } from "../../lib/resource-map-mock";
import { GLIDE, SNAP } from "./chrome";

const C = {
  pcb: "#0a1512",
  silk: "#8ea3ab",
  silkDim: "#4b5f66",
  gold: "#c8a04a",
  goldDim: "#6b5527",
  bus: "#3fe081",
  uart: "#5cc9f5",
  bottom: "#c08a3e",
  alarm: "#e5533c",
  idle: "#2b3a44",
};

const KIND_COLOR: Record<string, string> = {
  bus: C.bus,
  uart: C.uart,
  gpio: C.bottom,
  power: "#67798a",
  reserved: "#4b5f66",
  free: C.idle,
};

/** A copper run: soft bloom underneath, hard trace on top. */
function Trace({
  d,
  color,
  width = 1.6,
  dim,
  delay = 0,
}: {
  d: string;
  color: string;
  width?: number;
  dim?: boolean;
  delay?: number;
}) {
  return (
    <g>
      <path d={d} stroke={color} strokeWidth={width + 4} opacity={dim ? 0.04 : 0.11} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <motion.path
        d={d}
        stroke={color}
        strokeWidth={width}
        opacity={dim ? 0.42 : 0.95}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.7, delay, ease: "easeInOut" }}
      />
    </g>
  );
}

export function BoardView({ mode }: { mode: Mode }) {
  const conflict = mode === "conflict";
  const rows = pins(mode);
  const nodes = devices(mode);
  const relayColor = conflict ? C.alarm : C.bottom;

  return (
    <svg
      viewBox="0 0 860 480"
      className="ins-mono h-auto w-full select-none"
      role="img"
      aria-label={
        conflict
          ? "Board resource map. PB6 is claimed by both I2C1 SCL and the relay GPIO output — a pin collision, shown in red."
          : "Board resource map. Relay moved to PB5; no pin collisions remain and every net is clean."
      }
    >
      <defs>
        <linearGradient id="rm-pcb" x1="0" y1="0" x2="0.4" y2="1">
          <stop offset="0%" stopColor="#0c1b17" />
          <stop offset="100%" stopColor="#071110" />
        </linearGradient>
        <linearGradient id="rm-die" x1="0" y1="0" x2="0.3" y2="1">
          <stop offset="0%" stopColor="#151d24" />
          <stop offset="100%" stopColor="#0b1218" />
        </linearGradient>
        <linearGradient id="rm-dev" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#131c24" />
          <stop offset="100%" stopColor="#0d141b" />
        </linearGradient>
        <radialGradient id="rm-halo" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor="#3fe081" stopOpacity="0.14" />
          <stop offset="100%" stopColor="#3fe081" stopOpacity="0" />
        </radialGradient>
        {/* ground pour: the hatched copper fill that makes a PCB a PCB */}
        <pattern id="rm-pour" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="7" stroke="#3fe081" strokeWidth="0.5" opacity="0.075" />
        </pattern>
      </defs>

      {/* ---------------------------------------------------- board substrate */}
      <ellipse cx="275" cy="240" rx="340" ry="300" fill="url(#rm-halo)" />
      <rect x="60" y="34" width="430" height="410" rx="12" fill="url(#rm-pcb)" stroke="#1c3229" strokeWidth="1.5" />
      <rect x="60" y="34" width="430" height="410" rx="12" fill="url(#rm-pour)" />
      <rect x="64" y="38" width="422" height="402" rx="9" fill="none" stroke="#22453a" strokeWidth="0.75" opacity="0.7" />

      {/* mounting holes */}
      {[
        [74, 46],
        [476, 46],
        [74, 414],
        [476, 414],
      ].map(([cx, cy]) => (
        <g key={`${cx}-${cy}`}>
          <circle cx={cx} cy={cy} r="6" fill="#050b0a" stroke={C.goldDim} strokeWidth="1.5" />
          <circle cx={cx} cy={cy} r="2.4" fill="#020605" />
        </g>
      ))}

      {/* silkscreen */}
      <text x="330" y="26" textAnchor="middle" fontSize="10.5" fill={C.silkDim} letterSpacing="3">
        {TARGET.board}
      </text>
      <text x="330" y="48" textAnchor="middle" fontSize="12" fill={C.silk} letterSpacing="1.6">
        {TARGET.mcu}
      </text>
      <text x="72" y="440" fontSize="7.5" fill={C.silkDim} letterSpacing="1.6">
        EMBEDDPILOT · RESOURCE MAP · REV 2.0
      </text>
      <text x="478" y="440" textAnchor="end" fontSize="7.5" fill={C.silkDim} letterSpacing="1.6">
        {TARGET.pkg}
      </text>
      <text x="84" y="66" fontSize="7.5" fill={C.silkDim} letterSpacing="1.4">
        CN7 / CN10
      </text>

      {/* --------------------------------------- bottom copper (relay control) */}
      <g>
        <motion.path
          animate={{ d: relayNet(mode) }}
          transition={GLIDE}
          d={NETS.relayConflict}
          stroke={relayColor}
          strokeWidth="6"
          opacity="0.1"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <motion.path
          animate={{ d: relayNet(mode), stroke: relayColor }}
          transition={GLIDE}
          d={NETS.relayConflict}
          strokeWidth="2"
          strokeDasharray="7 4"
          opacity={conflict ? 0.95 : 0.8}
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={conflict ? "ins-strobe" : undefined}
        />
        <motion.text
          animate={{ x: 168, y: conflict ? 422 : 422 }}
          fontSize="8"
          fill={relayColor}
          opacity="0.85"
          letterSpacing="1.4"
        >
          {conflict ? "RELAY_CTRL · BOTTOM · UNRESOLVED" : "RELAY_CTRL · BOTTOM LAYER"}
        </motion.text>
      </g>

      {/* -------------------------------------------------------- header pads */}
      {rows.map((p, i) => {
        const color = p.conflict ? C.alarm : KIND_COLOR[p.kind];
        const live = p.wired && p.kind !== "power";
        return (
          <g key={p.id}>
            {/* stub into the die */}
            {p.wired ? (
              <Trace d={`M 108 ${p.y} H 250`} color={color} width={p.kind === "power" ? 1.2 : 1.6} dim={p.kind === "power" || p.kind === "reserved"} delay={0.1 + i * 0.035} />
            ) : (
              <>
                <path d={`M 108 ${p.y} H 168`} stroke={C.idle} strokeWidth="1.2" strokeDasharray="2 4" fill="none" />
                <circle cx="176" cy={p.y} r="3.5" fill="none" stroke={C.idle} strokeWidth="1.2" />
              </>
            )}

            {/* status lamp + pad */}
            <circle cx="76" cy={p.y} r="3.2" fill={live ? color : "#16221f"} opacity={live ? 1 : 0.8}>
              {p.conflict && <animate attributeName="opacity" values="1;0.2;1" dur="0.9s" repeatCount="indefinite" />}
            </circle>
            {live && <circle cx="76" cy={p.y} r="6" fill={color} opacity="0.14" />}
            <rect
              x="92"
              y={p.y - 6}
              width="16"
              height="12"
              rx="1.5"
              fill={p.conflict ? "#3a1512" : "#1a1608"}
              stroke={p.conflict ? C.alarm : C.gold}
              strokeWidth="1.2"
            />
            <rect x="96" y={p.y - 2.5} width="8" height="5" rx="1" fill={p.conflict ? C.alarm : C.gold} opacity="0.75" />

            {/* silkscreen legend above the trace, ownership below it */}
            <text
              x="118"
              y={p.y - 6}
              fontSize="10"
              letterSpacing="0.8"
              fill={p.conflict ? C.alarm : p.wired ? C.silk : C.silkDim}
              stroke={C.pcb}
              strokeWidth="3"
              style={{ paintOrder: "stroke" }}
            >
              {p.id}
              <tspan dx="8" fill={p.conflict ? C.alarm : live ? color : C.silkDim} fontSize="9">
                {p.fn}
              </tspan>
            </text>
            {p.owner && (
              <text
                x="118"
                y={p.y + 12}
                fontSize="8"
                letterSpacing="0.6"
                fill={p.conflict ? C.alarm : C.silkDim}
                stroke={C.pcb}
                strokeWidth="3"
                style={{ paintOrder: "stroke" }}
              >
                ◂ {p.owner}
              </text>
            )}

            {/* the collision itself */}
            {p.conflict && (
              <g>
                <circle cx="100" cy={p.y} r="13" fill="none" stroke={C.alarm} strokeWidth="1.4" className="ins-ring" />
                <circle cx="100" cy={p.y} r="11" fill="none" stroke={C.alarm} strokeWidth="1" opacity="0.55" />
              </g>
            )}
            {!conflict && p.id === "PB5" && (
              <motion.circle
                initial={{ scale: 0.3, opacity: 0 }}
                animate={{ scale: 1, opacity: 0.6 }}
                transition={{ ...SNAP, delay: 0.35 }}
                cx="100"
                cy={p.y}
                r="11"
                fill="none"
                stroke={C.bus}
                strokeWidth="1"
                style={{ transformBox: "fill-box", transformOrigin: "center" }}
              />
            )}
          </g>
        );
      })}

      {/* collision annotation, parked in the free silkscreen below the header */}
      {conflict && (
        <motion.g initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ ...SNAP, delay: 0.5 }}>
          <rect x="176" y="398" width="196" height="17" rx="2" fill="#2a0f0c" stroke={C.alarm} strokeWidth="1" />
          <rect x="176" y="398" width="3" height="17" fill={C.alarm} />
          <text x="186" y="410" fontSize="8.5" fill={C.alarm} letterSpacing="1.3">
            ⚠ NET COLLISION · PAD PB6 · 2 CLAIMS
          </text>
        </motion.g>
      )}

      {/* ------------------------------------------------------- the die */}
      <rect x="250" y="56" width="160" height="356" rx="5" fill="url(#rm-die)" stroke="#2b3944" strokeWidth="1.5" />
      <circle cx="262" cy="68" r="3.2" fill={C.silkDim} />
      {rows.map((p) => (
        <rect key={`lead-l-${p.id}`} x="243" y={p.y - 2.5} width="9" height="5" rx="1" fill={p.conflict ? C.alarm : C.goldDim} />
      ))}
      {[78, 112, 180, 214].map((y) => (
        <rect key={`lead-r-${y}`} x="408" y={y - 2.5} width="9" height="5" rx="1" fill={C.goldDim} />
      ))}

      {DIE_BLOCKS.map((b) => (
        <g key={b.label}>
          <rect x="264" y={b.y} width="132" height={b.h} rx="2" fill={b.lit ? "#101c1a" : "#0d1319"} stroke={b.lit ? "#20402f" : "#1b242d"} strokeWidth="1" />
          <rect x="264" y={b.y} width="2.5" height={b.h} fill={b.lit ? C.bus : "#233039"} opacity={b.lit ? 0.8 : 1} />
          <text x="274" y={b.y + 16} fontSize="10" fill={b.lit ? C.silk : C.silkDim} letterSpacing="1.2">
            {b.label}
          </text>
          <text x="274" y={b.y + 29} fontSize="8" fill={b.lit ? C.bus : C.silkDim} opacity={b.lit ? 0.75 : 0.6} letterSpacing="0.8">
            {b.note}
          </text>
          <circle cx="386" cy={b.y + 13} r="2.6" fill={b.lit ? C.bus : "#1b242d"} />
        </g>
      ))}

      {/* --------------------------------------------------- top copper buses */}
      <Trace d={NETS.scl} color={C.bus} delay={0.4} />
      <Trace d={NETS.sda} color={C.bus} delay={0.45} />
      <Trace d={NETS.daisyScl} color={C.bus} delay={0.55} />
      <Trace d={NETS.daisySda} color={C.bus} delay={0.6} />
      <Trace d={NETS.uartTx} color={C.uart} delay={0.5} />
      <Trace d={NETS.uartRx} color={C.uart} delay={0.55} />

      {/* signal flow — faster once emulation is actually running */}
      <g className={conflict ? "ins-flow" : "ins-flow ins-flow-fast"} opacity={conflict ? 0.35 : 0.9}>
        <path d={NETS.scl} stroke={C.bus} strokeWidth="2.2" fill="none" strokeLinecap="round" />
        <path d={NETS.sda} stroke={C.bus} strokeWidth="2.2" fill="none" strokeLinecap="round" />
        <path d={NETS.daisyScl} stroke={C.bus} strokeWidth="2.2" fill="none" strokeLinecap="round" />
        <path d={NETS.daisySda} stroke={C.bus} strokeWidth="2.2" fill="none" strokeLinecap="round" />
      </g>
      {!conflict && (
        <g className="ins-flow ins-flow-fast" opacity="0.85">
          <path d={NETS.uartTx} stroke={C.uart} strokeWidth="2.2" fill="none" strokeLinecap="round" />
        </g>
      )}

      <text x="500" y="70" fontSize="7.5" fill={C.silkDim} letterSpacing="1.4">
        I²C1
      </text>
      <text x="500" y="290" fontSize="7.5" fill={C.silkDim} letterSpacing="1.4">
        USART2
      </text>

      {/* board-edge exit notches */}
      {[78, 112, 180, 214, 428].map((y) => (
        <rect key={`notch-${y}`} x="486" y={y - 4} width="4" height="8" fill="#0b1a16" stroke="#22453a" strokeWidth="0.75" />
      ))}

      {/* ---------------------------------------------------------- devices */}
      {nodes.map((d) => {
        const bad = d.status === "conflict";
        const accent = bad ? C.alarm : d.id === "console" ? C.uart : C.bus;
        return (
          <motion.g key={d.id} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={{ ...SNAP, delay: 0.35 }}>
            <rect x="570" y={d.y} width="250" height={d.h} rx="3" fill="url(#rm-dev)" stroke={bad ? "#5e241c" : "#22303b"} strokeWidth="1.25" />
            <rect x="570" y={d.y} width="2.5" height={d.h} fill={accent} opacity={bad ? 1 : 0.55} className={bad ? "ins-strobe" : undefined} />
            {/* connector pins on the block edge */}
            {d.id === "bme280" &&
              [78, 112].map((y) => <rect key={y} x="562" y={y - 3} width="9" height="6" rx="1" fill={C.gold} opacity="0.8" />)}
            {d.id === "ssd1306" &&
              [598, 632].map((x) => <rect key={x} x={x - 3} y="164" width="6" height="9" rx="1" fill={C.gold} opacity="0.8" />)}
            {d.id === "console" &&
              [298, 332].map((y) => <rect key={y} x="562" y={y - 3} width="9" height="6" rx="1" fill={C.gold} opacity="0.8" />)}
            {d.id === "relay" && <rect x="562" y="425" width="9" height="6" rx="1" fill={bad ? C.alarm : C.gold} opacity="0.9" />}

            <circle cx="588" cy={d.y + 20} r="3.4" fill={accent}>
              {bad && <animate attributeName="opacity" values="1;0.2;1" dur="0.9s" repeatCount="indefinite" />}
            </circle>
            <text x="600" y={d.y + 24} fontSize="12.5" fill={bad ? C.alarm : C.silk} letterSpacing="1.6">
              {d.name}
            </text>
            <text x="808" y={d.y + 24} textAnchor="end" fontSize="10" fill={bad ? C.alarm : accent} letterSpacing="0.8">
              {d.iface}
              {d.addr ? `  @${d.addr}` : ""}
            </text>
            <text x="600" y={d.y + 39} fontSize="8.5" fill={bad ? "#a8564a" : C.silkDim} letterSpacing="0.6">
              {d.role}
            </text>
            {d.checks.length > 0 && (
              <text x="600" y={d.y + 62} fontSize="8.5" fill={C.bus} opacity="0.8" letterSpacing="0.8">
                {d.checks.map((c) => `✓ ${c.label}`).join("   ")}
              </text>
            )}
            {d.id === "console" && (
              <text x="600" y={d.y + 62} fontSize="8.5" fill={C.uart} opacity="0.8" letterSpacing="0.8">
                115200 8N1 · {conflict ? "idle" : "streaming"}
              </text>
            )}
          </motion.g>
        );
      })}

      {/* bus annotation under the device stack */}
      <text x="570" y="472" fontSize="8" fill={C.silkDim} letterSpacing="1.4">
        BUS I²C1 · 0x76 BME280 · 0x3C SSD1306 · no address collision
      </text>
    </svg>
  );
}
