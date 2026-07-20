"use client";

import { useMemo, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

const CLASSIFICATIONS = [
  { key: "shift_issues", label: "SHIFT_ISSUE", color: "#ef4444" },
  { key: "capture_timing_setup", label: "CAPTURE_TIMING_SETUP", color: "#3b82f6" },
  {
    key: "capture_timing_setup_anomaly",
    label: "CAPTURE_TIMING_SETUP_ANOMALY",
    color: "#1d4ed8",
  },
  { key: "capture_timing_hold", label: "CAPTURE_TIMING_HOLD", color: "#10b981" },
  {
    key: "capture_timing_hold_anomaly",
    label: "CAPTURE_TIMING_HOLD_ANOMALY",
    color: "#047857",
  },
  { key: "capture_cell_defect", label: "CAPTURE_CELL_DEFECT", color: "#8b5cf6" },
] as const;

type ClassificationKey = (typeof CLASSIFICATIONS)[number]["key"];

type SliceDatum = {
  key: ClassificationKey;
  label: string;
  color: string;
  value: number;
  name: string;
};

function buildSegments(shiftCapture: Record<string, unknown>) {
  return CLASSIFICATIONS.map((c) => ({
    ...c,
    value: Number(shiftCapture[c.key] ?? 0),
  })).filter((s) => s.value > 0);
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
  if (percent < 0.035) return null;
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
      fontSize={11}
      fontWeight={600}
    >
      {`${(percent * 100).toFixed(1)}%`}
    </text>
  );
}

function LegendToggle({
  seg,
  isHidden,
  grandTotal,
  onToggle,
}: {
  seg: { key: ClassificationKey; label: string; color: string; value: number };
  isHidden: boolean;
  grandTotal: number;
  onToggle: (key: ClassificationKey) => void;
}) {
  const share = grandTotal > 0 ? ((seg.value / grandTotal) * 100).toFixed(1) : "0.0";
  return (
    <button
      type="button"
      onClick={() => onToggle(seg.key)}
      className={`flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-[10px] transition ${
        isHidden
          ? "border-border/40 bg-transparent opacity-40 line-through"
          : "border-border bg-card/70 hover:border-primary/50 hover:bg-primary/10"
      }`}
      aria-pressed={!isHidden}
      title={isHidden ? "Click to show" : "Click to hide"}
    >
      <span
        className="h-3.5 w-3.5 shrink-0 rounded-sm border border-white/10"
        style={{ backgroundColor: isHidden ? "#475569" : seg.color }}
      />
      <span className="min-w-0 flex-1 leading-tight font-medium text-slate-100">
        {seg.label}
      </span>
      <span className="shrink-0 tabular-nums text-slate-400">
        {share}%
      </span>
    </button>
  );
}

export function ShiftCaptureChart({
  shiftCapture,
  title = "Failure Diagnostics Classification Breakdown",
  compact = false,
}: {
  shiftCapture: Record<string, unknown>;
  title?: string;
  compact?: boolean;
}) {
  const segments = useMemo(() => buildSegments(shiftCapture), [shiftCapture]);
  const [hidden, setHidden] = useState<Set<ClassificationKey>>(new Set());

  const visible = useMemo(
    () => segments.filter((s) => !hidden.has(s.key)),
    [segments, hidden],
  );

  const visibleTotal = visible.reduce((sum, s) => sum + s.value, 0);
  const grandTotal = segments.reduce((sum, s) => sum + s.value, 0);

  const chartData: SliceDatum[] = visible.map((s) => ({
    ...s,
    name: s.label,
  }));

  const toggle = (key: ClassificationKey) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <div className="rounded-xl border border-border bg-card/40 p-4">
      <h3 className="font-display text-sm font-semibold text-white">{title}</h3>
      <p className="mt-1 text-[11px] text-slate-500">
        Toggle classifications in the legend — slice percentages update for visible items only.
      </p>

      {!segments.length ? (
        <div className="flex h-48 items-center justify-center text-sm text-slate-500">
          No shift/capture breakdown
        </div>
      ) : (
        <div className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-start">
          <div
            className={`min-w-0 flex-1 ${compact ? "h-56 sm:h-64" : "h-64 sm:h-72"}`}
          >
            {!visible.length || visibleTotal === 0 ? (
              <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-border text-sm text-slate-500">
                All hidden — click a legend item to restore
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    key={chartData.map((d) => d.key).join("-")}
                    data={chartData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={compact ? 44 : 52}
                    outerRadius={compact ? 78 : 92}
                    paddingAngle={1}
                    labelLine={false}
                    label={PieSliceLabel}
                    isAnimationActive
                  >
                    {chartData.map((entry) => (
                      <Cell
                        key={entry.key}
                        fill={entry.color}
                        stroke="#0c111c"
                        strokeWidth={1}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value, _name, item) => {
                      const v = Number(value);
                      const pct =
                        visibleTotal > 0 ? ((v / visibleTotal) * 100).toFixed(1) : "0.0";
                      const payload = item?.payload as SliceDatum | undefined;
                      return [`${v.toLocaleString()} (${pct}%)`, payload?.label ?? ""];
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
            )}
          </div>

          <div className="w-full shrink-0 sm:w-56 lg:w-64">
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
              Classification legend
            </div>
            <div className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
              {segments.map((seg) => (
                <LegendToggle
                  key={seg.key}
                  seg={seg}
                  isHidden={hidden.has(seg.key)}
                  grandTotal={grandTotal}
                  onToggle={toggle}
                />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
