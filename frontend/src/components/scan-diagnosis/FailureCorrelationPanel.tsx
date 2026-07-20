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
  formatCorrelationInsight,
  formatFeatureLabel,
  formatMetricValue,
  maxAbsFromDict,
  regionPanelTitle,
  type CorrelationSummary,
  type TopologyProfile,
} from "@/lib/kpiDrillDown/correlationUtils";

const PASTEL = ["#a5b4fc", "#fcd34d", "#6ee7b7", "#fca5a5", "#c4b5fd", "#fdba74", "#86efac", "#f9a8d4"];
const SAFE = ["#0ea5e9", "#22c55e", "#eab308", "#f97316", "#a855f7", "#ec4899", "#14b8a6"];
const VIVID = ["#ef4444", "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"];

function pctToChartData(pct: Record<string, unknown> | undefined) {
  if (!pct) return [];
  return Object.entries(pct)
    .map(([name, value]) => ({ name, value: Number(value) }))
    .filter((d) => Number.isFinite(d.value) && d.value > 0)
    .sort((a, b) => b.value - a.value);
}

function PieSliceLabel({
  cx = 0,
  cy = 0,
  midAngle = 0,
  innerRadius = 0,
  outerRadius = 0,
  percent = 0,
}: {
  cx?: number;
  cy?: number;
  midAngle?: number;
  innerRadius?: number;
  outerRadius?: number;
  percent?: number;
}) {
  if (percent < 0.04) return null;
  const RAD = Math.PI / 180;
  const radius = innerRadius + (outerRadius - innerRadius) * 0.55;
  const x = cx + radius * Math.cos(-midAngle * RAD);
  const y = cy + radius * Math.sin(-midAngle * RAD);
  return (
    <text
      x={x}
      y={y}
      fill="#f8fafc"
      textAnchor="middle"
      dominantBaseline="central"
      fontSize={10}
      fontWeight={600}
    >
      {`${(percent * 100).toFixed(1)}%`}
    </text>
  );
}

function DistributionCard({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border bg-card/50 p-3">
      <h4 className="mb-2 text-xs font-semibold text-slate-200">{title}</h4>
      {children}
    </div>
  );
}

function DistributionPie({
  data,
  colors = PASTEL,
}: {
  data: { name: string; value: number }[];
  colors?: string[];
}) {
  if (!data.length) return null;
  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          innerRadius={42}
          outerRadius={72}
          paddingAngle={data.length > 1 ? 1 : 0}
          labelLine={false}
          label={PieSliceLabel}
        >
          {data.map((entry, idx) => (
            <Cell key={entry.name} fill={colors[idx % colors.length]} stroke="#0c111c" />
          ))}
          {data.length === 1 ? (
            <Label
              value={data[0].name}
              position="center"
              fill="#e2e8f0"
              style={{ fontSize: 10, fontWeight: 600 }}
            />
          ) : null}
        </Pie>
        <Tooltip
          formatter={(value, _name, item) => {
            const v = Number(value);
            const payload = item?.payload as { name?: string } | undefined;
            return [`${v.toFixed(1)}%`, payload?.name ?? ""];
          }}
          contentStyle={{
            background: "#111827",
            border: "1px solid #2D3748",
            borderRadius: 12,
            fontSize: 12,
          }}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

function DistributionBar({
  data,
  colors = SAFE,
  layout = "vertical",
}: {
  data: { name: string; value: number }[];
  colors?: string[];
  layout?: "vertical" | "horizontal";
}) {
  if (!data.length) return null;
  if (layout === "vertical") {
    return (
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} layout="vertical" margin={{ left: 4, right: 8, top: 4, bottom: 4 }}>
          <CartesianGrid stroke="#2D3748" strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" stroke="#94a3b8" fontSize={10} unit="%" />
          <YAxis
            type="category"
            dataKey="name"
            width={100}
            stroke="#94a3b8"
            fontSize={10}
            interval={0}
          />
          <Tooltip
            formatter={(value) => [`${Number(value).toFixed(1)}%`, "Share"]}
            contentStyle={{
              background: "#111827",
              border: "1px solid #2D3748",
              borderRadius: 12,
              fontSize: 12,
            }}
          />
          <Bar dataKey="value" radius={[0, 6, 6, 0]}>
            {data.map((entry, idx) => (
              <Cell key={entry.name} fill={colors[idx % colors.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ left: 4, right: 8, top: 4, bottom: 28 }}>
        <CartesianGrid stroke="#2D3748" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="name"
          stroke="#94a3b8"
          fontSize={9}
          angle={-35}
          textAnchor="end"
          height={48}
          interval={0}
        />
        <YAxis stroke="#94a3b8" fontSize={10} unit="%" />
        <Tooltip
          formatter={(value) => [`${Number(value).toFixed(1)}%`, "Share"]}
          contentStyle={{
            background: "#111827",
            border: "1px solid #2D3748",
            borderRadius: 12,
            fontSize: 12,
          }}
        />
        <Bar dataKey="value" radius={[6, 6, 0, 0]}>
          {data.map((entry, idx) => (
            <Cell key={entry.name} fill={colors[idx % colors.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex h-52 items-center justify-center text-center text-xs text-slate-500">
      {label}
    </div>
  );
}

function deltaToneForComparison(
  metric: string,
  chainVal: number | null | undefined,
  overallVal: number | null | undefined,
): "higher" | "lower" | "neutral" {
  if (
    chainVal == null ||
    overallVal == null ||
    !Number.isFinite(chainVal) ||
    !Number.isFinite(overallVal)
  ) {
    return "neutral";
  }
  const diff = chainVal - overallVal;
  if (Math.abs(diff) < 0.05 * Math.abs(overallVal || 1)) return "neutral";
  if (metric === "setup_slack_ps" || metric === "hold_slack_ps") {
    return diff > 0 ? "higher" : "lower";
  }
  return diff > 0 ? "higher" : "lower";
}

export function FailureCorrelationPanel({
  correlations,
  overallAverages,
  meta,
  onChainChange,
}: {
  correlations: Record<string, unknown>[];
  overallAverages: Record<string, unknown>;
  meta?: Record<string, unknown>;
  onChainChange?: (chain: string) => void;
}) {
  const summary = meta?.summary as CorrelationSummary | undefined;
  const regionField = meta?.region_field_used as string | null | undefined;
  const distributionMethod = meta?.distribution_method as string | undefined;

  const chains = useMemo(
    () => correlations.map((c) => String(c.chain)).filter(Boolean),
    [correlations],
  );
  const [selected, setSelected] = useState("");

  const activeChain = selected || chains[0] || "";
  const row = correlations.find((c) => String(c.chain) === activeChain);

  const pearson = (row?.pearson_correlations || {}) as Record<string, number>;
  const spatialCorrs = (row?.spatial_correlations || pearson) as Record<string, number>;
  const primaryDriver = String(row?.primary_driver ?? row?.primary_physical_driver ?? "");
  const primaryR = Number(pearson[primaryDriver] ?? 0);
  const spatialDriver = String(row?.primary_spatial_driver ?? "");
  const spatialR = Number(spatialCorrs[spatialDriver] ?? 0);
  const scanLoadDriver = String(row?.primary_scan_load_driver ?? "");
  const scanLoadR = Number(pearson[scanLoadDriver] ?? 0);
  const topologyProfile = (row?.topology_profile || {}) as TopologyProfile;
  const chainAvgs = (row?.chain_averages || {}) as Record<string, number | null>;
  const overall = overallAverages as Record<string, number | null>;
  const failureCount = Number(row?.failure_count ?? 0);

  const physicalTimingData = pctToChartData(
    (row?.physical_timing_percentages ?? row?.fail_type_percentages) as Record<string, unknown>,
  );
  const spatialData = pctToChartData(
    (row?.spatial_percentages ?? row?.failure_region_percentages) as Record<string, unknown>,
  );
  const driverData = pctToChartData(row?.correlation_driver_percentages as Record<string, unknown>);
  const groupData = pctToChartData(row?.correlation_group_percentages as Record<string, unknown>);
  const insight = formatCorrelationInsight(summary);

  if (!correlations.length) {
    return (
      <div className="flex h-48 items-center justify-center rounded-xl border border-border bg-card/40 text-sm text-slate-500">
        No correlation data available
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {insight ? (
        <div className="rounded-xl border border-primary/30 bg-primary/10 px-3 py-2 text-sm text-violet-100">
          {insight}
          {summary?.correlation_strength === "weak" ? (
            <span className="mt-1 block text-xs text-slate-400">
              Correlations are weak across this population — chain membership alone does not strongly
              separate physical features. Use categorical signatures below for chain-specific patterns.
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <label className="text-xs font-medium uppercase tracking-wide text-slate-400">
          Select scan chain
        </label>
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

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          label="Primary Driver"
          value={primaryDriver ? formatFeatureLabel(primaryDriver) : "—"}
          delta={primaryDriver ? `r = ${primaryR.toFixed(3)}` : undefined}
          deltaTone={Math.abs(primaryR) > 0.05 ? "accent" : "muted"}
        />
        <MetricCard
          label="Spatial Driver"
          value={spatialDriver ? formatFeatureLabel(spatialDriver) : "—"}
          delta={
            spatialDriver && Math.abs(spatialR) > 0
              ? `r = ${spatialR.toFixed(3)}`
              : maxAbsFromDict(spatialCorrs) > 0
                ? `max |r| = ${maxAbsFromDict(spatialCorrs).toFixed(3)}`
                : undefined
          }
          deltaTone={Math.abs(spatialR) > 0.05 ? "accent" : "muted"}
        />
        <MetricCard
          label="Scan Load Driver"
          value={scanLoadDriver ? formatFeatureLabel(scanLoadDriver) : "—"}
          delta={scanLoadDriver ? `r = ${scanLoadR.toFixed(3)}` : undefined}
          deltaTone={Math.abs(scanLoadR) > 0.05 ? "accent" : "muted"}
        />
        <MetricCard
          label="Avg Shift Cycles"
          value={formatMetricValue("shift_cycles", chainAvgs.shift_cycles)}
          delta={
            chainAvgs.scan_fail_count != null
              ? `Fails: ${formatMetricValue("scan_fail_count", chainAvgs.scan_fail_count)}`
              : undefined
          }
        />
      </div>

      {topologyProfile.clock_domain || topologyProfile.scan_length ? (
        <div className="rounded-xl border border-border bg-card/50 p-3">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            Topology profile — {activeChain}
          </h4>
          <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
            <TopologyField label="Clock domain" value={topologyProfile.clock_domain} />
            <TopologyField label="Scan master clock" value={topologyProfile.scan_master_clock} />
            <TopologyField
              label="Scan length"
              value={
                topologyProfile.scan_length != null
                  ? `${topologyProfile.scan_length} cells`
                  : null
              }
            />
            <TopologyField label="Instance type" value={topologyProfile.instance_type} />
            <TopologyField label="Decompressor" value={topologyProfile.decompressor_pin} />
            <TopologyField label="Compactor" value={topologyProfile.compactor_pin} />
            <TopologyField
              label="Compression ratio"
              value={
                topologyProfile.compression_ratio != null
                  ? String(topologyProfile.compression_ratio)
                  : null
              }
            />
            <TopologyField label="Scan in → out" value={
              topologyProfile.scan_in && topologyProfile.scan_out
                ? `${topologyProfile.scan_in} → ${topologyProfile.scan_out}`
                : null
            } />
          </div>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <MetricCard
          label="Avg IR Drop on Chain"
          value={formatMetricValue("ir_drop_mv", chainAvgs.ir_drop_mv)}
          delta={
            overall.ir_drop_mv != null
              ? `Overall: ${formatMetricValue("ir_drop_mv", overall.ir_drop_mv)}`
              : undefined
          }
          comparisonTone={deltaToneForComparison(
            "ir_drop_mv",
            chainAvgs.ir_drop_mv,
            overall.ir_drop_mv,
          )}
        />
        <MetricCard
          label="Avg Junction Temp"
          value={formatMetricValue("thermal_c", chainAvgs.thermal_c)}
          delta={
            overall.thermal_c != null
              ? `Overall: ${formatMetricValue("thermal_c", overall.thermal_c)}`
              : undefined
          }
          comparisonTone={deltaToneForComparison(
            "thermal_c",
            chainAvgs.thermal_c,
            overall.thermal_c,
          )}
        />
      </div>

      <div className="text-xs text-slate-500">
        {activeChain}: {failureCount.toLocaleString()} failure records in selected population
      </div>

      <div>
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Failure distribution by correlated features — {activeChain}
        </h4>
        {distributionMethod ? (
          <p className="mb-2 text-[11px] leading-relaxed text-slate-500">{distributionMethod}</p>
        ) : null}
        <div className="grid gap-3 lg:grid-cols-3">
          <DistributionCard title="Physical / Timing Stress">
            {!physicalTimingData.length ? (
              <EmptyChart label="No setup/hold slack data" />
            ) : (
              <DistributionPie data={physicalTimingData} colors={PASTEL} />
            )}
          </DistributionCard>

          <DistributionCard title={regionPanelTitle(regionField)}>
            {!spatialData.length ? (
              <EmptyChart
                label={
                  regionField
                    ? "No spatial data for this chain"
                    : "No spatial field in correlation set"
                }
              />
            ) : (
              <DistributionBar data={spatialData} colors={SAFE} layout="vertical" />
            )}
          </DistributionCard>

          <DistributionCard title="Correlated Feature Driver">
            {!driverData.length ? (
              <EmptyChart label="No correlated feature data" />
            ) : (
              <DistributionBar data={driverData} colors={VIVID} layout="horizontal" />
            )}
          </DistributionCard>
        </div>
        {groupData.length > 1 ? (
          <div className="mt-3">
            <DistributionCard title="Correlation Feature Group Mix">
              <DistributionPie data={groupData} colors={PASTEL} />
            </DistributionCard>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function TopologyField({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-0.5 font-medium text-slate-200">{value || "—"}</div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  delta,
  deltaTone = "accent",
  comparisonTone = "neutral",
}: {
  label: string;
  value: string;
  delta?: string;
  deltaTone?: "accent" | "muted";
  comparisonTone?: "higher" | "lower" | "neutral";
}) {
  const comparisonClass =
    comparisonTone === "higher"
      ? "text-amber-300"
      : comparisonTone === "lower"
        ? "text-sky-300"
        : "text-slate-400";

  return (
    <div className="rounded-xl border border-border bg-card/60 px-3 py-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 font-display text-lg font-semibold text-white">{value}</div>
      {delta ? (
        <div
          className={`mt-1 text-xs ${
            deltaTone === "muted" ? "text-slate-500" : comparisonClass || "text-primary"
          }`}
        >
          {delta}
        </div>
      ) : null}
    </div>
  );
}
