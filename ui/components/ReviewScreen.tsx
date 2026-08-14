"use client";

/* Screen 2: register map review — dense, sortable, editable before generation.
   V1.6: the top "Confirm device inputs" panel is the gate. Chip and interface
   arrive detected-from-the-document and must be confirmed or corrected; the
   platform is an explicit dropdown. The ONE Generate button stays disabled
   until every input carries a user/detected provenance — no silent defaults,
   no invented values reach the worker. Edits travel into provenance. */

import { motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import type {
  Command,
  DetectedValue,
  Provenance,
  Register,
  RegisterMap,
  Target,
} from "../lib/types";
import { OUTPUT_TARGETS, PLATFORMS } from "../lib/types";
import { getMcuMap, listMcuMaps, type McuMapSummary } from "../lib/api";
import {
  Button,
  Confidence,
  EASE,
  Field,
  Panel,
  ProvenanceTag,
  Select,
  inputCls,
} from "./ui";

type SortKey = "name" | "offset";

const KNOWN_PLATFORMS = new Set(PLATFORMS.map((p) => p.value).filter((v) => v !== "other"));

export function ReviewScreen({
  map: initialMap,
  platform: initialPlatform,
  onGenerate,
}: {
  map: RegisterMap;
  platform: string;
  onGenerate: (
    map: RegisterMap,
    platform: string,
    edits: string[],
    mcuMap?: unknown,
    target?: Target,
  ) => void;
}) {
  const [map, setMap] = useState<RegisterMap>(initialMap);
  const [edits, setEdits] = useState<string[]>([]);
  const [target, setTarget] = useState<Target>("bare-metal");
  const [sort, setSort] = useState<SortKey>("offset");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  // --- confirmable device inputs (Priority 1 gate) ---
  const [chip, setChip] = useState(initialMap.chip ?? "");
  const [chipProv, setChipProv] = useState<Provenance>(
    initialMap.provenance?.chip ?? null,
  );
  const [iface, setIface] = useState(initialMap.peripheral ?? "");
  const [ifaceProv, setIfaceProv] = useState<Provenance>(
    initialMap.provenance?.peripheral ?? null,
  );
  // platform: prefill the dropdown if it maps to a known token, else "Other"
  const [platformSel, setPlatformSel] = useState(
    initialPlatform && KNOWN_PLATFORMS.has(initialPlatform) ? initialPlatform
      : initialPlatform ? "other" : "",
  );
  const [platformOther, setPlatformOther] = useState(
    initialPlatform && !KNOWN_PLATFORMS.has(initialPlatform) ? initialPlatform : "",
  );

  const detectedChip = initialMap.detected?.chip;
  const detectedIfaces = initialMap.detected?.interfaces ?? [];
  const detectedVendor = initialMap.detected?.vendor;

  // V1.7 two-document flow: an optional MCU from the cached library turns this
  // into a complete driver (clock/GPIO/init/error) cross-checked against the MCU.
  const [mcuMaps, setMcuMaps] = useState<McuMapSummary[]>([]);
  const [mcuId, setMcuId] = useState("");
  const [mcuMap, setMcuMap] = useState<unknown>(null);
  useEffect(() => {
    listMcuMaps().then(setMcuMaps).catch(() => setMcuMaps([]));
  }, []);

  const track = (msg: string) => setEdits((e) => [...e, msg]);

  const pickMcu = async (id: string) => {
    setMcuId(id);
    if (!id) {
      setMcuMap(null);
      track("MCU: none (device-only driver)");
      return;
    }
    try {
      setMcuMap(await getMcuMap(id));
      track(`MCU: ${id} (complete driver)`);
    } catch {
      setMcuMap(null);
    }
  };

  const platform =
    platformSel === "other" ? platformOther.trim() : platformSel;

  // 'sample' provenance (bundled sample maps) is generatable, same as the API
  // gate accepts it — otherwise the Generate button stays disabled for samples.
  const resolved = (v: string, p: Provenance) =>
    v.trim() !== "" && (p === "user" || p === "detected" || p === "sample");
  const chipOk = resolved(chip, chipProv);
  const ifaceOk = resolved(iface, ifaceProv);
  const platformOk = platform.trim() !== "";
  const canGenerate = chipOk && ifaceOk && platformOk;

  const missing = [
    !chipOk && "chip / part number",
    !ifaceOk && "interface",
    !platformOk && "target platform",
  ].filter(Boolean) as string[];

  const editChip = (v: string) => {
    setChip(v);
    setChipProv("user");
    track(`chip: "${chip}" -> "${v}" (user)`);
  };
  const confirmChip = () => {
    setChipProv("detected");
    track(`chip confirmed as detected: "${chip}"`);
  };
  const pickIface = (v: string) => {
    setIface(v);
    setIfaceProv("detected");
    track(`interface confirmed as detected: "${v}"`);
  };
  const editIface = (v: string) => {
    setIface(v);
    setIfaceProv("user");
    track(`interface: "${iface}" -> "${v}" (user)`);
  };

  const submit = () => {
    const finalMap: RegisterMap = {
      ...map,
      chip: chip.trim(),
      peripheral: iface.trim(),
      provenance: { chip: chipProv, peripheral: ifaceProv },
    };
    // the Arduino target never uses an MCU map (items 4-6 are the core's job)
    const mcu = target === "arduino" ? undefined : (mcuMap ?? undefined);
    onGenerate(finalMap, platform, edits, mcu, target);
  };

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
    setMap((m) => ({ ...m, registers: m.registers.filter((_, k) => k !== i) }));
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
  const shapeHint = initialMap.detected?.shape_hint?.value?.replace(/_/g, " ");

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={EASE}
      className="grid gap-4 w-full"
    >
      {/* --- the input gate: confirm what the datasheet says, pick a platform --- */}
      <Panel title="Confirm device inputs">
        <div className="p-4 grid gap-4">
          <p className="text-[12px] text-ink-dim">
            Values below were <span className="text-amber">detected from the datasheet</span>.
            Confirm or correct them — generation is blocked until each is set. Nothing is
            auto-filled with a guess.
          </p>

          {/* V1.8: output target — bare-metal C driver or importable Arduino library */}
          <Field label="Output target">
            <div className="flex gap-1.5" role="radiogroup" aria-label="Output target">
              {OUTPUT_TARGETS.map((t) => (
                <button
                  key={t.value}
                  role="radio"
                  aria-checked={target === t.value}
                  onClick={() => {
                    setTarget(t.value);
                    track(`output target: ${t.value}`);
                  }}
                  className={`flex-1 text-left border rounded-sm px-3 py-2 transition-colors ${
                    target === t.value
                      ? "border-accent-dim bg-accent/10 text-ink"
                      : "border-line-2 text-ink-dim hover:border-ink-faint"
                  }`}
                >
                  <div className="font-mono text-[12px]">{t.label}</div>
                  <div className="text-[10.5px] text-ink-faint mt-0.5 leading-snug">
                    {t.hint}
                  </div>
                </button>
              ))}
            </div>
          </Field>

          <div className="grid gap-4 sm:grid-cols-3">
            {/* chip */}
            <div className="grid gap-1.5">
              <Field label="Chip / part number">
                <input
                  className={inputCls}
                  placeholder="e.g. BME280"
                  value={chip}
                  onChange={(e) => editChip(e.target.value)}
                />
              </Field>
              <div className="flex items-center gap-2 min-h-6">
                <ProvenanceTag
                  state={chip.trim() === "" ? "empty" : (chipProv ?? "detected_unconfirmed")}
                  pages={detectedChip?.source_pages}
                />
                {chipProv === "detected_unconfirmed" && chip.trim() !== "" && (
                  <button
                    onClick={confirmChip}
                    className="text-[11px] text-accent hover:underline underline-offset-2"
                  >
                    confirm
                  </button>
                )}
                {detectedVendor && (
                  <span className="text-[10px] text-ink-faint font-mono">
                    {detectedVendor.value}
                  </span>
                )}
              </div>
            </div>

            {/* interface */}
            <div className="grid gap-1.5">
              <Field label="Interface">
                <input
                  className={inputCls}
                  placeholder="e.g. I2C"
                  value={iface}
                  onChange={(e) => editIface(e.target.value)}
                />
              </Field>
              <div className="flex flex-wrap items-center gap-2 min-h-6">
                {detectedIfaces.length >= 2 ? (
                  <>
                    <span className="text-[10px] text-amber uppercase tracking-wide">
                      choose:
                    </span>
                    {detectedIfaces.map((d: DetectedValue) => (
                      <button
                        key={d.value}
                        onClick={() => pickIface(d.value)}
                        className={`border rounded-sm px-1.5 py-0.5 font-mono text-[11px] ${
                          iface === d.value && ifaceProv === "detected"
                            ? "text-accent border-accent-dim bg-accent/10"
                            : "text-ink-dim border-line-2 hover:border-ink-faint"
                        }`}
                      >
                        {d.value}
                        <span className="text-ink-faint">
                          {d.source_pages.length ? ` p.${d.source_pages.join(",")}` : ""}
                        </span>
                      </button>
                    ))}
                  </>
                ) : (
                  <>
                    <ProvenanceTag
                      state={iface.trim() === "" ? "empty" : (ifaceProv ?? "detected_unconfirmed")}
                      pages={detectedIfaces[0]?.source_pages}
                    />
                    {ifaceProv === "detected_unconfirmed" && iface.trim() !== "" && (
                      <button
                        onClick={() => pickIface(iface)}
                        className="text-[11px] text-accent hover:underline underline-offset-2"
                      >
                        confirm
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>

            {/* platform */}
            <div className="grid gap-1.5">
              <Field label="Target platform">
                <Select
                  ariaLabel="Target platform"
                  value={platformSel}
                  placeholder="Select platform…"
                  onChange={(v) => {
                    setPlatformSel(v);
                    track(`platform: "${platform}" -> "${v}"`);
                  }}
                  options={PLATFORMS}
                />
              </Field>
              {platformSel === "other" && (
                <input
                  className={inputCls}
                  placeholder="toolchain / MCU, e.g. RP2040"
                  value={platformOther}
                  onChange={(e) => setPlatformOther(e.target.value)}
                />
              )}
              {shapeHint && (
                <span className="text-[10px] text-ink-faint font-mono">
                  shape: {shapeHint}
                </span>
              )}
              {target === "arduino" ? (
                <span className="text-[10px] text-ink-faint font-mono leading-snug">
                  Arduino target: board-agnostic — you pass the {iface || "Wire/SPI"}
                  {" "}instance and pins in your sketch, so there is no peripheral
                  instance to choose. Clock, GPIO and init are the Arduino core&apos;s
                  job (items 4–6). Platform selects the compile cores only.
                </span>
              ) : (
                mcuMaps.length > 0 && (
                  <Field label="Target MCU (optional — complete driver)">
                    <Select
                      ariaLabel="Target MCU"
                      value={mcuId}
                      placeholder="None — device-only driver"
                      onChange={pickMcu}
                      options={[
                        { value: "", label: "None — device-only driver" },
                        ...mcuMaps.map((m) => ({
                          value: m.id,
                          label: `${m.label}${m.rm_revision ? ` (${m.rm_revision})` : ""}`,
                        })),
                      ]}
                    />
                    <span className="text-[10px] text-ink-faint font-mono">
                      {mcuId
                        ? "adds clock, GPIO/AF, init & error handling — cross-checked against the MCU map, then the peripheral instance (I2C1/2/3) is your pick"
                        : "device register access only (items 1–3)"}
                    </span>
                  </Field>
                )
              )}
            </div>
          </div>

          <div className="flex items-center gap-3 border-t border-line pt-3">
            {/* the single Generate button in the entire product */}
            <Button kind="primary" onClick={submit} disabled={!canGenerate}>
              Generate driver
            </Button>
            {!canGenerate && (
              <span role="alert" className="text-[12px] text-amber">
                Confirm {missing.join(", ")} before generating.
              </span>
            )}
          </div>
        </div>
      </Panel>

      <div className="font-mono text-[13px] text-ink-dim">
        <span className="text-ink">{chip || "—"}</span>
        {iface && <> · {iface}</>}
        {map.base_address ? (
          <>
            {" "}
            · base <span className="text-accent">{map.base_address}</span>
          </>
        ) : (
          <> · bus-attached device (no memory base)</>
        )}
        {" · confidence "}
        <Confidence level={map.extraction_confidence} />
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
