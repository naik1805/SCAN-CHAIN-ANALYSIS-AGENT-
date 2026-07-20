"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { JsonDataTable } from "./JsonDataTable";

const INFERNO = ["#fcffa4", "#f7d13d", "#fb9b06", "#ed6925", "#cf4446", "#a52c60", "#781c6d", "#4a0c6b"];

function confColor(v: number, max: number): string {
  if (!max || max <= 0) return INFERNO[INFERNO.length - 1];
  const t = Math.min(1, Math.max(0, v / max));
  const idx = Math.min(INFERNO.length - 1, Math.floor((1 - t) * (INFERNO.length - 1)));
  return INFERNO[idx];
}

function asConfidencePct(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(2)}%`;
}

export function SuspectedCellsPanel({
  table,
  chartData,
  meta,
  minObservations,
  onMinObservationsChange,
}: {
  table: Record<string, unknown>[];
  chartData: Record<string, unknown>[];
  meta: Record<string, unknown>;
  minObservations: number;
  onMinObservationsChange: (v: number) => void;
}) {
  const failingCells = Number(
    meta.failing_scan_cells ?? meta.suspected_cells ?? table.length ?? 0,
  );
  const chains = Number(meta.chains_involved ?? 0);
  const maxConf = meta.max_confidence == null ? null : Number(meta.max_confidence);

  const bars = [...(chartData || [])]
    .map((r) => ({
      label: String(r.label ?? `${r.chain} · ${r.fail_flop_id}`),
      confidence: Number(r.confidence ?? 0),
      cell_name: String(r.cell_name ?? ""),
      observations: Number(r.observations ?? 0),
    }))
    .filter((b) => Number.isFinite(b.confidence))
    .sort((a, b) => b.confidence - a.confidence);

  const maxBar = bars.reduce((m, b) => Math.max(m, b.confidence), 0) || 1;
  const chartHeight = Math.max(420, bars.length * 26 + 48);

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-400">
        Diagnosis-tool localization (not SmarTest): failing flop → bit position (via STIL
        chain length) → exact scan cell name, with confidence from corroborating
        observations.
      </p>

      <div className="rounded-xl border border-border bg-card/60 px-4 py-3">
        <div className="mb-2 flex items-center justify-between gap-3">
          <label className="text-xs font-medium uppercase tracking-wide text-slate-400">
            Minimum corroborating observations
          </label>
          <span className="font-display text-sm font-semibold text-primary">{minObservations}</span>
        </div>
        <input
          type="range"
          min={1}
          max={20}
          step={1}
          value={minObservations}
          onChange={(e) => onMinObservationsChange(Number(e.target.value))}
          className="w-full accent-primary"
          title="Higher = only cells with repeated, corroborating failures."
        />
        <div className="mt-1 flex justify-between text-[10px] text-slate-500">
          <span>1</span>
          <span>Higher = stricter (fewer cells)</span>
          <span>20</span>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Metric
          label="Failing scan cells"
          value={Number.isFinite(failingCells) ? failingCells.toLocaleString() : "—"}
        />
        <Metric
          label="Chains involved"
          value={Number.isFinite(chains) ? chains.toLocaleString() : "—"}
        />
        <Metric
          label="Max confidence"
          value={maxConf == null || Number.isNaN(maxConf) ? "—" : `${(maxConf * 100).toFixed(2)}%`}
        />
      </div>

      <div className="glass-card p-4" style={{ height: chartHeight }}>
        <h3 className="mb-2 font-display text-sm font-semibold text-white">
          Top failing cells by confidence
        </h3>
        {bars.length ? (
          <ResponsiveContainer width="100%" height="90%">
            <BarChart data={bars} layout="vertical" margin={{ left: 8, right: 48, top: 4, bottom: 4 }}>
              <CartesianGrid stroke="#2D3748" strokeDasharray="3 3" horizontal={false} />
              <XAxis
                type="number"
                domain={[0, Math.min(1, Math.ceil(maxBar * 10) / 10)]}
                tickFormatter={(v) => `${Math.round(Number(v) * 100)}%`}
                stroke="#94a3b8"
                fontSize={11}
              />
              <YAxis
                type="category"
                dataKey="label"
                width={180}
                stroke="#94a3b8"
                fontSize={10}
                interval={0}
              />
              <Tooltip
                contentStyle={{
                  background: "#111827",
                  border: "1px solid #2D3748",
                  borderRadius: 12,
                }}
                formatter={(value) => [asConfidencePct(value), "Confidence"]}
              />
              <Bar dataKey="confidence" radius={[0, 6, 6, 0]}>
                {bars.map((b, i) => (
                  <Cell key={`${b.label}-${i}`} fill={confColor(b.confidence, maxBar)} />
                ))}
                <LabelList
                  dataKey="confidence"
                  position="right"
                  fill="#cbd5e1"
                  fontSize={10}
                  formatter={(v: unknown) => asConfidencePct(v)}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-40 items-center justify-center text-sm text-slate-500">
            No failing scan cells at this threshold. Lower the minimum observations.
          </div>
        )}
      </div>

      <div>
        <h3 className="mb-2 font-display text-sm font-semibold text-white">
          Failing scan cells table (sorted by confidence)
        </h3>
        <JsonDataTable
          rows={table || []}
          filename="failing_scan_cells.json"
          showCsvDownload
          maxHeightClass="max-h-[28rem]"
        />
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-[#0d1220] px-4 py-3">
      <div className="text-[10px] font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 font-display text-2xl font-semibold text-white">{value}</div>
      {hint ? <div className="mt-1 text-[10px] text-slate-500">{hint}</div> : null}
    </div>
  );
}
