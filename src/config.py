"""
config.py — Typed configuration loader for the Scan Chain Diagnosis Agent.

Loads ``config.yaml`` from the project root and exposes a single
``AppConfig`` dataclass.  All other modules import from here instead
of hard-coding thresholds or paths.

Usage::

    from config import get_config
    cfg = get_config()
    print(cfg.ml.n_estimators)   # 200
    print(cfg.diagnosis.min_observations)   # 2
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml

log = logging.getLogger(__name__)

# Project root is two levels up from this file (src/ → project/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"


# ---------------------------------------------------------------------------
# Dataclass hierarchy — one sub-config per YAML section
# ---------------------------------------------------------------------------

@dataclass
class MLConfig:
    """Machine-learning hyperparameters and model persistence settings."""
    classifier: str = "random_forest"
    n_estimators: int = 200
    max_depth: int = 10
    min_samples_leaf: int = 2
    cv_folds: int = 5
    min_training_samples: int = 10
    anomaly_contamination: float = 0.05
    persist_model: bool = True
    model_dir: str = "data/models"


@dataclass
class DiagnosisConfig:
    """Diagnosis thresholds used by locate_cells and break detection."""
    min_observations: int = 2
    confidence_threshold: float = 0.60
    break_min_unique_positions: int = 5
    max_logs_per_lot: int = 15


@dataclass
class CacheConfig:
    """Parquet disk-cache settings."""
    backend: str = "parquet"
    compression: str = "snappy"
    cache_subdir: str = "data/cache"


@dataclass
class LoggingConfig:
    """Python logging configuration."""
    level: str = "INFO"
    log_dir: str = "output/run_logs"
    max_bytes: int = 5_242_880  # 5 MB
    backup_count: int = 5


@dataclass
class ReportingConfig:
    """Export and reporting settings."""
    company_name: str = "Scan Chain Diagnosis Agent"
    export_formats: List[str] = field(default_factory=lambda: ["json", "csv"])


@dataclass
class ProductionConfig:
    """Production hardening: reviews, retrain, dashboard cache."""
    retrain_feedback_threshold: int = 25
    dashboard_cache_ttl_sec: int = 120
    auto_seed_reviews: bool = True


@dataclass
class AppConfig:
    """Root configuration object.  All sub-configs are nested here."""
    ml: MLConfig = field(default_factory=MLConfig)
    diagnosis: DiagnosisConfig = field(default_factory=DiagnosisConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)
    production: ProductionConfig = field(default_factory=ProductionConfig)

    @property
    def project_root(self) -> Path:
        """Absolute path to the project root directory."""
        return _PROJECT_ROOT

    @property
    def model_dir_path(self) -> Path:
        """Absolute path to the model persistence directory."""
        return _PROJECT_ROOT / self.ml.model_dir

    @property
    def cache_dir_path(self) -> Path:
        """Absolute path to the Parquet cache directory."""
        return _PROJECT_ROOT / self.cache.cache_subdir

    @property
    def log_dir_path(self) -> Path:
        """Absolute path to the run-log directory."""
        return _PROJECT_ROOT / self.logging.log_dir


# ---------------------------------------------------------------------------
# Loader (cached singleton so YAML is only read once per process)
# ---------------------------------------------------------------------------

_config_singleton: AppConfig | None = None


def _parse_section(section_cls, data: dict):
    """Instantiate a dataclass from a dict, ignoring unknown keys."""
    import dataclasses
    known = {f.name for f in dataclasses.fields(section_cls)}
    return section_cls(**{k: v for k, v in data.items() if k in known})


def load_config(path: Path | None = None) -> AppConfig:
    """Parse ``config.yaml`` and return a fully populated ``AppConfig``.

    Falls back to all defaults if the file does not exist.

    Args:
        path: Optional override for the config file location.

    Returns:
        A populated ``AppConfig`` dataclass instance.
    """
    cfg_path = path or _CONFIG_PATH
    if not cfg_path.exists():
        log.warning("config.yaml not found at %s — using defaults.", cfg_path)
        return AppConfig()

    with cfg_path.open("r", encoding="utf-8") as fh:
        raw: dict = yaml.safe_load(fh) or {}

    return AppConfig(
        ml=_parse_section(MLConfig, raw.get("ml", {})),
        diagnosis=_parse_section(DiagnosisConfig, raw.get("diagnosis", {})),
        cache=_parse_section(CacheConfig, raw.get("cache", {})),
        logging=_parse_section(LoggingConfig, raw.get("logging", {})),
        reporting=_parse_section(ReportingConfig, raw.get("reporting", {})),
        production=_parse_section(ProductionConfig, raw.get("production", {})),
    )


def get_config() -> AppConfig:
    """Return the process-level singleton ``AppConfig`` (lazy-loaded).

    Subsequent calls return the already-loaded config without re-reading disk.
    """
    global _config_singleton
    if _config_singleton is None:
        _config_singleton = load_config()
    return _config_singleton


__all__ = [
    "AppConfig",
    "MLConfig",
    "DiagnosisConfig",
    "CacheConfig",
    "LoggingConfig",
    "ReportingConfig",
    "ProductionConfig",
    "get_config",
    "load_config",
]
