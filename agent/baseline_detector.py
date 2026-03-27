"""
agent/baseline_detector.py
---------------------------
Historical Baseline — Rolling Z-Score Detector
================================================
FUTURE WORK ITEM #5: Historical baseline

Complements Isolation Forest with a rolling Z-score detector.
Z-score is better at detecting gradual drift; Isolation Forest catches
sharp multivariate anomalies. Using both gives fewer false positives.

How it works:
  - Maintains a rolling window of the last N metric samples
  - Computes mean and std for each metric
  - Flags samples where |z-score| > threshold as anomalous
  - Combines results with Isolation Forest via AND/OR logic (configurable)

Why Z-score vs Isolation Forest:
  ┌─────────────────────┬──────────────────────────┬────────────────────┐
  │ Detector            │ Good At                  │ Weak At            │
  ├─────────────────────┼──────────────────────────┼────────────────────┤
  │ Isolation Forest    │ Multivariate anomalies   │ Gradual drift      │
  │                     │ Non-linear patterns      │ Needs training     │
  ├─────────────────────┼──────────────────────────┼────────────────────┤
  │ Rolling Z-Score     │ Gradual drift detection  │ Correlated features│
  │                     │ No training needed       │ Assumes normality  │
  └─────────────────────┴──────────────────────────┴────────────────────┘
"""

from collections import deque
from dataclasses import dataclass
from typing import Optional
import math


# ── Configuration ─────────────────────────────────────────────────────────────
ROLLING_WINDOW   = 60    # number of samples in baseline window (~5 min at 5s)
Z_THRESHOLD      = 2.5   # standard deviations to flag as anomaly
MIN_SAMPLES      = 10    # minimum samples before z-score is meaningful


@dataclass
class ZScoreAnomaly:
    """A single metric anomaly detected by Z-score analysis."""
    timestamp: str
    metric_name: str
    value: float
    mean: float
    std: float
    z_score: float
    is_anomaly: bool


@dataclass
class BaselineReport:
    """Combined baseline analysis report."""
    anomalies: list[ZScoreAnomaly]
    sample_count: int
    metrics_analyzed: list[str]

    @property
    def has_anomalies(self) -> bool:
        return bool(self.anomalies)

    @property
    def anomaly_summary(self) -> str:
        if not self.anomalies:
            return "No Z-score anomalies"
        parts = []
        for a in self.anomalies:
            parts.append(f"{a.metric_name}={a.value:.1f} (z={a.z_score:.2f})")
        return ", ".join(parts)


class RollingStats:
    """Welford's online algorithm for rolling mean and std."""

    def __init__(self, window_size: int):
        self.window_size = window_size
        self._values: deque = deque(maxlen=window_size)

    def add(self, value: float):
        self._values.append(value)

    @property
    def count(self) -> int:
        return len(self._values)

    @property
    def mean(self) -> Optional[float]:
        if not self._values:
            return None
        return sum(self._values) / len(self._values)

    @property
    def std(self) -> Optional[float]:
        if len(self._values) < 2:
            return None
        m = self.mean
        variance = sum((x - m) ** 2 for x in self._values) / (len(self._values) - 1)
        return math.sqrt(variance) if variance > 0 else 0.001

    def z_score(self, value: float) -> Optional[float]:
        m = self.mean
        s = self.std
        if m is None or s is None or s == 0:
            return None
        return (value - m) / s


class RollingZScoreDetector:
    """
    Detects metric anomalies using rolling Z-score analysis.
    Maintains independent rolling windows per metric.

    Usage:
        detector = RollingZScoreDetector()
        # Feed samples continuously:
        for sample in metric_samples:
            detector.add_sample(sample)
        # Check latest sample:
        report = detector.check_latest()
    """

    def __init__(self, window_size: int = ROLLING_WINDOW, threshold: float = Z_THRESHOLD):
        self.threshold = threshold
        self.window_size = window_size
        self._stats: dict[str, RollingStats] = {
            "cpu_pct":    RollingStats(window_size),
            "mem_pct":    RollingStats(window_size),
            "latency_ms": RollingStats(window_size),
        }
        self._latest: Optional[dict] = None

    def add_sample(self, sample: dict):
        """
        Add a metrics sample to the rolling windows.
        Call this for every sample, even before running detection.
        """
        for metric in self._stats:
            val = sample.get(metric)
            if val is not None:
                self._stats[metric].add(float(val))
        self._latest = sample

    def check_latest(self) -> BaselineReport:
        """
        Check the most recently added sample for Z-score anomalies.
        Returns a BaselineReport — call after add_sample().
        """
        if self._latest is None:
            return BaselineReport(anomalies=[], sample_count=0, metrics_analyzed=[])

        anomalies = []
        for metric, stats in self._stats.items():
            if stats.count < MIN_SAMPLES:
                continue  # Not enough data yet

            value = self._latest.get(metric)
            if value is None:
                continue

            z = stats.z_score(float(value))
            if z is None:
                continue

            is_anomaly = abs(z) > self.threshold
            if is_anomaly:
                anomalies.append(ZScoreAnomaly(
                    timestamp=self._latest.get("timestamp", ""),
                    metric_name=metric,
                    value=float(value),
                    mean=round(stats.mean, 2),
                    std=round(stats.std, 3),
                    z_score=round(z, 2),
                    is_anomaly=True,
                ))

        return BaselineReport(
            anomalies=anomalies,
            sample_count=min(s.count for s in self._stats.values()),
            metrics_analyzed=list(self._stats.keys()),
        )

    def feed_and_check(self, sample: dict) -> BaselineReport:
        """Convenience method: add sample + check in one call."""
        self.add_sample(sample)
        return self.check_latest()

    def get_current_baselines(self) -> dict:
        """Return current baseline stats for all metrics (for dashboard display)."""
        result = {}
        for metric, stats in self._stats.items():
            result[metric] = {
                "mean": round(stats.mean, 2) if stats.mean is not None else None,
                "std": round(stats.std, 3) if stats.std is not None else None,
                "count": stats.count,
                "threshold_upper": round(stats.mean + self.threshold * stats.std, 2)
                    if stats.mean is not None and stats.std is not None else None,
                "threshold_lower": round(stats.mean - self.threshold * stats.std, 2)
                    if stats.mean is not None and stats.std is not None else None,
            }
        return result


def combine_detectors(isolation_has_anomaly: bool,
                      zscore_report: BaselineReport,
                      mode: str = "OR") -> bool:
    """
    Combine Isolation Forest and Z-score signals.

    Args:
        isolation_has_anomaly: True if Isolation Forest flagged anomaly
        zscore_report: Report from RollingZScoreDetector
        mode: "OR" = flag if either detects anomaly (more sensitive)
              "AND" = flag only if both detect anomaly (fewer false positives)

    Returns:
        True if combined signal is anomalous.
    """
    zscore_has_anomaly = zscore_report.has_anomalies
    if mode == "AND":
        return isolation_has_anomaly and zscore_has_anomaly
    else:  # OR
        return isolation_has_anomaly or zscore_has_anomaly


# Singleton detector — shared across the agent loop
rolling_detector = RollingZScoreDetector()