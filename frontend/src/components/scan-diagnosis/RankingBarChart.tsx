"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export function RankingBarChart({
  ranking,
}: {
  ranking: Record<string, unknown>[];
}) {
  const data = [...ranking]
    .sort((a, b) => Number(a.rank ?? 0) - Number(b.rank ?? 0))
    .map((r) => ({
      name: String(r.chain ?? r.chain_with_rank ?? "?"),
      fails: Number(r.fail_count ?? r.failures ?? 0),
      rank: Number(r.rank ?? 0),
    }));

  if (!data.length) {
    return <EmptyChart label="No ranking data" />;
  }

  // Grow with chain count so every ranked chain is visible (min ~320px)
  const height = Math.max(320, data.length * 28 + 64);

  return (
    <div className="glass-card p-4" style={{ height }}>
      <h3 className="mb-2 font-display text-sm font-semibold text-white">
        Chain Failure Ranking ({data.length} chains)
      </h3>
      <ResponsiveContainer width="100%" height="90%">
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 12, top: 4, bottom: 4 }}>
          <CartesianGrid stroke="#2D3748" strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" stroke="#94a3b8" fontSize={11} />
          <YAxis
            type="category"
            dataKey="name"
            width={110}
            stroke="#94a3b8"
            fontSize={11}
            interval={0}
          />
          <Tooltip
            contentStyle={{
              background: "#111827",
              border: "1px solid #2D3748",
              borderRadius: 12,
            }}
            formatter={(value) => [value, "Fails"]}
            labelFormatter={(label, payload) => {
              const rank = payload?.[0]?.payload?.rank;
              return rank ? `#${rank} ${label}` : String(label);
            }}
          />
          <Bar dataKey="fails" fill="#7C3AED" radius={[0, 8, 8, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="glass-card flex h-80 items-center justify-center text-sm text-slate-500">
      {label}
    </div>
  );
}
