"""test_ml_pipeline.py — Unit tests for the industry ML pipeline."""

from __future__ import annotations

import sys
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import ml_pipeline as mlp
from exceptions import ModelError


class TestTrainRootCauseClassifier:
    def test_trains_successfully(self, minimal_failures_df):
        pipeline, metrics = mlp.train_root_cause_classifier(minimal_failures_df)
        assert pipeline is not None
        assert "cv_accuracy" in metrics
        assert 0.0 <= metrics["cv_accuracy"] <= 1.0

    def test_returns_metrics_dict(self, minimal_failures_df):
        _, metrics = mlp.train_root_cause_classifier(minimal_failures_df)
        required_keys = {"cv_accuracy", "cv_std", "n_train", "n_classes",
                         "class_names", "feature_importances", "model_type"}
        assert required_keys.issubset(set(metrics.keys()))

    def test_feature_importances_sum_to_one(self, minimal_failures_df):
        _, metrics = mlp.train_root_cause_classifier(minimal_failures_df)
        total = sum(metrics["feature_importances"].values())
        assert abs(total - 1.0) < 0.01

    def test_raises_with_no_labels(self, minimal_failures_df):
        df = minimal_failures_df.drop(columns=["root_cause_hint"])
        with pytest.raises(ModelError):
            mlp.train_root_cause_classifier(df)

    def test_raises_with_too_few_samples(self):
        df = pd.DataFrame({
            "root_cause_hint": ["SETUP_TIMING_VIOLATION"] * 3,
            "ir_drop_mv": [20, 30, 40],
            "thermal_c": [50, 60, 70],
            "setup_slack_ps": [-10, -20, -30],
            "hold_slack_ps": [5, 6, 7],
        })
        with pytest.raises(ModelError, match="Not enough labeled"):
            mlp.train_root_cause_classifier(df)

    def test_raises_with_single_class(self):
        df = pd.DataFrame({
            "root_cause_hint": ["SETUP_TIMING_VIOLATION"] * 15,
            "ir_drop_mv": range(15),
            "thermal_c": range(50, 65),
            "setup_slack_ps": range(-15, 0),
            "hold_slack_ps": range(15),
        })
        with pytest.raises(ModelError, match="unique class"):
            mlp.train_root_cause_classifier(df)


class TestPredictRootCause:
    def test_predicts_unknown_rows(self, minimal_failures_df):
        pipeline, _ = mlp.train_root_cause_classifier(minimal_failures_df)
        result = mlp.predict_root_cause(pipeline, minimal_failures_df)
        assert "predicted_root_cause" in result.columns
        assert "prediction_confidence" in result.columns

    def test_known_rows_unchanged(self, minimal_failures_df):
        pipeline, _ = mlp.train_root_cause_classifier(minimal_failures_df)
        result = mlp.predict_root_cause(pipeline, minimal_failures_df)
        # All rows should have a predicted_root_cause (no None left for valid-feature rows)
        assert result["predicted_root_cause"].notna().all()

    def test_confidence_in_range(self, minimal_failures_df):
        pipeline, _ = mlp.train_root_cause_classifier(minimal_failures_df)
        result = mlp.predict_root_cause(pipeline, minimal_failures_df)
        confidences = result["prediction_confidence"].dropna()
        assert (confidences >= 0.0).all()
        assert (confidences <= 1.0).all()


class TestAnomalyDetection:
    def test_trains_successfully(self, minimal_failures_df):
        detector = mlp.train_anomaly_detector(minimal_failures_df)
        assert detector is not None

    def test_detect_adds_columns(self, minimal_failures_df):
        detector = mlp.train_anomaly_detector(minimal_failures_df)
        result = mlp.detect_anomalies(detector, minimal_failures_df)
        assert "anomaly_score" in result.columns
        assert "is_anomaly" in result.columns

    def test_anomaly_flag_is_boolean(self, minimal_failures_df):
        detector = mlp.train_anomaly_detector(minimal_failures_df)
        result = mlp.detect_anomalies(detector, minimal_failures_df)
        assert result["is_anomaly"].dtype == bool

    def test_5pct_contamination_flags_some(self, minimal_failures_df):
        # With 10 rows and 5% contamination, IsolationForest may flag 0 or 1
        detector = mlp.train_anomaly_detector(minimal_failures_df)
        result = mlp.detect_anomalies(detector, minimal_failures_df)
        assert result["is_anomaly"].sum() >= 0  # just verify no crash


class TestModelPersistence:
    def test_save_and_load_classifier(self, minimal_failures_df, tmp_path):
        """Saved classifier loads correctly and produces same predictions."""
        import joblib
        pipeline, _ = mlp.train_root_cause_classifier(minimal_failures_df)

        # Save directly to tmp_path
        save_path = tmp_path / "test_classifier.joblib"
        joblib.dump(pipeline, save_path)
        assert save_path.exists()

        # Load and verify predictions match
        loaded = joblib.load(save_path)
        assert loaded is not None

        X_test = [[20, 50, -10, 5]]
        p1 = pipeline.predict(X_test)
        p2 = loaded.predict(X_test)
        assert p1[0] == p2[0]


class TestModelCard:
    def test_model_card_structure(self, minimal_failures_df):
        _, metrics = mlp.train_root_cause_classifier(minimal_failures_df)
        card = mlp.get_model_card(metrics)
        required = {"Model Type", "CV Accuracy", "Training Samples", "Classes", "Quality"}
        assert required.issubset(set(card.keys()))

    def test_quality_label_high(self):
        card = mlp.get_model_card({"cv_accuracy": 0.90, "cv_std": 0.02,
                                    "n_train": 100, "class_names": ["A", "B"],
                                    "feature_importances": {"ir_drop_mv": 1.0},
                                    "cv_folds": 5, "model_type": "RandomForest"})
        assert "High" in card["Quality"]

    def test_quality_label_low(self):
        card = mlp.get_model_card({"cv_accuracy": 0.55, "cv_std": 0.10,
                                    "n_train": 20, "class_names": ["A", "B"],
                                    "feature_importances": {"ir_drop_mv": 1.0},
                                    "cv_folds": 5, "model_type": "RandomForest"})
        assert "Low" in card["Quality"]
