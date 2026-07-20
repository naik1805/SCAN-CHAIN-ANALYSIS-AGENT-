"use client";

import type { KpiCard } from "@/lib/kpiDrillDown/diagnosisTypes";
import { KPI_ORDER, type SectionProfile } from "@/lib/kpiDrillDown/kpiProfiles";
import { KpiCardView } from "./KpiCard";

export function KpiSection({
  profile,
  kpis,
  onSelect,
}: {
  profile: SectionProfile;
  kpis: KpiCard[];
  onSelect: (id: string) => void;
}) {
  const order = KPI_ORDER[profile.id];
  const ordered = order
    .map((id) => kpis.find((k) => k.id === id))
    .filter(Boolean) as KpiCard[];
  const extras = kpis.filter((k) => k.section === profile.id && !order.includes(k.id));
  const cards = [...ordered, ...extras];

  if (!cards.length) return null;

  return (
    <section className="mb-8">
      <div className="mb-3">
        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
          {profile.eyebrow}
        </div>
        <h2 className="font-display text-lg font-semibold text-white">{profile.title}</h2>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-4">
        {cards.map((kpi) => (
          <KpiCardView key={kpi.id} kpi={kpi} onClick={() => onSelect(kpi.id)} />
        ))}
      </div>
    </section>
  );
}
