"use client";

import { useEffect, useState } from "react";
import { Check, Pause, X } from "lucide-react";
import { forceModelRetrain, submitReview } from "@/lib/kpiDrillDown/diagnosisApi";

type ReviewItem = {
  id?: string;
  kind?: string;
  chain?: string;
  cell_name?: string;
  confidence_pct?: number;
  predicted_root_cause?: string;
  location_status?: string;
  observations?: number;
  lots_affected?: number | null;
  lot_id?: string;
};

export function ReviewQueuePanel({
  items,
  meta,
  onChanged,
}: {
  items: ReviewItem[];
  meta: Record<string, unknown>;
  onChanged?: (summary?: Record<string, unknown>) => void;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<string>("");
  const [retraining, setRetraining] = useState(false);
  const [localItems, setLocalItems] = useState<ReviewItem[]>(items);
  const [localMeta, setLocalMeta] = useState({
    pending: Number(meta.pending ?? items.length),
    confirmed: Number(meta.confirmed ?? 0),
    rejected: Number(meta.rejected ?? 0),
    feedback: Number(meta.feedback_records ?? 0),
  });

  useEffect(() => {
    setLocalItems(items);
    setLocalMeta({
      pending: Number(meta.pending ?? items.length),
      confirmed: Number(meta.confirmed ?? 0),
      rejected: Number(meta.rejected ?? 0),
      feedback: Number(meta.feedback_records ?? 0),
    });
  }, [items, meta]);

  const lifecycle = (meta.lifecycle as Record<string, unknown>) || {};

  async function act(id: string, decision: "confirm" | "reject" | "defer") {
    setBusyId(id);
    setMessage("");

    // Optimistic UI — remove from pending list immediately (except defer)
    const prevItems = localItems;
    const prevMeta = localMeta;
    const removed = localItems.find((it) => String(it.id) === id);
    const isCell = String(removed?.kind || "") === "cell";
    if (decision !== "defer") {
      setLocalItems((cur) => cur.filter((it) => String(it.id) !== id));
      const nextMeta = {
        pending: Math.max(0, prevMeta.pending - 1),
        confirmed: prevMeta.confirmed + (decision === "confirm" ? 1 : 0),
        rejected: prevMeta.rejected + (decision === "reject" ? 1 : 0),
        // Only cell decisions write verified feedback rows
        feedback: prevMeta.feedback + (isCell ? 1 : 0),
      };
      setLocalMeta(nextMeta);
      // Patch dashboard KPI immediately (before API returns)
      onChanged?.({
        pending: nextMeta.pending,
        confirmed: nextMeta.confirmed,
        rejected: nextMeta.rejected,
        feedback_records: nextMeta.feedback,
      });
    }

    try {
      const res = await submitReview(id, decision);
      const retrain = (res.retrain as Record<string, unknown>) || {};
      const summary =
        (res.summary as Record<string, unknown> | undefined) ||
        ({
          pending: Number(res.pending ?? Math.max(0, prevMeta.pending - (decision === "defer" ? 0 : 1))),
          confirmed: prevMeta.confirmed + (decision === "confirm" ? 1 : 0),
          rejected: prevMeta.rejected + (decision === "reject" ? 1 : 0),
          feedback_records:
            typeof res.feedback_records === "number"
              ? Number(res.feedback_records)
              : prevMeta.feedback + (isCell ? 1 : 0),
        } as Record<string, unknown>);
      if (typeof summary.pending === "number") {
        setLocalMeta({
          pending: Number(summary.pending),
          confirmed: Number(summary.confirmed ?? prevMeta.confirmed),
          rejected: Number(summary.rejected ?? prevMeta.rejected),
          feedback: Number(summary.feedback_records ?? prevMeta.feedback),
        });
      }
      setMessage(
        retrain.retrained
          ? `Saved · models retrained (${retrain.reason})`
          : `Saved · pending ${summary.pending ?? "—"} · feedback ${summary.feedback_records ?? localMeta.feedback}`,
      );
      onChanged?.(summary);
    } catch (err) {
      // Roll back optimistic update
      setLocalItems(prevItems);
      setLocalMeta(prevMeta);
      onChanged?.({
        pending: prevMeta.pending,
        confirmed: prevMeta.confirmed,
        rejected: prevMeta.rejected,
        feedback_records: prevMeta.feedback,
      });
      setMessage(err instanceof Error ? err.message : "Review failed");
    } finally {
      setBusyId(null);
    }
  }

  async function onRetrain() {
    setRetraining(true);
    setMessage("");
    try {
      const res = await forceModelRetrain();
      setMessage(
        res.retrained
          ? `Forced retrain complete`
          : `Retrain: ${String(res.reason ?? "no-op")}`,
      );
      onChanged?.();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Retrain failed");
    } finally {
      setRetraining(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-4">
        {[
          { label: "Pending", value: localMeta.pending },
          { label: "Confirmed", value: localMeta.confirmed },
          { label: "Rejected", value: localMeta.rejected },
          { label: "Verified feedback", value: localMeta.feedback },
        ].map((t) => (
          <div key={t.label} className="rounded-xl border border-border bg-[#0d1220] px-3 py-3">
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{t.label}</div>
            <div className="font-display text-2xl font-semibold tabular-nums text-white">
              {t.value}
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <span>
          Retrain threshold: {String(lifecycle.threshold ?? 25)} feedback rows · due:{" "}
          {lifecycle.retrain_due ? "yes" : "no"}
        </span>
        <button
          type="button"
          disabled={retraining}
          onClick={onRetrain}
          className="rounded-lg border border-primary/40 bg-primary/15 px-3 py-1.5 font-medium text-violet-200 hover:bg-primary/25 disabled:opacity-50"
        >
          {retraining ? "Retraining…" : "Force model retrain"}
        </button>
        {message ? <span className="text-slate-300">{message}</span> : null}
      </div>

      {!localItems.length ? (
        <div className="rounded-xl border border-border bg-card/40 p-8 text-center text-sm text-slate-500">
          No pending reviews — queue will seed from top cell/break leads on dashboard refresh.
        </div>
      ) : (
        <ul className="space-y-2">
          {localItems.map((item) => {
            const id = String(item.id ?? "");
            const busy = busyId === id;
            return (
              <li
                key={id}
                className="rounded-xl border border-border/70 bg-[#0d1220]/80 px-3 py-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded border border-violet-500/30 bg-violet-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-violet-200">
                        {item.kind || "item"}
                      </span>
                      <span className="font-medium text-slate-100">{item.chain}</span>
                      <span className="truncate text-slate-400">{item.cell_name}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-slate-500">
                      {item.confidence_pct != null ? (
                        <span>Confidence {item.confidence_pct}%</span>
                      ) : null}
                      {item.predicted_root_cause ? (
                        <span>RC {String(item.predicted_root_cause)}</span>
                      ) : null}
                      {item.location_status ? <span>{item.location_status}</span> : null}
                      {item.observations != null ? <span>{item.observations} obs</span> : null}
                      {item.lots_affected != null ? <span>{item.lots_affected} lots</span> : null}
                      {item.lot_id ? <span>Lot {item.lot_id}</span> : null}
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-1.5">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => act(id, "confirm")}
                      className="inline-flex items-center gap-1 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-2.5 py-1.5 text-xs font-medium text-emerald-200 disabled:opacity-50"
                    >
                      <Check size={12} /> Confirm
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => act(id, "reject")}
                      className="inline-flex items-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/15 px-2.5 py-1.5 text-xs font-medium text-rose-200 disabled:opacity-50"
                    >
                      <X size={12} /> Reject
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => act(id, "defer")}
                      className="inline-flex items-center gap-1 rounded-lg border border-border bg-card/60 px-2.5 py-1.5 text-xs text-slate-300 disabled:opacity-50"
                    >
                      <Pause size={12} /> Defer
                    </button>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
