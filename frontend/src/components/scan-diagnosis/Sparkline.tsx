"use client";

import { Area, AreaChart, ResponsiveContainer } from "recharts";
import type { SparkPoint } from "@/lib/kpiDrillDown/diagnosisTypes";

export function Sparkline({ data }: { data?: SparkPoint[] }) {
  if (!data?.length) {
    return <div className="h-8 w-full opacity-20" />;
  }
  return (
    <div className="h-8 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <defs>
            <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#7C3AED" stopOpacity={0.55} />
              <stop offset="100%" stopColor="#7C3AED" stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="y"
            stroke="#7C3AED"
            strokeWidth={2}
            fill="url(#sparkFill)"
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
