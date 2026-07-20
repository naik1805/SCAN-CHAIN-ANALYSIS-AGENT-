import type { DiagnosisDashboard, KpiWorkspace, WorkspacePanel } from "./diagnosisTypes";
import { computeOverallAverages } from "./correlationUtils";

function breaksDistributionByLot(
  breaks: Record<string, unknown>[] | undefined,
): Record<string, unknown>[] {
  if (!breaks?.length) return [];
  const counts = new Map<string, number>();
  for (const row of breaks) {
    const lot = String(row.lot_id ?? "UNKNOWN");
    counts.set(lot, (counts.get(lot) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([lot_id, scan_chain_break_count]) => ({ lot_id, scan_chain_break_count }));
}

/** Client-side workspace builder used when API workspace is unavailable. */
export function buildKpiWorkspace(
  kpiId: string,
  dashboard: DiagnosisDashboard,
): KpiWorkspace {
  const card = dashboard.kpis.find((k) => k.id === kpiId);
  const panels: WorkspacePanel[] = [];

  if (["failing_chains", "ranked_chains", "top_failing_chain"].includes(kpiId)) {
    panels.push({
      kind: "ranking_table",
      title: "Chain failure ranking",
      table: dashboard.ranking,
      chart: { type: "bar_h", data: dashboard.ranking },
    });
  }
  if (kpiId === "failing_cells") {
    panels.push({
      kind: "cells_table",
      title: "Failing Scan Cells",
      table: dashboard.cells_table,
      meta: dashboard.confidence,
    });
  }
  if (kpiId === "avg_confidence") {
    const conf = dashboard.confidence || {};
    const overallPct =
      typeof conf.overall_confidence_pct === "number"
        ? conf.overall_confidence_pct
        : typeof conf.mean_suspect_confidence === "number"
          ? Math.round(conf.mean_suspect_confidence * 1000) / 10
          : null;
    panels.push({
      kind: "diagnosis_confidence",
      title: "Diagnosis confidence (FR-010)",
      description:
        "How well our ML models and rule-based diagnosis logic performed — one trust score per model and per logic module.",
      table: (conf.categories as Record<string, unknown>[]) || [],
      meta: {
        ...conf,
        overall_confidence_pct: overallPct,
        ml_categories: conf.ml_categories || [],
        logic_categories: conf.logic_categories || [],
      },
    });
  }
  if (kpiId === "chain_breaks") {
    const lotRows = breaksDistributionByLot(dashboard.breaks_table);
    panels.push({
      kind: "breaks_by_lot",
      title: "Breaks Distribution by Lot",
      description: "Number of detected scan chain break signatures per lot (SCD-FR-006).",
      table: lotRows,
      meta: {
        total_break_signatures: dashboard.breaks_table?.length ?? 0,
        lots_affected: lotRows.length,
      },
    });
    panels.push({
      kind: "break_visualizer",
      title: "Interactive Scan Chain Break Visualizer",
      description: "Select die and broken chain to view zoomed schematic.",
      table: dashboard.breaks_table,
    });
    panels.push({
      kind: "breaks_table",
      title: "Scan chain breaks",
      table: dashboard.breaks_table,
    });
  }
  if (kpiId === "shift_capture") {
    panels.push({
      kind: "shift_capture",
      title: "Shift vs Capture",
      meta: dashboard.shift_capture,
      chart: { type: "pie", data: dashboard.shift_capture },
    });
    panels.push({
      kind: "diagnostics_registry",
      title: "Diagnostics Registry Table",
      description:
        "Per-failure shift/capture classification (SCD-FR-007). Load from API for full registry rows.",
      table: [],
      meta: { record_count: 0 },
    });
  }
  if (kpiId === "topology_chains") {
    const topo = dashboard.topology_summary || {};
    const summary = (topo.summary || {}) as Record<string, unknown>;
    panels.push({
      kind: "topology_overview",
      title: "Scan Chain Topology Analysis (SCD-FR-003)",
      description: "Load from API for full FR-003 topology drill-down.",
      meta: {
        number_of_scan_chains: topo.total_scan_chains,
        summary,
        chain_balance: summary.chain_balance || {},
        compression: summary.compression || {},
      },
    });
  }
  if (kpiId === "failure_correlations") {
    const correlations = dashboard.correlations || [];
    const overallAverages = computeOverallAverages(correlations);
    const sharedMeta = {
      overall_averages: overallAverages,
      chains: correlations.map((c) => c.chain),
      region_field_used: correlations.some((c) =>
        Object.keys((c.spatial_percentages as object) || (c.failure_region_percentages as object) || {}).length,
      )
        ? "die_label"
        : "failure_region",
      signature_method:
        "Chain Signature compares each chain's failure averages to the overall average across all failures. Distinguishing factors are ranked by percent difference from that average.",
      distribution_method:
        "Timing stress from setup/hold slack; spatial from die/wafer fields.",
      physical_features: [
        "ir_drop_mv",
        "thermal_c",
        "setup_slack_ps",
        "hold_slack_ps",
        "ai_severity_score",
      ],
      scan_load_features: [
        "shift_cycles",
        "capture_cycles",
        "scan_fail_count",
        "transition_faults",
        "test_time_ms",
      ],
      spatial_features: ["die_row", "die_col", "wafer_x", "wafer_y"],
      topology_fields: ["scan_length", "instance_type_code", "compression_channel_count"],
      topology_available: correlations.some((c) => {
        const profile = c.topology_profile as { scan_length?: number } | undefined;
        return Boolean(profile?.scan_length);
      }),
    };
    const overview = correlations
      .map((c) => {
        const factors = (c.distinguishing_factors as { label?: string; pct_diff?: number }[]) || [];
        const bullets = (c.signature_bullets as string[]) || [];
        const top = factors[0];
        return {
          chain: c.chain,
          failure_count: c.failure_count,
          top_factor: top?.label,
          top_pct_diff: top?.pct_diff,
          summary: bullets[1] || bullets[0] || "",
        };
      })
      .sort((a, b) => Math.abs(Number(b.top_pct_diff ?? 0)) - Math.abs(Number(a.top_pct_diff ?? 0)));
    panels.push({
      kind: "chain_signature_overview",
      title: "Chain Signature Overview",
      description: "All chains ranked by deviation from overall average.",
      table: overview,
      meta: sharedMeta,
    });
    panels.push({
      kind: "chain_signature_profile",
      title: "Chain Signature Profile",
      description: "Plain-language signature, comparisons, and distributions per chain.",
      table: correlations,
      meta: sharedMeta,
    });
    panels.push({
      kind: "correlation_chain_averages",
      title: "Scan Chain Average Physical Metrics & Severity Levels",
      description: "Per-chain mean metrics.",
      table: [],
      meta: sharedMeta,
    });
  }
  if (["diagnosis_reports", "pending_reviews"].includes(kpiId)) {
    panels.push({
      kind: "reports",
      title: "Reports",
      meta: dashboard.reports_meta,
    });
  }
  if (kpiId === "debug_locations") {
    panels.push({
      kind: "debug_locations",
      title: "Debug locations",
      table: [],
      meta: {},
    });
  }

  return {
    kpi_id: kpiId,
    title: card?.label ?? kpiId,
    status: card?.status ?? "ok",
    summary: { value: card?.value, badge: card?.badge },
    panels,
    data_source: dashboard.data_source,
    message: card?.caption ?? null,
  };
}
