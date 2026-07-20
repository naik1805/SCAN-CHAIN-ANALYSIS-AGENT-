"use client";

import { useMemo, useState, type ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Label,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  formatFeatureLabel,
  formatMetricValue,
  regionPanelTitle,
  type TopologyProfile,
} from "@/lib/kpiDrillDown/correlationUtils";

const PASTEL = ["#a5b4fc", "#fcd34d", "#6ee7b7", "#fca5a5", "#c4b5fd", "#fdba74", "#86efac", "#f9a8d4"];
const SAFE = ["#0ea5e9", "#22c55e", "#eab308", "#f97316", "#a855f7", "#ec4899", "#14b8a6"];
const VIVID = ["#ef4444", "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"];

type MetricComparison = {
  metric: string;
  label: string;
  chain_avg: number;
  overall_avg: number;
  delta: number;
  pct_diff: number | null;
  direction: string;
};

type DistinguishingFactor = {
  label: string;
  metric: string;
  pct_diff: number;
  direction: string;
  chain_avg: number;
  overall_avg: number;
};

type SignatureOverviewRow = {
  chain: string;
  failure_count: number;
  top_factor?: string;
  top_pct_diff?: number;
  summary?: string;
};

function pctToChartData(pct: Record<string, unknown> | undefined) {
  if (!pct) return [];
  return Object.entries(pct)
    .map(([name, value]) => ({ name, value: Number(value) }))
    .filter((d) => Number.isFinite(d.value) && d.value > 0)
    .sort((a, b) => b.value - a.value);
}

function PieCategoryLabel({
  cx = 0,
  cy = 0,
  midAngle = 0,
  outerRadius = 0,
  percent = 0,
  name = "",
}: {
  cx?: number;
  cy?: number;
  midAngle?: number;
  innerRadius?: number;
  outerRadius?: number;
  percent?: number;
  name?: string;
}) {
  if (!name || percent <= 0) return null;
  const RAD = Math.PI / 180;
  const small = percent < 0.04;
  const radius = outerRadius + (small ? 22 : 16);
  const x = cx + radius * Math.cos(-midAngle * RAD);
  const y = cy + radius * Math.sin(-midAngle * RAD);
  const anchor = x > cx ? "start" : "end";
  return (
    <text
      x={x}
      y={y}
      fill="#e2e8f0"
      textAnchor={anchor}
      dominantBaseline="central"
      fontSize={small ? 8 : 9}
      fontWeight={600}
    >
      {`${name} ${(percent * 100).toFixed(1)}%`}
    </text>
  );
}

function DistributionLegend({
  data,
  colors,
}: {
  data: { name: string; value: number }[];
  colors: string[];
}) {
  if (!data.length) return null;
  return (
    <ul className="mt-2 space-y-1.5">
      {data.map((entry, idx) => (
        <li key={entry.name} className="flex items-center gap-2 text-[10px] leading-tight text-slate-300">
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-sm border border-white/10"
            style={{ backgroundColor: colors[idx % colors.length] }}
          />
          <span className="min-w-0 flex-1">{entry.name}</span>
          <span className="shrink-0 tabular-nums text-slate-400">{entry.value.toFixed(1)}%</span>
        </li>
      ))}
    </ul>
  );
}

function percentTooltip(
  value: number | string,
  _name: unknown,
  item: { payload?: { name?: string } },
) {
  const v = Number(value);
  const label = item?.payload?.name ?? (typeof _name === "string" ? _name : "Category");
  return [`${v.toFixed(1)}%`, label];
}

function DistributionCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-card/50 p-3">
      <h4 className="mb-2 text-xs font-semibold text-slate-200">{title}</h4>
      {children}
    </div>
  );
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex h-52 items-center justify-center text-center text-xs text-slate-500">{label}</div>
  );
}

function deltaArrow(direction: string): string {
  if (direction === "higher") return "↑";
  if (direction === "lower") return "↓";
  return "≈";
}

function deltaClass(direction: string): string {
  if (direction === "higher") return "text-amber-300";
  if (direction === "lower") return "text-sky-300";
  return "text-slate-400";
}

export function ChainSignatureOverview({
  overview,
  selectedChain,
  onSelectChain,
}: {
  overview: SignatureOverviewRow[];
  selectedChain?: string;
  onSelectChain?: (chain: string) => void;
}) {
  if (!overview.length) return null;
  return (
    <div className="overflow-auto rounded-xl border border-border">
      <table className="w-full min-w-[640px] text-xs">
        <thead>
          <tr className="border-b border-border bg-card/60 text-left text-slate-400">
            <th className="px-3 py-2">Chain</th>
            <th className="px-3 py-2">Failures</th>
            <th className="px-3 py-2">Top distinguishing factor</th>
            <th className="px-3 py-2">Signature</th>
          </tr>
        </thead>
        <tbody>
          {overview.map((row) => {
            const chain = String(row.chain);
            const active = selectedChain === chain;
            return (
              <tr
                key={chain}
                className={`border-t border-border/60 cursor-pointer hover:bg-card/40 ${
                  active ? "bg-primary/10" : ""
                }`}
                onClick={() => onSelectChain?.(chain)}
              >
                <td className="px-3 py-2 font-medium text-slate-200">{chain}</td>
                <td className="px-3 py-2 tabular-nums text-slate-300">{row.failure_count}</td>
                <td className="px-3 py-2 text-slate-300">
                  {row.top_factor ? (
                    <>
                      {row.top_factor}
                      {row.top_pct_diff != null ? (
                        <span className={`ml-1 ${deltaClass(row.top_pct_diff > 0 ? "higher" : "lower")}`}>
                          {row.top_pct_diff > 0 ? "+" : ""}
                          {row.top_pct_diff}%
                        </span>
                      ) : null}
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-3 py-2 text-slate-400">{row.summary || "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function ChainSignaturePanel({
  correlations,
  meta,
  onChainChange,
}: {
  correlations: Record<string, unknown>[];
  meta?: Record<string, unknown>;
  onChainChange?: (chain: string) => void;
}) {
  const regionField = meta?.region_field_used as string | null | undefined;

  const chains = useMemo(
    () => correlations.map((c) => String(c.chain)).filter(Boolean),
    [correlations],
  );
  const [selected, setSelected] = useState("");

  const activeChain = selected || chains[0] || "";
  const row = correlations.find((c) => String(c.chain) === activeChain);

  const bullets = (row?.signature_bullets as string[]) || [];
  const comparisons = (row?.metric_comparisons as MetricComparison[]) || [];
  const factors = (row?.distinguishing_factors as DistinguishingFactor[]) || [];
  const topologyProfile = (row?.topology_profile || {}) as TopologyProfile;
  const failureCount = Number(row?.failure_count ?? 0);

  const physicalTimingData = pctToChartData(row?.physical_timing_percentages as Record<string, unknown>);
  const spatialData = pctToChartData(
    (row?.spatial_percentages ?? row?.failure_region_percentages) as Record<string, unknown>,
  );
  const factorChartData = factors.map((f) => ({
    name: f.label,
    value: Math.abs(f.pct_diff),
    signed: f.pct_diff,
    direction: f.direction,
  }));

  if (!correlations.length) {
    return (
      <div className="flex h-48 items-center justify-center rounded-xl border border-border bg-card/40 text-sm text-slate-500">
        No chain signature data available
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Select scan chain</label>
        <select
          value={activeChain}
          onChange={(e) => {
            setSelected(e.target.value);
            onChainChange?.(e.target.value);
          }}
          className="w-full max-w-xs rounded-lg border border-border bg-[#090B12] px-3 py-2 text-sm text-white"
        >
          {chains.map((chain) => {
            const cRow = correlations.find((c) => String(c.chain) === chain);
            const count = Number(cRow?.failure_count ?? 0);
            return (
              <option key={chain} value={chain}>
                {chain} ({count} failures)
              </option>
            );
          })}
        </select>
      </div>

      {bullets.length ? (
        <div className="rounded-xl border border-primary/30 bg-primary/10 px-4 py-3">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-violet-300">
            Chain signature — {activeChain}
          </div>
          <ul className="space-y-1 text-sm text-violet-50">
            {bullets.map((line) => (
              <li key={line} className="flex gap-2">
                <span className="text-violet-400">•</span>
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {comparisons.length ? (
        <DistributionCard title="Chain vs average — metric comparison">
          <p className="mb-2 text-[11px] leading-relaxed text-slate-500">
            <span className="font-semibold text-slate-400">Difference vs avg</span> — Is this chain higher or lower than usual?
            {" "}
            <span className="text-amber-300">↑ +90%</span> means this chain is much higher than normal.
            {" "}
            <span className="text-sky-300">↓ −5%</span> means a bit lower than normal.
            {" "}
            Bigger numbers = this chain stands out more on that metric.
          </p>
          <div className="overflow-auto">
            <table className="w-full min-w-[520px] text-xs">
              <thead>
                <tr className="border-b border-border text-left text-slate-500">
                  <th className="px-2 py-1.5">Metric</th>
                  <th className="px-2 py-1.5" title="Average for the chain you picked">
                    This chain
                  </th>
                  <th className="px-2 py-1.5" title="Typical value across all chains">
                    Average
                  </th>
                  <th className="px-2 py-1.5" title="How much higher or lower than usual">
                    Higher / lower
                  </th>
                </tr>
              </thead>
              <tbody>
                {comparisons.slice(0, 12).map((c) => (
                  <tr key={c.metric} className="border-t border-border/50">
                    <td className="px-2 py-1.5 font-medium text-slate-200">{c.label}</td>
                    <td className="px-2 py-1.5 tabular-nums text-slate-300">
                      {formatMetricValue(c.metric, c.chain_avg)}
                    </td>
                    <td className="px-2 py-1.5 tabular-nums text-slate-400">
                      {formatMetricValue(c.metric, c.overall_avg)}
                    </td>
                    <td
                      className={`px-2 py-1.5 tabular-nums ${deltaClass(c.direction)}`}
                      title={
                        c.pct_diff != null
                          ? c.pct_diff > 0
                            ? `${Math.abs(c.pct_diff)}% higher than usual`
                            : c.pct_diff < 0
                              ? `${Math.abs(c.pct_diff)}% lower than usual`
                              : "About the same as usual"
                          : undefined
                      }
                    >
                      {deltaArrow(c.direction)}{" "}
                      {c.pct_diff != null ? `${c.pct_diff > 0 ? "+" : ""}${c.pct_diff}%` : formatMetricValue(c.metric, c.delta)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DistributionCard>
      ) : null}

      {factorChartData.length ? (
        <DistributionCard title="Ranked distinguishing factors (% vs average)">
          <p className="mb-2 text-[11px] text-slate-500">
            Metrics where this chain looks most different from normal (biggest gaps first).
          </p>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={factorChartData} layout="vertical" margin={{ left: 4, right: 8, top: 4, bottom: 4 }}>
              <CartesianGrid stroke="#2D3748" strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" stroke="#94a3b8" fontSize={10} unit="%" />
              <YAxis type="category" dataKey="name" width={110} stroke="#94a3b8" fontSize={10} interval={0} />
              <Tooltip
                formatter={(value, _n, item) => {
                  const p = item?.payload as { signed?: number } | undefined;
                  const signed = p?.signed ?? Number(value);
                  return [`${signed > 0 ? "+" : ""}${signed.toFixed(1)}% vs average`, "Deviation"];
                }}
                contentStyle={{ background: "#111827", border: "1px solid #2D3748", borderRadius: 12, fontSize: 12 }}
              />
              <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                {factorChartData.map((entry) => (
                  <Cell
                    key={entry.name}
                    fill={entry.signed >= 0 ? "#f59e0b" : "#38bdf8"}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </DistributionCard>
      ) : null}

      {topologyProfile.clock_domain || topologyProfile.scan_length ? (
        <div className="rounded-xl border border-border bg-card/50 p-3">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Topology — {activeChain}
          </h4>
          <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Clock" value={topologyProfile.clock_domain} />
            <Field label="Scan length" value={topologyProfile.scan_length != null ? `${topologyProfile.scan_length} cells` : null} />
            <Field label="Instance" value={topologyProfile.instance_type} />
            <Field label="Compression" value={topologyProfile.compression_ratio != null ? String(topologyProfile.compression_ratio) : null} />
          </div>
        </div>
      ) : null}

      <div className="text-xs text-slate-500">
        {activeChain}: {failureCount.toLocaleString()} failure records
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <DistributionCard title="Physical / timing stress">
          {!physicalTimingData.length ? (
            <EmptyChart label="No setup/hold slack data" />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={260}>
                <PieChart margin={{ top: 16, right: 36, bottom: 16, left: 36 }}>
                <Pie
                  data={physicalTimingData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={40}
                  outerRadius={68}
                  paddingAngle={physicalTimingData.length > 1 ? 1 : 0}
                  labelLine={{ stroke: "#64748b", strokeWidth: 1 }}
                  label={PieCategoryLabel}
                >
                  {physicalTimingData.map((entry, idx) => (
                    <Cell key={entry.name} fill={PASTEL[idx % PASTEL.length]} stroke="#0c111c" />
                  ))}
                  {physicalTimingData.length === 1 ? (
                    <Label value={physicalTimingData[0].name} position="center" fill="#e2e8f0" style={{ fontSize: 10, fontWeight: 600 }} />
                  ) : null}
                </Pie>
                <Tooltip
                  formatter={percentTooltip}
                  contentStyle={{ background: "#111827", border: "1px solid #2D3748", borderRadius: 12, fontSize: 12 }}
                />
              </PieChart>
              </ResponsiveContainer>
              <DistributionLegend data={physicalTimingData} colors={PASTEL} />
            </>
          )}
        </DistributionCard>
        <DistributionCard title={regionPanelTitle(regionField)}>
          {!spatialData.length ? (
            <EmptyChart label="No spatial data" />
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={spatialData} layout="vertical" margin={{ left: 4, right: 8, top: 4, bottom: 4 }}>
                <CartesianGrid stroke="#2D3748" strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" stroke="#94a3b8" fontSize={10} unit="%" />
                <YAxis type="category" dataKey="name" width={88} stroke="#94a3b8" fontSize={10} interval={0} />
                <Tooltip
                  formatter={percentTooltip}
                  contentStyle={{ background: "#111827", border: "1px solid #2D3748", borderRadius: 12, fontSize: 12 }}
                />
                <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                  {spatialData.map((entry, idx) => (
                    <Cell key={entry.name} fill={SAFE[idx % SAFE.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </DistributionCard>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-0.5 font-medium text-slate-200">{value || "—"}</div>
    </div>
  );
}

/** Compact dashboard card — top chains by distinguishing factor. */
export function ChainSignatureCompact({
  overview,
}: {
  overview: SignatureOverviewRow[];
}) {
  const top = [...overview]
    .sort((a, b) => b.failure_count - a.failure_count || Math.abs(b.top_pct_diff ?? 0) - Math.abs(a.top_pct_diff ?? 0))
    .slice(0, 6);

  if (!top.length) {
    return (
      <div className="glass-card flex min-h-[320px] items-center justify-center text-sm text-slate-500">
        No chain signatures computed
      </div>
    );
  }

  const maxFails = Math.max(...top.map((r) => r.failure_count), 1);

  return (
    <div className="glass-card flex min-h-[320px] flex-col p-4">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h3 className="font-display text-sm font-semibold text-white">Top chain signatures</h3>
        <span className="text-[10px] uppercase tracking-wide text-slate-500">vs lot average</span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-border/60 text-[10px] uppercase tracking-wide text-slate-500">
              <th className="pb-2 pr-2 font-medium">Chain</th>
              <th className="pb-2 pr-2 font-medium">Fails</th>
              <th className="pb-2 pr-2 font-medium">Key factor</th>
              <th className="pb-2 font-medium text-right">vs avg</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/40">
            {top.map((row) => {
              const pp = row.top_pct_diff;
              const ppLabel =
                pp == null || !Number.isFinite(pp)
                  ? "—"
                  : `${pp >= 0 ? "+" : ""}${pp.toFixed(1)} pp`;
              const ppTone =
                pp == null || Math.abs(pp) < 0.3
                  ? "text-slate-400"
                  : pp > 0
                    ? "text-amber-300"
                    : "text-emerald-300";
              const failPct = Math.round((row.failure_count / maxFails) * 100);

              return (
                <tr key={row.chain} className="align-top">
                  <td className="py-2.5 pr-2 font-medium text-slate-200">{row.chain}</td>
                  <td className="py-2.5 pr-2">
                    <div className="font-display tabular-nums text-white">{row.failure_count}</div>
                    <div className="mt-1 h-1.5 w-16 overflow-hidden rounded-full bg-border/80">
                      <div
                        className="h-full rounded-full bg-primary/80"
                        style={{ width: `${failPct}%` }}
                      />
                    </div>
                  </td>
                  <td className="py-2.5 pr-2">
                    {row.top_factor ? (
                      <span className="inline-block max-w-[140px] truncate rounded-md border border-violet-500/30 bg-violet-500/10 px-2 py-0.5 text-[10px] font-medium text-violet-200">
                        {row.top_factor}
                      </span>
                    ) : (
                      <span className="text-slate-500">—</span>
                    )}
                    {row.summary ? (
                      <p className="mt-1 line-clamp-2 max-w-[200px] text-[10px] leading-snug text-slate-500">
                        {row.summary}
                      </p>
                    ) : null}
                  </td>
                  <td className={`py-2.5 text-right font-display tabular-nums font-semibold ${ppTone}`}>
                    {ppLabel}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
