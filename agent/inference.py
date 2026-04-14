"""
agent/inference.py
------------------
RUNTIME INFERENCE PHASE
========================
Loads pre-trained Isolation Forest models and runs inference on:
  - recent system metrics (sliding window)
  - recent log patterns (sliding window)

Returns structured AnomalyReport objects consumed by the agent loop.

Key design: Models are loaded ONCE at startup to avoid disk I/O in the hot loop.
"""

import json
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np

MODELS_DIR = Path("models")
APP_LOG = Path("logs_store/app.log")

# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class MetricAnomaly:
    """Detected anomaly in system metrics."""
    timestamp: str
    cpu_pct: float
    mem_pct: float
    latency_ms: float
    anomaly_score: float     # lower (more negative) = more anomalous
    is_anomaly: bool


@dataclass
class LogAnomaly:
    """Detected anomaly in log patterns."""
    window_start: str
    error_count: int
    warning_count: int
    slow_count: int
    total_requests_in_window: int          # renamed to match rca_builder usage
    anomaly_score: float
    is_anomaly: bool
    sample_error_messages: list[str] = field(default_factory=list)


@dataclass
class AnomalyReport:
    """Combined report of all anomalies in one inference cycle."""
    generated_at: str
    metric_anomalies: list[MetricAnomaly]
    log_anomalies: list[LogAnomaly]
    
    @property
    def has_anomalies(self) -> bool:
        return bool(self.metric_anomalies or self.log_anomalies)


# ── Model loader ──────────────────────────────────────────────────────────────

class ModelStore:
    """Loads and caches trained models. Call load() once at startup."""

    def __init__(self):
        self.metrics_model = None
        self.metrics_scaler = None
        self.log_model = None
        self.log_scaler = None
        self._loaded = False

    def load(self):
        """Load both models from disk."""
        metrics_path = MODELS_DIR / "metrics_model.pkl"
        log_path = MODELS_DIR / "log_model.pkl"

        if not metrics_path.exists() or not log_path.exists():
            raise FileNotFoundError(
                "Trained models not found. Run: python agent/train.py"
            )

        with open(metrics_path, "rb") as f:
            bundle = pickle.load(f)
            self.metrics_model = bundle["model"]
            self.metrics_scaler = bundle["scaler"]

        with open(log_path, "rb") as f:
            bundle = pickle.load(f)
            self.log_model = bundle["model"]
            self.log_scaler = bundle["scaler"]

        self._loaded = True
        print("[Inference] Models loaded successfully.")

    def is_ready(self) -> bool:
        return self._loaded


# Singleton model store — shared across the agent loop
model_store = ModelStore()


# ── Inference helpers ─────────────────────────────────────────────────────────

def infer_metrics(recent_samples: list[dict]) -> list[MetricAnomaly]:
    """
    Run metric anomaly detection on recent samples.
    
    Args:
        recent_samples: List of dicts from metrics/collector.py get_recent_metrics()
    Returns:
        List of MetricAnomaly (only anomalous ones).
    """
    if not model_store.is_ready():
        raise RuntimeError("Models not loaded. Call model_store.load() first.")
    if len(recent_samples) < 3:
        return []

    # Build feature matrix
    rows = []
    for s in recent_samples:
        rows.append([
            float(s.get("cpu_pct", 0)),
            float(s.get("mem_pct", 0)),
            float(s.get("latency_ms", 0)),
        ])
    X = np.array(rows)
    X_scaled = model_store.metrics_scaler.transform(X)

    # Isolation Forest: predict returns -1 (anomaly) or +1 (normal)
    predictions = model_store.metrics_model.predict(X_scaled)
    scores = model_store.metrics_model.score_samples(X_scaled)

    anomalies = []
    for i, (pred, score) in enumerate(zip(predictions, scores)):
        if pred == -1:
            s = recent_samples[i]
            anomalies.append(MetricAnomaly(
                timestamp=s.get("timestamp", "unknown"),
                cpu_pct=float(s.get("cpu_pct", 0)),
                mem_pct=float(s.get("mem_pct", 0)),
                latency_ms=float(s.get("latency_ms", 0)),
                anomaly_score=float(score),
                is_anomaly=True,
            ))
    return anomalies


def _parse_recent_logs(window_minutes: int = 5) -> tuple[list[dict], list[dict]]:
    """
    Read app.log and return:
      (all_recent_records, error_records_only)
    for the last `window_minutes` minutes.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    records = []
    errors = []

    if not APP_LOG.exists():
        return [], []

    with open(APP_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts_str = rec.get("timestamp", "")
                # Parse ISO timestamp
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts >= cutoff:
                    records.append(rec)
                    if rec.get("level") in ("ERROR", "CRITICAL"):
                        errors.append(rec)
            except (json.JSONDecodeError, ValueError):
                continue

    return records, errors


def infer_logs(window_minutes: int = 5) -> list[LogAnomaly]:
    """
    Analyze recent log window for anomalies.
    Returns list of LogAnomaly (only anomalous windows).
    """
    if not model_store.is_ready():
        raise RuntimeError("Models not loaded.")

    records, errors = _parse_recent_logs(window_minutes)
    if not records:
        return []

    # Build single feature vector for the whole window
    error_count   = sum(1 for r in records if r.get("level") == "ERROR")
    warning_count = sum(1 for r in records if r.get("level") == "WARNING")
    slow_count    = sum(1 for r in records if (r.get("latency_ms") or 0) > 1000)
    total         = len(records)

    X = np.array([[error_count, warning_count, slow_count, total]], dtype=float)
    X_scaled = model_store.log_scaler.transform(X)

    pred = model_store.log_model.predict(X_scaled)[0]
    score = model_store.log_model.score_samples(X_scaled)[0]

    if pred == -1:
        # Gather sample error messages for RCA context
        sample_msgs = [
            r.get("message", "")
            for r in errors[:5]  # at most 5 error messages
        ]
        now_str = datetime.utcnow().isoformat() + "Z"
        return [LogAnomaly(
            window_start=now_str,
            error_count=int(error_count),
            warning_count=int(warning_count),
            slow_count=int(slow_count),
            total_requests_in_window=int(total),
            anomaly_score=float(score),
            is_anomaly=True,
            sample_error_messages=sample_msgs,
        )]
    return []


def run_inference(recent_metrics: list[dict], window_minutes: int = 5) -> AnomalyReport:
    """
    Main inference entry point — called by the agent loop each cycle.
    
    Args:
        recent_metrics: From metrics.collector.get_recent_metrics()
        window_minutes: Log sliding window size
    Returns:
        AnomalyReport with all detected anomalies.
    """
    metric_anomalies = infer_metrics(recent_metrics)
    log_anomalies = infer_logs(window_minutes)

    return AnomalyReport(
        generated_at=datetime.utcnow().isoformat() + "Z",
        metric_anomalies=metric_anomalies,
        log_anomalies=log_anomalies,
    )