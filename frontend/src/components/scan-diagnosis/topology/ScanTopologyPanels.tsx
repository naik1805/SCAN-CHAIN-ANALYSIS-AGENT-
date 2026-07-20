"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { JsonDataTable } from "../JsonDataTable";

type PanelMeta = Record<string, unknown>;
type Row = Record<string, unknown>;

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-card/60 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="truncate text-sm text-white">{value}</div>
    </div>
  );
}

export function TopologyOverviewPanel({ meta }: { meta: PanelMeta }) {
  const summary = (meta.summary || {}) as PanelMeta;
  const balance = (meta.chain_balance || {}) as PanelMeta;
  const compression = (meta.compression || {}) as PanelMeta;
  const dieCtx = (summary.die_context_from_logs || {}) as PanelMeta;

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Metric label="Scan Chains" value={String(meta.number_of_scan_chains ?? "—")} />
        <Metric
          label="Total FFs"
          value={Number(summary.total_flip_flops ?? 0).toLocaleString()}
        />
        <Metric
          label="Chain Length"
          value={`${summary.min_chain_length ?? "—"}–${summary.max_chain_length ?? "—"}`}
        />
        <Metric
          label="Balance"
          value={
            balance.is_balanced
              ? "Balanced"
              : `${Number(balance.imbalance_pct ?? 0).toFixed(1)}% skew`
          }
        />
        <Metric
          label="Compression"
          value={`${Number(compression.compression_ratio ?? 0).toFixed(1)}x`}
        />
        <Metric label="Logs Used" value={String(summary.logs_analyzed ?? "—")} />
      </div>
      {dieCtx.logs_analyzed ? (
        <p className="text-xs text-slate-500">
          Die context from {String(dieCtx.logs_analyzed)} logs — wafer centre ≈ (
          {String(dieCtx.wafer_x_mean ?? "N/A")}, {String(dieCtx.wafer_y_mean ?? "N/A")}) mm,
          die rows {JSON.stringify(dieCtx.die_row_range)}, cols{" "}
          {JSON.stringify(dieCtx.die_col_range)}.
        </p>
      ) : null}
    </div>
  );
}

export function TopologyChainBalancePanel({
  table,
  meta,
}: {
  table: Row[];
  meta: PanelMeta;
}) {
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-4">
        <Metric label="Min Length" value={String(meta.min_length ?? "—")} />
        <Metric label="Max Length" value={String(meta.max_length ?? "—")} />
        <Metric label="Mean Length" value={String(meta.mean_length ?? "—")} />
        <Metric label="Std Dev" value={String(meta.std_length ?? "—")} />
      </div>
      <div className="glass-card p-4" style={{ height: Math.max(320, table.length * 28 + 80) }}>
        <h4 className="mb-2 text-sm font-semibold text-white">
          Scan Chain Length Distribution
        </h4>
        {table.length ? (
          <ResponsiveContainer width="100%" height="90%">
            <BarChart data={table} margin={{ left: 4, right: 8, top: 4, bottom: 60 }}>
              <CartesianGrid stroke="#2D3748" strokeDasharray="3 3" />
              <XAxis
                dataKey="chain"
                stroke="#94a3b8"
                fontSize={9}
                angle={-45}
                textAnchor="end"
                height={70}
                interval={0}
              />
              <YAxis stroke="#94a3b8" fontSize={11} label={{ value: "Length (FFs)", angle: -90, position: "insideLeft", fill: "#94a3b8" }} />
              <Tooltip
                contentStyle={{
                  background: "#111827",
                  border: "1px solid #2D3748",
                  borderRadius: 12,
                }}
              />
              <Bar dataKey="chain_length" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-48 items-center justify-center text-sm text-slate-500">
            No chain balance data
          </div>
        )}
      </div>
    </div>
  );
}

export function TopologySharedResourcesPanel({ meta }: { meta: PanelMeta }) {
  const [tab, setTab] = useState<"clocks" | "se" | "decomp">("clocks");
  const clocks = (meta.shared_clocks as Row[]) || [];
  const se = (meta.shared_scan_enable as Row[]) || [];
  const decomp = (meta.shared_decompressor_channels as Row[]) || [];

  const tabs = [
    { id: "clocks" as const, label: "Clocks", rows: clocks },
    { id: "se" as const, label: "Scan Enable", rows: se },
    { id: "decomp" as const, label: "Decompressor Channels", rows: decomp },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 border-b border-border pb-2">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
              tab === t.id
                ? "bg-primary/20 text-violet-200 ring-1 ring-primary/40"
                : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tabs.find((t) => t.id === tab)?.rows.length ? (
        <JsonDataTable rows={tabs.find((t) => t.id === tab)!.rows} maxHeightClass="max-h-64" />
      ) : (
        <p className="text-sm text-slate-500">
          {tab === "clocks"
            ? "No clock domains shared across multiple chains."
            : tab === "se"
              ? "No scan-enable signals shared across multiple chains."
              : "Each chain maps to a distinct decompressor channel."}
        </p>
      )}
      <p className="text-xs text-slate-500">
        Active clocks: {((meta.active_clocks as string[]) || []).join(", ") || "—"}
      </p>
      <p className="text-xs text-slate-500">
        Scan-enable signals:{" "}
        {((meta.scan_enable_signals as string[]) || []).join(", ") || "—"}
      </p>
    </div>
  );
}

function chainLabel(entry: Row): string {
  const inst = String(entry.instance_type ?? "");
  const short = inst === "core_inst" ? "core" : inst === "phy_inst" ? "phy" : inst;
  const name = String(entry.chain_name ?? "?");
  return short ? `${name} (${short})` : name;
}

export function TopologySchematicPanel({
  entries,
  chains,
  selectedChainId,
  onSelectChain,
}: {
  entries: Row[];
  chains: Row[];
  selectedChainId?: string | null;
  onSelectChain?: (chainId: string | null) => void;
}) {
  const [uid, setUid] = useState("");
  const activeUid = uid || String(entries[0]?.uid ?? "");

  useEffect(() => {
    if (!selectedChainId) return;
    const match = entries.find((e) => e.scan_chain_id === selectedChainId);
    if (match?.uid) setUid(String(match.uid));
  }, [selectedChainId, entries]);
  const activeEntry = entries.find((e) => e.uid === activeUid) || entries[0];
  const activeChain = useMemo(() => {
    if (!activeEntry) return null;
    const cid = activeEntry.scan_chain_id;
    return chains.find((c) => c.scan_chain_id === cid) as Row | undefined;
  }, [activeEntry, chains]);

  const cellRows = useMemo(() => {
    const cells = (activeChain?.cells as Row[]) || [];
    return cells.map((cell) => ({
      position: cell.position,
      bit_position: cell.bit_position,
      offset_from_scan_in: cell.offset_from_scan_in,
      cell_name: cell.cell_name,
    }));
  }, [activeChain]);

  const connRows = ((activeChain?.scan_cell_connectivity as Row[]) || []).slice(0, 500);
  const physRows = useMemo(() => {
    const cells = (activeChain?.cells as Row[]) || [];
    return cells.map((cell) => {
      const phys = (cell.physical_location || {}) as Row;
      return {
        cell_name: cell.cell_name,
        position: cell.position,
        x_local_um: phys.x_local_um,
        y_local_um: phys.y_local_um,
      };
    });
  }, [activeChain]);

  const evRows = useMemo(() => {
    const cells = (activeChain?.cells as Row[]) || [];
    return cells
      .filter((c) => c.log_evidence)
      .map((c) => {
        const ev = c.log_evidence as Row;
        return {
          cell_name: c.cell_name,
          failure_observations: ev.failure_observations,
          distinct_logs: ev.distinct_logs,
          distinct_dies: ev.distinct_dies,
        };
      });
  }, [activeChain]);

  const chainLogSummary = (activeChain?.log_failure_summary || {}) as Row;

  const [detailTab, setDetailTab] = useState<
    "cells" | "connectivity" | "physical" | "evidence"
  >("cells");

  if (!entries.length) {
    return <p className="text-sm text-slate-500">No scan chains available.</p>;
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(280px,360px)_1fr]">
      <div className="space-y-2 rounded-xl border border-border bg-card/40 p-3">
        <div className="text-[10px] uppercase tracking-wide text-slate-500">
          System diagram — click a chain
        </div>
        <div className="rounded-lg border border-border/60 bg-[#090B12] p-2 text-[10px] text-slate-400">
          <div className="flex items-center gap-2 pb-2">
            <span className="rounded border border-cyan-500/40 px-1.5 py-0.5 text-cyan-300">JTAG</span>
            <span>→</span>
            <span className="rounded border border-cyan-500/40 px-1.5 py-0.5 text-cyan-300">TAP</span>
            <span>→</span>
            <span className="rounded border border-violet-500/40 px-1.5 py-0.5 text-violet-300">EDT</span>
          </div>
        </div>
        <div className="max-h-[420px] space-y-0.5 overflow-y-auto">
          {entries.map((e) => {
            const selected = e.uid === activeUid;
            return (
              <button
                key={String(e.uid)}
                type="button"
                onClick={() => {
                  setUid(String(e.uid));
                  onSelectChain?.(String(e.scan_chain_id ?? "") || null);
                }}
                className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs transition ${
                  selected || String(e.scan_chain_id) === selectedChainId
                    ? "bg-primary/15 text-sky-200 ring-1 ring-primary/40"
                    : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
                }`}
              >
                <span className="font-mono text-[10px] text-slate-500">
                  [{String(e.scan_length)} FFs]
                </span>
                <span className="truncate font-medium">{chainLabel(e)}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="space-y-3">
        {activeChain ? (
          <>
            <div className="grid gap-2 sm:grid-cols-4">
              <Metric label="Chain Length" value={String(activeChain.chain_length ?? "—")} />
              <Metric label="Clock Domain" value={String(activeChain.clock_domain ?? "N/A")} />
              <Metric
                label="Scan Enable"
                value={String(activeChain.scan_enable_se ?? "N/A").slice(0, 24)}
              />
              <Metric
                label="Cells"
                value={String((activeChain.scan_cell_names as string[])?.length ?? 0)}
              />
            </div>
            <div className="grid gap-2 text-xs text-slate-400 sm:grid-cols-2">
              <div>
                SI: <span className="text-slate-200">{String(activeChain.scan_input_si)}</span>
              </div>
              <div>
                SO: <span className="text-slate-200">{String(activeChain.scan_output_so)}</span>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 border-b border-border pb-2">
              {(
                [
                  ["cells", "Cell Order & Names"],
                  ["connectivity", "Connectivity"],
                  ["physical", "Physical Locations"],
                  ["evidence", "Log Evidence"],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setDetailTab(id)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
                    detailTab === id
                      ? "bg-primary/20 text-violet-200 ring-1 ring-primary/40"
                      : "text-slate-400 hover:bg-white/5"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {detailTab === "cells" ? (
              <JsonDataTable rows={cellRows} maxHeightClass="max-h-72" showCsvDownload csvDownloadLabel="Download cell order (CSV)" />
            ) : null}
            {detailTab === "connectivity" ? (
              <>
                <JsonDataTable rows={connRows} maxHeightClass="max-h-72" />
                <p className="text-xs text-slate-500">
                  Linear scan path: {String(activeChain.scan_input_si)} →{" "}
                  {String(activeChain.chain_length)} cells → {String(activeChain.scan_output_so)}
                </p>
              </>
            ) : null}
            {detailTab === "physical" ? (
              <>
                <div className="glass-card h-64 p-2">
                  {physRows.length ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <ScatterChart margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                        <CartesianGrid stroke="#2D3748" />
                        <XAxis type="number" dataKey="x_local_um" name="X µm" stroke="#94a3b8" fontSize={10} />
                        <YAxis type="number" dataKey="y_local_um" name="Y µm" stroke="#94a3b8" fontSize={10} />
                        <ZAxis range={[40, 40]} />
                        <Tooltip
                          cursor={{ strokeDasharray: "3 3" }}
                          contentStyle={{
                            background: "#111827",
                            border: "1px solid #2D3748",
                            borderRadius: 12,
                          }}
                        />
                        <Scatter data={physRows} fill="#8b5cf6" />
                      </ScatterChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="flex h-full items-center justify-center text-sm text-slate-500">
                      No placement data
                    </div>
                  )}
                </div>
                <p className="text-xs text-slate-500">
                  Synthetic die-local coordinates (serpentine heuristic). Real DEF placement not loaded.
                </p>
                <JsonDataTable rows={physRows.slice(0, 50)} maxHeightClass="max-h-48" />
              </>
            ) : null}
            {detailTab === "evidence" ? (
              evRows.length ? (
                <JsonDataTable rows={evRows} maxHeightClass="max-h-72" />
              ) : Number(chainLogSummary.failure_records) > 0 ? (
                <div className="space-y-2 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-slate-300">
                  <p>
                    This chain has{" "}
                    <span className="font-semibold text-white">
                      {String(chainLogSummary.failure_records)}
                    </span>{" "}
                    FAIL records in the loaded logs ({String(chainLogSummary.distinct_logs)}{" "}
                    logs, {String(chainLogSummary.distinct_dies)} dies) — but no per-cell
                    evidence rows matched STIL cell names yet.
                  </p>
                  <p className="text-xs text-slate-500">
                    Chain-level failures use log IDs like <code>channel05</code>; STIL topology
                    uses <code>chain_5</code> / <code>channel5</code>. Failures are real; cell
                    mapping depends on flop → bit → cell name resolution.
                  </p>
                </div>
              ) : (
                <p className="text-sm text-slate-500">
                  No failure evidence for cells on this chain in the loaded logs.
                </p>
              )
            ) : null}
          </>
        ) : (
          <p className="text-sm text-slate-500">Select a chain from the diagram.</p>
        )}
      </div>
    </div>
  );
}
