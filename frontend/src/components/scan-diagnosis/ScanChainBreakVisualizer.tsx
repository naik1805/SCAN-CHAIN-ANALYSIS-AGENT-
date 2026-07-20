"use client";

import { useMemo, useState } from "react";
import {
  breakDieLabel,
  buildBreakSchematic,
  sortBreakRows,
  type SchematicCell,
} from "@/lib/scanChainBreak/buildBreakSchematic";

const Y = 90;
const X_START = 220;
const X_SPACING = 75;

function cellStyles(kind: SchematicCell["kind"]) {
  if (kind === "break") {
    return {
      fill: "rgba(239, 68, 68, 0.2)",
      stroke: "#ef4444",
      text: "#fee2e2",
      glow: true,
    };
  }
  if (kind === "upstream") {
    return {
      fill: "rgba(249, 115, 22, 0.08)",
      stroke: "rgba(249, 115, 22, 0.5)",
      text: "#ffedd5",
      glow: false,
    };
  }
  if (kind === "downstream") {
    return {
      fill: "rgba(16, 185, 129, 0.08)",
      stroke: "rgba(16, 185, 129, 0.5)",
      text: "#a7f3d0",
      glow: false,
    };
  }
  return { fill: "transparent", stroke: "transparent", text: "#9ca3af", glow: false };
}

function connectorColor(left: SchematicCell, right: SchematicCell): string {
  if (left.kind === "downstream" || right.kind === "downstream") return "#10b981";
  return "#f97316";
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-card/60 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="truncate text-sm text-white">{value}</div>
    </div>
  );
}

export function ScanChainBreakVisualizer({
  rows,
}: {
  rows: Record<string, unknown>[];
}) {
  const sorted = useMemo(() => sortBreakRows(rows), [rows]);
  const dieOptions = useMemo(
    () => [...new Set(sorted.map(breakDieLabel))].sort(),
    [sorted],
  );

  const [die, setDie] = useState("");
  const [chain, setChain] = useState("");

  const activeDie = die || dieOptions[0] || "";
  const chainsForDie = useMemo(() => {
    const list = sorted
      .filter((r) => breakDieLabel(r) === activeDie)
      .map((r) => String(r.chain ?? ""));
    return [...new Set(list)].sort(
      (a, b) =>
        Number(a.replace(/\D/g, "") || 0) - Number(b.replace(/\D/g, "") || 0) ||
        a.localeCompare(b),
    );
  }, [sorted, activeDie]);

  const activeChain = chain || chainsForDie[0] || "";

  const selected = useMemo(
    () =>
      sorted.find(
        (r) => breakDieLabel(r) === activeDie && String(r.chain) === activeChain,
      ),
    [sorted, activeDie, activeChain],
  );

  const schematic = useMemo(
    () => (selected ? buildBreakSchematic(selected) : null),
    [selected],
  );

  if (!sorted.length) {
    return (
      <div className="rounded-xl border border-border bg-card/40 p-6 text-sm text-slate-400">
        No scan chain breaks detected in the active dataset.
      </div>
    );
  }

  const status = String(selected?.location_status ?? "UNCERTAIN");
  const locConf = Number(selected?.location_confidence ?? 0);
  const N = schematic?.breakBit ?? 0;
  const exactBit =
    status === "CERTAIN" && selected?.exact_break_bit_position != null
      ? String(selected.exact_break_bit_position)
      : "—";
  const candidateCell =
    String(selected?.candidate_break_cell ?? selected?.suspected_break_cell ?? "—");
  const exactCell =
    status === "CERTAIN"
      ? String(selected?.exact_break_cell ?? candidateCell)
      : candidateCell;

  const lastCellEnd =
    schematic ? X_START + (schematic.cells.length - 1) * X_SPACING + 50 : 0;
  const compactorX = lastCellEnd + 25;
  const scanOutX = compactorX + 85 + 25;

  return (
    <div className="space-y-4 rounded-xl border border-border bg-[#060814] p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs text-slate-400">
          Select affected die (Lot · Log File)
          <select
            value={activeDie}
            onChange={(e) => {
              setDie(e.target.value);
              setChain("");
            }}
            className="mt-1 w-full rounded-lg border border-border bg-[#0c111c] px-3 py-2 text-sm text-white"
          >
            {dieOptions.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-slate-400">
          Select broken scan chain
          <select
            value={activeChain}
            onChange={(e) => setChain(e.target.value)}
            className="mt-1 w-full rounded-lg border border-border bg-[#0c111c] px-3 py-2 text-sm text-white"
          >
            {chainsForDie.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </label>
      </div>

      {status === "CERTAIN" ? (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
          Chain break detected — pattern agreement {(locConf * 100).toFixed(1)}%. Localized at bit {N}{" "}
          · cell <span className="font-mono">{String(selected?.exact_break_cell)}</span>.
        </div>
      ) : (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
          Chain break detected — candidate break at bit {N} · cell{" "}
          <span className="font-mono">{candidateCell}</span>. Pattern agreement{" "}
          {(locConf * 100).toFixed(1)}% (below 70% threshold for exact localization).
        </div>
      )}

      <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Metric label="Break Localization" value={status} />
        <Metric label="Localized Break Bit" value={exactBit} />
        <Metric label="Candidate Break Bit" value={String(N)} />
        <Metric
          label={status === "CERTAIN" ? "Break Cell" : "Candidate Cell"}
          value={status === "CERTAIN" ? exactCell : candidateCell}
        />
        <Metric label="Pattern Agreement" value={`${(locConf * 100).toFixed(1)}%`} />
        <Metric label="Failing Records" value={String(selected?.fail_count ?? "—")} />
      </div>

      <div>
        <h4 className="mb-2 font-display text-sm font-semibold text-white">
          Zoomed Scan Chain Break Schematic Diagram
        </h4>
        {status === "UNCERTAIN" ? (
          <p className="mb-2 text-[11px] text-amber-200/80">
            Red highlight = candidate break bit from log analysis. CERTAIN status requires ≥70%
            pattern agreement across ≥2 patterns.
          </p>
        ) : null}
        {schematic ? (
          <div className="overflow-x-auto rounded-xl border border-white/[0.03] bg-[#060814] p-2">
            <svg
              viewBox={`0 0 ${schematic.width} 180`}
              className="min-w-[720px]"
              style={{ height: 180, width: "100%" }}
              role="img"
              aria-label="Scan chain break schematic"
            >
              <defs>
                <marker
                  id="arrow-green"
                  viewBox="0 0 10 10"
                  refX="6"
                  refY="5"
                  markerWidth="5"
                  markerHeight="5"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#10b981" />
                </marker>
                <marker
                  id="arrow-orange"
                  viewBox="0 0 10 10"
                  refX="6"
                  refY="5"
                  markerWidth="5"
                  markerHeight="5"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#f97316" />
                </marker>
              </defs>

              <rect
                x="15"
                y={Y - 35}
                width="80"
                height="70"
                rx="6"
                fill="rgba(249, 115, 22, 0.08)"
                stroke="rgba(249, 115, 22, 0.25)"
                strokeWidth="1.5"
              />
              <text x="55" y={Y - 15} fill="#f97316" fontSize="9" fontWeight="700" textAnchor="middle">
                SCAN INPUT
              </text>
              <text x="55" y={Y + 12} fill="#ffedd5" fontSize="10" fontWeight="500" textAnchor="middle">
                {schematic.scanIn}
              </text>
              <path
                d={`M 95 ${Y} L 115 ${Y}`}
                stroke="#f97316"
                strokeWidth="1.5"
                markerEnd="url(#arrow-orange)"
              />

              <rect
                x="120"
                y={Y - 35}
                width="80"
                height="70"
                rx="6"
                fill="rgba(59, 130, 246, 0.08)"
                stroke="rgba(59, 130, 246, 0.25)"
                strokeWidth="1.5"
              />
              <text x="160" y={Y - 15} fill="#3b82f6" fontSize="9" fontWeight="700" textAnchor="middle">
                DECOMPRESSOR
              </text>
              <text x="160" y={Y + 12} fill="#dbeafe" fontSize="9" fontWeight="500" textAnchor="middle">
                {schematic.decompChannel}
              </text>
              <path
                d={`M 200 ${Y} L 215 ${Y}`}
                stroke="#f97316"
                strokeWidth="1.5"
                markerEnd="url(#arrow-orange)"
              />

              {schematic.cells.map((cell, idx) => {
                const x = X_START + idx * X_SPACING;
                const styles = cellStyles(cell.kind);
                const next = schematic.cells[idx + 1];
                const pathColor = next ? connectorColor(cell, next) : "#f97316";
                const marker = pathColor === "#10b981" ? "url(#arrow-green)" : "url(#arrow-orange)";

                return (
                  <g key={`${cell.label}-${idx}`}>
                    {cell.kind === "ellipsis" ? (
                      <text x={x + 15} y={Y + 8} fill="#9ca3af" fontSize="20" textAnchor="middle">
                        ...
                      </text>
                    ) : (
                      <g className={styles.glow ? "animate-pulse" : undefined}>
                        <title>
                          {`Position: ${cell.bit}\nCell: ${cell.cellPath}\nStatus: ${cell.kind.toUpperCase()}`}
                        </title>
                        <rect
                          x={x}
                          y={Y - 20}
                          width="50"
                          height="40"
                          rx="6"
                          fill={styles.fill}
                          stroke={styles.stroke}
                          strokeWidth={cell.kind === "break" ? 2 : 1.5}
                        />
                        <text
                          x={x + 25}
                          y={Y + 4}
                          fill={styles.text}
                          fontSize="9"
                          fontWeight="600"
                          textAnchor="middle"
                        >
                          {cell.label}
                        </text>
                      </g>
                    )}
                    {next ? (
                      cell.kind !== "ellipsis" && next.kind !== "ellipsis" ? (
                        <path
                          d={`M ${x + 50} ${Y} L ${x + X_SPACING - 5} ${Y}`}
                          stroke={pathColor}
                          strokeWidth="1.5"
                          markerEnd={marker}
                        />
                      ) : cell.kind !== "ellipsis" && next.kind === "ellipsis" ? (
                        <path
                          d={`M ${x + 50} ${Y} L ${x + X_SPACING - 5} ${Y}`}
                          stroke={pathColor}
                          strokeWidth="1.5"
                          strokeDasharray="2 2"
                        />
                      ) : cell.kind === "ellipsis" && next.kind !== "ellipsis" ? (
                        <path
                          d={`M ${x + 35} ${Y} L ${x + X_SPACING - 5} ${Y}`}
                          stroke={pathColor}
                          strokeWidth="1.5"
                          strokeDasharray="2 2"
                          markerEnd={marker}
                        />
                      ) : null
                    ) : null}
                  </g>
                );
              })}

              <path
                d={`M ${lastCellEnd} ${Y} L ${compactorX - 5} ${Y}`}
                stroke="#10b981"
                strokeWidth="1.5"
                markerEnd="url(#arrow-green)"
              />
              <rect
                x={compactorX}
                y={Y - 35}
                width="85"
                height="70"
                rx="6"
                fill="rgba(59, 130, 246, 0.08)"
                stroke="rgba(59, 130, 246, 0.25)"
                strokeWidth="1.5"
              />
              <text
                x={compactorX + 42.5}
                y={Y - 15}
                fill="#3b82f6"
                fontSize="9"
                fontWeight="700"
                textAnchor="middle"
              >
                COMPACTOR
              </text>
              <text
                x={compactorX + 42.5}
                y={Y + 12}
                fill="#dbeafe"
                fontSize="9"
                fontWeight="500"
                textAnchor="middle"
              >
                {schematic.compChannel}
              </text>
              <path
                d={`M ${compactorX + 85} ${Y} L ${scanOutX - 5} ${Y}`}
                stroke="#f97316"
                strokeWidth="1.5"
                markerEnd="url(#arrow-orange)"
              />
              <rect
                x={scanOutX}
                y={Y - 35}
                width="85"
                height="70"
                rx="6"
                fill="rgba(249, 115, 22, 0.08)"
                stroke="rgba(249, 115, 22, 0.25)"
                strokeWidth="1.5"
              />
              <text
                x={scanOutX + 42.5}
                y={Y - 15}
                fill="#f97316"
                fontSize="9"
                fontWeight="700"
                textAnchor="middle"
              >
                SCAN OUTPUT
              </text>
              <text
                x={scanOutX + 42.5}
                y={Y + 12}
                fill="#ffedd5"
                fontSize="10"
                fontWeight="500"
                textAnchor="middle"
              >
                {schematic.scanOut}
              </text>
            </svg>
          </div>
        ) : null}
      </div>
    </div>
  );
}
