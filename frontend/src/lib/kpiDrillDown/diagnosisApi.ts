import type { CopilotResponse, DiagnosisDashboard, KpiWorkspace } from "./diagnosisTypes";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8000";

export function getApiMode(): "live" {
  return "live";
}

async function fetchJson<T>(path: string, timeoutMs = 120_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: controller.signal,
    });
    if (!res.ok) {
      throw new Error(`API ${res.status}: ${path}`);
    }
    return res.json() as Promise<T>;
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error(
        `API timeout (${Math.round(timeoutMs / 1000)}s) — live diagnosis is still computing. Retry or check FastAPI logs.`,
      );
    }
    if (err instanceof TypeError) {
      throw new Error(
        `Cannot reach API at ${API_BASE}. Start FastAPI: uvicorn api.main:app --reload --port 8000`,
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchDashboard(params?: {
  lot?: string;
  wafer?: string;
  force?: boolean;
}): Promise<DiagnosisDashboard> {
  const qs = new URLSearchParams({ mode: "live" });
  if (params?.lot) qs.set("lot", params.lot);
  if (params?.wafer) qs.set("wafer", params.wafer);
  if (params?.force) qs.set("force", "true");
  return fetchJson<DiagnosisDashboard>(
    `/api/v1/diagnosis/dashboard?${qs.toString()}`,
    180_000,
  );
}

export function getReportHtmlUrl(download = false, version?: string | number): string {
  const params = new URLSearchParams();
  if (download) params.set("download", "true");
  if (version != null && version !== "") params.set("v", String(version));
  const qs = params.toString();
  return `${API_BASE}/api/v1/diagnosis/report/html${qs ? `?${qs}` : ""}`;
}

export async function fetchKpiWorkspace(
  kpiId: string,
  opts?: { minObservations?: number },
): Promise<KpiWorkspace> {
  const qs = new URLSearchParams({ mode: "live" });
  if (opts?.minObservations != null) {
    qs.set("min_observations", String(opts.minObservations));
  }
  // Pending reviews is cheap; others reuse server dashboard cache — no cache-bust
  const timeout = kpiId === "pending_reviews" ? 60_000 : 180_000;
  return fetchJson<KpiWorkspace>(
    `/api/v1/kpi/${encodeURIComponent(kpiId)}/workspace?${qs.toString()}`,
    timeout,
  );
}

export async function askCopilot(
  question: string,
  kpiId?: string,
): Promise<CopilotResponse> {
  try {
    const res = await fetch(
      `${API_BASE}/api/v1/diagnosis/copilot?mode=live`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ question, kpi_id: kpiId ?? null }),
      },
    );
    if (!res.ok) throw new Error("copilot failed");
    return (await res.json()) as CopilotResponse;
  } catch {
    return {
      answer: "Copilot unavailable — start the FastAPI server on port 8000.",
      citations: [],
      data_source: "fastapi-live",
    };
  }
}

export async function submitReview(
  itemId: string,
  decision: "confirm" | "reject" | "defer",
  reviewerNote?: string,
): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/api/v1/diagnosis/reviews/${encodeURIComponent(itemId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ decision, reviewer_note: reviewerNote ?? null }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Review failed (${res.status})`);
  }
  return res.json() as Promise<Record<string, unknown>>;
}

export async function fetchReviewQueue(opts?: {
  limit?: number;
  seed?: boolean;
}): Promise<{
  summary: Record<string, unknown>;
  items: Record<string, unknown>[];
  seeded?: boolean;
  fingerprint?: string;
  lifecycle?: Record<string, unknown>;
}> {
  const q = new URLSearchParams();
  q.set("limit", String(opts?.limit ?? 100));
  if (opts?.seed === false) q.set("seed", "false");
  return fetchJson(`/api/v1/diagnosis/reviews?${q.toString()}`, 180_000);
}

/** Patch Pending Reviews KPI on a cached dashboard payload (live UI without full rebuild). */
export function patchDashboardReviewSummary<T extends DiagnosisDashboard>(
  dash: T,
  summary: Record<string, unknown>,
): T {
  const pending = Number(summary.pending ?? 0);
  const confirmed = Number(summary.confirmed ?? 0);
  const feedback = Number(summary.feedback_records ?? 0);
  return {
    ...dash,
    kpis: (dash.kpis || []).map((k) =>
      k.id === "pending_reviews"
        ? {
            ...k,
            value: pending,
            badge: `${confirmed} confirmed · ${feedback} verified feedback`,
            status: "ok" as const,
          }
        : k,
    ),
    production_validation: {
      ...(dash.production_validation || {}),
      review_queue: summary,
    },
  };
}

export async function forceModelRetrain(): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/api/v1/diagnosis/models/retrain`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`Retrain failed (${res.status})`);
  return res.json() as Promise<Record<string, unknown>>;
}

export function apiFooterLabel(dashboard?: DiagnosisDashboard | null): string {
  if (!dashboard) return "Data source: —";
  return dashboard.footer || `Data source: ${dashboard.data_source}`;
}
