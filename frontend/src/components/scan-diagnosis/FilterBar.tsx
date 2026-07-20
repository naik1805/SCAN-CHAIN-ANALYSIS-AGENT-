"use client";

import type { DatasetSummary, FilterOptions } from "@/lib/kpiDrillDown/diagnosisTypes";

export function FilterBar({
  filters,
  summary,
  lot,
  onLot,
}: {
  filters: FilterOptions;
  summary?: DatasetSummary | null;
  lot: string;
  onLot: (v: string) => void;
}) {
  const s = summary ?? {
    stil_file: "—",
    log_files: [],
    log_file_count: 0,
    total_failure_records: 0,
    failing_chains: 0,
    all_chains: 0,
    failing_flops: 0,
  };

  const logLabel =
    s.log_file_count <= 0
      ? "—"
      : s.log_file_count <= 3
        ? (s.log_files || []).join(", ")
        : `${s.log_file_count} files (e.g. ${(s.log_files || []).slice(0, 2).join(", ")}…)`;

  return (
    <div className="mb-6 space-y-3 rounded-glass border border-border/80 bg-card/50 p-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Lot" value={lot} onChange={onLot} options={filters.lots} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <Stat
          label="Source — STIL"
          value={s.stil_file || "—"}
          hint="Active topology / STIL file"
        />
        <Stat
          label="Source — Logs"
          value={logLabel}
          hint={`${s.log_file_count} log file(s)`}
          title={(s.log_files || []).join("\n")}
        />
        <Stat
          label="Total failure records"
          value={fmt(s.total_failure_records)}
          hint={`Parsed FAIL rows from ${s.log_file_count || 0} ATE log file(s)`}
        />
        <Stat label="Failing chains" value={fmt(s.failing_chains)} hint="Distinct chains in logs" />
        <Stat label="All chains" value={fmt(s.all_chains)} hint="Chains in topology" />
        <Stat label="Failing flops" value={fmt(s.failing_flops)} hint="Suspected cells (≥2 observations)" />
      </div>
    </div>
  );
}

function fmt(n: number | undefined | null): string {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString();
}

function Stat({
  label,
  value,
  hint,
  title,
}: {
  label: string;
  value: string;
  hint?: string;
  title?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1 rounded-xl border border-border bg-[#0d1220] px-3 py-2">
      <span className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
        {label}
      </span>
      <span
        className="truncate font-display text-sm font-semibold text-white"
        title={title || value}
      >
        {value}
      </span>
      {hint ? <span className="truncate text-[10px] text-slate-500">{hint}</span> : null}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <label className="flex min-w-[160px] max-w-xs flex-col gap-1 text-xs text-slate-400">
      <span className="font-medium uppercase tracking-wide">{label}</span>
      <select
        disabled={!options.length}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-xl border border-border bg-[#0d1220] px-3 py-2 text-sm text-slate-100 outline-none disabled:opacity-50"
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}
