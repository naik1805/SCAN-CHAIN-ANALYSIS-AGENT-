"use client";

import { useMemo, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, Download, Search } from "lucide-react";

const COLUMN_LABELS: Record<string, string> = {
  rank: "Rank",
  pfa_priority: "Debug Priority",
  priority: "Priority",
  confidence_pct: "Confidence %",
  predicted_root_cause: "Root Cause",
  distinct_dies_affected: "Dies Affected",
  die_occurrence_count: "Occurrences",
  logical_offset: "Logical Offset",
  x_um: "X (µm)",
  y_um: "Y (µm)",
  selection_rationale: "Why Chosen",
  evidence_summary: "Evidence",
  chain: "Chain",
  fail_count: "Fail Count",
  fail_pct: "Fail %",
  cumulative_pct: "Cumulative %",
  lot_id: "Lot ID",
  source_file: "File",
  pattern_id: "Pattern ID",
  fail_flop_id: "Flop ID",
  setup_slack_ps: "Setup Slack (ps)",
  hold_slack_ps: "Hold Slack (ps)",
  classification: "Diagnosis Class",
  diagnosis_details: "Details",
  scan_enable_se: "Scan Enable (SE)",
  decompressor_pin: "Decompressor",
  compactor_pin: "Compactor",
  cell_count: "Cell Count",
  scan_chain_id_short: "Scan Chain ID",
  scan_input_si: "Scan In (SI)",
  scan_output_so: "Scan Out (SO)",
  deviation_from_mean: "Deviation from Mean",
  resource: "Resource",
  chain_count: "Chain Count",
  chains: "Chains",
  bit_position: "Bit Position",
  offset_from_scan_in: "Offset from SI",
  cell_name: "Cell Name",
  x_local_um: "X (µm)",
  y_local_um: "Y (µm)",
  failure_observations: "Failure Obs",
  scan_chain_break_count: "Scan Chain Break Count",
  break_bit_position: "Bit",
  location_status: "Status",
  suspected_break_cell: "Cell",
  suspected_cell: "Cell",
  confidence: "Confidence",
  confidence_display: "Confidence",
  diagnosis_type: "Diagnosis type",
  requirement: "Requirement",
  target: "Target",
  detail: "Detail",
  observations: "Obs",
  wafer: "Wafer",
  tester: "Tester",
  fab: "Fab",
  date: "Date",
  cell: "Cell",
  count: "Count",
  pct: "Pct",
  correlation: "Correlation",
  feature_a: "Feature A",
  feature_b: "Feature B",
};

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;

function humanizeKey(key: string): string {
  if (COLUMN_LABELS[key]) return COLUMN_LABELS[key];
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function isPrimitiveArray(v: unknown): v is (string | number)[] {
  return (
    Array.isArray(v) &&
    v.length > 0 &&
    v.every((item) => typeof item === "string" || typeof item === "number")
  );
}

function formatCell(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") {
    return Number.isInteger(v) ? String(v) : v.toFixed(3);
  }
  if (isPrimitiveArray(v)) return v.map(String).join(", ");
  if (typeof v === "object") return JSON.stringify(v).slice(0, 80);
  const s = String(v);
  return s.length > 120 ? `${s.slice(0, 117)}…` : s;
}

function StringArrayCell({ items }: { items: (string | number)[] }) {
  return (
    <div className="flex max-w-xl flex-wrap gap-1 py-0.5">
      {items.map((item, i) => (
        <span
          key={`${String(item)}-${i}`}
          className="rounded border border-violet-500/30 bg-violet-500/10 px-1.5 py-0.5 font-mono text-[10px] leading-tight text-violet-200"
        >
          {String(item)}
        </span>
      ))}
    </div>
  );
}

function renderCellContent(v: unknown): ReactNode {
  if (v == null) return "—";
  if (Array.isArray(v) && v.length === 0) return "—";
  if (isPrimitiveArray(v)) return <StringArrayCell items={v} />;
  return formatCell(v);
}

function cellClassName(v: unknown): string {
  const base = "px-3 py-2 text-slate-200";
  if (isPrimitiveArray(v)) return `${base} align-top whitespace-normal`;
  return `${base} max-w-[28rem] truncate`;
}

const REGISTRY_COLUMNS = [
  "lot_id",
  "source_file",
  "pattern_id",
  "chain",
  "fail_flop_id",
  "setup_slack_ps",
  "hold_slack_ps",
  "classification",
  "diagnosis_details",
] as const;

/** True when a cell has nothing useful to show (null/empty/placeholder). */
function isBlankCell(v: unknown): boolean {
  if (v == null) return true;
  if (typeof v === "string") {
    const s = v.trim();
    return s === "" || s.toLowerCase() === "nan" || s.toLowerCase() === "none" || s === "—";
  }
  if (Array.isArray(v)) return v.length === 0;
  return false;
}

/** Drop columns that are blank in every row (e.g. Tessent-only fields on inline logs). */
function dropAllBlankColumns(
  rows: Record<string, unknown>[],
  columns: string[],
): string[] {
  if (!rows.length) return columns;
  return columns.filter((key) => rows.some((row) => !isBlankCell(row[key])));
}

function inferColumns(rows: Record<string, unknown>[]): string[] {
  const keys = new Set<string>();
  for (const row of rows) {
    for (const k of Object.keys(row)) keys.add(k);
  }
  let columns: string[];
  if (keys.has("classification") && keys.has("diagnosis_details")) {
    const ordered: string[] = REGISTRY_COLUMNS.filter((k) => keys.has(k));
    const rest = Array.from(keys).filter((k) => !ordered.includes(k));
    columns = [...ordered, ...rest];
  } else {
    // Prefer Streamlit FR-001 column order when present
    const preferred = [
      "source_file", "lot_folder", "tester_name", "test_program", "device_name",
      "lot_id", "defect_type", "die_label", "die_row", "die_col",
      "x1", "y1", "x2", "y2", "wafer_x", "wafer_y",
      "test_mode", "shift_cycles", "capture_cycles", "scan_chains", "total_patterns",
      "pattern_id", "channel_id", "chain", "expected_output", "status", "actual_output",
    ];
    const ordered = preferred.filter((k) => keys.has(k));
    const rest = Array.from(keys).filter((k) => !ordered.includes(k));
    if (ordered.length) {
      columns = [...ordered, ...rest];
    } else {
      // Shared resources / compression rows: resource → chains → chain_count
      const sharedPreferred = ["resource", "chains", "chain_count"];
      if (sharedPreferred.some((k) => keys.has(k))) {
        const sharedOrdered = sharedPreferred.filter((k) => keys.has(k));
        const sharedRest = Array.from(keys).filter((k) => !sharedOrdered.includes(k));
        columns = [...sharedOrdered, ...sharedRest];
      } else {
        columns = [...ordered, ...rest];
      }
    }
  }
  return dropAllBlankColumns(rows, columns);
}

function rowMatchesQuery(row: Record<string, unknown>, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return Object.values(row).some((v) => {
    if (v == null) return false;
    if (isPrimitiveArray(v)) {
      return v.some((item) => String(item).toLowerCase().includes(q));
    }
    return String(v).toLowerCase().includes(q);
  });
}

export function downloadJson(data: unknown, filename: string) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function downloadCsv(rows: Record<string, unknown>[], filename: string) {
  if (!rows.length) return;
  const cols = dropAllBlankColumns(
    rows,
    Array.from(
      rows.reduce((set, row) => {
        Object.keys(row).forEach((k) => set.add(k));
        return set;
      }, new Set<string>()),
    ),
  );
  if (!cols.length) return;
  const esc = (v: unknown) => {
    const s = v == null ? "" : String(v);
    if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  const lines = [
    cols.join(","),
    ...rows.map((row) => cols.map((c) => esc(row[c])).join(",")),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".csv") ? filename : `${filename.replace(/\.json$/i, "")}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export function JsonDataTable({
  rows,
  filename = "data.json",
  pageSizeOptions = PAGE_SIZE_OPTIONS,
  defaultPageSize = 50,
  caption,
  showCsvDownload = false,
  csvDownloadLabel = "Download parsed failures (CSV)",
  jsonDownloadLabel = "Download JSON",
  searchPlaceholder = "Filter rows…",
  maxHeightClass = "max-h-72",
}: {
  rows: Record<string, unknown>[];
  filename?: string;
  pageSizeOptions?: readonly number[];
  defaultPageSize?: number;
  caption?: string | null;
  showCsvDownload?: boolean;
  csvDownloadLabel?: string;
  jsonDownloadLabel?: string;
  searchPlaceholder?: string;
  maxHeightClass?: string;
}) {
  const [query, setQuery] = useState("");
  const [pageSize, setPageSize] = useState(defaultPageSize);
  const [page, setPage] = useState(0);

  const columns = useMemo(() => inferColumns(rows), [rows]);

  const filtered = useMemo(
    () => rows.filter((row) => rowMatchesQuery(row, query)),
    [rows, query],
  );

  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize) || 1);
  const safePage = Math.min(page, totalPages - 1);
  const start = total === 0 ? 0 : safePage * pageSize;
  const end = Math.min(start + pageSize, total);
  const visible = filtered.slice(start, end);

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card/60">
      {caption ? (
        <div className="border-b border-border px-3 py-2 text-sm text-slate-300">
          {caption}
        </div>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
          <div className="relative min-w-[10rem] max-w-xs flex-1">
            <Search
              size={12}
              className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-slate-500"
            />
            <input
              type="search"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(0);
              }}
              placeholder={searchPlaceholder}
              className="w-full rounded-lg border border-border bg-[#090B12] py-1.5 pl-7 pr-2 text-[11px] text-slate-200 placeholder:text-slate-600 focus:border-primary/50 focus:outline-none"
            />
          </div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">
            {total === 0
              ? `0 of ${rows.length} rows`
              : `Showing ${start + 1}–${end} of ${total}${
                  query.trim() && total !== rows.length ? ` (filtered from ${rows.length})` : ""
                }`}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {showCsvDownload ? (
            <button
              type="button"
              onClick={() => downloadCsv(rows, filename)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-[#090B12] px-2.5 py-1.5 text-[11px] font-medium text-slate-200 transition hover:border-primary/50 hover:bg-primary/10 hover:text-white"
            >
              <Download size={12} className="text-primary" />
              {csvDownloadLabel}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => downloadJson(rows, filename)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-[#090B12] px-2.5 py-1.5 text-[11px] font-medium text-slate-200 transition hover:border-primary/50 hover:bg-primary/10 hover:text-white"
          >
            <Download size={12} className="text-primary" />
            {jsonDownloadLabel}
          </button>
        </div>
      </div>
      <div className={`${maxHeightClass} overflow-auto`}>
        {!rows.length ? (
          <div className="p-6 text-sm text-slate-500">No rows</div>
        ) : !visible.length ? (
          <div className="p-6 text-sm text-slate-500">No rows match filter</div>
        ) : (
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-[#0d1220] text-slate-400">
              <tr>
                {columns.map((key) => (
                  <th key={key} className="whitespace-nowrap px-3 py-2 font-medium">
                    {humanizeKey(key)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((row, idx) => (
                <tr
                  key={start + idx}
                  className="border-t border-border/50 hover:bg-white/5"
                >
                  {columns.map((key) => (
                    <td
                      key={key}
                      className={cellClassName(row[key])}
                      title={formatCell(row[key])}
                    >
                      {renderCellContent(row[key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {rows.length > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2">
          <label className="flex items-center gap-1.5 text-[11px] text-slate-400">
            Per page
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(0);
              }}
              className="rounded-md border border-border bg-[#090B12] px-1.5 py-1 text-[11px] text-slate-200"
            >
              {pageSizeOptions.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={safePage <= 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="inline-flex items-center rounded-md border border-border bg-[#090B12] p-1.5 text-slate-300 disabled:cursor-not-allowed disabled:opacity-40 hover:border-primary/50 hover:text-white"
              aria-label="Previous page"
            >
              <ChevronLeft size={14} />
            </button>
            <span className="min-w-[4.5rem] text-center text-[11px] text-slate-400">
              Page {safePage + 1} / {totalPages}
            </span>
            <button
              type="button"
              disabled={safePage >= totalPages - 1}
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              className="inline-flex items-center rounded-md border border-border bg-[#090B12] p-1.5 text-slate-300 disabled:cursor-not-allowed disabled:opacity-40 hover:border-primary/50 hover:text-white"
              aria-label="Next page"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** Filename hint from panel kind / title for downloads. */
export function tableDownloadFilename(kind: string, title?: string | null): string {
  const base =
    kind === "ranking_table"
      ? "ranked-chains"
      : kind === "fail_records"
        ? "parsed_scan_failures"
      : kind === "diagnostics_registry"
        ? "shift_capture_diagnostics"
      : (title || kind || "data")
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-|-$/g, "") || "data";
  return `${base}.json`;
}
