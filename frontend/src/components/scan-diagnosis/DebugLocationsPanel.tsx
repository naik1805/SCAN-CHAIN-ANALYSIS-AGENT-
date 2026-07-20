"use client";

import { JsonDataTable } from "./JsonDataTable";

type DebugRecommendation = Record<string, unknown>;

function priorityTone(priority: unknown): string {
  const p = String(priority ?? "").toLowerCase();
  if (p === "high") return "border-rose-500/40 bg-rose-500/10 text-rose-200";
  if (p === "medium") return "border-amber-500/40 bg-amber-500/10 text-amber-200";
  return "border-slate-500/40 bg-slate-500/10 text-slate-300";
}

function confTone(pct: number): string {
  if (pct >= 70) return "text-emerald-300";
  if (pct >= 50) return "text-amber-300";
  return "text-rose-300";
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-card/60 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="font-display text-lg font-semibold text-white">{value}</div>
    </div>
  );
}

export function DebugLocationsPanel({
  topRecommendations,
  allRows,
  meta,
}: {
  topRecommendations: DebugRecommendation[];
  allRows: DebugRecommendation[];
  meta: Record<string, unknown>;
}) {
  const total = Number(meta.total_recommendations ?? allRows.length ?? 0);
  const chains = Number(meta.top_per_chain_count ?? meta.unique_chains ?? 0);
  const high = Number(meta.high_priority_count ?? 0);
  const medium = Number(meta.medium_priority_count ?? 0);
  const low = Number(meta.low_priority_count ?? 0);
  const scoringNote = String(meta.scoring_note ?? "");

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-400">
        Ranked silicon debug locations for production testers — start with the top picks per chain,
        then drill into the full recommendation table. KPI count matches the full table row count.
      </p>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Total recommendations" value={total.toLocaleString()} />
        <Metric label="Chains (top pick each)" value={chains.toLocaleString()} />
        <Metric label="High priority" value={high.toLocaleString()} />
        <Metric
          label="Medium / Low"
          value={`${medium.toLocaleString()} / ${low.toLocaleString()}`}
        />
      </div>

      {scoringNote ? (
        <div className="rounded-xl border border-primary/25 bg-primary/10 px-4 py-3 text-xs text-violet-100/90">
          {scoringNote}
        </div>
      ) : null}

      {topRecommendations.length ? (
        <section className="space-y-3">
          <h4 className="font-display text-sm font-semibold text-white">
            Top ranked locations (best per chain)
          </h4>
          <div className="grid gap-3 lg:grid-cols-2">
            {topRecommendations.map((rec, idx) => {
              const rank = Number(rec.rank ?? idx + 1);
              const confPct = Number(rec.confidence_pct ?? 0);
              const bullets = (rec.evidence_bullets as string[]) || [];
              const priority = rec.pfa_priority ?? rec.priority;
              return (
                <article
                  key={`${String(rec.chain)}-${String(rec.cell_name)}-${rank}`}
                  className="rounded-xl border border-border bg-[#0d1220] p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                        Rank #{rank} · {String(rec.chain ?? "—")}
                      </div>
                      <div className="mt-1 font-display text-sm font-semibold text-white">
                        {String(rec.cell_name ?? rec.fail_flop_id ?? "—")}
                      </div>
                      <div className="mt-1 text-[11px] text-slate-500">
                        Flop {String(rec.fail_flop_id ?? "—")} · offset{" "}
                        {String(rec.logical_offset ?? "—")}
                      </div>
                    </div>
                    <span
                      className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${priorityTone(priority)}`}
                    >
                      {String(priority ?? "—")}
                    </span>
                  </div>

                  <div className={`mt-3 font-display text-2xl font-bold tabular-nums ${confTone(confPct)}`}>
                    {Number.isFinite(confPct) ? `${confPct.toFixed(1)}%` : "—"}
                    <span className="ml-2 text-xs font-normal text-slate-500">confidence</span>
                  </div>

                  <ul className="mt-3 space-y-1 text-[11px] text-slate-400">
                    {bullets.slice(0, 5).map((bullet) => (
                      <li key={bullet} className="flex gap-2">
                        <span className="text-primary">•</span>
                        <span>{bullet}</span>
                      </li>
                    ))}
                  </ul>

                  {rec.selection_rationale ? (
                    <p className="mt-3 text-[10px] italic text-slate-500">
                      {String(rec.selection_rationale)}
                    </p>
                  ) : null}
                </article>
              );
            })}
          </div>
        </section>
      ) : null}

      <section className="space-y-3">
        <h4 className="font-display text-sm font-semibold text-white">
          Full recommendation table
        </h4>
        <JsonDataTable
          rows={allRows}
          filename="debug_locations_recommendations"
          showCsvDownload
          csvDownloadLabel="Download all recommendations (CSV)"
          jsonDownloadLabel="Download all recommendations (JSON)"
          searchPlaceholder="Search chain, cell, flop, root cause, priority…"
          defaultPageSize={50}
          maxHeightClass="max-h-[28rem]"
        />
      </section>
    </div>
  );
}
