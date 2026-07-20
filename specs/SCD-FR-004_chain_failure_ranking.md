# Technical AI Agent Specification — SCD-FR-004

> Fill this template for each AI Agent. This document specifies **one functional requirement** (FR-004) of the Scan Chain Diagnosis Agent so it can be rebuilt exactly.

---

## 1. Document Information

| Field | Value |
|-------|-------|
| **Project** | Enterprise Scan Chain Diagnosis Agent (SCDA) |
| **Agent Name** | Chain Failure Ranking Agent |
| **Requirement ID** | SCD-FR-004 |
| **Version** | v1.0 |
| **Author** | Diagnosis Engineering |
| **Reviewer** | DFT Lead |
| **Date** | 2026-07-18 |
| **Example** | Chain Ranking Agent v1.0 |

---

## 2. Project Overview

**Objective:** Rank scan chains by failure frequency with Pareto (80/20) cumulative coverage to focus debug effort.

**Scope of this FR:** Deterministic ranking using `pandas.Series.rank(method="dense")` and cumulative percentage.

**Stakeholders:** DFT / yield engineers prioritizing debug.

---

## 3. Business Objective

**Problem:** Engineers need to know the vital-few chains that cause most failures.

**Expected outcome:** Ordered ranking + count of chains covering 80% of failures.

**KPI:** `ranked_chains` and `top_failing_chain` (engineering section).

---

## 4. Technical Overview

**Workflow:** parse → normalize → **`chain_ranking.rank_chains_by_frequency`** → `export_outputs.build_fr004` → JSON.

**Technologies:** pandas native ranking, cumulative sum for Pareto.

---

## 5. Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 15, React 19, TypeScript, Recharts |
| **Backend** | FastAPI, Uvicorn, Pydantic v2 |
| **LLM / ML** | None |
| **Framework** | pandas, numpy |
| **Database** | Parquet cache, JSON artifacts |
| **IDE** | VS Code / Cursor |
| **Deployment** | Docker (API), local Next.js |

---

## 6. Agent Responsibilities

**Responsibilities:**
- Count failures per chain, compute fail %, cumulative %, and dense rank.
- Identify top chain and number of chains covering 80% of failures.

**Exclusions:** Cell/break analysis; correlation.

---

## 7. Functional Requirements

| Field | Value |
|-------|-------|
| **FR ID** | SCD-FR-004 |
| **Description** | Rank scan chains by failure frequency using `pandas.Series.rank` with Pareto cumulative coverage. |
| **Priority** | Medium-High |
| **Inputs** | Failure DataFrame + paths. Columns: `chain`, `lot_id`, `chain_id`. |
| **Outputs** | `SCD-FR-004_chain_failure_ranking.json` (see §11). |
| **Processing Logic** | groupby size → fail %, dense rank, cumulative % (see §18). |
| **Dependencies** | FR-001 parse pipeline; pandas. |

---

## 8. Non-Functional Requirements

- **Response time:** Sub-second aggregation.
- **Scalability:** Handles all chains in loaded logs.
- **Logging:** INFO; ranking method recorded in artifact.
- **Availability:** Deterministic recompute.

---

## 9. AI Behavior Specification

- **Role:** Deterministic ranker.
- **Workflow:** count → percent → rank → cumulate.
- **Decision logic:** `Series.rank(method="dense", ascending=False)`; sort `[rank, fail_count, chain]`.
- **Limitations:** Frequency-based only (not severity-weighted).

---

## 10. Input Specification

| Name | Type | Required | Validation |
|------|------|----------|-----------|
| `failures_df` | DataFrame | Yes | Normalized schema; needs `chain`. |
| `paths` | list[Path] | Yes | For `logs_parsed` input metadata. |

---

## 11. Output Specification

**Format:** JSON. **File:** `output/SCD-FR-004_chain_failure_ranking.json`.

**Top keys:** `requirement_id`, `requirement`, `acceptance_criteria`, `status`, `generated_at`, `inputs{logs_parsed, lots}`, `ranking_feature`, `summary`, `ranking[]`.

**`ranking_feature`:** `{api:"pandas.Series.rank", default_method:"dense", methods{}, options{}, fr004_usage{column_ranked:"fail_count", method:"dense", ascending:false, pct:false, meaning}}`.

**`summary`:** `total_fail_records`, `distinct_failing_chains`, `top_chain`, `top_chain_fail_count`, `chains_covering_80pct`, `rank_method`.

**`ranking[]` item:** `rank`, `chain`, `fail_count`, `fail_pct`, `cumulative_pct`, `rank_method`.

`rank_chains_by_frequency` returns DataFrame cols: `chain`, `fail_count`, `fail_pct`, `cumulative_pct`, `rank`, `rank_method`.

---

## 12. Business Rules

- **BR-001:** `fail_pct = fail_count / total × 100` (3 dp).
- **BR-002:** Rank via dense method, descending.
- **BR-003:** `chains_covering_80pct = (cumulative_pct <= 80.0).sum()` (min 1 if any).
- **BR-004:** Sort tie-break `[rank, fail_count, chain]`.

---

## 13. Key Engineering Rules

- Never invent counts — from parsed records only.
- Preserve terminology; document ranking API in output.
- Deterministic ordering.

---

## 14. Constraints

- Frequency ranking only; severity ranking is out of scope.
- Reflects loaded subset when `max_per_lot` set.

---

## 15. API Specification

| Field | Value |
|-------|-------|
| **Endpoints** | `GET /api/v1/kpi/ranked_chains/workspace`, `GET /api/v1/kpi/top_failing_chain/workspace` |
| **Method** | GET |
| **Response** | Panel kind `ranking_table` |
| **Errors** | Empty ranking when no FAILs. |

---

## 16. Database Design

- Parquet cache; artifact `output/SCD-FR-004_chain_failure_ranking.json`.

---

## 17. Dashboard Integration

- **Screen:** Engineering KPIs `ranked_chains`, `top_failing_chain`.
- **Action:** Drill-down → `RankingBarChart.tsx`.
- **Outputs:** Ranked bar chart + cumulative Pareto.

---

## 18. AI Workflow (Step-by-Step)

1. `groupby("chain").size()` → `fail_count`.
2. `fail_pct = fail_count/total×100`.
3. `rank = Series.rank(method="dense", ascending=False)`.
4. Sort `[rank, fail_count, chain]`; `cumulative_pct = fail_pct.cumsum()`.
5. Pareto: count chains where `cumulative_pct <= 80`.
6. Serialize with `ranking_feature` metadata.

---

## 19. Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| Empty DataFrame | No FAILs | Empty ranking, `status` reflects it. |
| Missing `chain` | Bad schema | `normalize_failure_schema` alias-maps. |

---

## 20. Logging & Monitoring

- **Logs:** INFO ranking summary.
- **Metrics:** `top_chain`, `chains_covering_80pct`.
- **Alerts:** N/A.

---

## 21. Security

- No auth; local data only.

---

## 22. Test Cases

| TC ID | Requirement | Steps | Expected Result | Status |
|-------|-------------|-------|-----------------|--------|
| TC-004-01 | FR-004 | Rank fixture | Descending dense ranks | Pass |
| TC-004-02 | FR-004 | Pareto | `chains_covering_80pct` correct | Pass |
| TC-004-03 | FR-004 | Cumulative | `cumulative_pct` monotonic to ~100 | Pass |

---

## 23. Acceptance Criteria

- Ranks dense + descending; top chain correct.
- Cumulative % monotonic; Pareto count valid.
- `ranking_feature` documents the API used.

---

## 24. Risks & Assumptions

- **Risk:** Frequency ≠ severity; mitigation: FR-005/FR-010 add context.
- **Assumption:** Fail counts are comparable across chains.

---

## 25. Dependencies

- Internal: FR-001 pipeline, `chain_ranking`.
- External: pandas.

---

## 26. Traceability Matrix

| FR | Module/Function | Artifact | TC | AC |
|----|-----------------|----------|----|----|
| SCD-FR-004 | `chain_ranking.rank_chains_by_frequency`, `export_outputs.build_fr004` | `SCD-FR-004_chain_failure_ranking.json` | TC-004-01..03 | §23 |

---

## 27. Reviewer Checklist

- [ ] Ranking deterministic + descending.
- [ ] Pareto count correct.
- [ ] Cumulative % consistent.

---

## 28. Approval

| Approver | Date | Remarks |
|----------|------|---------|
| DFT Lead | | |
| Yield Engineering | | |
