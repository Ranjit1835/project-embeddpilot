"use client";

/* Screen 2: register map review — dense, sortable, editable before generation.
   Edits are tracked verbatim and travel into provenance. The ONE Generate
   button in the product lives here. */

import { motion } from "framer-motion";
import { useMemo, useState } from "react";
import type { Command, Register, RegisterMap } from "../lib/types";
import { Button, Confidence, EASE, Field, Panel, inputCls } from "./ui";

type SortKey = "name" | "offset";

export function ReviewScreen({
  map: initialMap,
  platform: initialPlatform,
  onGenerate,
}: {
  map: RegisterMap;
  platform: string;
  onGenerate: (map: RegisterMap, platform: string, edits: string[]) => void;
}) {
  const [map, setMap] = useState<RegisterMap>(initialMap);
  const [platform, setPlatform] = useState(initialPlatform);
  const [edits, setEdits] = useState<string[]>([]);
  const [sort, setSort] = useState<SortKey>("offset");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const track = (msg: string) => setEdits((e) => [...e, msg]);

  const registers = useMemo(() => {
    const rows = map.registers.map((r, i) => ({ r, i }));
    rows.sort((a, b) =>
      sort === "offset"
        ? parseInt(a.r.offset, 16) - parseInt(b.r.offset, 16)
        : a.r.name.localeCompare(b.r.name),
    );
    return rows;
  }, [map.registers, sort]);

  const editRegister = (i: number, field: keyof Register, value: string) => {
    const old = String(map.registers[i][field] ?? "");
    if (old === value) return;
    setMap((m) => {
      const regs = m.registers.slice();
      regs[i] = { ...regs[i], [field]: value || null };
      return { ...m, registers: regs };
    });
    track(`register[${map.registers[i].name}].${field}: "${old}" -> "${value}"`);
  };

  const deleteRegister = (i: number) => {
    track(`deleted register ${map.registers[i].name} (${map.registers[i].offset})`);
    setMap((m) => ({
      ...m,
      registers: m.registers.filter((_, k) => k !== i),
    }));
  };

  const deleteCommand = (i: number) => {
    const c = (map.commands ?? [])[i];
    track(`deleted command ${c.name} (${c.opcode})`);
    setMap((m) => ({
      ...m,
      commands: (m.commands ?? []).filter((_, k) => k !== i),
    }));
  };

  const emptyFieldCount = map.registers.filter((r) => r.fields.length === 0).length;
  const warnings: string[] = [
    ...(map.warnings ?? []),
    ...(emptyFieldCount === map.registers.length && map.registers.length > 0
      ? [
          "Bit-field layouts unavailable from this datasheet — the generated driver will expose whole-register access instead of named fields.",
        ]
      : []),
  ];

  const th =
    "text-left px-2 py-1 text-[10px] uppercase tracking-[0.12em] text-ink-dim font-medium select-none";
  const td = "px-2 py-0.5 font-mono text-[13px] whitespace-nowrap";

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={EASE}
      className="grid gap-4 w-full"
    >
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div className="font-mono text-[13px] text-ink-dim">
          <span className="text-ink">{map.chip}</span>
          {map.peripheral && <> · {map.peripheral}</>}
          {map.base_address && (
            <>
              {" "}
              · base <span className="text-accent">{map.base_address}</span>
            </>
          )}
          {!map.base_address && <> · bus-attached device (no memory base)</>}
          {" · confidence "}
          <Confidence level={map.extraction_confidence} />
        </div>
        <div className="flex items-end gap-3">
          <div className="w-40">
            <Field label="Target platform">
              <input
                className={inputCls}
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
              />
            </Field>
          </div>
          {/* the single Generate button in the entire product */}
          <Button kind="primary" onClick={() => onGenerate(map, platform, edits)}>
            Generate driver
          </Button>
        </div>
      </div>

      {warnings.length > 0 && (
        <Panel title="Warnings">
          <ul className="p-3 grid gap-1">
            {warnings.map((w, i) => (
              <li key={i} className="flex gap-2 text-[13px] text-amber">
                <span aria-hidden>!</span>
                <span>{w}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {map.registers.length > 0 && (
        <Panel title={`Registers (${map.registers.length}) — click a value to edit`}>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead className="border-b border-line">
                <tr>
                  <th className={th}></th>
                  <th className={th}>
                    <button onClick={() => setSort("name")} className="uppercase">
                      Name {sort === "name" && "▾"}
                    </button>
                  </th>
                  <th className={th}>
                    <button onClick={() => setSort("offset")} className="uppercase">
                      Offset {sort === "offset" && "▾"}
                    </button>
                  </th>
                  <th className={th}>Reset</th>
                  <th className={th}>Access</th>
                  <th className={th}>Fields</th>
                  <th className={th}>Pages</th>
                  <th className={th}>Conf</th>
                  <th className={th}></th>
                </tr>
              </thead>
              <tbody>
                {registers.map(({ r, i }) => (
                  <RegisterRow
                    key={`${r.name}-${r.offset}`}
                    r={r}
                    expanded={expanded.has(i)}
                    onToggle={() =>
                      setExpanded((s) => {
                        const n = new Set(s);
                        if (n.has(i)) n.delete(i);
                        else n.add(i);
                        return n;
                      })
                    }
                    onEdit={(f, v) => editRegister(i, f, v)}
                    onDelete={() => deleteRegister(i)}
                    td={td}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {(map.commands?.length ?? 0) > 0 && (
        <Panel title={`Commands (${map.commands!.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead className="border-b border-line">
                <tr>
                  <th className={th}>Name</th>
                  <th className={th}>Opcode</th>
                  <th className={th}>Addr bytes</th>
                  <th className={th}>Direction</th>
                  <th className={th}>Detail</th>
                  <th className={th}>Pages</th>
                  <th className={th}></th>
                </tr>
              </thead>
              <tbody>
                {map.commands!.map((c: Command, i) => (
                  <tr
                    key={`${c.name}-${c.opcode}`}
                    className="border-b border-line/50 hover:bg-panel-2"
                  >
                    <td className={`${td} text-ink`}>{c.name}</td>
                    <td className={`${td} text-accent`}>{c.opcode}</td>
                    <td className={td}>{c.address_bytes ?? "—"}</td>
                    <td className={td}>{c.data_direction ?? "—"}</td>
                    <td className={`${td} text-ink-dim max-w-72 truncate`}>
                      {c.description || "—"}
                    </td>
                    <td className={`${td} text-ink-faint`}>
                      {c.source_pages.join(",")}
                    </td>
                    <td className={td}>
                      <button
                        aria-label={`delete command ${c.name}`}
                        onClick={() => deleteCommand(i)}
                        className="text-ink-faint hover:text-red px-1"
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {edits.length > 0 && (
        <Panel title={`Your edits (${edits.length}) — included in provenance`}>
          <ul className="p-3 grid gap-0.5 font-mono text-[12px] text-ink-dim">
            {edits.map((e, i) => (
              <li key={i}>· {e}</li>
            ))}
          </ul>
        </Panel>
      )}
    </motion.div>
  );
}

function RegisterRow({
  r,
  expanded,
  onToggle,
  onEdit,
  onDelete,
  td,
}: {
  r: Register;
  expanded: boolean;
  onToggle: () => void;
  onEdit: (field: keyof Register, value: string) => void;
  onDelete: () => void;
  td: string;
}) {
  const cell = (field: keyof Register, value: string, width: string) => (
    <input
      className={`cell font-mono text-[13px] ${width}`}
      defaultValue={value}
      aria-label={`${r.name} ${field}`}
      onBlur={(e) => onEdit(field, e.target.value.trim())}
    />
  );
  return (
    <>
      <tr className="border-b border-line/50 hover:bg-panel-2">
        <td className={td}>
          {r.fields.length > 0 && (
            <button
              aria-expanded={expanded}
              aria-label={`${r.name} bit fields`}
              onClick={onToggle}
              className="text-ink-faint hover:text-ink w-4"
            >
              {expanded ? "▾" : "▸"}
            </button>
          )}
        </td>
        <td className={`${td} text-ink`}>{cell("name", r.name, "w-52")}</td>
        <td className={`${td} text-accent`}>{cell("offset", r.offset, "w-20")}</td>
        <td className={td}>{cell("reset_value", r.reset_value ?? "", "w-20")}</td>
        <td className={td}>{cell("access", r.access ?? "", "w-14")}</td>
        <td className={`${td} ${r.fields.length ? "text-ink" : "text-ink-faint"}`}>
          {r.fields.length || "unknown"}
        </td>
        <td className={`${td} text-ink-faint`}>{r.source_pages.join(",")}</td>
        <td className={td}>
          <Confidence level={r.confidence} />
        </td>
        <td className={td}>
          <button
            aria-label={`delete register ${r.name}`}
            onClick={onDelete}
            className="text-ink-faint hover:text-red px-1"
          >
            ✕
          </button>
        </td>
      </tr>
      {expanded &&
        r.fields.map((f) => (
          <tr key={f.name} className="border-b border-line/30 bg-panel-2/50">
            <td></td>
            <td className={`${td} pl-8 text-ink-dim`} colSpan={2}>
              {f.name}
            </td>
            <td className={`${td} text-amber`} colSpan={2}>
              {f.bits}
            </td>
            <td className={`${td} text-ink-faint`} colSpan={4}>
              {f.description || ""}
            </td>
          </tr>
        ))}
    </>
  );
}
