"use client";

import { Bell, Calendar, Download, FileText, RefreshCw, Search, Upload } from "lucide-react";

export function DiagnosisHeader({
  title,
  subtitle,
  onRefresh,
  onExport,
  onReport,
}: {
  title: string;
  subtitle: string;
  onRefresh: () => void;
  onExport: () => void;
  onReport: () => void;
}) {
  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-[#090B12]/80 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1400px] flex-col gap-4 px-4 py-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-primary">
            COMPTY · Enterprise DFT
          </div>
          <h1 className="font-display text-2xl font-semibold text-white md:text-3xl">{title}</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">{subtitle}</p>
        </div>

        <div className="flex flex-1 flex-col gap-3 lg:max-w-xl lg:items-end">
          <div className="relative w-full">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              className="w-full rounded-2xl border border-border bg-card/80 py-2.5 pl-10 pr-3 text-sm text-slate-200 outline-none ring-primary/40 placeholder:text-slate-500 focus:ring-2"
              placeholder="Search scan chains, patterns, chips, flops..."
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="rounded-xl border border-border p-2 text-slate-300 hover:bg-card" title="Calendar">
              <Calendar size={16} />
            </button>
            <button type="button" className="rounded-xl border border-border p-2 text-slate-300 hover:bg-card" title="Notifications">
              <Bell size={16} />
            </button>
            <button
              type="button"
              onClick={onRefresh}
              className="inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-xs font-medium text-slate-200 hover:bg-card"
            >
              <RefreshCw size={14} /> Refresh
            </button>
            <button
              type="button"
              onClick={onExport}
              className="inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-xs font-medium text-slate-200 hover:bg-card"
            >
              <Download size={14} /> Export
            </button>
            <button
              type="button"
              onClick={onReport}
              className="inline-flex items-center gap-1.5 rounded-xl border border-primary/40 bg-primary/15 px-3 py-2 text-xs font-medium text-violet-200 hover:bg-primary/25"
            >
              <FileText size={14} /> Generate Report
            </button>
            <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-xl bg-primary px-3 py-2 text-xs font-semibold text-white shadow-lift">
              <Upload size={14} /> Upload
              <input type="file" className="hidden" multiple />
            </label>
          </div>
        </div>
      </div>
    </header>
  );
}
