"""Engineer review queue + PFA feedback store for production hardening."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd

log = logging.getLogger(__name__)

ReviewDecision = Literal["confirm", "reject", "defer"]

_QUEUE_NAME = "review_queue.json"
_FEEDBACK_NAME = "engineer_feedback.json"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _queue_path() -> Path:
    return _project_root() / "data" / "cache" / _QUEUE_NAME


def _feedback_path() -> Path:
    return _project_root() / "data" / "cache" / _FEEDBACK_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Failed reading %s: %s", path, exc)
        return default


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_queue() -> dict[str, Any]:
    data = _load_json(_queue_path(), {"items": [], "updated_at": None})
    if not isinstance(data, dict):
        return {"items": [], "updated_at": None}
    data.setdefault("items", [])
    return data


def pending_items(limit: int | None = None) -> list[dict[str, Any]]:
    items = [i for i in load_queue().get("items", []) if i.get("status") == "pending"]
    items.sort(key=lambda r: (-float(r.get("priority_score") or 0), str(r.get("id"))))
    if limit is not None:
        return items[:limit]
    return items


def pending_count() -> int:
    return len(pending_items())


def reviewed_count() -> int:
    return sum(1 for i in load_queue().get("items", []) if i.get("status") in {"confirmed", "rejected"})


def seed_review_queue(
    suspects: pd.DataFrame | list[dict[str, Any]],
    breaks: list[dict[str, Any]] | pd.DataFrame,
    *,
    max_cells: int = 40,
    max_breaks: int = 25,
    force: bool = False,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    """Seed actionable review items from top suspects + uncertain breaks.

    Same dataset (matching ``fingerprint``): never re-add after seeding once.
    New dataset (fingerprint changed): add a fresh pending set for the new data.
    Dedupe keys are namespaced by fingerprint so new lots get new reviews.
    """
    queue = load_queue()
    existing_items = list(queue.get("items") or [])
    prev_fp = queue.get("seeded_fingerprint")

    # Same data already seeded — keep pending at whatever is left (usually 0)
    if not force and fingerprint and prev_fp == fingerprint and existing_items:
        return {
            "added": 0,
            "pending": pending_count(),
            "total": len(existing_items),
            "skipped": "same_dataset_already_seeded",
        }

    # No fingerprint and queue already exists — do not keep re-adding
    if not force and not fingerprint and existing_items:
        return {
            "added": 0,
            "pending": pending_count(),
            "total": len(existing_items),
            "skipped": "queue_exists_no_fingerprint",
        }

    fp_ns = fingerprint or prev_fp or "default"
    existing_keys = {str(i.get("dedupe_key")) for i in existing_items if i.get("dedupe_key")}

    suspects_df = suspects if isinstance(suspects, pd.DataFrame) else pd.DataFrame(suspects or [])
    if isinstance(breaks, pd.DataFrame):
        break_rows = breaks.to_dict(orient="records") if not breaks.empty else []
    else:
        break_rows = list(breaks or [])

    added = 0
    items = list(existing_items)

    # Top cell per chain (actionable leads)
    if not suspects_df.empty and "confidence" in suspects_df.columns:
        chain_key = "chain_id" if "chain_id" in suspects_df.columns else "chain"
        ranked = suspects_df.sort_values("confidence", ascending=False)
        if chain_key in ranked.columns:
            top = ranked.groupby(chain_key, sort=False).head(1).head(max_cells)
        else:
            top = ranked.head(max_cells)

        for _, row in top.iterrows():
            chain = str(row.get("chain") or row.get("chain_id") or "?")
            cell = str(row.get("cell_name") or row.get("fail_flop_id") or "?")
            dedupe = f"{fp_ns}|cell|{chain}|{cell}"
            if not force and dedupe in existing_keys:
                continue
            conf = float(row.get("confidence") or 0)
            item_id = str(uuid.uuid4())
            items.append({
                "id": item_id,
                "dedupe_key": dedupe,
                "data_fingerprint": fp_ns,
                "kind": "cell",
                "status": "pending",
                "priority_score": conf,
                "chain": chain,
                "cell_name": cell,
                "fail_flop_id": row.get("fail_flop_id"),
                "confidence": round(conf, 4),
                "confidence_pct": round(conf * 100, 1),
                "predicted_root_cause": row.get("predicted_root_cause") or row.get("dominant_root_cause"),
                "observations": int(row.get("observations") or 0),
                "lots_affected": int(row.get("lots_affected") or 0) if pd.notna(row.get("lots_affected")) else None,
                "evidence_score": float(row["evidence_score"]) if "evidence_score" in row and pd.notna(row.get("evidence_score")) else None,
                "ml_confidence": float(row["ml_confidence"]) if "ml_confidence" in row and pd.notna(row.get("ml_confidence")) else None,
                "offset_from_scan_in": row.get("offset_from_scan_in"),
                "chain_length": row.get("chain_length"),
                "created_at": _now_iso(),
                "reviewed_at": None,
                "decision": None,
                "reviewer_note": None,
            })
            existing_keys.add(dedupe)
            added += 1

    def _break_sort_key(r: dict[str, Any]) -> tuple:
        status = str(r.get("location_status", "")).upper()
        conf = float(r.get("location_confidence") or 0)
        return (0 if status != "CERTAIN" else 1, -conf)

    for br in sorted(break_rows, key=_break_sort_key)[:max_breaks]:
        chain = str(br.get("chain") or "?")
        bit = br.get("exact_break_bit_position", br.get("suspected_break_bit"))
        cell = str(br.get("exact_break_cell") or br.get("suspected_break_cell") or bit or "?")
        lot = str(br.get("lot_id") or "")
        die = f"{br.get('die_x')}|{br.get('die_y')}|{br.get('die_label') or ''}"
        dedupe = f"{fp_ns}|break|{chain}|{bit}|{lot}|{die}"
        if not force and dedupe in existing_keys:
            continue
        status = str(br.get("location_status", "UNCERTAIN")).upper()
        conf = float(br.get("location_confidence") or 0)
        priority = conf + (0.15 if status != "CERTAIN" else 0.0)
        item_id = str(uuid.uuid4())
        items.append({
            "id": item_id,
            "dedupe_key": dedupe,
            "data_fingerprint": fp_ns,
            "kind": "break",
            "status": "pending",
            "priority_score": priority,
            "chain": chain,
            "cell_name": cell,
            "location_status": status,
            "location_confidence": conf,
            "confidence_pct": round(conf * 100, 1),
            "lot_id": br.get("lot_id"),
            "die_x": br.get("die_x"),
            "die_y": br.get("die_y"),
            "exact_break_bit_position": bit,
            "created_at": _now_iso(),
            "reviewed_at": None,
            "decision": None,
            "reviewer_note": None,
        })
        existing_keys.add(dedupe)
        added += 1

    new_dataset = bool(fingerprint and prev_fp and fingerprint != prev_fp)
    queue = {
        "items": items,
        "updated_at": _now_iso(),
        "last_seed_added": added,
        "seeded_fingerprint": fingerprint or prev_fp,
        "previous_fingerprint": prev_fp if new_dataset else queue.get("previous_fingerprint"),
    }
    _save_json(_queue_path(), queue)
    return {
        "added": added,
        "pending": sum(1 for i in items if i.get("status") == "pending"),
        "total": len(items),
        "fingerprint": queue.get("seeded_fingerprint"),
        "new_dataset": new_dataset,
    }


def submit_review(
    item_id: str,
    decision: ReviewDecision,
    *,
    reviewer_note: str | None = None,
) -> dict[str, Any]:
    """Apply engineer decision; confirmed cells feed the PFA feedback store."""
    if decision not in ("confirm", "reject", "defer"):
        raise ValueError(f"Invalid decision: {decision}")

    queue = load_queue()
    items = queue.get("items", [])
    found = None
    for item in items:
        if str(item.get("id")) == str(item_id):
            found = item
            break
    if found is None:
        raise KeyError(f"Review item not found: {item_id}")

    if decision == "defer":
        found["status"] = "pending"
        found["decision"] = "defer"
        found["reviewer_note"] = reviewer_note
        found["reviewed_at"] = _now_iso()
    elif decision == "confirm":
        found["status"] = "confirmed"
        found["decision"] = "confirm"
        found["reviewer_note"] = reviewer_note
        found["reviewed_at"] = _now_iso()
        if found.get("kind") == "cell":
            _append_pfa_feedback(found, confirmed=True)
    else:
        found["status"] = "rejected"
        found["decision"] = "reject"
        found["reviewer_note"] = reviewer_note
        found["reviewed_at"] = _now_iso()
        if found.get("kind") == "cell":
            _append_pfa_feedback(found, confirmed=False)

    queue["items"] = items
    queue["updated_at"] = _now_iso()
    _save_json(_queue_path(), queue)

    return {
        "ok": True,
        "item": found,
        "pending": pending_count(),
        "confirmed": sum(1 for i in items if i.get("status") == "confirmed"),
        "rejected": sum(1 for i in items if i.get("status") == "rejected"),
        "feedback_records": feedback_count(),
        "summary": queue_summary(),
    }


def _append_pfa_feedback(item: dict[str, Any], *, confirmed: bool) -> None:
    """Append a training row compatible with confidence_score historical features."""
    path = _feedback_path()
    rows = _load_json(path, [])
    if not isinstance(rows, list):
        rows = []

    evidence = item.get("evidence_score")
    if evidence is None:
        evidence = item.get("confidence") or 0.5
    pattern_count = int(item.get("observations") or 1)
    offset = item.get("offset_from_scan_in") or 0
    chain_length = item.get("chain_length") or 234
    rc = str(item.get("predicted_root_cause") or "DEFECT").upper()
    # Map RF wafer/defect labels into confidence model RC buckets
    if any(k in rc for k in ("SHIFT",)):
        rc_type = "SHIFT"
    elif any(k in rc for k in ("SETUP", "TIMING")):
        rc_type = "SETUP"
    elif "HOLD" in rc:
        rc_type = "HOLD"
    else:
        rc_type = "DEFECT"

    rows.append({
        "pattern_consistency": float(evidence),
        "offset_from_scan_in": int(offset) if offset is not None else 0,
        "chain_length": int(chain_length) if chain_length else 234,
        "pattern_count": pattern_count,
        "root_cause_type": rc_type,
        "pfa_confirmed": 1 if confirmed else 0,
        "source": "engineer_review",
        "review_item_id": item.get("id"),
        "chain": item.get("chain"),
        "cell_name": item.get("cell_name"),
        "recorded_at": _now_iso(),
    })
    _save_json(path, rows)


def feedback_count() -> int:
    rows = _load_json(_feedback_path(), [])
    return len(rows) if isinstance(rows, list) else 0


def load_feedback_records() -> list[dict[str, Any]]:
    rows = _load_json(_feedback_path(), [])
    return rows if isinstance(rows, list) else []


def queue_summary() -> dict[str, Any]:
    items = load_queue().get("items", [])
    pending = [i for i in items if i.get("status") == "pending"]
    confirmed = sum(1 for i in items if i.get("status") == "confirmed")
    rejected = sum(1 for i in items if i.get("status") == "rejected")
    return {
        "pending": len(pending),
        "confirmed": confirmed,
        "rejected": rejected,
        "total": len(items),
        "feedback_records": feedback_count(),
        "updated_at": load_queue().get("updated_at"),
    }
