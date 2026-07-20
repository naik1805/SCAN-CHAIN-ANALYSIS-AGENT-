"use client";

function StatTile({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-border/70 bg-[#0d1220]/80 px-3 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 font-display text-2xl font-semibold tabular-nums text-white">{value}</div>
      {sub ? <div className="mt-0.5 text-[11px] text-slate-500">{sub}</div> : null}
    </div>
  );
}

export function TopologyGraph({
  topology,
}: {
  topology: Record<string, unknown>;
}) {
  const total = Number(topology.total_scan_chains ?? 0);
  const summary = (topology.summary || {}) as Record<string, unknown>;
  const ffs = Number(summary.total_flip_flops ?? 0);
  const meanLen = Number(summary.mean_chain_length ?? 0);
  const minLen = Number(summary.min_chain_length ?? 0);
  const maxLen = Number(summary.max_chain_length ?? 0);
  const hasRange = minLen > 0 && maxLen > 0 && maxLen >= minLen;
  const meanPct = hasRange ? ((meanLen - minLen) / (maxLen - minLen)) * 100 : 50;

  return (
    <div className="glass-card p-4">
      <h3 className="mb-3 font-display text-sm font-semibold text-white">Chain Topology</h3>
      {!total ? (
        <div className="flex h-40 items-center justify-center text-sm text-slate-500">
          No topology loaded
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Scan chains" value={total.toLocaleString()} sub="FR-003 loaded" />
            <StatTile
              label="Flip-flops"
              value={ffs ? ffs.toLocaleString() : "—"}
              sub={ffs ? "total in STIL map" : undefined}
            />
            <StatTile
              label="Mean length"
              value={meanLen ? Math.round(meanLen).toLocaleString() : "—"}
              sub="cells per chain"
            />
            <StatTile
              label="Length range"
              value={hasRange ? `${minLen}–${maxLen}` : "—"}
              sub={hasRange ? "min → max cells" : undefined}
            />
          </div>

          {hasRange ? (
            <div className="rounded-xl border border-border/60 bg-card/30 px-4 py-3">
              <div className="mb-2 flex items-center justify-between text-[11px] text-slate-400">
                <span>Chain length distribution</span>
                <span className="tabular-nums text-slate-500">
                  mean {Math.round(meanLen)} · spread {maxLen - minLen} cells
                </span>
              </div>
              <div className="relative h-3 overflow-hidden rounded-full bg-border/80">
                <div className="absolute inset-y-0 left-0 w-full rounded-full bg-gradient-to-r from-primary/40 via-violet-500/50 to-primary/40" />
                <div
                  className="absolute top-1/2 h-4 w-1 -translate-y-1/2 rounded-full bg-white shadow-[0_0_8px_rgba(255,255,255,0.6)]"
                  style={{ left: `calc(${Math.min(100, Math.max(0, meanPct))}% - 2px)` }}
                  title={`Mean chain length: ${Math.round(meanLen)}`}
                />
              </div>
              <div className="mt-1.5 flex justify-between text-[10px] tabular-nums text-slate-500">
                <span>Shortest {minLen}</span>
                <span>Longest {maxLen}</span>
              </div>
            </div>
          ) : null}
        </div>
      )}
      <p className="mt-3 truncate text-xs text-slate-500" title={String(topology.source ?? "FR-003")}>
        Source: {String(topology.source ?? "FR-003")}
      </p>
    </div>
  );
}
