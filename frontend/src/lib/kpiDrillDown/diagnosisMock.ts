import type { DiagnosisDashboard, KpiWorkspace } from "./diagnosisTypes";
import { buildKpiWorkspace } from "./buildKpiWorkspace";

const EMPTY_SUBTITLE =
  "Real-time diagnosis of scan chain failures using topology analysis, AI root cause detection and engineering recommendations.";

/** Empty dashboard shell — no decorative KPIs or fixed counts. */
export function emptyDashboard(message: string): DiagnosisDashboard {
  return {
    title: "Scan Diagnosis",
    subtitle: EMPTY_SUBTITLE,
    data_source: "fastapi-live",
    mode: "live",
    filters: { lots: [], wafers: [], testers: [], fabs: [], dates: [] },
    dataset_summary: {
      stil_file: "",
      log_files: [],
      log_file_count: 0,
      total_failure_records: 0,
      failing_chains: 0,
      all_chains: 0,
      failing_flops: 0,
    },
    kpis: [],
    ranking: [],
    correlations: [],
    shift_capture: {},
    confidence: {},
    topology_summary: {},
    breaks_table: [],
    cells_table: [],
    reports_meta: {},
    footer: message,
  };
}

/** Client-side workspace when the API workspace endpoint is unreachable. */
export function unavailableWorkspace(kpiId: string): KpiWorkspace {
  return buildKpiWorkspace(
    kpiId,
    emptyDashboard("API workspace unavailable — start FastAPI on port 8000."),
  );
}
