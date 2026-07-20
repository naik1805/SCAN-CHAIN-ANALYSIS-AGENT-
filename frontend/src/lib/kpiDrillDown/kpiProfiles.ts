import type { KpiSection } from "./diagnosisTypes";

export interface SectionProfile {
  id: KpiSection;
  title: string;
  eyebrow: string;
}

export const SECTION_PROFILES: SectionProfile[] = [
  {
    id: "overview",
    title: "Diagnosis Overview",
    eyebrow: "Detection & Identification",
  },
  {
    id: "engineering",
    title: "Engineering Analysis",
    eyebrow: "Topology & Ranking",
  },
  {
    id: "ai",
    title: "AI Diagnosis",
    eyebrow: "Reports · Confidence · Debug",
  },
];

export const KPI_ORDER: Record<KpiSection, string[]> = {
  overview: ["failing_chains", "failing_cells", "chain_breaks", "shift_capture"],
  engineering: [
    "topology_chains",
    "ranked_chains",
    "failure_correlations",
    "top_failing_chain",
  ],
  ai: ["diagnosis_reports", "debug_locations", "avg_confidence", "pending_reviews"],
};
