"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  apiFooterLabel,
  fetchDashboard,
  fetchReviewQueue,
  patchDashboardReviewSummary,
} from "@/lib/kpiDrillDown/diagnosisApi";
import type { DiagnosisDashboard } from "@/lib/kpiDrillDown/diagnosisTypes";
import { SECTION_PROFILES } from "@/lib/kpiDrillDown/kpiProfiles";
import { MlStatusBanner } from "./MlStatusBanner";
import { DiagnosisHeader } from "./DiagnosisHeader";
import { FilterBar } from "./FilterBar";
import { KpiSection } from "./KpiSection";
import { KpiWorkspaceModal } from "./KpiWorkspaceModal";
import { RankingBarChart } from "./RankingBarChart";
import { ChainSignatureCompact } from "./ChainSignaturePanel";
import { TopologyGraph } from "./TopologyGraph";
import { ShiftCaptureChart } from "./ShiftCaptureChart";
import { EngineeringTables } from "./EngineeringTables";
import { AICopilotPanel } from "./AICopilotPanel";
import { DatasetSnapshot, KpiBriefOverview } from "./KpiBriefOverview";

export function ScanDiagnosisTab() {
  const [lot, setLot] = useState("");
  const [activeKpi, setActiveKpi] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["diagnosis-dashboard", lot],
    queryFn: () =>
      fetchDashboard({
        lot: lot || undefined,
      }),
    staleTime: 60_000,
    gcTime: 10 * 60_000,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    placeholderData: (prev) => prev,
  });

  // Lightweight review KPI sync — no heavy seed on the interval (seed only when fingerprint changes).
  useQuery({
    queryKey: ["diagnosis-reviews-sync"],
    queryFn: async () => {
      // Cheap summary first (no seed)
      const synced = await fetchReviewQueue({ limit: 50, seed: false });
      const summary = synced.summary || {};
      queryClient.setQueriesData<DiagnosisDashboard>(
        { queryKey: ["diagnosis-dashboard"] },
        (old) => (old ? patchDashboardReviewSummary(old, summary) : old),
      );
      return synced;
    },
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    staleTime: 15_000,
  });

  const kpisBySection = useMemo(() => data?.kpis ?? [], [data]);

  return (
    <div className="pb-16">
      <DiagnosisHeader
        title={data?.title ?? "Scan Diagnosis"}
        subtitle={
          data?.subtitle ??
          "Real-time diagnosis of scan chain failures using topology analysis, AI root cause detection and engineering recommendations."
        }
        onRefresh={() => {
          void queryClient.fetchQuery({
            queryKey: ["diagnosis-dashboard", lot],
            queryFn: () =>
              fetchDashboard({
                lot: lot || undefined,
                force: true,
              }),
          });
        }}
        onExport={() => {
          if (!data) return;
          const blob = new Blob([JSON.stringify(data, null, 2)], {
            type: "application/json",
          });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = "scan-diagnosis-dashboard.json";
          a.click();
          URL.revokeObjectURL(url);
        }}
        onReport={() => setActiveKpi("diagnosis_reports")}
      />

      <div className="mx-auto max-w-[1400px] px-4 py-6">
        <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full border border-primary/40 bg-primary/15 px-3 py-1 font-medium text-violet-200">
            Scan Diagnosis
          </span>
          <span className="rounded-full border border-border px-3 py-1 text-slate-400">
            Source: {data?.data_source ?? "—"}
          </span>
          <span className="rounded-full border border-border px-3 py-1 text-slate-400">
            {isFetching ? "Refreshing…" : apiFooterLabel(data)}
          </span>
        </div>

        {data ? (
          <>
            <FilterBar
              filters={data.filters}
              summary={data.dataset_summary}
              lot={lot}
              onLot={setLot}
            />
            <MlStatusBanner status={data.ml_status} production={data.production_validation} />
          </>
        ) : null}

        {isLoading ? (
          <div className="glass-card space-y-2 p-10 text-center text-slate-400">
            <div>Loading diagnosis dashboard…</div>
            <div className="text-xs text-slate-500">
              Live analysis over 5k+ failures can take 10–30 seconds. Ensure FastAPI is running on
              port 8000.
            </div>
          </div>
        ) : isError && !data ? (
          <div className="glass-card space-y-2 p-10 text-center text-danger">
            <div>Failed to load dashboard.</div>
            <div className="text-xs text-slate-400">
              Start the API:{" "}
              <code className="text-slate-300">uvicorn api.main:app --reload --port 8000</code>
            </div>
          </div>
        ) : data ? (
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="min-w-0">
              {SECTION_PROFILES.map((profile) => (
                <KpiSection
                  key={profile.id}
                  profile={profile}
                  kpis={kpisBySection.filter((k) => k.section === profile.id)}
                  onSelect={setActiveKpi}
                />
              ))}

              <motion.section
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-6 grid gap-4 lg:grid-cols-2"
              >
                <RankingBarChart ranking={data.ranking} />
                <ChainSignatureCompact
                  overview={
                    (data.correlations || [])
                      .map((c) => {
                        const factors = (c.distinguishing_factors as { label?: string; pct_diff?: number }[]) || [];
                        const bullets = (c.signature_bullets as string[]) || [];
                        const top = factors[0];
                        return {
                          chain: String(c.chain),
                          failure_count: Number(c.failure_count ?? 0),
                          top_factor: top?.label,
                          top_pct_diff: top?.pct_diff,
                          summary: bullets[1] || bullets[0] || "",
                        };
                      })
                      .sort((a, b) => Math.abs(b.top_pct_diff ?? 0) - Math.abs(a.top_pct_diff ?? 0))
                  }
                />
                <ShiftCaptureChart
                  shiftCapture={data.shift_capture}
                  title="Shift vs Capture"
                  compact
                />
                <KpiBriefOverview kpis={kpisBySection} onSelect={setActiveKpi} />
                <TopologyGraph topology={data.topology_summary} />
                <DatasetSnapshot summary={data.dataset_summary} />
              </motion.section>

              <EngineeringTables breaks={data.breaks_table} cells={data.cells_table} />
            </div>

            <AICopilotPanel
              kpiId={activeKpi}
              dashboard={data}
              onSelectKpi={setActiveKpi}
            />
          </div>
        ) : null}

        <footer className="mt-10 text-center text-xs text-slate-500">
          {apiFooterLabel(data)} · FastAPI{" "}
          <code className="text-slate-400">uvicorn api.main:app --port 8000</code>
        </footer>
      </div>

      <KpiWorkspaceModal kpiId={activeKpi} onClose={() => setActiveKpi(null)} />
    </div>
  );
}
