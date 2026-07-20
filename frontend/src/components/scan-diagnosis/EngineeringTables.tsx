"use client";

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";

const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;

function formatCell(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3);
  if (typeof v === "object") return JSON.stringify(v).slice(0, 80);
  return String(v);
}

function rowMatchesQuery(row: Record<string, unknown>, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return Object.values(row).some((v) => {
    if (v == null) return false;
    return String(v).toLowerCase().includes(q);
  });
}

function SimpleTable({
  title,
  rows,
  columns,
  defaultPageSize = 50,
}: {
  title: string;
  rows: Record<string, unknown>[];
  columns: { key: string; label: string }[];
  defaultPageSize?: number;
}) {
  const [query, setQuery] = useState("");
  const [pageSize, setPageSize] = useState(defaultPageSize);
  const [page, setPage] = useState(0);

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
    <div className="glass-card overflow-hidden">
      <div className="border-b border-border px-4 py-3 font-display text-sm font-semibold text-white">
        {title}
        <span className="ml-2 font-sans text-[11px] font-normal uppercase tracking-wide text-slate-500">
          {rows.length} total
        </span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
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
            placeholder="Filter rows…"
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
      <div className="max-h-72 overflow-auto">
        {!rows.length ? (
          <div className="p-6 text-sm text-slate-500">No rows</div>
        ) : !visible.length ? (
          <div className="p-6 text-sm text-slate-500">No rows match filter</div>
        ) : (
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-[#0d1220] text-slate-400">
              <tr>
                {columns.map((c) => (
                  <th key={c.key} className="px-3 py-2 font-medium">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((row, idx) => (
                <tr key={start + idx} className="border-t border-border/50 hover:bg-white/5">
                  {columns.map((c) => (
                    <td key={c.key} className="px-3 py-2 text-slate-200">
                      {formatCell(row[c.key])}
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
              {PAGE_SIZE_OPTIONS.map((n) => (
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

export function EngineeringTables({
  breaks,
  cells,
}: {
  breaks: Record<string, unknown>[];
  cells: Record<string, unknown>[];
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <SimpleTable
        title="Chain Breaks (FR-006)"
        rows={breaks}
        columns={[
          { key: "chain", label: "Chain" },
          { key: "lot_id", label: "Lot" },
          { key: "break_bit_position", label: "Bit" },
          { key: "location_status", label: "Status" },
          { key: "suspected_break_cell", label: "Cell" },
        ]}
      />
      <SimpleTable
        title="Suspected Cells (FR-002)"
        rows={cells}
        columns={[
          { key: "chain", label: "Chain" },
          { key: "suspected_cell", label: "Cell" },
          { key: "fail_flop_id", label: "Flop" },
          { key: "confidence", label: "Confidence" },
          { key: "observations", label: "Obs" },
        ]}
      />
    </div>
  );
}
