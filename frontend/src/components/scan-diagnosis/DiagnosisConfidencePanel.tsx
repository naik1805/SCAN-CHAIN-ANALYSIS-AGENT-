"use client";

type Category = {
  id?: string;
  label?: string;
  requirement?: string;
  pillar?: string;
  count?: number;
  confidence_pct?: number;
  hint?: string;
};

function confTone(pct: number): string {
  if (pct >= 75) return "text-emerald-300";
  if (pct >= 50) return "text-amber-300";
  return "text-rose-300";
}

function confBarClass(pct: number): string {
  if (pct >= 75) return "bg-emerald-500";
  if (pct >= 50) return "bg-amber-400";
  return "bg-rose-400";
}

function CategoryGrid({ title, items }: { title: string; items: Category[] }) {
  if (!items.length) return null;
  return (
    <section className="space-y-3">
      <h3 className="font-display text-sm font-semibold text-white">{title}</h3>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((cat) => {
          const pct = Number(cat.confidence_pct ?? 0);
          return (
            <div
              key={String(cat.id ?? cat.label)}
              className="rounded-xl border border-border bg-[#0d1220] p-4"
            >
              <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                {cat.requirement}
              </div>
              <div className="mt-1 font-display text-sm font-semibold text-white">{cat.label}</div>
              <div className={`mt-3 font-display text-3xl font-bold tabular-nums ${confTone(pct)}`}>
                {pct.toFixed(1)}%
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-border">
                <div
                  className={`h-full rounded-full ${confBarClass(pct)}`}
                  style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
                />
              </div>
              <div className="mt-2 text-[11px] text-slate-500">
                {cat.count?.toLocaleString() ?? 0} results · {cat.hint}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export function DiagnosisConfidencePanel({
  categories,
  meta,
  minObservations,
  onMinObservationsChange,
}: {
  categories: Category[];
  meta: Record<string, unknown>;
  minObservations: number;
  onMinObservationsChange: (v: number) => void;
}) {
  const overallPct = meta.overall_confidence_pct as number | undefined;
  const trustLabel = String(meta.trust_label ?? "—");
  const mlSummary = meta.ml_summary as string | undefined;
  const scoringNote = meta.scoring_note as string | undefined;
  const validation = (meta.model_validation as Record<string, unknown>) || {};
  const rcCv = validation.root_cause_cv_accuracy_pct as number | undefined;
  const rcTrain = validation.root_cause_n_train as number | undefined;
  const cellTrain = validation.cell_gbm_n_train as number | undefined;
  const cellPos = validation.cell_gbm_positive_rate_pct as number | undefined;
  const mlCategories = (meta.ml_categories as Category[]) || categories.filter((c) => c.pillar === "ml");
  const logicCategories =
    (meta.logic_categories as Category[]) || categories.filter((c) => c.pillar === "logic");

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-400">
        Production trust scores for the leads you would actually act on —{" "}
        <span className="text-slate-300">top suspect per chain</span> and{" "}
        <span className="text-slate-300">model-reported probabilities</span>, not diluted
        averages over every alternate cell.
      </p>

      {rcCv != null || cellTrain != null ? (
        <div className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100/90">
          <div className="font-medium text-emerald-200">Model validation (offline holdout)</div>
          <ul className="mt-2 space-y-1 text-xs text-emerald-100/80">
            {rcCv != null ? (
              <li>
                Root cause Random Forest: <span className="font-semibold text-emerald-200">{rcCv}%</span>
                {rcTrain != null ? ` CV accuracy · trained on ${rcTrain.toLocaleString()} records` : ""}
              </li>
            ) : null}
            {cellTrain != null ? (
              <li>
                Cell confidence GBM: trained on {cellTrain.toLocaleString()} historical verified records
                {cellPos != null ? ` · ${cellPos}% confirmed in training` : ""}
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}

      <div className="rounded-xl border border-primary/30 bg-primary/10 px-6 py-5 text-center">
        <div className="text-xs font-semibold uppercase tracking-wide text-violet-300">
          Overall diagnosis confidence
        </div>
        <div
          className={`mt-2 font-display text-5xl font-bold tabular-nums ${
            overallPct == null ? "text-slate-500" : confTone(overallPct)
          }`}
        >
          {overallPct == null ? "N/A" : `${overallPct.toFixed(1)}%`}
        </div>
        <div className="mt-1 text-sm text-violet-100/80">{trustLabel}</div>
        {typeof meta.full_pipeline_confidence_pct === "number" ? (
          <div className="mt-1 text-[11px] text-slate-500">
            Full pipeline health (incl. breaks & debug rules):{" "}
            {Number(meta.full_pipeline_confidence_pct).toFixed(1)}%
          </div>
        ) : null}
        {mlSummary ? <div className="mt-2 text-xs text-slate-400">{mlSummary}</div> : null}
        {scoringNote ? <div className="mt-2 text-[11px] text-slate-500">{scoringNote}</div> : null}
      </div>

      <div className="rounded-xl border border-border bg-card/60 px-4 py-3">
        <div className="mb-2 flex items-center justify-between gap-3">
          <label className="text-xs font-medium uppercase tracking-wide text-slate-400">
            Minimum corroborating observations (cell logic only)
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
        />
      </div>

      <CategoryGrid title="AI / ML models" items={mlCategories} />
      <CategoryGrid title="Rule-based diagnosis logic" items={logicCategories} />

      {!mlCategories.length && !logicCategories.length ? (
        <div className="rounded-xl border border-border bg-card/40 p-6 text-center text-sm text-slate-500">
          No diagnosis confidence data at this threshold.
        </div>
      ) : null}
    </div>
  );
}
