"use client";

/* The board IS the screen. A two-layer copper render of the composed system:
   header pads on the left, the die as a peripheral inventory in the middle,
   devices hanging off the right. Top copper is phosphor (buses), bottom copper
   is bronze (plain GPIO nets) — so crossings read as deliberate layer changes,
   and a genuine double-booking reads as an alarm.

   This component is a RENDERER. It holds no facts about any board: every pad,
   peripheral block, device and trace comes from the `BoardModel` it is handed,
   which lib/v2-view.ts derives strictly from what the pipeline reported. If the
   pipeline reported no pin claims, this draws no pins — it does not know enough
   about any MCU to fill the gap, and pretending otherwise is the exact class of
   invented fact `resource_crosscheck` exists to catch. */

import { motion } from "framer-motion";
import type { BoardModel, NetTone } from "../../lib/v2-view";
import { SNAP } from "./chrome";

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

const NET_COLOR: Record<NetTone, string> = {
  bus: C.bus,
  uart: C.uart,
  gpio: C.bottom,
  alarm: C.alarm,
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
  dashed,
  delay = 0,
  strobe,
}: {
  d: string;
  color: string;
  width?: number;
  dim?: boolean;
  dashed?: boolean;
  delay?: number;
  strobe?: boolean;
}) {
  return (
    <g>
      <path
        d={d}
        stroke={color}
        strokeWidth={width + 4}
        opacity={dim ? 0.04 : 0.11}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <motion.path
        d={d}
        stroke={color}
        strokeWidth={width}
        strokeDasharray={dashed ? "7 4" : undefined}
        opacity={dim ? 0.42 : 0.95}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.7, delay, ease: "easeInOut" }}
        className={strobe ? "ins-strobe" : undefined}
      />
    </g>
  );
}

function describe(board: BoardModel): string {
  if (board.empty) return `Board resource map. ${board.empty}`;
  const conflicts = board.devices.filter((d) => d.status === "conflict");
  const base =
    `Board resource map for ${board.target.mcu} on ${board.target.board}. ` +
    `${board.devices.length} composed device(s), ${board.die.length} claimed ` +
    `peripheral(s), ${board.pins.length} claimed pin(s).`;
  return conflicts.length
    ? `${base} ${conflicts.length} device(s) are involved in a reported resource conflict, shown in red: ${conflicts
        .map((d) => d.name)
        .join(", ")}.`
    : `${base} No resource conflicts were reported.`;
}

export function BoardView({ board }: { board: BoardModel }) {
  const connected = new Set(board.nets.map((n) => n.id));

  return (
    <svg
      viewBox="0 0 860 480"
      className="ins-mono h-auto w-full select-none"
      role="img"
      aria-label={describe(board)}
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

      {/* silkscreen — the target the SPEC states, never a default */}
      <text x="330" y="26" textAnchor="middle" fontSize="10.5" fill={C.silkDim} letterSpacing="3">
        {board.target.board}
      </text>
      <text x="330" y="48" textAnchor="middle" fontSize="12" fill={C.silk} letterSpacing="1.6">
        {board.target.mcu}
      </text>
      <text x="72" y="440" fontSize="7.5" fill={C.silkDim} letterSpacing="1.6">
        EMBEDDPILOT · RESOURCE MAP · REV 2.0
      </text>

      {/* -------------------------------------------------------- header pads */}
      {board.pins.map((p, i) => {
        const color = p.conflict ? C.alarm : KIND_COLOR[p.kind];
        const live = p.wired && p.kind !== "power";
        return (
          <g key={p.id}>
            {/* stub into the die */}
            {p.wired ? (
              <Trace
                d={`M 108 ${p.y} H 250`}
                color={color}
                width={p.kind === "power" ? 1.2 : 1.6}
                dim={p.kind === "power" || p.kind === "reserved"}
                delay={0.1 + i * 0.035}
              />
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
          </g>
        );
      })}

      {/* the spec claimed no pins — say so on the silkscreen rather than
          drawing a pinout nobody asked for */}
      {board.pins.length === 0 && !board.empty && (
        <g>
          <rect x="76" y="150" width="160" height="52" rx="2" fill="#0d1a16" stroke="#1e3a30" strokeWidth="1" strokeDasharray="4 3" />
          <text x="86" y="170" fontSize="8.5" fill={C.silkDim} letterSpacing="1.2">
            NO PIN CLAIMS
          </text>
          <text x="86" y="184" fontSize="7.5" fill={C.silkDim} letterSpacing="0.8">
            the spec named no pins, so
          </text>
          <text x="86" y="195" fontSize="7.5" fill={C.silkDim} letterSpacing="0.8">
            none are drawn or verified
          </text>
        </g>
      )}

      {/* collision annotation, parked in the free silkscreen below the header */}
      {board.alarm && (
        <motion.g initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ ...SNAP, delay: 0.5 }}>
          {/* sized from the caption: SVG text neither wraps nor ellipsizes, so
              a fixed plate width silently truncates a longer alarm */}
          <rect x="120" y="398" width={board.alarm.length * 6.3 + 20} height="17" rx="2" fill="#2a0f0c" stroke={C.alarm} strokeWidth="1" />
          <rect x="120" y="398" width="3" height="17" fill={C.alarm} />
          <text x="130" y="410" fontSize="8.5" fill={C.alarm} letterSpacing="1.3">
            {board.alarm}
          </text>
        </motion.g>
      )}

      {/* ------------------------------------------------------------ the die */}
      <rect x="250" y="56" width="160" height="356" rx="5" fill="url(#rm-die)" stroke="#2b3944" strokeWidth="1.5" />
      <circle cx="262" cy="68" r="3.2" fill={C.silkDim} />
      {board.pins.map((p) => (
        <rect key={`lead-l-${p.id}`} x="243" y={p.y - 2.5} width="9" height="5" rx="1" fill={p.conflict ? C.alarm : C.goldDim} />
      ))}
      {board.die.map((b) => (
        <rect key={`lead-r-${b.label}`} x="408" y={b.y + b.h / 2 - 2.5} width="9" height="5" rx="1" fill={C.goldDim} />
      ))}

      {board.die.map((b) => (
        <g key={b.label}>
          <rect
            x="264"
            y={b.y}
            width="132"
            height={b.h}
            rx="2"
            fill={b.conflict ? "#1c1210" : b.lit ? "#101c1a" : "#0d1319"}
            stroke={b.conflict ? "#5e241c" : b.lit ? "#20402f" : "#1b242d"}
            strokeWidth="1"
          />
          <rect
            x="264"
            y={b.y}
            width="2.5"
            height={b.h}
            fill={b.conflict ? C.alarm : b.lit ? C.bus : "#233039"}
            opacity={b.lit ? 0.8 : 1}
            className={b.conflict ? "ins-strobe" : undefined}
          />
          <text x="274" y={b.y + 16} fontSize="10" fill={b.conflict ? C.alarm : b.lit ? C.silk : C.silkDim} letterSpacing="1.2">
            {b.label}
          </text>
          <text
            x="274"
            y={b.y + Math.min(29, b.h - 6)}
            fontSize="8"
            fill={b.conflict ? "#a8564a" : b.lit ? C.bus : C.silkDim}
            opacity={b.lit ? 0.75 : 0.6}
            letterSpacing="0.8"
          >
            {b.note}
          </text>
          <circle cx="386" cy={b.y + 13} r="2.6" fill={b.conflict ? C.alarm : b.lit ? C.bus : "#1b242d"} />
        </g>
      ))}

      {board.die.length === 0 && !board.empty && (
        <text x="330" y="240" textAnchor="middle" fontSize="9" fill={C.silkDim} letterSpacing="1.2">
          NO PERIPHERAL CLAIMS
        </text>
      )}

      {/* --------------------------------------------------------- the copper */}
      {board.nets.map((n) => (
        <Trace
          key={n.id}
          d={n.d}
          color={NET_COLOR[n.tone]}
          dashed={n.dashed}
          delay={n.delay}
          strobe={n.tone === "alarm"}
        />
      ))}

      {/* signal flow — a bright dash chasing each clean trace */}
      <g className="ins-flow ins-flow-fast">
        {board.nets
          .filter((n) => n.flow)
          .map((n) => (
            <path
              key={`flow-${n.id}`}
              d={n.d}
              stroke={NET_COLOR[n.tone]}
              strokeWidth="2.2"
              fill="none"
              strokeLinecap="round"
              opacity="0.8"
            />
          ))}
      </g>

      {/* board-edge exit notches, one per departing net */}
      {board.nets.map((n, i) => {
        const m = n.d.match(/H 570$/) ? n.d.match(/V ([\d.]+) H 570$/) : null;
        const y = m ? Number(m[1]) : null;
        return y === null ? null : (
          <rect key={`notch-${i}`} x="486" y={y - 4} width="4" height="8" fill="#0b1a16" stroke="#22453a" strokeWidth="0.75" />
        );
      })}

      {/* ------------------------------------------------------------ devices */}
      {board.devices.map((d, i) => {
        const bad = d.status === "conflict";
        const accent = bad ? C.alarm : C.bus;
        const hasNet = connected.has(`${d.id}-net`);
        return (
          <motion.g key={d.id} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={{ ...SNAP, delay: 0.3 + i * 0.05 }}>
            <rect x="570" y={d.y} width="250" height={d.h} rx="3" fill="url(#rm-dev)" stroke={bad ? "#5e241c" : "#22303b"} strokeWidth="1.25" />
            <rect x="570" y={d.y} width="2.5" height={d.h} fill={accent} opacity={bad ? 1 : 0.55} className={bad ? "ins-strobe" : undefined} />
            {hasNet && (
              <rect x="562" y={d.y + d.h / 2 - 3} width="9" height="6" rx="1" fill={bad ? C.alarm : C.gold} opacity="0.85" />
            )}

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
            {d.h > 46 && (
              <text x="600" y={d.y + 39} fontSize="8.5" fill={bad ? "#a8564a" : C.silkDim} letterSpacing="0.6">
                {d.role}
              </text>
            )}
            {d.h > 62 && (
              <text x="600" y={d.y + 58} fontSize="8.5" fill={bad ? "#a8564a" : C.bus} opacity="0.8" letterSpacing="0.8">
                {d.facts.join("   ")}
              </text>
            )}
          </motion.g>
        );
      })}

      {/* the honest line: what the map does and does not cover */}
      {board.footnote && (
        <text x="60" y="472" fontSize="8" fill={C.silkDim} letterSpacing="1.2">
          {board.footnote.slice(0, 132)}
        </text>
      )}

      {board.empty && (
        <text x="695" y="240" textAnchor="middle" fontSize="10" fill={C.silkDim} letterSpacing="1.2">
          NO DEVICES COMPOSED
        </text>
      )}
    </svg>
  );
}
