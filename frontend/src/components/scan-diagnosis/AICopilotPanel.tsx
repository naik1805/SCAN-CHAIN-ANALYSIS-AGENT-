"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Brain,
  Link2,
  MapPin,
  Send,
  Sparkles,
} from "lucide-react";
import { askCopilot } from "@/lib/kpiDrillDown/diagnosisApi";
import type { DiagnosisDashboard, KpiCard } from "@/lib/kpiDrillDown/diagnosisTypes";

const QUICK_PROMPTS = [
  "What is the top failing chain?",
  "How many chain breaks?",
  "What is diagnosis confidence?",
  "Where should I debug first?",
];

function kpiValue(kpis: KpiCard[], id: string): string {
  const card = kpis.find((k) => k.id === id);
  return card ? String(card.value) : "—";
}

function FindingRow({
  icon,
  label,
  value,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  onClick?: () => void;
}) {
  const Comp = onClick ? "button" : "div";
  return (
    <Comp
      type={onClick ? "button" : undefined}
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-lg border border-border/50 bg-[#0d1220]/70 px-2.5 py-2 text-left ${
        onClick ? "transition hover:border-primary/40 hover:bg-primary/5" : ""
      }`}
    >
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[10px] uppercase tracking-wide text-slate-500">{label}</span>
        <span className="block truncate font-display text-sm font-semibold text-white">{value}</span>
      </span>
      {onClick ? <ArrowRight size={12} className="shrink-0 text-slate-600" /> : null}
    </Comp>
  );
}

export function AICopilotPanel({
  kpiId,
  dashboard,
  onSelectKpi,
}: {
  kpiId?: string | null;
  dashboard?: DiagnosisDashboard | null;
  onSelectKpi?: (id: string) => void;
}) {
  const [q, setQ] = useState("What is the top failing chain?");
  const [answer, setAnswer] = useState<string>("");
  const [citations, setCitations] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const kpis = dashboard?.kpis ?? [];
  const trust = kpis.find((k) => k.id === "avg_confidence")?.badge;
  const topChain = kpiValue(kpis, "top_failing_chain");
  const breaks = kpiValue(kpis, "chain_breaks");
  const confidence = kpiValue(kpis, "avg_confidence");
  const debugLocs = kpiValue(kpis, "debug_locations");
  const cells = kpiValue(kpis, "failing_cells");

  async function onAsk(prompt?: string) {
    const question = (prompt ?? q).trim();
    if (!question) return;
    setQ(question);
    setLoading(true);
    try {
      const res = await askCopilot(question, kpiId ?? undefined);
      setAnswer(res.answer);
      setCitations(res.citations || []);
    } finally {
      setLoading(false);
    }
  }

  return (
    <motion.aside
      initial={{ opacity: 0, x: 12 }}
      animate={{ opacity: 1, x: 0 }}
      className="glass-card gradient-border sticky top-24 flex max-h-[calc(100vh-7rem)] flex-col gap-4 overflow-y-auto p-4"
    >
      {/* Key findings fill the tall empty rail */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <Sparkles size={14} className="text-primary" />
          <div className="font-display text-sm font-semibold text-white">Key findings</div>
        </div>
        <div className="space-y-1.5">
          <FindingRow
            icon={<AlertTriangle size={14} />}
            label="Top failing chain"
            value={topChain}
            onClick={onSelectKpi ? () => onSelectKpi("top_failing_chain") : undefined}
          />
          <FindingRow
            icon={<Brain size={14} />}
            label="Diagnosis confidence"
            value={trust ? `${confidence} · ${trust}` : confidence}
            onClick={onSelectKpi ? () => onSelectKpi("avg_confidence") : undefined}
          />
          <FindingRow
            icon={<Link2 size={14} />}
            label="Chain breaks"
            value={`${breaks} signatures`}
            onClick={onSelectKpi ? () => onSelectKpi("chain_breaks") : undefined}
          />
          <FindingRow
            icon={<MapPin size={14} />}
            label="Debug locations"
            value={`${debugLocs} debug sites`}
            onClick={onSelectKpi ? () => onSelectKpi("debug_locations") : undefined}
          />
          <FindingRow
            icon={<Bot size={14} />}
            label="Failing cells"
            value={`${cells} suspects`}
            onClick={onSelectKpi ? () => onSelectKpi("failing_cells") : undefined}
          />
        </div>
      </div>

      <div>
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
          Suggested next steps
        </div>
        <ol className="space-y-2 text-[11px] leading-snug text-slate-400">
          <li className="rounded-lg border border-border/40 bg-black/20 px-2.5 py-2">
            <span className="font-medium text-slate-300">1. Inspect </span>
            {topChain !== "—" ? topChain : "top chain"} break schematic and fail ranking.
          </li>
          <li className="rounded-lg border border-border/40 bg-black/20 px-2.5 py-2">
            <span className="font-medium text-slate-300">2. Open </span>
            Debug Locations for ranked debug coordinates with evidence.
          </li>
          <li className="rounded-lg border border-border/40 bg-black/20 px-2.5 py-2">
            <span className="font-medium text-slate-300">3. Check </span>
            Diagnosis Confidence before sending leads to silicon debug.
          </li>
        </ol>
      </div>

      <div className="border-t border-border/60 pt-3">
        <div className="mb-3 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary/20 text-primary">
            <Bot size={16} />
          </div>
          <div>
            <div className="font-display text-sm font-semibold text-white">AI Copilot</div>
            <div className="text-[11px] text-slate-500">Ask about any KPI or finding</div>
          </div>
        </div>

        <div className="mb-2 flex flex-wrap gap-1.5">
          {QUICK_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => onAsk(prompt)}
              className="rounded-full border border-border/70 bg-[#0d1220] px-2 py-1 text-[10px] text-slate-400 transition hover:border-primary/40 hover:text-violet-200"
            >
              {prompt.replace(/\?$/, "")}
            </button>
          ))}
        </div>

        <textarea
          value={q}
          onChange={(e) => setQ(e.target.value)}
          rows={3}
          className="mb-2 w-full rounded-xl border border-border bg-[#0d1220] p-3 text-sm text-slate-100 outline-none focus:ring-2 focus:ring-primary/40"
        />
        <button
          type="button"
          disabled={loading}
          onClick={() => onAsk()}
          className="mb-3 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-3 py-2 text-sm font-semibold text-white disabled:opacity-60"
        >
          <Send size={14} /> {loading ? "Thinking…" : "Ask"}
        </button>
        {answer ? (
          <div className="rounded-xl border border-border/80 bg-black/20 p-3 text-sm text-slate-200">
            {answer}
            {citations.length ? (
              <div className="mt-2 text-[11px] text-slate-500">
                Citations: {citations.join(", ")}
              </div>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-slate-500">
            Answers use live diagnosis KPIs and engine exports.
          </p>
        )}
      </div>
    </motion.aside>
  );
}
