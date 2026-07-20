"use client";

export function ConfidenceGauge({
  confidence,
}: {
  confidence: Record<string, unknown>;
}) {
  const raw =
    confidence.mean_suspect_confidence ??
    confidence.analysis_quality_score ??
    null;
  const value = raw == null ? null : Number(raw);
  const pct = value == null || Number.isNaN(value) ? null : Math.round(value * 100);
  const angle = pct == null ? 0 : (pct / 100) * 180;

  return (
    <div className="glass-card flex h-80 flex-col items-center justify-center p-4">
      <h3 className="mb-4 self-start font-display text-sm font-semibold text-white">
        Diagnosis Confidence
      </h3>
      <div className="relative h-28 w-56 overflow-hidden">
        <div className="absolute inset-0 rounded-t-full border-[12px] border-border border-b-0" />
        <div
          className="absolute bottom-0 left-1/2 h-24 w-1 origin-bottom bg-primary"
          style={{ transform: `translateX(-50%) rotate(${angle - 90}deg)` }}
        />
      </div>
      <div className="mt-2 font-display text-3xl font-semibold text-white">
        {pct == null ? "N/A" : `${pct}%`}
      </div>
      <p className="mt-1 text-center text-xs text-slate-500">
        Best per-chain localization confidence (fail-weighted)
      </p>
    </div>
  );
}
