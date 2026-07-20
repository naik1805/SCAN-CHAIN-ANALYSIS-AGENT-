"""test_confidence_score.py — Unit tests for ML confidence scoring model (SCD-FR-010)."""

from __future__ import annotations

import sys
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from confidence_score import (
    LogisticRegressionModel,
    train_confidence_model,
    load_confidence_model,
    predict_diagnosis_confidence,
    aggregate_diagnosis_confidence,
    compute_evidence_scores,
    CONFIDENCE_DEFINITION,
)


class TestLogisticRegressionModel:
    def test_fit_and_predict_probability(self):
        X = np.array([
            [1.0, 0.5],
            [1.5, 0.2],
            [2.0, 0.1],
            [-1.0, 0.5],
            [-1.5, 0.8],
            [-2.0, 0.9],
        ])
        y = np.array([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])

        model = LogisticRegressionModel(n_features=2)
        model.fit(X, y, epochs=100, lr=0.5)

        probs = model.predict_proba(X)
        assert len(probs) == 6
        assert (probs >= 0.0).all()
        assert (probs <= 1.0).all()
        assert probs[0] > 0.5
        assert probs[5] < 0.5


class TestConfidenceScorePipeline:
    def test_load_confidence_model_returns_dict(self):
        model_data = load_confidence_model()
        assert isinstance(model_data, dict)
        assert "feature_cols" in model_data
        is_sklearn = model_data.get("model_type", "").startswith("sklearn")
        is_logistic = "weights" in model_data and "bias" in model_data
        assert is_sklearn or is_logistic
        if is_sklearn:
            assert "estimator" in model_data

    def test_predict_diagnosis_confidence_updates_column(self):
        suspects_data = [
            {
                "chain": "channel1",
                "chain_id": "channel1",
                "instance": "U_core",
                "cell_name": "cell_1",
                "fail_flop_id": "FF_1",
                "offset_from_scan_in": 10,
                "chain_length": 234,
                "observations": 5,
                "corroborating_patterns": 5,
                "chain_observations": 100,
                "chain_pattern_count": 20,
                "fail_type_consistency": 0.9,
                "predicted_root_cause": "CAPTURE_TIMING_SETUP",
            },
            {
                "chain": "channel2",
                "chain_id": "channel2",
                "instance": "U_core",
                "cell_name": "cell_2",
                "fail_flop_id": "FF_2",
                "offset_from_scan_in": 200,
                "chain_length": 234,
                "observations": 1,
                "corroborating_patterns": 1,
                "chain_observations": 100,
                "chain_pattern_count": 40,
                "fail_type_consistency": 0.4,
                "predicted_root_cause": "CAPTURE_TIMING_HOLD",
            },
        ]
        suspects_df = pd.DataFrame(suspects_data)
        model_data = load_confidence_model()

        result_df = predict_diagnosis_confidence(suspects_df, model_data)
        assert "confidence" in result_df.columns
        assert len(result_df) == 2
        assert (result_df["confidence"] >= 0.0).all()
        assert (result_df["confidence"] <= 1.0).all()
        assert result_df["confidence"].iloc[0] > result_df["confidence"].iloc[1]

    def test_strong_corroboration_scores_high(self):
        """Dominant, multi-pattern, consistent cell should land well above dilute ~0.2."""
        df = pd.DataFrame([
            {
                "chain_id": "chA",
                "offset_from_scan_in": 20,
                "chain_length": 234,
                "observations": 40,
                "corroborating_patterns": 12,
                "chain_observations": 50,
                "chain_pattern_count": 14,
                "fail_type_consistency": 0.95,
                "predicted_root_cause": "SCAN_SHIFT",
            },
            {
                "chain_id": "chA",
                "offset_from_scan_in": 100,
                "chain_length": 234,
                "observations": 5,
                "corroborating_patterns": 2,
                "chain_observations": 50,
                "chain_pattern_count": 14,
                "fail_type_consistency": 0.5,
                "predicted_root_cause": "CAPTURE_TIMING_HOLD",
            },
            {
                "chain_id": "chA",
                "offset_from_scan_in": 180,
                "chain_length": 234,
                "observations": 5,
                "corroborating_patterns": 1,
                "chain_observations": 50,
                "chain_pattern_count": 14,
                "fail_type_consistency": 0.4,
                "predicted_root_cause": "UNKNOWN",
            },
        ])
        model_data = load_confidence_model()
        result = predict_diagnosis_confidence(df, model_data)
        top = float(result["confidence"].iloc[0])
        weak = float(result["confidence"].iloc[2])
        assert top >= 0.70, f"strong cell confidence {top} expected >= 0.70"
        assert weak < top
        assert weak < 0.55
        # No artificial floor: a weak cell can still be below 0.5
        assert weak < 0.70

    def test_evidence_only_fallback_without_model(self):
        df = pd.DataFrame([
            {
                "chain_id": "c1",
                "observations": 10,
                "corroborating_patterns": 8,
                "chain_observations": 12,
                "chain_pattern_count": 9,
                "fail_type_consistency": 1.0,
                "offset_from_scan_in": 5,
                "chain_length": 100,
            }
        ])
        result = predict_diagnosis_confidence(df, None)
        assert result["confidence"].iloc[0] >= 0.75

    def test_aggregate_uses_per_chain_top_not_global_mean(self):
        df = pd.DataFrame([
            {"chain_id": "c1", "confidence": 0.90, "chain_observations": 100},
            {"chain_id": "c1", "confidence": 0.20, "chain_observations": 100},
            {"chain_id": "c1", "confidence": 0.10, "chain_observations": 100},
            {"chain_id": "c2", "confidence": 0.80, "chain_observations": 50},
            {"chain_id": "c2", "confidence": 0.15, "chain_observations": 50},
        ])
        agg = aggregate_diagnosis_confidence(df, top_k=1)
        assert agg["mean_suspect_confidence"] is not None
        # Fail-weighted: (0.90*100 + 0.80*50) / 150 = 0.8667
        assert abs(agg["mean_suspect_confidence"] - (0.9 * 100 + 0.8 * 50) / 150) < 1e-3
        assert agg["global_mean_all_suspects"] < agg["mean_suspect_confidence"]
        assert "relative_dominance" in CONFIDENCE_DEFINITION or "evidence" in CONFIDENCE_DEFINITION.lower()
        assert agg["confidence_definition"] == CONFIDENCE_DEFINITION

    def test_compute_evidence_relative_dominance(self):
        df = pd.DataFrame([
            {"chain_id": "c1", "observations": 8, "chain_observations": 10, "corroborating_patterns": 4},
            {"chain_id": "c1", "observations": 2, "chain_observations": 10, "corroborating_patterns": 1},
        ])
        ev = compute_evidence_scores(df)
        assert ev["relative_dominance"].iloc[0] == 1.0
        assert ev["relative_dominance"].iloc[1] == 0.25

    def test_train_model_saves_classifier(self, tmp_path):
        hist_data = [
            {
                "pattern_consistency": 0.9,
                "offset_from_scan_in": 10,
                "chain_length": 234,
                "pattern_count": 15,
                "root_cause_type": "SHIFT",
                "pfa_confirmed": 1,
            },
            {
                "pattern_consistency": 0.2,
                "offset_from_scan_in": 220,
                "chain_length": 234,
                "pattern_count": 1,
                "root_cause_type": "HOLD",
                "pfa_confirmed": 0,
            },
        ]

        hist_file = tmp_path / "mock_historical.json"
        hist_file.write_text(json.dumps(hist_data, indent=2), encoding="utf-8")

        model_data = train_confidence_model(hist_file, tmp_path)
        assert isinstance(model_data, dict)
        assert (tmp_path / "confidence_classifier.json").exists()
        assert (tmp_path / "confidence_classifier.joblib").exists()
        assert model_data.get("model_type", "").startswith("sklearn")
        assert len(model_data["feature_cols"]) == 11

        saved = json.loads((tmp_path / "confidence_classifier.json").read_text(encoding="utf-8"))
        assert saved["model_type"].startswith("sklearn")
        assert saved["joblib"] == "confidence_classifier.joblib"
