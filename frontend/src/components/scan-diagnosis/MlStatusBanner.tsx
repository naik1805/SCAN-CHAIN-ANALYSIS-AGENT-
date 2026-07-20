"use client";

import { Brain, Gauge, ShieldAlert, Sparkles } from "lucide-react";
import type { MlStatusSummary } from "@/lib/kpiDrillDown/diagnosisTypes";

export function MlStatusBanner({
  status,
  production,
}: {
  status?: MlStatusSummary | null;
  production?: Record<string, unknown> | null;
}) {
  if (!status && !production) return null;

  const analyzed = status?.failure_records_analyzed ?? 0;
  const estimated = status?.root_causes_estimated ?? 0;
  const anomalyPct = status?.anomaly_flagged_pct ?? 0;
  const active = status?.active;

  const readiness = production?.readiness_score_pct as number | undefined;
  const grade = String(production?.readiness_grade ?? "unknown").replace(/_/g, " ");
  const holdout = (production?.lot_holdout as Record<string, unknown>) || {};
  const breaks = (production?.break_localization as Record<string, unknown>) || {};
  const reviews = (production?.review_queue as Record<string, unknown>) || {};
  const summary = String(
    production?.client_summary || status?.client_summary || "Production metrics loading…",
  );

  const gradeTone =
    grade.includes("production")
      ? "bg-emerald-500/15 text-emerald-300"
      : grade.includes("pilot")
        ? "bg-amber-500/15 text-amber-300"
        : "bg-slate-700/50 text-slate-400";

  return (
    <section
      className="mb-6 rounded-2xl border border-border bg-card/50 px-4 py-4 md:px-5"
      aria-label="AI analysis status"
    >
      <div className="flex flex-wrap items-start gap-3">
        <div
          className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${
            active ? "bg-emerald-500/15 text-emerald-400" : "bg-slate-700/40 text-slate-400"
          }`}
        >
          <Brain size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-display text-sm font-semibold text-white">
              Production AI status
            </h2>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                active
                  ? "bg-emerald-500/15 text-emerald-300"
                  : "bg-slate-700/50 text-slate-400"
              }`}
            >
              {active ? "Active" : "Waiting for data"}
            </span>
            {readiness != null ? (
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${gradeTone}`}>
                {readiness.toFixed(0)}% · {grade}
              </span>
            ) : null}
          </div>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-300">{summary}</p>
          <ul className="mt-3 grid gap-2 text-xs text-slate-400 sm:grid-cols-2 lg:grid-cols-4">
              <li className="flex items-center gap-2 rounded-lg border border-border/60 bg-[#0d1220]/80 px-3 py-2">
              <Gauge size={14} className="shrink-0 text-emerald-400" />
              <span>
                <span className="block text-slate-500">Holdout accuracy</span>
                <span className="font-medium text-slate-200">
                  {((production?.stratified_holdout as Record<string, unknown>)?.holdout_accuracy_pct as number | undefined) !=
                  null
                    ? `${(production?.stratified_holdout as Record<string, unknown>).holdout_accuracy_pct}% stratified`
                    : holdout.holdout_accuracy_pct != null
                      ? `${holdout.holdout_accuracy_pct}% lot`
                      : "—"}
                </span>
              </span>
            </li>
            <li className="flex items-center gap-2 rounded-lg border border-border/60 bg-[#0d1220]/80 px-3 py-2">
              <ShieldAlert size={14} className="shrink-0 text-amber-400" />
              <span>
                <span className="block text-slate-500">Break CERTAIN</span>
                <span className="font-medium text-slate-200">
                  {breaks.certain != null
                    ? `${breaks.certain}/${breaks.total} (${breaks.certain_pct ?? 0}%)`
                    : "—"}
                </span>
              </span>
            </li>
            <li className="flex items-center gap-2 rounded-lg border border-border/60 bg-[#0d1220]/80 px-3 py-2">
              <Sparkles size={14} className="shrink-0 text-violet-400" />
              <span>
                <span className="block text-slate-500">Pending reviews</span>
                <span className="font-medium text-slate-200">
                  {reviews.pending != null ? String(reviews.pending) : "—"}
                </span>
              </span>
            </li>
            <li className="flex items-center gap-2 rounded-lg border border-border/60 bg-[#0d1220]/80 px-3 py-2">
              <Brain size={14} className="shrink-0 text-sky-400" />
              <span>
                <span className="block text-slate-500">Root cause / anomalies</span>
                <span className="font-medium text-slate-200">
                  {estimated.toLocaleString()} est · {anomalyPct.toFixed(1)}% flagged
                </span>
              </span>
            </li>
          </ul>
          {active && analyzed > 0 ? (
            <p className="mt-2 text-[11px] text-slate-500">
              Analyzed {analyzed.toLocaleString()} failures · {status?.root_cause_model} ·{" "}
              {status?.confidence_model}
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}
