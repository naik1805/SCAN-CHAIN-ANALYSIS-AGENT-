"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { RotateCcw, ZoomIn, ZoomOut } from "lucide-react";

type GraphNode = {
  id: string;
  x: number;
  y: number;
  label: string;
  kind: string;
  hover?: string;
  details?: Record<string, unknown>;
};

type GraphEdge = { from: string; to: string };

const NODE_COLORS: Record<string, string> = {
  controller: "#06b6d4",
  decompressor: "#3b82f6",
  chain: "#10b981",
  compactor: "#8b5cf6",
};

const LEGEND = [
  { kind: "controller", label: "Controller", color: NODE_COLORS.controller },
  { kind: "decompressor", label: "Decompressor", color: NODE_COLORS.decompressor },
  { kind: "chain", label: "Scan Chain", color: NODE_COLORS.chain },
  { kind: "compactor", label: "Compactor", color: NODE_COLORS.compactor },
];

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-card/60 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="truncate text-sm text-white">{value}</div>
    </div>
  );
}

function nodeRadius(kind: string): number {
  if (kind === "controller") return 10;
  if (kind === "chain") return 7;
  return 8;
}

export function TopologyConnectivityPanel({
  meta,
  selectedChainId,
  onSelectChain,
}: {
  meta: Record<string, unknown>;
  selectedChainId?: string | null;
  onSelectChain?: (chainId: string | null) => void;
}) {
  const graph = (meta.system_graph || {}) as {
    nodes?: GraphNode[];
    edges?: GraphEdge[];
    stats?: Record<string, unknown>;
  };
  const stats = graph.stats || {};
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];

  const pos = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>();
    for (const n of nodes) m.set(n.id, { x: n.x, y: n.y });
    return m;
  }, [nodes]);

  const chainCount = nodes.filter((n) => n.kind === "chain").length;
  const baseW = 780;
  const baseH = Math.max(480, chainCount * 24 + 140);
  const pad = 56;

  const mapX = useCallback(
    (x: number) => pad + (x / 6.8) * (baseW - pad * 2),
    [baseW, pad],
  );
  const mapY = useCallback(
    (y: number) => pad + (1 - y) * (baseH - pad * 2),
    [baseH, pad],
  );

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; node: GraphNode } | null>(
    null,
  );
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  const dragRef = useRef<{ px: number; py: number; vx: number; vy: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const activeId = hoveredId || selectedChainId || null;

  const connected = useMemo(() => {
    if (!activeId) return new Set<string>();
    const set = new Set<string>([activeId]);
    for (const e of edges) {
      if (e.from === activeId) set.add(e.to);
      if (e.to === activeId) set.add(e.from);
    }
    return set;
  }, [activeId, edges]);

  const selectedNode = nodes.find((n) => n.id === selectedChainId);

  const zoom = (delta: number) => {
    setView((v) => ({
      ...v,
      scale: Math.min(2.5, Math.max(0.45, v.scale + delta)),
    }));
  };

  const resetView = () => setView({ x: 0, y: 0, scale: 1 });

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    zoom(e.deltaY > 0 ? -0.08 : 0.08);
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if ((e.target as Element).closest("[data-graph-node]")) return;
    dragRef.current = { px: e.clientX, py: e.clientY, vx: view.x, vy: view.y };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.px;
    const dy = e.clientY - dragRef.current.py;
    setView((v) => ({
      ...v,
      x: dragRef.current!.vx + dx,
      y: dragRef.current!.vy + dy,
    }));
  };

  const onPointerUp = () => {
    dragRef.current = null;
  };

  const handleNodeEnter = (node: GraphNode, e: React.MouseEvent) => {
    setHoveredId(node.id);
    const rect = svgRef.current?.getBoundingClientRect();
    if (rect) {
      setTooltip({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
        node,
      });
    }
  };

  const handleNodeClick = (node: GraphNode) => {
    if (node.kind === "chain") {
      onSelectChain?.(node.id === selectedChainId ? null : node.id);
    }
  };

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-3">
        <Metric label="Graph Nodes" value={String(stats.graph_nodes ?? "—")} />
        <Metric label="Graph Edges" value={String(stats.graph_edges ?? "—")} />
        <Metric label="Chain Nodes" value={String(stats.chain_nodes ?? "—")} />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-3">
          {LEGEND.map((l) => (
            <span key={l.kind} className="inline-flex items-center gap-1.5 text-[10px] text-slate-400">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: l.color }}
              />
              {l.label}
            </span>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => zoom(0.12)}
            className="rounded-lg border border-border p-1.5 text-slate-300 hover:bg-white/5"
            title="Zoom in"
          >
            <ZoomIn size={14} />
          </button>
          <button
            type="button"
            onClick={() => zoom(-0.12)}
            className="rounded-lg border border-border p-1.5 text-slate-300 hover:bg-white/5"
            title="Zoom out"
          >
            <ZoomOut size={14} />
          </button>
          <button
            type="button"
            onClick={resetView}
            className="rounded-lg border border-border p-1.5 text-slate-300 hover:bg-white/5"
            title="Reset view"
          >
            <RotateCcw size={14} />
          </button>
        </div>
      </div>

      <div
        className="relative overflow-hidden rounded-xl border border-border bg-[#060810] touch-none"
        style={{ height: Math.min(640, baseH + 40) }}
        onWheel={onWheel}
      >
        <svg
          ref={svgRef}
          width="100%"
          height="100%"
          viewBox={`0 0 ${baseW} ${baseH}`}
          className="cursor-grab active:cursor-grabbing"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={onPointerUp}
        >
          <g transform={`translate(${view.x} ${view.y}) scale(${view.scale})`}>
            {edges.map((e, i) => {
              const a = pos.get(e.from);
              const b = pos.get(e.to);
              if (!a || !b) return null;
              const highlighted =
                activeId &&
                (e.from === activeId ||
                  e.to === activeId ||
                  connected.has(e.from) ||
                  connected.has(e.to));
              return (
                <line
                  key={`${e.from}-${e.to}-${i}`}
                  x1={mapX(a.x)}
                  y1={mapY(a.y)}
                  x2={mapX(b.x)}
                  y2={mapY(b.y)}
                  stroke={highlighted ? "rgba(56,189,248,0.75)" : "rgba(148,163,184,0.35)"}
                  strokeWidth={highlighted ? 2 : 1.2}
                />
              );
            })}
            {nodes.map((n) => {
              const cx = mapX(n.x);
              const cy = mapY(n.y);
              const r = nodeRadius(n.kind);
              const isChain = n.kind === "chain";
              const isSelected = selectedChainId === n.id;
              const isHovered = hoveredId === n.id;
              const dimmed = activeId && !connected.has(n.id) && n.id !== activeId;
              const fill = NODE_COLORS[n.kind] || "#64748b";

              return (
                <g
                  key={n.id}
                  data-graph-node
                  style={{ cursor: isChain ? "pointer" : "default", opacity: dimmed ? 0.35 : 1 }}
                  onMouseEnter={(e) => handleNodeEnter(n, e)}
                  onMouseMove={(e) => handleNodeEnter(n, e)}
                  onMouseLeave={() => {
                    setHoveredId(null);
                    setTooltip(null);
                  }}
                  onClick={() => handleNodeClick(n)}
                >
                  {(isSelected || isHovered) && isChain ? (
                    <circle cx={cx} cy={cy} r={r + 6} fill="none" stroke="#38bdf8" strokeWidth={2} />
                  ) : null}
                  <circle
                    cx={cx}
                    cy={cy}
                    r={r}
                    fill={fill}
                    stroke={isSelected ? "#e0f2fe" : "#1f2937"}
                    strokeWidth={isSelected ? 2 : 1}
                  />
                  {isChain ? (
                    <text
                      x={cx + 12}
                      y={cy + 4}
                      fill={isSelected || isHovered ? "#e0f2fe" : "#a7f3d0"}
                      fontSize={9}
                      fontWeight={isSelected ? 700 : 400}
                    >
                      {n.label}
                    </text>
                  ) : n.kind !== "chain" && (isHovered || n.kind === "controller") ? (
                    <text
                      x={cx}
                      y={cy - r - 4}
                      fill="#94a3b8"
                      fontSize={8}
                      textAnchor="middle"
                    >
                      {n.label}
                    </text>
                  ) : null}
                </g>
              );
            })}
          </g>
        </svg>

        {tooltip ? (
          <div
            className="pointer-events-none absolute z-10 max-w-xs rounded-lg border border-border bg-[#111827]/95 px-3 py-2 text-[11px] text-slate-200 shadow-lg"
            style={{
              left: Math.min(tooltip.x + 12, baseW - 200),
              top: Math.max(tooltip.y - 8, 8),
            }}
          >
            {tooltip.node.kind === "chain" && tooltip.node.details ? (
              <div className="space-y-1">
                <div className="font-semibold text-white">
                  {String(tooltip.node.details.chain_name)}
                </div>
                <div className="text-slate-400">
                  {String(tooltip.node.details.instance_type)} ·{" "}
                  {String(tooltip.node.details.chain_length)} FFs
                </div>
                <div>SI: {String(tooltip.node.details.scan_input_si)}</div>
                <div>SO: {String(tooltip.node.details.scan_output_so)}</div>
                <div>Clock: {String(tooltip.node.details.clock_domain ?? "N/A")}</div>
                <div className="text-primary/90">Click to select · syncs schematic below</div>
              </div>
            ) : (
              <div>{tooltip.node.hover || tooltip.node.label}</div>
            )}
          </div>
        ) : null}
      </div>

      {selectedNode?.details ? (
        <div className="rounded-xl border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-slate-300">
          <span className="font-semibold text-white">
            Selected: {String(selectedNode.details.chain_name)}
          </span>
          {" · "}
          {String(selectedNode.details.chain_length)} FFs · SI{" "}
          {String(selectedNode.details.scan_input_si)} → SO{" "}
          {String(selectedNode.details.scan_output_so)}
        </div>
      ) : null}

      <p className="text-xs text-slate-500">
        Interactive system-level DFT graph ({String(stats.chain_nodes ?? 0)} chains ·{" "}
        {Number(stats.compression_ratio ?? 0).toFixed(1)}x compression). Hover for details, click
        a scan chain to highlight paths and sync the schematic panel. Drag to pan, scroll or use
        buttons to zoom.
      </p>
    </div>
  );
}
