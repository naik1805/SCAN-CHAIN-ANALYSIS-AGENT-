"""Production hardening: holdout validation, review queue, model lifecycle."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


class TestHoldoutValidation:
    def test_break_certain_rate_empty(self):
        from holdout_validation import _break_certain_rate

        out = _break_certain_rate([])
        assert out["total"] == 0
        assert out["certain_pct"] is None

    def test_compute_with_tiny_frame(self):
        from holdout_validation import compute_production_validation

        failures = pd.DataFrame({
            "lot_id": ["A", "A", "B", "B", "C", "C"] * 10,
            "root_cause_hint": ["LOCAL"] * 60,
            "ir_drop_mv": [10.0] * 60,
            "thermal_c": [40.0] * 60,
            "setup_slack_ps": [20.0] * 60,
            "hold_slack_ps": [15.0] * 60,
            "die_row": [1] * 60,
            "die_col": [2] * 60,
            "wafer_x": [0.1] * 60,
            "wafer_y": [0.2] * 60,
        })
        suspects = pd.DataFrame({
            "chain": ["c1", "c2"],
            "confidence": [0.9, 0.8],
            "lots_affected": [2, 1],
        })
        report = compute_production_validation(
            failures, suspects, [{"location_status": "UNCERTAIN"}], fingerprint="test", use_cache=False
        )
        assert "readiness_grade" in report
        assert "lot_holdout" in report


class TestReviewQueue:
    def test_seed_and_confirm(self, tmp_path, monkeypatch):
        import review_queue as rq

        monkeypatch.setattr(rq, "_queue_path", lambda: tmp_path / "queue.json")
        monkeypatch.setattr(rq, "_feedback_path", lambda: tmp_path / "feedback.json")

        suspects = pd.DataFrame({
            "chain": ["channel01"],
            "chain_id": ["channel01"],
            "cell_name": ["U_core/ff[1]"],
            "fail_flop_id": ["FF_1"],
            "confidence": [0.85],
            "observations": [5],
            "lots_affected": [2],
            "evidence_score": [0.6],
            "ml_confidence": [0.9],
            "offset_from_scan_in": [10],
            "chain_length": [234],
            "predicted_root_cause": ["SETUP"],
        })
        seeded = rq.seed_review_queue(suspects, [], force=True)
        assert seeded["added"] >= 1
        assert rq.pending_count() >= 1

        item = rq.pending_items(limit=1)[0]
        result = rq.submit_review(item["id"], "confirm")
        assert result["ok"] is True
        assert rq.feedback_count() >= 1

    def test_new_fingerprint_seeds_pending_same_data_does_not(self, tmp_path, monkeypatch):
        import review_queue as rq

        monkeypatch.setattr(rq, "_queue_path", lambda: tmp_path / "queue.json")
        monkeypatch.setattr(rq, "_feedback_path", lambda: tmp_path / "feedback.json")

        suspects = pd.DataFrame({
            "chain": ["channel01"],
            "chain_id": ["channel01"],
            "cell_name": ["U_core/ff[1]"],
            "fail_flop_id": ["FF_1"],
            "confidence": [0.85],
            "observations": [5],
            "lots_affected": [2],
            "evidence_score": [0.6],
            "ml_confidence": [0.9],
            "offset_from_scan_in": [10],
            "chain_length": [234],
            "predicted_root_cause": ["SETUP"],
        })
        first = rq.seed_review_queue(suspects, [], fingerprint="fp-a")
        assert first["added"] >= 1
        item = rq.pending_items(limit=1)[0]
        rq.submit_review(item["id"], "confirm")
        assert rq.pending_count() == 0

        same = rq.seed_review_queue(suspects, [], fingerprint="fp-a")
        assert same.get("skipped") == "same_dataset_already_seeded"
        assert rq.pending_count() == 0

        anew = rq.seed_review_queue(suspects, [], fingerprint="fp-b")
        assert anew["added"] >= 1
        assert anew.get("new_dataset") is True
        assert rq.pending_count() >= 1


class TestModelLifecycle:
    def test_should_retrain_threshold(self, tmp_path, monkeypatch):
        import model_lifecycle as ml
        import review_queue as rq

        monkeypatch.setattr(ml, "_state_path", lambda: tmp_path / "life.json")
        monkeypatch.setattr(rq, "_feedback_path", lambda: tmp_path / "fb.json")
        monkeypatch.setattr(rq, "feedback_count", lambda: 5)

        check = ml.should_retrain(threshold=25)
        assert check["due"] is False
        assert check["feedback_count"] == 5
