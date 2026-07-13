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
    predict_diagnosis_confidence
)


class TestLogisticRegressionModel:
    def test_fit_and_predict_probability(self):
        # Create a simple linearly separable dataset
        # Feature 0 determines the class directly
        X = np.array([
            [1.0, 0.5],
            [1.5, 0.2],
            [2.0, 0.1],
            [-1.0, 0.5],
            [-1.5, 0.8],
            [-2.0, 0.9]
        ])
        y = np.array([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
        
        model = LogisticRegressionModel(n_features=2)
        model.fit(X, y, epochs=100, lr=0.5)
        
        # Test predictions
        probs = model.predict_proba(X)
        assert len(probs) == 6
        assert (probs >= 0.0).all()
        assert (probs <= 1.0).all()
        
        # Positive values should have high probability, negative values should have low probability
        assert probs[0] > 0.5
        assert probs[5] < 0.5


class TestConfidenceScorePipeline:
    def test_load_confidence_model_returns_dict(self):
        model_data = load_confidence_model()
        assert isinstance(model_data, dict)
        assert "weights" in model_data
        assert "bias" in model_data
        assert "feature_cols" in model_data

    def test_predict_diagnosis_confidence_updates_column(self):
        # Create mock suspects dataframe
        suspects_data = [
            {
                "chain": "channel1",
                "instance": "U_core",
                "cell_name": "cell_1",
                "fail_flop_id": "FF_1",
                "offset_from_scan_in": 10,
                "chain_length": 234,
                "observations": 5,
                "chain_observations": 100,
                "predicted_root_cause": "CAPTURE_TIMING_SETUP"
            },
            {
                "chain": "channel2",
                "instance": "U_core",
                "cell_name": "cell_2",
                "fail_flop_id": "FF_2",
                "offset_from_scan_in": 200,
                "chain_length": 234,
                "observations": 1,
                "chain_observations": 100,
                "predicted_root_cause": "CAPTURE_TIMING_HOLD"
            }
        ]
        suspects_df = pd.DataFrame(suspects_data)
        model_data = load_confidence_model()
        
        result_df = predict_diagnosis_confidence(suspects_df, model_data)
        assert "confidence" in result_df.columns
        assert len(result_df) == 2
        assert (result_df["confidence"] >= 0.0).all()
        assert (result_df["confidence"] <= 1.0).all()
        
        # Cell 1 (more observations, better root cause) should have higher confidence than Cell 2
        assert result_df["confidence"].iloc[0] > result_df["confidence"].iloc[1]

    def test_train_model_saves_classifier(self, tmp_path):
        # Create mock historical data file
        hist_data = [
            {
                "pattern_consistency": 0.9,
                "offset_from_scan_in": 10,
                "chain_length": 234,
                "pattern_count": 15,
                "root_cause_type": "SHIFT",
                "pfa_confirmed": 1
            },
            {
                "pattern_consistency": 0.2,
                "offset_from_scan_in": 220,
                "chain_length": 234,
                "pattern_count": 1,
                "root_cause_type": "HOLD",
                "pfa_confirmed": 0
            }
        ]
        
        hist_file = tmp_path / "mock_historical.json"
        hist_file.write_text(json.dumps(hist_data, indent=2), encoding="utf-8")
        
        model_data = train_confidence_model(hist_file, tmp_path)
        assert isinstance(model_data, dict)
        assert (tmp_path / "confidence_classifier.json").exists()
        
        # Verify saved file structure
        saved = json.loads((tmp_path / "confidence_classifier.json").read_text(encoding="utf-8"))
        assert "weights" in saved
        assert "bias" in saved
        assert len(saved["weights"]) == 7
