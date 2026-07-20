export const PHYSICAL_TIMING_FEATURES = [
  "ir_drop_mv",
  "thermal_c",
  "setup_slack_ps",
  "hold_slack_ps",
  "ai_severity_score",
] as const;

export const SCAN_LOAD_FEATURES = [
  "shift_cycles",
  "capture_cycles",
  "scan_fail_count",
  "transition_faults",
  "test_time_ms",
] as const;

export const SPATIAL_FEATURES = [
  "die_row",
  "die_col",
  "wafer_x",
  "wafer_y",
] as const;

export const TOPOLOGY_FEATURES = [
  "scan_length",
  "instance_type_code",
  "compression_channel_count",
] as const;

export const CORRELATION_FEATURES = [
  ...PHYSICAL_TIMING_FEATURES,
  ...SCAN_LOAD_FEATURES,
  ...SPATIAL_FEATURES,
  ...TOPOLOGY_FEATURES,
] as const;

export type CorrelationFeature = (typeof CORRELATION_FEATURES)[number];

export type CorrelationFeatureGroup = {
  id: string;
  label: string;
  features: readonly string[];
};

export const CORRELATION_FEATURE_GROUPS: CorrelationFeatureGroup[] = [
  { id: "physical", label: "Physical / Timing", features: PHYSICAL_TIMING_FEATURES },
  { id: "scan_load", label: "Scan / Test Load", features: SCAN_LOAD_FEATURES },
  { id: "spatial", label: "Spatial (Die / Wafer)", features: SPATIAL_FEATURES },
  { id: "topology", label: "Topology / Clock / Compression", features: TOPOLOGY_FEATURES },
];

export const FEATURE_LABELS: Record<string, string> = {
  ir_drop_mv: "IR DROP MV",
  thermal_c: "THERMAL C",
  setup_slack_ps: "SETUP SLACK PS",
  hold_slack_ps: "HOLD SLACK PS",
  ai_severity_score: "AI SEVERITY SCORE",
  shift_cycles: "SHIFT CYCLES",
  capture_cycles: "CAPTURE CYCLES",
  scan_fail_count: "SCAN FAIL COUNT",
  transition_faults: "TRANSITION FAULTS",
  test_time_ms: "TEST TIME MS",
  die_row: "DIE ROW",
  die_col: "DIE COL",
  wafer_x: "WAFER X",
  wafer_y: "WAFER Y",
  scan_length: "SCAN LENGTH",
  instance_type_code: "INSTANCE TYPE",
  compression_channel_count: "COMPRESSION CHANNELS",
};

export type CorrelationSummary = {
  chain_count?: number;
  total_fail_records?: number;
  strongest_correlation?: {
    chain?: string;
    metric?: string;
    r?: number;
  } | null;
  max_abs_r?: number;
  correlation_strength?: string;
};

export type TopologyProfile = {
  clock_domain?: string | null;
  scan_master_clock?: string | null;
  scan_length?: number | null;
  instance_type?: string | null;
  decompressor_pin?: string | null;
  compactor_pin?: string | null;
  scan_in?: string | null;
  scan_out?: string | null;
  compression_ratio?: number | null;
  compression_logic?: string | null;
};

export function chainSortKey(chain: string): number {
  const digits = chain.replace(/\D/g, "");
  return digits ? Number(digits) : 0;
}

export function maxAbsCorrelation(row: Record<string, unknown>): number {
  const pearson = (row.pearson_correlations || {}) as Record<string, number>;
  return Math.max(0, ...Object.values(pearson).map((v) => Math.abs(Number(v) || 0)));
}

export function maxAbsFromDict(corr: Record<string, number> | undefined): number {
  if (!corr) return 0;
  return Math.max(0, ...Object.values(corr).map((v) => Math.abs(Number(v) || 0)));
}

export function sortChainsByStrongestCorrelation(
  correlations: Record<string, unknown>[],
): Record<string, unknown>[] {
  return [...correlations].sort(
    (a, b) =>
      maxAbsCorrelation(b) - maxAbsCorrelation(a) ||
      chainSortKey(String(a.chain)) - chainSortKey(String(b.chain)),
  );
}

/** RdBu-style diverging color for Pearson r in [-1, 1]. */
export function correlationCellColor(r: number): string {
  const clamped = Math.max(-1, Math.min(1, r));
  if (clamped >= 0) {
    const t = clamped;
    const rC = Math.round(239 - t * 180);
    const gC = Math.round(68 + t * 90);
    const bC = Math.round(68 + t * 170);
    const alpha = 0.18 + t * 0.62;
    return `rgba(${rC}, ${gC}, ${bC}, ${alpha})`;
  }
  const t = Math.abs(clamped);
  const rC = Math.round(59 + t * 180);
  const gC = Math.round(130 - t * 80);
  const bC = Math.round(246 - t * 120);
  const alpha = 0.18 + t * 0.62;
  return `rgba(${rC}, ${gC}, ${bC}, ${alpha})`;
}

export function formatFeatureLabel(key: string): string {
  return FEATURE_LABELS[key] ?? key.replace(/_/g, " ").toUpperCase();
}

export function formatMetricValue(key: string, value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (key === "ir_drop_mv") return `${value.toFixed(1)} mV`;
  if (key === "thermal_c") return `${value.toFixed(1)} °C`;
  if (key.endsWith("_ps")) return `${value.toFixed(1)} ps`;
  if (key === "test_time_ms") return `${value.toFixed(1)} ms`;
  if (key === "scan_length") return `${Math.round(value)} cells`;
  if (key === "instance_type_code") {
    if (value === 1) return "core_inst";
    if (value === 2) return "phy_inst";
    return "unknown";
  }
  return value.toFixed(3);
}

export function formatCorrelationInsight(summary: CorrelationSummary | undefined): string | null {
  if (!summary?.strongest_correlation) return null;
  const { chain, metric, r } = summary.strongest_correlation;
  if (!chain || !metric || r == null) return null;
  const strength = summary.correlation_strength ?? "weak";
  return `Strongest correlation (${strength}): ${formatFeatureLabel(metric)} on ${chain}, r=${Number(r).toFixed(3)}`;
}

export function regionPanelTitle(regionField?: string | null): string {
  switch (regionField) {
    case "failure_region":
      return "Failure Region Distribution";
    case "die_label":
      return "Die Location Distribution";
    case "die_row":
      return "Die Row Distribution";
    case "defect_type":
      return "Defect Type Distribution";
    default:
      return "Failure Region Distribution";
  }
}

export function rootCausePanelTitle(rootCauseField?: string | null): string {
  if (rootCauseField === "predicted_root_cause") {
    return "Predicted Root Cause Distribution";
  }
  return "Root Cause Hint Distribution";
}

export function resolveFeatureGroups(meta?: Record<string, unknown>): CorrelationFeatureGroup[] {
  if (!meta) return CORRELATION_FEATURE_GROUPS;
  const groups: CorrelationFeatureGroup[] = [];
  const mapping: [string, string, string][] = [
    ["physical_features", "physical", "Physical / Timing"],
    ["scan_load_features", "scan_load", "Scan / Test Load"],
    ["spatial_features", "spatial", "Spatial (Die / Wafer)"],
    ["topology_fields", "topology", "Topology / Clock / Compression"],
  ];
  for (const [metaKey, id, label] of mapping) {
    const feats = meta[metaKey] as string[] | undefined;
    if (feats?.length) {
      groups.push({ id, label, features: feats });
    }
  }
  return groups.length ? groups : CORRELATION_FEATURE_GROUPS;
}

export function computeOverallAverages(
  correlations: Record<string, unknown>[],
): Record<string, number | null> {
  const totals: Record<string, { sum: number; count: number }> = {};
  for (const row of correlations) {
    const avgs = (row.chain_averages || {}) as Record<string, number | null>;
    for (const [key, value] of Object.entries(avgs)) {
      if (value == null || !Number.isFinite(value)) continue;
      if (!totals[key]) totals[key] = { sum: 0, count: 0 };
      totals[key].sum += value;
      totals[key].count += 1;
    }
  }
  const overall: Record<string, number | null> = {};
  for (const [key, { sum, count }] of Object.entries(totals)) {
    overall[key] = count ? Math.round((sum / count) * 100) / 100 : null;
  }
  return overall;
}
