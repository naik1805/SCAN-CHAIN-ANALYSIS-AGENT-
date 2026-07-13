"""
logger.py — Structured audit logging for the Scan Chain Diagnosis Agent.

Every diagnosis run receives a unique ``run_id`` (UUID4 + timestamp).
Log lines are emitted in structured JSON format to both the console and
a rotating file under ``output/run_logs/``.

Usage::

    from logger import get_run_logger, new_run_id
    run_id = new_run_id()
    log = get_run_logger(run_id)
    log.info("Parsed %d records from %d files", n_records, n_files)
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import get_config


# ---------------------------------------------------------------------------
# Run ID helper
# ---------------------------------------------------------------------------

def new_run_id() -> str:
    """Return a unique run identifier: ``<ISO-timestamp>_<8-char UUID>``.

    Example: ``2026-06-23T11-00-00Z_a1b2c3d4``
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{ts}_{short_uuid}"


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self._run_id = run_id

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "run_id": self._run_id,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


# ---------------------------------------------------------------------------
# Logger factory
# ---------------------------------------------------------------------------

_loggers: dict[str, logging.Logger] = {}


def get_run_logger(run_id: str, name: str = "sca") -> logging.Logger:
    """Return a logger that tags every line with *run_id*.

    The logger writes to:
    - ``stdout``  (human-readable format)
    - ``output/run_logs/sca_<run_id>.log``  (JSON, rotating)

    Args:
        run_id: Unique identifier for this diagnosis run.
        name: Logger namespace (default ``"sca"``).

    Returns:
        A configured :class:`logging.Logger` instance.
    """
    key = f"{name}:{run_id}"
    if key in _loggers:
        return _loggers[key]

    cfg = get_config()
    log_dir = cfg.log_dir_path
    log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, cfg.logging.level.upper(), logging.INFO)

    logger = logging.getLogger(key)
    logger.setLevel(level)
    logger.propagate = False

    # ── Console handler (plain text for readability) ──────────────────────
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s  [%(levelname)-8s]  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(ch)

    # ── Rotating JSON file handler ────────────────────────────────────────
    log_file = log_dir / f"sca_{run_id}.log"
    fh = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=cfg.logging.max_bytes,
        backupCount=cfg.logging.backup_count,
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(_JsonFormatter(run_id))
    logger.addHandler(fh)

    _loggers[key] = logger
    return logger


def list_run_logs() -> list[dict[str, Any]]:
    """Return metadata for all past run log files, newest first.

    Returns:
        List of dicts with keys ``run_id``, ``path``, ``size_kb``,
        ``modified``.
    """
    cfg = get_config()
    log_dir = cfg.log_dir_path
    if not log_dir.exists():
        return []

    entries = []
    for f in sorted(log_dir.glob("sca_*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
        entries.append({
            "run_id": f.stem.removeprefix("sca_"),
            "path": str(f),
            "size_kb": round(f.stat().st_size / 1024, 1),
            "modified": datetime.fromtimestamp(
                f.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
        })
    return entries


__all__ = ["new_run_id", "get_run_logger", "list_run_logs"]
