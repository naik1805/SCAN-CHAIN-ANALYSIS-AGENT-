"use client";

import { Download, ExternalLink, FileText } from "lucide-react";
import { getReportHtmlUrl } from "@/lib/kpiDrillDown/diagnosisApi";

type ReportStat = { label: string; value: string };
type ReportSection = {
  number: number;
  title: string;
  description?: string;
  stats?: ReportStat[];
};

type ChainSignatureRow = {
  chain?: string;
  failure_count?: number;
  summary?: string;
};

function CountBadge({ n, label }: { n: number; label: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-border/80 bg-card/50 px-2.5 py-0.5 text-[11px] font-medium text-slate-400">
      {n.toLocaleString()} {label}
    </span>
  );
}

function DataTable({
  columns,
  rows,
}: {
  columns: { key: string; label: string; align?: "left" | "right" }[];
  rows: Record<string, unknown>[];
}) {
  return (
    <div className="mt-3 max-h-[420px] overflow-auto rounded-lg border border-border/70">
      <table className="w-full min-w-[480px] border-collapse text-xs">
        <thead className="sticky top-0 z-[1] bg-[#0d1220]">
          <tr className="border-b border-border text-left text-slate-500">
            {columns.map((c) => (
              <th
                key={c.key}
                className={`px-3 py-2 font-semibold ${c.align === "right" ? "text-right" : ""}`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr
              key={idx}
              className="border-t border-border/40 odd:bg-[#0a0f18] even:bg-[#0c111c]"
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={`px-3 py-1.5 text-slate-300 ${
                    c.align === "right" ? "text-right tabular-nums" : ""
                  }`}
                >
                  {String(row[c.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DiagnosisReportPanel({
  meta,
  rankedChains,
}: {
  meta?: Record<string, unknown>;
  rankedChains?: Record<string, unknown>[];
}) {
  const htmlExists = Boolean(meta?.html_exists);
  const generatedAt = meta?.generated_at as string | undefined;
  const sections = (meta?.sections as ReportSection[]) || [];
  const signatures = (meta?.chain_signatures as ChainSignatureRow[]) || [];
  const topCells = (meta?.top_suspected_cells as Record<string, unknown>[]) || [];
  const breaks = (meta?.breaks as Record<string, unknown>[]) || [];
  const stilFile = String(meta?.stil_file ?? "—");
  const logCount = Number(meta?.log_file_count ?? 0);
  const totalFails = Number(meta?.total_failure_records ?? 0);
  const mlSummary = meta?.ml_summary as string | undefined;

  const metaChains = (meta?.top_ranked_chains as Record<string, unknown>[]) || [];
  const chains = metaChains.length ? metaChains : rankedChains?.length ? rankedChains : [];
  const chainRows = chains.map((row, idx) => ({
    rank: String(row.rank ?? idx + 1),
    chain: String(row.chain ?? "—"),
    fail_count: Number(row.fail_count ?? row.failures ?? 0).toLocaleString(),
    fail_pct:
      row.fail_pct != null
        ? `${Number(row.fail_pct).toFixed(2)}%`
        : row.percentage != null
          ? `${Number(row.percentage).toFixed(2)}%`
          : "—",
  }));

  const cellRows = topCells.map((row) => ({
    chain: String(row.chain ?? "—"),
    fail_flop_id: String(row.fail_flop_id ?? "—"),
    cell_name: String(row.cell_name ?? row.suspected_cell ?? "—"),
    confidence:
      row.confidence != null ? `${(Number(row.confidence) * 100).toFixed(1)}%` : "—",
  }));

  const breakRows = breaks.map((row) => ({
    chain: String(row.chain ?? "—"),
    lot_id: String(row.lot_id ?? "—"),
    location_status: String(row.location_status ?? "—"),
    candidate_cell: String(
      row.candidate_break_cell ?? row.suspected_break_cell ?? row.exact_break_cell ?? "—",
    ),
    fail_count: Number(row.fail_count ?? 0).toLocaleString(),
  }));

  const previewUrl = getReportHtmlUrl(false, generatedAt || Date.now());
  const downloadUrl = getReportHtmlUrl(true, generatedAt || Date.now());

  const summaryCounts = [
    { label: "Ranked chains", n: chainRows.length },
    { label: "Signatures", n: signatures.length },
    { label: "Suspected cells", n: cellRows.length },
    { label: "Break rows", n: breakRows.length },
  ].filter((x) => x.n > 0);

  return (
    <div className="space-y-5">
      {summaryCounts.length ? (
        <div className="flex flex-wrap gap-2 rounded-xl border border-primary/30 bg-primary/5 p-3">
          <span className="w-full text-[11px] font-semibold uppercase tracking-wide text-primary/90">
            Full report row counts (uncapped)
          </span>
          {summaryCounts.map((item) => (
            <CountBadge key={item.label} n={item.n} label={item.label} />
          ))}
        </div>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-border bg-card/50 p-4">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <FileText size={16} className="shrink-0 text-primary" />
            DFT Scan Chain Diagnosis Report
          </div>
          <p className="text-xs text-slate-500">
            {logCount.toLocaleString()} log file(s) · {totalFails.toLocaleString()} failures · STIL:{" "}
            <span className="break-all text-slate-400">{stilFile}</span>
          </p>
          {generatedAt ? (
            <p className="text-[11px] text-slate-600">
              Report generated {new Date(generatedAt).toLocaleString()}
            </p>
          ) : null}
          {mlSummary ? <p className="text-[11px] leading-relaxed text-slate-400">{mlSummary}</p> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {htmlExists ? (
            <>
              <a
                href={previewUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-[#090B12] px-3 py-2 text-xs font-medium text-slate-200 hover:border-primary/50 hover:bg-primary/10"
              >
                <ExternalLink size={14} />
                Open full report
              </a>
              <a
                href={downloadUrl}
                download="SCD-FR-008_scan_diagnosis_report.html"
                className="inline-flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/15 px-3 py-2 text-xs font-semibold text-violet-100 hover:bg-primary/25"
              >
                <Download size={14} />
                Download HTML report
              </a>
            </>
          ) : (
            <p className="text-xs text-amber-300/90">
              HTML report not found — run export to generate FR-008.
            </p>
          )}
        </div>
      </div>

      <div className="space-y-3">
        {sections.map((section) => (
          <section
            key={section.number}
            className="rounded-xl border border-border bg-[#0a0f18] p-4"
          >
            <h3 className="border-l-4 border-primary pl-3 font-display text-sm font-semibold text-white">
              {section.number}. {section.title}
            </h3>
            {section.description ? (
              <p className="mt-1 pl-4 text-xs text-slate-500">{section.description}</p>
            ) : null}
            {section.stats?.length ? (
              <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {section.stats.map((stat) => (
                  <div
                    key={stat.label}
                    className="min-w-0 rounded-lg border border-border/70 bg-card/40 px-3 py-2 text-center"
                  >
                    <div className="break-words text-lg font-bold tabular-nums text-primary">
                      {stat.value}
                    </div>
                    <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                      {stat.label}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </section>
        ))}
      </div>

      {chainRows.length ? (
        <section className="rounded-xl border border-border bg-[#0a0f18] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="border-l-4 border-primary pl-3 font-display text-sm font-semibold text-white">
              Failing chains (detail)
            </h3>
            <CountBadge n={chainRows.length} label="rows" />
          </div>
          <DataTable
            columns={[
              { key: "rank", label: "Rank" },
              { key: "chain", label: "Chain" },
              { key: "fail_count", label: "Failures", align: "right" },
              { key: "fail_pct", label: "%", align: "right" },
            ]}
            rows={chainRows}
          />
        </section>
      ) : null}

      {signatures.length ? (
        <section className="rounded-xl border border-border bg-[#0a0f18] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="border-l-4 border-primary pl-3 font-display text-sm font-semibold text-white">
              Chain signatures (FR-005)
            </h3>
            <CountBadge n={signatures.length} label="chains" />
          </div>
          <ul className="mt-3 max-h-[360px] space-y-2 overflow-auto pr-1">
            {signatures.map((row) => (
              <li
                key={String(row.chain)}
                className="rounded-lg border border-border/60 bg-card/30 px-3 py-2 text-xs"
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-medium text-slate-200">{row.chain}</span>
                  <span className="text-slate-500">
                    ({Number(row.failure_count ?? 0).toLocaleString()} failures)
                  </span>
                </div>
                {row.summary ? (
                  <p className="mt-1 leading-relaxed text-slate-400">{row.summary}</p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {cellRows.length ? (
        <section className="rounded-xl border border-border bg-[#0a0f18] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="border-l-4 border-primary pl-3 font-display text-sm font-semibold text-white">
              Suspected cells (FR-002)
            </h3>
            <CountBadge n={cellRows.length} label="cells" />
          </div>
          <DataTable
            columns={[
              { key: "chain", label: "Chain" },
              { key: "fail_flop_id", label: "Flop" },
              { key: "cell_name", label: "Cell" },
              { key: "confidence", label: "Confidence", align: "right" },
            ]}
            rows={cellRows}
          />
        </section>
      ) : null}

      {breakRows.length ? (
        <section className="rounded-xl border border-border bg-[#0a0f18] p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="border-l-4 border-primary pl-3 font-display text-sm font-semibold text-white">
              Chain breaks (FR-006)
            </h3>
            <CountBadge n={breakRows.length} label="rows" />
          </div>
          <DataTable
            columns={[
              { key: "lot_id", label: "Lot" },
              { key: "chain", label: "Chain" },
              { key: "location_status", label: "Status" },
              { key: "candidate_cell", label: "Cell" },
              { key: "fail_count", label: "Fails", align: "right" },
            ]}
            rows={breakRows}
          />
        </section>
      ) : null}

      {htmlExists ? (
        <section className="relative z-0 isolate clear-both overflow-hidden rounded-xl border border-border bg-[#0a0f18] p-4">
          <h3 className="mb-2 border-l-4 border-primary pl-3 font-display text-sm font-semibold text-white">
            Full report preview
          </h3>
          <p className="mb-3 pl-4 text-xs text-slate-500">
            Live preview of the exported HTML (full row counts, no caps). Scroll inside the frame;
            open in a new tab for the full layout.
          </p>
          <div className="relative z-0 isolate max-w-full overflow-hidden rounded-lg border border-border bg-white [contain:layout_paint]">
            <iframe
              key={String(generatedAt || "report-preview")}
              title="Scan diagnosis HTML report preview"
              src={previewUrl}
              className="relative z-0 block h-[min(720px,70vh)] w-full max-w-full border-0 bg-white"
              sandbox="allow-same-origin allow-popups"
              loading="lazy"
            />
          </div>
        </section>
      ) : null}
    </div>
  );
}
