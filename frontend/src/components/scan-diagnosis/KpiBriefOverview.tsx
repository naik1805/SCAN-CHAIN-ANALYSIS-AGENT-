"use client";

import {
  Activity,
  AlertTriangle,
  Brain,
  GitBranch,
  Link2,
  MapPin,
  Shield,
} from "lucide-react";
import type { KpiCard } from "@/lib/kpiDrillDown/diagnosisTypes";
import { KPI_ORDER, SECTION_PROFILES } from "@/lib/kpiDrillDown/kpiProfiles";

const ICONS: Record<string, React.ReactNode> = {
  failing_chains: <Link2 size={14} />,
  failing_cells: <Activity size={14} />,
  chain_breaks: <AlertTriangle size={14} />,
  shift_capture: <GitBranch size={14} />,
  topology_chains: <MapPin size={14} />,
  ranked_chains: <Activity size={14} />,
  failure_correlations: <Activity size={14} />,
  top_failing_chain: <AlertTriangle size={14} />,
  diagnosis_reports: <Shield size={14} />,
  debug_locations: <MapPin size={14} />,
  avg_confidence: <Brain size={14} />,
  pending_reviews: <Shield size={14} />,
};

const BRIEF: Record<string, string> = {
  failing_chains: "Distinct chains with parsed FAIL records (FR-001).",
  failing_cells: "Suspected cells ranked by evidence + ML (FR-002).",
  chain_breaks: "Exact shift-path break bit per chain (FR-006).",
  shift_capture: "Shift vs capture timing mix (FR-007).",
  topology_chains: "STIL scan map — chains, lengths, flip-flops (FR-003).",
  ranked_chains: "Dense Pareto rank by failure count (FR-004).",
  failure_correlations: "How each chain differs from lot average (FR-005).",
  top_failing_chain: "Worst chain by fail frequency across lots.",
  diagnosis_reports: "Engineering HTML report artifact (FR-008).",
  debug_locations: "Ranked debug coordinates with evidence (FR-009).",
  avg_confidence: "Actionable ML + logic trust score (FR-010).",
  pending_reviews: "Engineer confirm/reject queue — feeds model retrain.",
};

function briefFor(kpi: KpiCard): string {
  return kpi.caption || BRIEF[kpi.id] || kpi.help || "Click for drill-down workspace.";
}

export function KpiBriefOverview({
  kpis,
  onSelect,
}: {
  kpis: KpiCard[];
  onSelect: (id: string) => void;
}) {
  const byId = new Map(kpis.map((k) => [k.id, k]));

  return (
    <div className="glass-card flex min-h-[320px] flex-col p-4">
      <div className="mb-3">
        <h3 className="font-display text-sm font-semibold text-white">KPI overview</h3>
        <p className="mt-0.5 text-[11px] text-slate-500">
          All dashboard metrics — click any row to open drill-down.
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
        {SECTION_PROFILES.map((section) => {
          const order = KPI_ORDER[section.id];
          const cards = order
            .map((id) => byId.get(id))
            .filter(Boolean) as KpiCard[];

          if (!cards.length) return null;

          return (
            <div key={section.id}>
              <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-primary">
                {section.eyebrow}
              </div>
              <ul className="space-y-1.5">
                {cards.map((kpi) => (
                  <li key={kpi.id}>
                    <button
                      type="button"
                      onClick={() => onSelect(kpi.id)}
                      title={kpi.help || kpi.label}
                      className="flex w-full items-start gap-2.5 rounded-lg border border-border/60 bg-[#0d1220]/60 px-2.5 py-2 text-left transition hover:border-primary/40 hover:bg-primary/5"
                    >
                      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
                        {ICONS[kpi.id] ?? <Activity size={14} />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-baseline justify-between gap-2">
                          <span className="truncate text-xs font-medium text-slate-200">
                            {kpi.label}
                          </span>
                          <span className="shrink-0 font-display text-sm font-semibold tabular-nums text-white">
                            {kpi.value}
                          </span>
                        </span>
                        <span className="mt-0.5 line-clamp-2 text-[10px] leading-snug text-slate-500">
                          {briefFor(kpi)}
                        </span>
                        {kpi.badge ? (
                          <span className="mt-1 inline-block max-w-full truncate rounded border border-border/80 bg-card/80 px-1.5 py-0.5 text-[9px] text-slate-400">
                            {kpi.badge}
                          </span>
                        ) : null}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function DatasetSnapshot({
  summary,
}: {
  summary?: Record<string, unknown>;
}) {
  if (!summary) return null;

  const tiles = [
    { label: "Failure records", value: Number(summary.total_failure_records ?? 0) },
    { label: "Log files", value: Number(summary.log_file_count ?? 0) },
    { label: "Failing chains", value: Number(summary.failing_chains ?? 0) },
    { label: "Failing flops", value: Number(summary.failing_flops ?? 0) },
  ];

  return (
    <div className="glass-card p-4">
      <h3 className="mb-3 font-display text-sm font-semibold text-white">Dataset snapshot</h3>
      <div className="grid grid-cols-2 gap-2">
        {tiles.map((t) => (
          <div
            key={t.label}
            className="rounded-lg border border-border/60 bg-[#0d1220]/60 px-3 py-2"
          >
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{t.label}</div>
            <div className="font-display text-lg font-semibold tabular-nums text-white">
              {t.value.toLocaleString()}
            </div>
          </div>
        ))}
      </div>
      {summary.stil_file ? (
        <p className="mt-3 truncate text-[10px] text-slate-500" title={String(summary.stil_file)}>
          STIL: {String(summary.stil_file)}
        </p>
      ) : null}
    </div>
  );
}
