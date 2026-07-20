# Technical AI Agent Specification — SCD-FR-002

> Fill this template for each AI Agent. This document specifies **one functional requirement** (FR-002) of the Scan Chain Diagnosis Agent so it can be rebuilt exactly.

---

## 1. Document Information

| Field | Value |
|-------|-------|
| **Project** | Enterprise Scan Chain Diagnosis Agent (SCDA) |
| **Agent Name** | Suspected Failing Cell Localization Agent |
| **Requirement ID** | SCD-FR-002 |
| **Version** | v1.0 |
| **Author** | Diagnosis Engineering |
| **Reviewer** | DFT Lead |
| **Date** | 2026-07-18 |
| **Example** | Cell Localization Agent v1.0 |

---

## 2. Project Overview

**Objective:** Localize the physical scan cells most likely responsible for failures by mapping each failing flop → bit position → cell name, scoring a calibrated confidence, and attaching an ML-predicted root cause.

**Scope of this FR:** Suspected-cell localization with confidence + root cause. Confidence math is defined in FR-010 (`confidence_score.py`); FR-002 consumes it.

**Stakeholders:** PFA engineers (where to physically probe), DFT engineers.

---

## 3. Business Objective

**Problem:** A failing chain has hundreds of flops; engineers need the *specific* suspect cells, ranked by trustworthiness.

**Expected outcome:** Per-chain top suspect cells with confidence and root cause, drastically narrowing PFA scope.

**KPI:** `failing_cells` (suspected-cell count) and `avg_confidence` (FR-010 trust) both read this artifact.

---

## 4. Technical Overview

**Workflow:** parse → normalize → ML enrich → **`locate_cells.locate_failing_cells`** (position mapping + aggregation + confidence via `confidence_score`) → `export_outputs.build_fr002` → JSON.

**Technologies:** Vectorized pandas position math (two-stage float rounding for exact parity), scikit-learn GBM/logistic confidence, RandomForest root cause.

---

## 5. Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 15, React 19, TypeScript, TailwindCSS, Recharts |
| **Backend** | FastAPI, Uvicorn, Pydantic v2 |
| **LLM / ML** | scikit-learn (GradientBoosting + CalibratedClassifierCV confidence; RandomForest root cause), joblib persistence |
| **Framework** | pandas, numpy |
| **Database** | Parquet cache + JSON artifacts; model files under `data/models/` |
| **IDE** | VS Code / Cursor |
| **Deployment** | Docker (API), local Next.js |

---

## 6. Agent Responsibilities

**Responsibilities:**
- Map `fail_flop_id` → `bit_position` → `cell_name` using STIL `cell_order`.
- Aggregate observations/patterns per `(chain_id, fail_flop_id)`.
- Compute calibrated confidence and dominant fail-type/region/root-cause.
- Emit per-chain top suspect + full suspect list, filtered by `min_observations`.

**Exclusions:** Break localization (FR-006), debug coordinates (FR-009), report rendering (FR-008).

---

## 7. Functional Requirements

| Field | Value |
|-------|-------|
| **FR ID** | SCD-FR-002 |
| **Description** | Localize suspected failing scan cells with calibrated confidence and ML-predicted root cause. |
| **Priority** | High |
| **Inputs** | Failure DataFrame + chain_map (STIL/MD). Columns: `fail_flop_id`, `chain_id`, `chain`, `pattern_id`, `fail_type`, `failure_region`, `root_cause_hint`, `predicted_root_cause`, `ai_severity_score`, `lot_id`, `ir_drop_mv`, `thermal_c`, `setup_slack_ps`, `hold_slack_ps`, `shift_cycles`; STIL `scan_length`, `scan_in`, `scan_out`, `scan_master_clock`, `cell_order`. |
| **Outputs** | `SCD-FR-002_suspected_failing_cells.json` (see §11). |
| **Processing Logic** | Position mapping + groupby aggregation + confidence blend (see §18). |
| **Dependencies** | FR-001 parse pipeline, FR-003 chain_map, FR-010 `confidence_score`, `ml_pipeline` RF. Config `min_observations=2`. |

---

## 8. Non-Functional Requirements

- **Response time:** Vectorized mapping ~39× faster than row-wise `.apply`.
- **Scalability:** Thousands of suspects across 90 logs.
- **Logging:** Rotating INFO logs; model load/fallback logged.
- **Availability:** Confidence model auto-loads from `data/models/`; logistic fallback if joblib missing.

---

## 9. AI Behavior Specification

- **Role:** Localizer + calibrated confidence scorer.
- **Workflow:** deterministic position mapping → statistical evidence → ML probability blend.
- **Decision logic:** `confidence = 0.50·evidence + 0.50·GBM_P(PFA)` (sklearn) or `0.55·evidence + 0.45·ml` (logistic); root cause from RandomForest, inline KNN only if RF prediction missing.
- **Limitations:** No artificial confidence floor; low-evidence cells legitimately score low.

---

## 10. Input Specification

| Name | Type | Required | Validation |
|------|------|----------|-----------|
| `failures_df` | DataFrame | Yes | Normalized schema. |
| `chain_map` | dict | Yes | STIL `ScanStructures` or `hardware_topology.md`; provides `cell_order`, `scan_length`. |
| `min_observations` | int | No | `config.diagnosis.min_observations=2`; API range 1–20. Fallback to 1 if filter empties result. |

---

## 11. Output Specification

**Format:** JSON. **File:** `output/SCD-FR-002_suspected_failing_cells.json`.

**Top keys:** `requirement_id`, `requirement`, `acceptance_criteria`, `method`, `status`, `generated_at`, `inputs{logs_parsed, stil_file, stil_chains, min_observations}`, `summary{total_suspected_cells, chains_involved, max_confidence, mean_confidence, diagnosis_confidence, global_mean_all_suspects, confidence_definition, top_n_recorded}`, `per_chain_top_suspect[]`, `suspected_cells[]`, `top_suspected_cells[]`.

**Cell record keys:** `chain`, `instance`, `chain_id`, `suspected_cell`, `fail_flop_id`, `bit_position`, `offset_from_scan_in`, `chain_length`, `observations`, `corroborating_patterns`, `chain_observations`, `confidence`, `dominant_fail_type`, `dominant_region`, `dominant_root_cause`, `predicted_root_cause`, `mean_ai_severity`, `mean_ai_severity_level` (High≥0.8 / Medium≥0.4 / Low), `lots_affected`, `scan_in`, `scan_out`, `scan_master_clock`.

Internal (also computed): `obs_share`, `relative_dominance`, `pattern_corroboration`, `evidence_score`, `ml_confidence`, `fail_type_consistency`, `chain_pattern_count`, `mean_ir_drop`, `mean_temp`, `mean_setup_slack`, `mean_hold_slack`.

---

## 12. Business Rules

- **BR-001:** `flop_number` = first integer in `fail_flop_id`.
- **BR-002:** `chain_length = scan_length_stil.fillna(shift_cycles).fillna(234)`.
- **BR-003:** `bit_position = (flop_number-1) % chain_length`; `offset_from_scan_in = chain_length-1-bit_position`.
- **BR-004:** Report a cell only if `observations >= min_observations` (fallback 1 if empty).
- **BR-005:** No artificial confidence floor.

---

## 13. Key Engineering Rules

- Never hallucinate cell names — use STIL `cell_order` with defined fallbacks: `hierarchical_path[bp]`, `U_core/reg_c{idx}_ff[bp]`, `{chain_id}.sff_{bp:03d}`.
- Two-stage float rounding `round(round(x,10),3)` for exact parity.
- Preserve terminology (`bit_position`, `offset_from_scan_in`).
- Deterministic (`random_state=42` in models).

---

## 14. Constraints

- Chain-length fallback `234`.
- Confidence model files: `data/models/confidence_classifier.joblib` (+ `.json`); RF `root_cause_classifier.joblib`.
- `confidence_threshold=0.60` (marks low-confidence).

---

## 15. API Specification

| Field | Value |
|-------|-------|
| **Endpoint** | `GET /api/v1/kpi/failing_cells/workspace?min_observations=` |
| **Method** | GET |
| **Response** | Workspace with panel kind `cells_table` (suspected cells) |
| **Related** | `avg_confidence` KPI (FR-010) reads the same artifact |
| **Errors** | Empty result → fallback `min_observations=1`; engine error → unavailable dashboard. |

---

## 16. Database Design

- **Model store:** `data/models/confidence_classifier.joblib/.json`, `root_cause_classifier.joblib`, timestamped backups.
- **Artifact:** `output/SCD-FR-002_suspected_failing_cells.json`.
- **Cache:** Parquet failures.

---

## 17. Dashboard Integration

- **Screen:** Overview KPI `failing_cells`; AI section `avg_confidence`.
- **Action:** Drill-down → `SuspectedCellsPanel.tsx`, `JsonDataTable.tsx`; `min_observations` slider.
- **Outputs:** Ranked suspect cards + full cell table.

---

## 18. AI Workflow (Step-by-Step)

1. Resolve chain via `stil_parser.resolve_chain`; build `cell_order` (`build_cell_order`, `cell_name_at`).
2. Map each `fail_flop_id` → `bit_position` → `offset_from_scan_in` → `cell_name`.
3. Group by `(chain_id, fail_flop_id)`: `observations=size`, `corroborating_patterns=nunique(pattern_id)`, modes for fail_type/region/root_cause; `fail_type_consistency` = share matching dominant fail type (fillna 0.5).
4. Filter `observations >= min_observations`.
5. Compute evidence: `evidence = 0.40·relative_dominance + 0.25·pattern_corroboration + 0.20·obs_share + 0.15·fail_type_consistency`.
6. Blend with ML PFA probability → `confidence`; clip [0,1].
7. Attach RF `predicted_root_cause`.
8. Select per-chain top-1 + full list; serialize.

---

## 19. Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| No STIL cell_order | Missing STIL/MD | Use fallback cell-name synthesis. |
| Confidence model missing | No joblib | Logistic fallback (`0.55/0.45` blend). |
| Empty after filter | High `min_observations` | Retry with `min_observations=1`. |

---

## 20. Logging & Monitoring

- **Logs:** model load path or fallback reason; suspects localized count.
- **Metrics:** `total_suspected_cells`, `mean_confidence`, `diagnosis_confidence`.
- **Alerts:** N/A batch.

---

## 21. Security

- No auth (internal tool). Test data + PFA labels kept on local storage; models persisted locally.

---

## 22. Test Cases

| TC ID | Requirement | Steps | Expected Result | Status |
|-------|-------------|-------|-----------------|--------|
| TC-002-01 | FR-002 | Localize known flop | Correct `bit_position`, `cell_name` | Pass |
| TC-002-02 | FR-002 | `min_observations=2` filter | Sub-threshold cells excluded | Pass |
| TC-002-03 | FR-002 | Confidence in [0,1] | All confidences bounded | Pass |
| TC-002-04 | FR-002 | Model missing | Logistic fallback used, no crash | Pass |

---

## 23. Acceptance Criteria

- Each suspect maps to a deterministic `bit_position`/`cell_name`.
- Confidence is calibrated, bounded, floor-free.
- Per-chain top suspect present; `diagnosis_confidence` populated for FR-010.

---

## 24. Risks & Assumptions

- **Risk:** STIL/MD mismatch → wrong cell name; mitigation: fallback naming + parity tests.
- **Assumption:** `fail_flop_id` encodes flop index; STIL length authoritative.

---

## 25. Dependencies

- Internal: FR-001 pipeline, FR-003 chain_map, FR-010 `confidence_score`, `ml_pipeline`, `stil_parser`, `locate_cells`.
- External: scikit-learn, joblib, numpy, pandas.

---

## 26. Traceability Matrix

| FR | Module/Function | Artifact | TC | AC |
|----|-----------------|----------|----|----|
| SCD-FR-002 | `locate_cells.locate_failing_cells`, `export_outputs.build_fr002` | `SCD-FR-002_suspected_failing_cells.json` | TC-002-01..04 | §23 |

---

## 27. Reviewer Checklist

- [ ] Position mapping matches STIL cell order.
- [ ] Confidence bounded and unfloored.
- [ ] Root cause attached from RF.
- [ ] `min_observations` behavior correct incl. fallback.

---

## 28. Approval

| Approver | Date | Remarks |
|----------|------|---------|
| DFT Lead | | |
| PFA Engineering | | |
