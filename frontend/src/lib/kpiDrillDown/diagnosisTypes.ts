export type BadgeTone = "danger" | "success" | "warning" | "info" | "neutral";
export type KpiSection = "overview" | "engineering" | "ai";
export type DataSource = "fastapi-live" | "fastapi-exports" | "mock";

export interface SparkPoint {
  x: string;
  y: number;
}

export interface KpiCard {
  id: string;
  section: KpiSection;
  label: string;
  value: string | number;
  unit?: string | null;
  trend_pct?: number | null;
  badge?: string | null;
  badge_tone?: BadgeTone;
  status?: "ok" | "empty" | "na" | "error";
  caption?: string | null;
  sparkline?: SparkPoint[];
  help?: string | null;
}

export interface FilterOptions {
  lots: string[];
  wafers: string[];
  testers: string[];
  fabs: string[];
  dates: string[];
}

export interface DatasetSummary {
  stil_file: string;
  log_files: string[];
  log_file_count: number;
  total_failure_records: number;
  failing_chains: number;
  all_chains: number;
  failing_flops: number;
}

export interface MlStatusSummary {
  active: boolean;
  failure_records_analyzed: number;
  root_cause_model: string;
  anomaly_model: string;
  confidence_model: string;
  root_causes_estimated: number;
  anomaly_flagged_count: number;
  anomaly_flagged_pct: number;
  client_summary: string;
}

export interface DiagnosisDashboard {
  title: string;
  subtitle: string;
  data_source: DataSource;
  mode: "live" | "mock";
  filters: FilterOptions;
  dataset_summary?: DatasetSummary;
  ml_status?: MlStatusSummary;
  production_validation?: Record<string, unknown>;
  kpis: KpiCard[];
  ranking: Record<string, unknown>[];
  correlations: Record<string, unknown>[];
  shift_capture: Record<string, unknown>;
  confidence: Record<string, unknown>;
  topology_summary: Record<string, unknown>;
  breaks_table: Record<string, unknown>[];
  cells_table: Record<string, unknown>[];
  reports_meta: Record<string, unknown>;
  footer: string;
}

export interface WorkspacePanel {
  kind: string;
  title: string;
  description?: string | null;
  table?: Record<string, unknown>[];
  chart?: Record<string, unknown> | null;
  meta?: Record<string, unknown>;
}

export interface KpiWorkspace {
  kpi_id: string;
  title: string;
  status: "ok" | "empty" | "na" | "error";
  summary: Record<string, unknown>;
  panels: WorkspacePanel[];
  data_source: string;
  message?: string | null;
}

export interface CopilotResponse {
  answer: string;
  citations: string[];
  data_source: string;
}
