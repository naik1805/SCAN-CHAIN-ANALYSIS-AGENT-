# Technical AI Agent Specification — SCD-FR-010

> Fill this template for each AI Agent. This document specifies **one functional requirement** (FR-010) of the Scan Chain Diagnosis Agent so it can be rebuilt exactly.

---

## 1. Document Information

| Field | Value |
|-------|-------|
| **Project** | Enterprise Scan Chain Diagnosis Agent (SCDA) |
| **Agent Name** | Diagnosis Confidence Scoring Agent |
| **Requirement ID** | SCD-FR-010 |
| **Version** | v1.0 |
| **Author** | Diagnosis Engineering |
| **Reviewer** | DFT Lead |
| **Date** | 2026-07-18 |
| **Example** | Diagnosis Confidence Agent v1.0 |

---

## 2. Project Overview

**Objective:** Provide a calibrated per-cell confidence and an overall dashboard trust KPI (fail-weighted mean of per-chain top-1 confidence). No separate artifact — reuses FR-002 output.

**Scope of this FR:** The confidence math (`confidence_score.py`) consumed by FR-002/FR-009 and the `avg_confidence` KPI. Includes the PFA-trained ML model + auto-retrain lifecycle.

**Stakeholders:** DFT / PFA engineers deciding whether to act on a lead.

---

## 3. Business Objective

**Problem:** Engineers need a trustworthy, non-inflated confidence — high only when evidence is strong.

**Expected outcome:** A calibrated confidence with a headline "actionable trust" %, backed by PFA-confirmed labels.

**KPI:** `avg_confidence` — "Diagnosis Confidence (SCD-FR-010)"; headline `overall_confidence_pct` + `trust_label` (High/Moderate/Low).

---

## 4. Technical Overview

**Workflow:** FR-002 suspects → **`confidence_score.compute_evidence_scores` + `_ml_probabilities`** → blended `confidence` → `aggregate_diagnosis_confidence` → dashboard KPI. Auto-retrain via `model_lifecycle` on accumulated PFA/engineer feedback.

**Technologies:** scikit-learn GradientBoosting + isotonic CalibratedClassifierCV; logistic fallback; joblib persistence.

---

## 5. Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 15, React 19, TypeScript, Recharts (gauge) |
| **Backend** | FastAPI (dashboard, reviews, retrain endpoints), Uvicorn |
| **LLM / ML** | scikit-learn (`GradientBoostingClassifier`, `CalibratedClassifierCV`, `StandardScaler`, `Pipeline`), joblib |
| **Framework** | pandas, numpy |
| **Database** | `data/historical_pfa_accuracy.json` (training), model store `data/models/`, review/lifecycle JSON in `data/cache/` |
| **IDE** | VS Code / Cursor |
| **Deployment** | Docker (API), local Next.js |

---

## 6. Agent Responsibilities

**Responsibilities:**
- Compute evidence sub-scores + calibrated ML PFA probability; blend into `confidence`.
- Aggregate an overall fail-weighted trust score for the dashboard.
- Train/persist/reload the confidence model; auto-retrain on feedback threshold.

**Exclusions:** Position mapping (FR-002), coordinate export (FR-009).

---

## 7. Functional Requirements

| Field | Value |
|-------|-------|
| **FR ID** | SCD-FR-010 |
| **Description** | Calibrated per-cell diagnosis confidence + overall dashboard trust KPI, trained on PFA-confirmed labels with auto-retrain. |
| **Priority** | High |
| **Inputs** | Suspect DataFrame (`observations`, `chain_observations`, `corroborating_patterns`, `chain_pattern_count`, `fail_type_consistency`, `offset_from_scan_in`, `chain_length`, `predicted_root_cause`). Training: `data/historical_pfa_accuracy.json`. |
| **Outputs** | Adds `evidence_score`, `ml_confidence`, `confidence` columns; `aggregate_diagnosis_confidence` dict; dashboard `overall_confidence_pct` + `trust_label`. |
| **Processing Logic** | Evidence weights + ML blend + fail-weighted aggregate (see §18). |
| **Dependencies** | FR-002 suspects; scikit-learn, joblib, numpy, pandas. Config `confidence_threshold=0.60`, `production.retrain_feedback_threshold=25`. |

---

## 8. Non-Functional Requirements

- **Response time:** Model load + score sub-second (cached joblib).
- **Scalability:** Scores all suspects; aggregate is per-chain top-1.
- **Logging:** INFO; model load path, fallback, retrain steps + backups.
- **Availability:** Logistic fallback if joblib absent; timestamped model backups.

---

## 9. AI Behavior Specification

- **Role:** Calibrated trust scorer + lifecycle manager.
- **Workflow:** evidence → ML probability → blend → aggregate → (retrain when feedback ≥ threshold).
- **Decision logic:** `evidence = 0.40·relative_dominance + 0.25·pattern_corroboration + 0.20·obs_share + 0.15·fail_type_consistency`; sklearn blend `0.50/0.50`, logistic `0.55/0.45`; `RC_STABILITY_PRIOR={SHIFT:0.75, SETUP:0.70, HOLD:0.55, DEFECT:0.65}`. Trust labels: High≥0.75, Moderate≥0.50, else Low.
- **Limitations:** No artificial floor; overall reflects actionable (per-chain top-1) leads, not all suspects.

---

## 10. Input Specification

| Name | Type | Required | Validation |
|------|------|----------|-----------|
| `suspects_df` | DataFrame | Yes | Needs evidence feature columns. |
| PFA training JSON | file | No | `data/historical_pfa_accuracy.json`; fields incl. `pattern_consistency`, `pattern_count`, `chain_length`, `root_cause_type`, `pfa_confirmed`. |
| feedback store | JSON | No | Engineer confirm/reject rows drive retrain. |

`FEATURE_COLS = [pattern_consistency, offset_ratio, log_pattern_count, relative_dominance, pattern_corroboration, obs_share, fail_type_consistency, rc_SHIFT, rc_SETUP, rc_HOLD, rc_DEFECT]`.

---

## 11. Output Specification

- **Suspect columns added:** `obs_share`, `relative_dominance`, `pattern_corroboration`, `fail_type_consistency`, `evidence_score`, `ml_confidence`, `confidence`.
- **`aggregate_diagnosis_confidence` returns:** `{mean_suspect_confidence, per_chain_top_mean, global_mean_all_suspects, max_confidence, top_k, confidence_definition}`.
- **Surfaced in:** FR-002 JSON `summary.diagnosis_confidence` / `global_mean_all_suspects`; dashboard `avg_confidence` KPI (`overall_confidence_pct`, `trust_label`).
- **Model files:** `data/models/confidence_classifier.joblib` + `.json`.

---

## 12. Business Rules

- **BR-001:** Evidence weights `0.40 / 0.25 / 0.20 / 0.15`.
- **BR-002:** Blend `0.50/0.50` (sklearn) or `0.55/0.45` (logistic).
- **BR-003:** Overall KPI = fail-weighted mean of per-chain top-1 confidence (weights = `chain_observations`).
- **BR-004:** Headline "actionable" trust weights `{ml_root_cause:0.35, ml_cell_confidence:0.35, logic_cell_localization:0.20, logic_cell_evidence:0.10}`.
- **BR-005:** Auto-retrain when engineer/PFA feedback ≥ `retrain_feedback_threshold` (25).

---

## 13. Key Engineering Rules

- Never inflate confidence — no artificial floor; calibrated probabilities only.
- Deterministic (`random_state=42`); back up model before retrain.
- Preserve terminology (PFA = Physical Failure Analysis, evidence vs ML).

---

## 14. Constraints

- Calibration when `len(y)>=30` (isotonic, cv=5); else logistic fallback.
- GBM: `n_estimators=300, max_depth=4, learning_rate=0.05, min_samples_leaf=8, subsample=0.85, random_state=42`.
- `confidence_threshold=0.60` marks low-confidence.

---

## 15. API Specification

| Field | Value |
|-------|-------|
| **Endpoint** | `GET /api/v1/kpi/avg_confidence/workspace?min_observations=` |
| **Related** | `GET /api/v1/diagnosis/production/validation`, `GET/POST /api/v1/diagnosis/reviews`, `POST /api/v1/diagnosis/models/retrain`, `GET /api/v1/diagnosis/production/fingerprint` |
| **Method** | GET / POST |
| **Response** | Panel kind `diagnosis_confidence` with `overall_confidence_pct`, `trust_label`, ml/logic category scores, model validation |
| **Errors** | Missing model → logistic fallback; validation error → `readiness_grade="unknown"`. |

---

## 16. Database Design

- **Training:** `data/historical_pfa_accuracy.json` + merged engineer feedback (`pfa_train_merged.json`).
- **Models:** `confidence_classifier.joblib/.json` + timestamped backups; `root_cause_classifier.joblib`.
- **Lifecycle/reviews:** `data/cache/model_lifecycle.json`, `review_queue.json`, `engineer_feedback.json`.

---

## 17. Dashboard Integration

- **Screen:** AI section KPI `avg_confidence` ("Diagnosis Confidence (SCD-FR-010)").
- **Action:** Drill-down → `DiagnosisConfidencePanel.tsx`, `ConfidenceGauge.tsx`; `MlStatusBanner.tsx` for model status.
- **Outputs:** Overall trust gauge, per-module ML vs logic scores, validation metrics.

---

## 18. AI Workflow (Step-by-Step)

1. `compute_evidence_scores` → sub-scores + `evidence_score`.
2. `_ml_probabilities` → GBM/calibrated (or logistic) P(PFA-confirmed) → `ml_confidence`.
3. Blend → `confidence` (clip [0,1]).
4. `aggregate_diagnosis_confidence` → per-chain top-1, fail-weighted overall + global means.
5. Compute headline actionable trust (weighted ML + logic modules) → `overall_confidence_pct`, `trust_label`.
6. Lifecycle: when feedback ≥ threshold, back up + retrain GBM (and RF), persist, stamp lifecycle state.

---

## 19. Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| Model file missing | No joblib | Logistic fallback (`_default_logistic_model`). |
| Too few labels | `len(y)<30` | Skip calibration; logistic. |
| Retrain failure | Training error | Keep prior model, log `gbm_failed`/`rf_failed`. |
| Validation error | Holdout fails | `readiness_grade="unknown"`. |

---

## 20. Logging & Monitoring

- **Logs:** model load/fallback, retrain steps + backup filenames, feedback count.
- **Metrics:** `overall_confidence_pct`, `trust_label`, GBM `n_train`/`positive_rate`, RF `cv_accuracy`.
- **Alerts:** N/A (batch); lifecycle state persisted.

---

## 21. Security

- No auth. PFA labels + models on local/volume storage; models are internal artifacts.

---

## 22. Test Cases

| TC ID | Requirement | Steps | Expected Result | Status |
|-------|-------------|-------|-----------------|--------|
| TC-010-01 | FR-010 | Score suspects | `confidence` in [0,1], no floor | Pass |
| TC-010-02 | FR-010 | Model missing | Logistic fallback, no crash | Pass |
| TC-010-03 | FR-010 | Feedback ≥ 25 | Auto-retrain triggers, backup written | Pass |
| TC-010-04 | FR-010 | Aggregate | Overall = fail-weighted per-chain top-1 | Pass |

---

## 23. Acceptance Criteria

- Confidence calibrated, bounded, floor-free.
- Overall KPI reflects actionable per-chain leads with High/Moderate/Low label.
- Retrain lifecycle backs up and persists models on feedback threshold.

---

## 24. Risks & Assumptions

- **Risk:** Sparse PFA labels weaken calibration; mitigation: logistic fallback + threshold-gated retrain.
- **Assumption:** PFA-confirmed labels are ground truth for training.

---

## 25. Dependencies

- Internal: FR-002 suspects, `confidence_score`, `model_lifecycle`, `review_queue`, `holdout_validation`.
- External: scikit-learn, joblib, numpy, pandas.

---

## 26. Traceability Matrix

| FR | Module/Function | Artifact | TC | AC |
|----|-----------------|----------|----|----|
| SCD-FR-010 | `confidence_score.*` (`compute_evidence_scores`, `aggregate_diagnosis_confidence`, `train_confidence_model`), `model_lifecycle.maybe_retrain` | (no own artifact; uses `SCD-FR-002_suspected_failing_cells.json`) | TC-010-01..04 | §23 |

---

## 27. Reviewer Checklist

- [ ] Evidence weights + blend match spec.
- [ ] No artificial floor; bounded confidence.
- [ ] Overall = fail-weighted per-chain top-1.
- [ ] Retrain backs up + persists; fallback works.

---

## 28. Approval

| Approver | Date | Remarks |
|----------|------|---------|
| DFT Lead | | |
| ML/Data Engineering | | |
