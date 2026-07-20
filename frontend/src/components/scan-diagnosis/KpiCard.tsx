"use client";

import { motion } from "framer-motion";
import { Activity, AlertTriangle, Brain, GitBranch, Link2, MapPin, Shield } from "lucide-react";
import type { KpiCard as KpiCardModel } from "@/lib/kpiDrillDown/diagnosisTypes";
import { Sparkline } from "./Sparkline";

const ICONS: Record<string, React.ReactNode> = {
  failing_chains: <Link2 size={16} />,
  failing_cells: <Activity size={16} />,
  chain_breaks: <AlertTriangle size={16} />,
  shift_capture: <GitBranch size={16} />,
  topology_chains: <MapPin size={16} />,
  ranked_chains: <Activity size={16} />,
  failure_correlations: <Activity size={16} />,
  top_failing_chain: <AlertTriangle size={16} />,
  diagnosis_reports: <Shield size={16} />,
  debug_locations: <MapPin size={16} />,
  avg_confidence: <Brain size={16} />,
  pending_reviews: <Shield size={16} />,
};

const TONE: Record<string, string> = {
  danger: "bg-danger/15 text-danger border-danger/30",
  success: "bg-success/15 text-success border-success/30",
  warning: "bg-warning/15 text-warning border-warning/30",
  info: "bg-cyan-500/15 text-cyan-300 border-cyan-500/30",
  neutral: "bg-slate-500/15 text-slate-300 border-slate-500/30",
};

export function KpiCardView({
  kpi,
  onClick,
}: {
  kpi: KpiCardModel;
  onClick: () => void;
}) {
  const tone = TONE[kpi.badge_tone || "neutral"];
  const trend =
    kpi.trend_pct == null
      ? null
      : kpi.trend_pct === 0
        ? "0%"
        : `${kpi.trend_pct > 0 ? "+" : ""}${kpi.trend_pct}%`;

  return (
    <motion.button
      type="button"
      layout
      whileHover={{ y: -2 }}
      onClick={onClick}
      title={kpi.help || kpi.label}
      className="glass-card gradient-border group relative w-full p-4 text-left"
    >
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary/15 text-primary">
          {ICONS[kpi.id] ?? <Activity size={16} />}
        </div>
        {kpi.badge ? (
          <span className={`max-w-[60%] truncate rounded-full border px-2 py-0.5 text-[10px] font-medium ${tone}`}>
            {kpi.badge}
          </span>
        ) : null}
      </div>

      <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">{kpi.label}</div>
      <div className="font-display text-3xl font-semibold tracking-tight text-white">
        {kpi.value}
      </div>
      {trend != null ? (
        <div className={`mt-1 text-xs font-medium ${kpi.trend_pct && kpi.trend_pct < 0 ? "text-danger" : "text-success"}`}>
          {trend} trend
        </div>
      ) : (
        <div className="mt-1 text-xs text-slate-500">Click for drill-down</div>
      )}
      {kpi.caption ? <div className="mt-1 text-[11px] text-slate-500">{kpi.caption}</div> : null}
      <div className="mt-3">
        <Sparkline data={kpi.sparkline} />
      </div>
    </motion.button>
  );
}
