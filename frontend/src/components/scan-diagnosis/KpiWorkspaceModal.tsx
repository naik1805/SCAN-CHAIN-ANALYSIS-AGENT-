"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import {
  fetchKpiWorkspace,
  patchDashboardReviewSummary,
} from "@/lib/kpiDrillDown/diagnosisApi";
import type { DiagnosisDashboard } from "@/lib/kpiDrillDown/diagnosisTypes";
import { RankingBarChart } from "./RankingBarChart";
import { ChainSignatureCompact, ChainSignatureOverview, ChainSignaturePanel } from "./ChainSignaturePanel";
import { ShiftCaptureChart } from "./ShiftCaptureChart";
import { TopologyGraph } from "./TopologyGraph";
import { SuspectedCellsPanel } from "./SuspectedCellsPanel";
import { ScanChainBreakVisualizer } from "./ScanChainBreakVisualizer";
import { DiagnosisReportPanel } from "./DiagnosisReportPanel";
import { DiagnosisConfidencePanel } from "./DiagnosisConfidencePanel";
import { DebugLocationsPanel } from "./DebugLocationsPanel";
import { ReviewQueuePanel } from "./ReviewQueuePanel";
import { JsonDataTable, downloadJson, tableDownloadFilename } from "./JsonDataTable";
import {
  TopologyOverviewPanel,
  TopologyChainBalancePanel,
  TopologySharedResourcesPanel,
  TopologySchematicPanel,
} from "./topology/ScanTopologyPanels";
import { TopologyConnectivityPanel } from "./topology/TopologyConnectivityGraph";

export function KpiWorkspaceModal({
  kpiId,
  onClose,
}: {
  kpiId: string | null;
  onClose: () => void;
}) {
  const [minObservations, setMinObservations] = useState(2);
  const [topologySelectedChainId, setTopologySelectedChainId] = useState<string | null>(null);
  const [correlationSelectedChain, setCorrelationSelectedChain] = useState<string>("");
  const isCells = kpiId === "failing_cells";
  const isConfidence = kpiId === "avg_confidence";
  const usesMinObservations = isCells || isConfidence;
  const queryClient = useQueryClient();

  useEffect(() => {
    setTopologySelectedChainId(null);
    setCorrelationSelectedChain("");
  }, [kpiId]);

  const { data, isLoading, error, isFetching, refetch } = useQuery({
    queryKey: ["kpi-workspace", kpiId, usesMinObservations ? minObservations : null],
    queryFn: () =>
      fetchKpiWorkspace(kpiId!, usesMinObservations ? { minObservations } : undefined),
    enabled: !!kpiId,
    staleTime: kpiId === "pending_reviews" ? 5_000 : kpiId === "diagnosis_reports" ? 0 : 60_000,
    gcTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    placeholderData: (prev) => prev,
  });

  return (
    <AnimatePresence>
      {kpiId ? (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-3 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            role="dialog"
            aria-modal
            initial={{ opacity: 0, y: 24, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            onClick={(e) => e.stopPropagation()}
            className="flex h-[92vh] w-[95vw] max-w-[1400px] flex-col overflow-hidden rounded-glass border border-border bg-[#0c111c] shadow-glass"
          >
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <div>
                <div className="text-[11px] uppercase tracking-[0.18em] text-primary">
                  KPI Workspace
                  {isFetching ? " · Updating…" : ""}
                </div>
                <h2 className="font-display text-xl font-semibold text-white">
                  {kpiId === "failing_chains"
                    ? "Distinct failing scan chains"
                    : kpiId === "failing_cells"
                      ? "Failing Scan Cells (SCD-FR-002)"
                      : kpiId === "avg_confidence"
                        ? "Diagnosis Confidence (SCD-FR-010)"
                        : (data?.title ?? kpiId)}
                </h2>
                {data?.message ? (
                  <p className="text-xs text-slate-500">{data.message}</p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-xl border border-border p-2 text-slate-300 hover:bg-card"
              >
                <X size={16} />
              </button>
            </div>

            <div className="flex-1 overflow-auto p-5">
              {isLoading ? (
                <div className="space-y-2 text-sm text-slate-400">
                  <div>Loading workspace…</div>
                  <div className="text-xs text-slate-500">
                    {kpiId === "failure_correlations" || kpiId === "topology_chains"
                      ? "Correlation and topology workspaces can take 10–20 seconds."
                      : "Fetching drill-down data from the API."}
                  </div>
                </div>
              ) : error ? (
                <div className="space-y-2 text-sm text-danger">
                  <div>Failed to load workspace.</div>
                  <div className="text-xs text-slate-400">
                    Confirm FastAPI is running on port 8000, then click Refresh on the dashboard.
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  {!isCells ? (
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Meta
                        label={kpiId === "failing_chains" ? "Failed chains" : "Value"}
                        value={String(data?.summary?.value ?? "—")}
                      />
                      <Meta label="Badge" value={String(data?.summary?.badge ?? "—")} />
                    </div>
                  ) : null}

                  {(data?.panels || []).map((panel, idx) => {
                    if (panel.kind === "break_visualizer") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <ScanChainBreakVisualizer rows={panel.table || []} />
                        </div>
                      );
                    }

                    if (panel.kind === "cells_table") {
                      const chartData = (panel.chart?.data as Record<string, unknown>[]) || [];
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-4">
                          <SuspectedCellsPanel
                            table={panel.table || []}
                            chartData={chartData}
                            meta={panel.meta || {}}
                            minObservations={minObservations}
                            onMinObservationsChange={setMinObservations}
                          />
                        </div>
                      );
                    }

                    if (panel.kind === "diagnosis_confidence") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <DiagnosisConfidencePanel
                            categories={(panel.table || []) as Parameters<typeof DiagnosisConfidencePanel>[0]["categories"]}
                            meta={panel.meta || {}}
                            minObservations={minObservations}
                            onMinObservationsChange={setMinObservations}
                          />
                        </div>
                      );
                    }

                    if (panel.kind === "shift_capture") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <ShiftCaptureChart
                            shiftCapture={panel.meta || {}}
                            title="Failure Diagnostics Classification Breakdown"
                          />
                        </div>
                      );
                    }

                    if (panel.kind === "topology_overview") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <TopologyOverviewPanel meta={panel.meta || {}} />
                        </div>
                      );
                    }

                    if (panel.kind === "topology_chain_balance") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <TopologyChainBalancePanel
                            table={panel.table || []}
                            meta={panel.meta || {}}
                          />
                        </div>
                      );
                    }

                    if (panel.kind === "topology_shared_resources") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <TopologySharedResourcesPanel meta={panel.meta || {}} />
                        </div>
                      );
                    }

                    if (panel.kind === "topology_compression") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <div className="grid gap-2 sm:grid-cols-3">
                            <Meta
                              label="Decompressor Channels"
                              value={String(panel.meta?.decompressor_channels ?? "—")}
                            />
                            <Meta
                              label="Compactor Channels"
                              value={String(panel.meta?.compactor_channels ?? "—")}
                            />
                            <Meta
                              label="Compression Ratio"
                              value={`${Number(panel.meta?.compression_ratio ?? 0).toFixed(2)}x`}
                            />
                          </div>
                          <JsonDataTable
                            rows={panel.table || []}
                            showCsvDownload
                            csvDownloadLabel="Download compression mapping (CSV)"
                            maxHeightClass="max-h-72"
                          />
                        </div>
                      );
                    }

                    if (panel.kind === "topology_registry") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <JsonDataTable
                            rows={panel.table || []}
                            filename={tableDownloadFilename(panel.kind, panel.title)}
                            showCsvDownload
                            csvDownloadLabel="Download scan chain registry (CSV)"
                            jsonDownloadLabel="Download scan chain registry (JSON)"
                            maxHeightClass="max-h-[28rem]"
                          />
                        </div>
                      );
                    }

                    if (panel.kind === "topology_connectivity") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <TopologyConnectivityPanel
                            meta={panel.meta || {}}
                            selectedChainId={topologySelectedChainId}
                            onSelectChain={setTopologySelectedChainId}
                          />
                        </div>
                      );
                    }

                    if (panel.kind === "topology_schematic") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <TopologySchematicPanel
                            entries={panel.table || []}
                            chains={(panel.meta?.chains as Record<string, unknown>[]) || []}
                            selectedChainId={topologySelectedChainId}
                            onSelectChain={setTopologySelectedChainId}
                          />
                        </div>
                      );
                    }

                    if (panel.kind === "chain_signature_overview") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <ChainSignatureOverview
                            overview={(panel.table || []) as Parameters<typeof ChainSignatureOverview>[0]["overview"]}
                            selectedChain={correlationSelectedChain || undefined}
                            onSelectChain={setCorrelationSelectedChain}
                          />
                        </div>
                      );
                    }

                    if (panel.kind === "chain_signature_profile") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <ChainSignaturePanel
                            correlations={panel.table || []}
                            meta={panel.meta || {}}
                            onChainChange={setCorrelationSelectedChain}
                          />
                        </div>
                      );
                    }

                    {/* Legacy Pearson panels — hidden if API still returns old kinds */}
                    if (panel.kind === "correlation_heatmap" || panel.kind === "correlation_details" || panel.kind === "correlation_matrix") {
                      return null;
                    }

                    if (panel.kind === "correlation_chain_averages") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <JsonDataTable
                            rows={panel.table || []}
                            filename={tableDownloadFilename(panel.kind, panel.title)}
                            showCsvDownload
                            csvDownloadLabel="Download chain averages (CSV)"
                            maxHeightClass="max-h-80"
                          />
                        </div>
                      );
                    }

                    if (panel.kind === "debug_locations_panel") {
                      const tablePanel = (data?.panels || []).find(
                        (p) => p.kind === "debug_locations_table",
                      );
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <DebugLocationsPanel
                            topRecommendations={panel.table || []}
                            allRows={tablePanel?.table || []}
                            meta={panel.meta || {}}
                          />
                        </div>
                      );
                    }

                    if (panel.kind === "debug_locations_table") {
                      return null;
                    }

                    if (panel.kind === "review_queue") {
                      return (
                        <div key={`${panel.kind}-${idx}`} className="space-y-3">
                          <div>
                            <h3 className="font-display text-base font-semibold text-white">
                              {panel.title}
                            </h3>
                            {panel.description ? (
                              <p className="text-xs text-slate-500">{panel.description}</p>
                            ) : null}
                          </div>
                          <ReviewQueuePanel
                            items={(panel.table || []) as Parameters<typeof ReviewQueuePanel>[0]["items"]}
                            meta={panel.meta || {}}
                            onChanged={(summary) => {
                              if (summary) {
                                queryClient.setQueriesData<DiagnosisDashboard>(
                                  { queryKey: ["diagnosis-dashboard"] },
                                  (old) =>
                                    old ? patchDashboardReviewSummary(old, summary) : old,
                                );
                              }
                              // Only refresh the lightweight review workspace — not the full dashboard
                              void refetch();
                            }}
                          />
                        </div>
                      );
                    }

                    if (panel.kind === "reports") {
                      return (
                        <div key={`${panel.kind}-${idx}`}>
                          <DiagnosisReportPanel
                            meta={panel.meta || {}}
                            rankedChains={panel.table || []}
                          />
                        </div>
                      );
                    }

                    return (
                      <div key={`${panel.kind}-${idx}`} className="space-y-3">
                        <div>
                          <h3 className="font-display text-base font-semibold text-white">
                            {panel.title}
                          </h3>
                          {panel.description ? (
                            <p className="text-xs text-slate-500">{panel.description}</p>
                          ) : null}
                        </div>
                        {panel.kind === "ranking_table" ? (
                          <RankingBarChart
                            ranking={
                              (panel.table?.length
                                ? panel.table
                                : (panel.chart?.data as Record<string, unknown>[]) ||
                                  []) as Record<string, unknown>[]
                            }
                          />
                        ) : null}
                        {panel.kind === "correlation" ? (
                          <ChainSignatureCompact
                            overview={((panel.meta?.chain_signature_overview as Parameters<typeof ChainSignatureCompact>[0]["overview"]) || [])}
                          />
                        ) : null}
                        {panel.kind === "topology" ? (
                          <TopologyGraph topology={panel.meta || {}} />
                        ) : null}
                        {panel.table?.length || panel.kind === "fail_records" || panel.kind === "diagnostics_registry" ? (
                          <JsonDataTable
                            rows={panel.table || []}
                            filename={tableDownloadFilename(panel.kind, panel.title)}
                            showCsvDownload={
                              panel.kind === "fail_records" ||
                              panel.kind === "diagnostics_registry"
                            }
                            csvDownloadLabel={
                              panel.kind === "diagnostics_registry"
                                ? "Download Diagnostics Table (CSV)"
                                : "Download parsed failures (CSV)"
                            }
                            jsonDownloadLabel={
                              panel.kind === "diagnostics_registry"
                                ? "Download Diagnostics Table (JSON)"
                                : "Download JSON"
                            }
                            searchPlaceholder={
                              panel.kind === "diagnostics_registry"
                                ? "Search registry (e.g. Lot ID, File, Chain, Class, details)"
                                : "Filter rows…"
                            }
                            maxHeightClass={
                              panel.kind === "fail_records" ||
                              panel.kind === "diagnostics_registry"
                                ? "max-h-[28rem]"
                                : "max-h-72"
                            }
                          />
                        ) : null}
                        {panel.meta &&
                        !panel.table?.length &&
                        panel.kind !== "topology" &&
                        panel.kind !== "shift_capture" &&
                        panel.kind !== "reports" &&
                        !panel.kind.startsWith("topology_") ? (
                          <div className="overflow-hidden rounded-xl border border-border bg-card/60">
                            <div className="flex items-center justify-end border-b border-border px-3 py-2">
                              <button
                                type="button"
                                onClick={() =>
                                  downloadJson(
                                    panel.meta,
                                    tableDownloadFilename(panel.kind, panel.title),
                                  )
                                }
                                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-[#090B12] px-2.5 py-1.5 text-[11px] font-medium text-slate-200 transition hover:border-primary/50 hover:bg-primary/10 hover:text-white"
                              >
                                Download JSON
                              </button>
                            </div>
                            <pre className="max-h-64 overflow-auto bg-black/30 p-3 text-[11px] text-slate-300">
                              {JSON.stringify(panel.meta, null, 2)}
                            </pre>
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-card/60 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="truncate text-sm text-white">{value}</div>
    </div>
  );
}
