# Technical AI Agent Specification — SCD-FR-005

> Fill this template for each AI Agent. This document specifies **one functional requirement** (FR-005) of the Scan Chain Diagnosis Agent so it can be rebuilt exactly.

---

## 1. Document Information

| Field | Value |
|-------|-------|
| **Project** | Enterprise Scan Chain Diagnosis Agent (SCDA) |
| **Agent Name** | Failure Correlation Agent |
| **Requirement ID** | SCD-FR-005 |
| **Version** | v1.0 |
| **Author** | Diagnosis Engineering |
| **Reviewer** | DFT Lead |
| **Date** | 2026-07-18 |
| **Example** | Failure Correlation Agent v1.0 |

---

## 2. Project Overview

**Objective:** Quantify how each scan chain's failures correlate with physical/timing, scan-load, spatial, and topology variables (Pearson), plus categorical signature profiles and chain-vs-population comparisons.

**Scope of this FR:** Per-chain correlation + distinguishing factors + signature bullets.

**Stakeholders:** DFT / device physics / yield engineers.

---

## 3. Business Objective

**Problem:** Engineers need to know *why* a chain fails — is it IR drop, thermal, setup/hold slack, spatial location, or compression channel?

**Expected outcome:** A per-chain "signature" identifying the primary physical driver and how it deviates from the population.

**KPI:** `failure_correlations` (engineering section).

---

## 4. Technical Overview

**Workflow:** parse → normalize → enrich with topology → **`correlation_analysis.build_correlation_rows`** → `export_outputs.build_fr005` → JSON.

**Technologies:** pandas Pearson correlation, z-score dominant-driver detection.

---

## 5. Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 15, React 19, TypeScript, Recharts |
| **Backend** | FastAPI, Uvicorn, Pydantic v2 |
| **LLM / ML** | None (statistics) |
| **Framework** | pandas, numpy |
| **Database** | Parquet cache, JSON artifacts |
| **IDE** | VS Code / Cursor |
| **Deployment** | Docker (API), local Next.js |

---

## 6. Agent Responsibilities

**Responsibilities:**
- Compute per-chain Pearson `r` for physical/timing, scan-load, spatial, topology features.
- Determine primary drivers (max |z-score| vs population).
- Build categorical distribution profiles, metric comparisons, distinguishing factors, signature bullets.

**Exclusions:** Ranking (FR-004), localization (FR-002).

---

## 7. Functional Requirements

| Field | Value |
|-------|-------|
| **FR ID** | SCD-FR-005 |
| **Description** | Per-chain Pearson correlations + categorical signature profiles + chain-vs-population comparisons. |
| **Priority** | Medium |
| **Inputs** | Failure DataFrame + chain_map. Feature groups: `PHYSICAL_TIMING_COLS=[ir_drop_mv, thermal_c, setup_slack_ps, hold_slack_ps, ai_severity_score]`, `SCAN_LOAD_COLS=[shift_cycles, capture_cycles, scan_fail_count, transition_faults, test_time_ms]`, `SPATIAL_COLS=[die_row, die_col, wafer_x, wafer_y]`, `TOPOLOGY_NUMERIC_COLS=[scan_length, instance_type_code, compression_channel_count]`. Region priority `[failure_region, die_label, die_row, defect_type]`. |
| **Outputs** | `SCD-FR-005_failure_correlation.json` (see §11). |
| **Processing Logic** | Binary `is_chain` Pearson + z-score driver + buckets (see §18). |
| **Dependencies** | FR-001 pipeline, FR-003 chain_map + `topology_analysis`; numpy, pandas. |

---

## 8. Non-Functional Requirements

- **Response time:** Sub-second to few seconds across chains × features.
- **Scalability:** All chains × ~17 numeric features.
- **Logging:** INFO; region/root-cause field chosen recorded.
- **Availability:** Handles missing feature columns gracefully (0.0 r).

---

## 9. AI Behavior Specification

- **Role:** Deterministic statistical correlator.
- **Workflow:** per-chain binary membership → Pearson → driver ranking → categorical profiles.
- **Decision logic:** `r = is_chain.corr(numeric_col)` (4 dp; 0.0 if constant); dominant driver = max |z|; summary strength `strong` if `max_abs_r≥0.3`, `moderate` if `≥0.1`, else `weak`.
- **Limitations:** Correlation ≠ causation; small samples may be noisy.

---

## 10. Input Specification

| Name | Type | Required | Validation |
|------|------|----------|-----------|
| `failures_df` | DataFrame | Yes | Normalized; numeric feature cols coerced. |
| `chain_map` | dict | Yes | Enables topology enrichment (`enrich_failures_with_topology`). |

---

## 11. Output Specification

**Format:** JSON. **File:** `output/SCD-FR-005_failure_correlation.json`.

**Top keys:** `requirement_id`, `requirement`, `acceptance_criteria`, `status`, `generated_at`, `inputs{logs_parsed, total_fail_records}`, `correlations[]`, `region_field_used`, `root_cause_field_used`, `numerical_features`, `correlation_feature_count`, `chains_analyzed`, `physical_features`, `scan_load_features`, `spatial_features`, `topology_fields`, `topology_available`, `compression_summary`, `summary`.

**`correlations[]` item:** `chain`, `failure_count`, `pearson_correlations{}`, `spatial_correlations{}`, `topology_correlations{}`, `primary_physical_driver`, `primary_spatial_driver`, `primary_scan_load_driver`, `primary_topology_driver`, `primary_driver`, `physical_timing_percentages{}`, `spatial_percentages{}`, `correlation_driver_percentages{}`, `correlation_group_percentages{}`, `chain_averages{}`, `topology_profile{}`, `metric_comparisons[]`, `distinguishing_factors[]`, `signature_bullets[]`.

---

## 12. Business Rules

- **BR-001:** Pearson `r` rounded 4 dp; constant column ⇒ `r=0.0`.
- **BR-002:** Timing stress buckets from setup/hold slack signs (Setup / Hold / Setup+Hold Stress / Within Spec).
- **BR-003:** Dominant driver = max |z-score| vs population mean/std.
- **BR-004:** Summary strength thresholds `0.3` / `0.1`.

---

## 13. Key Engineering Rules

- Never fabricate correlations — computed from real numeric columns.
- Preserve metric terminology (IR drop, slack, wafer X/Y).
- Deterministic; report which region/root-cause field was used.

---

## 14. Constraints

- Requires ≥2 numeric points per chain for meaningful `r`.
- Topology correlations only when topology available.

---

## 15. API Specification

| Field | Value |
|-------|-------|
| **Endpoint** | `GET /api/v1/kpi/failure_correlations/workspace` |
| **Method** | GET |
| **Response** | Panels `chain_signature_profile`, `chain_signature_overview` |
| **Errors** | Empty correlations if no numeric features. |

---

## 16. Database Design

- Parquet cache; artifact `output/SCD-FR-005_failure_correlation.json`.

---

## 17. Dashboard Integration

- **Screen:** Engineering KPI `failure_correlations`.
- **Action:** Drill-down → `ChainSignaturePanel.tsx`, `FailureCorrelationPanel.tsx`, `CorrelationHeatmap.tsx`, `EngineeringTables.tsx`.
- **Outputs:** Chain selector, primary driver cards, distribution charts, signature bullets.

---

## 18. AI Workflow (Step-by-Step)

1. Enrich failures with topology (`enrich_failures_with_topology`).
2. For each chain: build binary `is_chain` series.
3. Pearson `r = is_chain.corr(to_numeric(col))` for each feature group.
4. Compute timing stress buckets; categorical percentages; driver percentages.
5. Dominant driver via max |z-score|; `build_metric_comparisons` (pct_diff, direction); `build_distinguishing_factors`; `build_signature_bullets`/`build_signature_summary`.
6. Assemble summary strength + serialize.

---

## 19. Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| Constant column | No variance | `r=0.0`. |
| Missing feature | Column absent | Skip; note available features. |
| No topology | Missing chain_map fields | `topology_available=false`. |

---

## 20. Logging & Monitoring

- **Logs:** chosen region/root-cause field, chains analyzed.
- **Metrics:** `correlation_feature_count`, summary strength.
- **Alerts:** N/A.

---

## 21. Security

- No auth; local data only.

---

## 22. Test Cases

| TC ID | Requirement | Steps | Expected Result | Status |
|-------|-------------|-------|-----------------|--------|
| TC-005-01 | FR-005 | Correlate fixture | `pearson_correlations` populated | Pass |
| TC-005-02 | FR-005 | Constant col | `r == 0.0` | Pass |
| TC-005-03 | FR-005 | Driver detection | Primary driver = max \|z\| | Pass |

---

## 23. Acceptance Criteria

- Each chain has correlation dict + primary driver.
- Constant columns handled (0.0).
- Signature bullets and comparisons present.

---

## 24. Risks & Assumptions

- **Risk:** Correlation misread as causation; mitigation: labeled drivers + comparisons.
- **Assumption:** Numeric features are physically meaningful.

---

## 25. Dependencies

- Internal: FR-001 pipeline, FR-003 topology, `correlation_analysis`.
- External: numpy, pandas.

---

## 26. Traceability Matrix

| FR | Module/Function | Artifact | TC | AC |
|----|-----------------|----------|----|----|
| SCD-FR-005 | `correlation_analysis.build_correlation_rows`, `export_outputs.build_fr005` | `SCD-FR-005_failure_correlation.json` | TC-005-01..03 | §23 |

---

## 27. Reviewer Checklist

- [ ] Pearson computed per chain.
- [ ] Constant-column guard works.
- [ ] Primary driver logic correct.
- [ ] Signature/comparison fields present.

---

## 28. Approval

| Approver | Date | Remarks |
|----------|------|---------|
| DFT Lead | | |
| Device Physics | | |
