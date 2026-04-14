"""
agent/rca_builder.py
--------------------
Root Cause Analysis (RCA) Evidence Builder
==========================================
Transforms raw AnomalyReport into a structured, human-readable evidence
bundle that is passed to the LLM for reasoning.

Design principle: Structure first, LLM second.
The LLM should receive clean, correlated evidence — not raw log dumps.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from agent.inference import AnomalyReport


@dataclass
class RCAEvidence:
    """
    Structured evidence bundle for RCA.
    This is what gets serialized and sent to the LLM.
    """
    timestamp: str
    severity: str                      # LOW / MEDIUM / HIGH / CRITICAL
    correlated: bool                   # True if both metrics AND logs show anomalies
    
    # Metric summary
    avg_cpu_pct: Optional[float]
    max_cpu_pct: Optional[float]
    avg_mem_pct: Optional[float]
    avg_latency_ms: Optional[float]
    max_latency_ms: Optional[float]
    metric_anomaly_count: int
    
    # Log summary
    error_count: int
    warning_count: int
    slow_request_count: int
    total_requests_in_window: int
    sample_error_messages: list[str]
    log_anomaly_count: int
    
    # Derived signals
    error_rate_pct: float
    dominant_issue: str                # human-readable primary signal
    context_summary: str               # 2-3 sentence narrative for LLM context


def _assess_severity(report: AnomalyReport) -> str:
    """
    Rule-based severity escalation:
      - CRITICAL: correlated metric + log anomalies, high error rate
      - HIGH:     many metric anomalies OR high error count
      - MEDIUM:   some anomalies
      - LOW:      edge case / minor
    """
    m = report.metric_anomalies
    l = report.log_anomalies

    if not m and not l:
        return "NONE"

    correlated = bool(m and l)
    error_total = sum(la.error_count for la in l)
    metric_count = len(m)

    if correlated and error_total >= 3:
        return "CRITICAL"
    if correlated or metric_count >= 5 or error_total >= 5:
        return "HIGH"
    if metric_count >= 2 or error_total >= 2:
        return "MEDIUM"
    return "LOW"


def _dominant_issue(report: AnomalyReport) -> str:
    """Identify the most prominent signal from anomalies."""
    m = report.metric_anomalies
    l = report.log_anomalies

    if m and l:
        # Both signals present — find which metric is spiking most
        max_cpu = max((a.cpu_pct for a in m), default=0)
        max_lat = max((a.latency_ms for a in m), default=0)
        error_cnt = sum(la.error_count for la in l)

        if max_cpu > 85:
            return f"CPU spike ({max_cpu:.1f}%) correlated with {error_cnt} errors in logs"
        if max_lat > 2000:
            return f"High latency ({max_lat:.0f}ms) correlated with {error_cnt} errors in logs"
        return f"Correlated system + log anomalies ({error_cnt} errors)"

    if m:
        max_cpu = max((a.cpu_pct for a in m), default=0)
        max_lat = max((a.latency_ms for a in m), default=0)
        if max_cpu > 80:
            return f"CPU overload ({max_cpu:.1f}%)"
        if max_lat > 1500:
            return f"Response latency spike ({max_lat:.0f}ms)"
        return "Metric anomaly detected (cpu/mem/latency)"

    if l:
        la = l[0]
        if la.error_count > 0:
            return f"Elevated error rate ({la.error_count} errors in window)"
        if la.slow_count > 0:
            return f"Slow requests detected ({la.slow_count} slow in window)"
        return "Log pattern anomaly"

    return "Unknown"


def build_evidence(report: AnomalyReport) -> Optional[RCAEvidence]:
    """
    Main entry point. Build an RCAEvidence from an AnomalyReport.
    Returns None if no anomalies found.
    """
    if not report.has_anomalies:
        return None

    m = report.metric_anomalies
    l = report.log_anomalies

    # Metric aggregates
    avg_cpu = round(sum(a.cpu_pct for a in m) / len(m), 2) if m else None
    max_cpu = round(max((a.cpu_pct for a in m), default=0), 2) if m else None
    avg_mem = round(sum(a.mem_pct for a in m) / len(m), 2) if m else None
    avg_lat = round(sum(a.latency_ms for a in m) / len(m), 2) if m else None
    max_lat = round(max((a.latency_ms for a in m), default=0), 2) if m else None

    # Log aggregates
    error_cnt = sum(la.error_count for la in l)
    warn_cnt  = sum(la.warning_count for la in l)
    slow_cnt  = sum(la.slow_count for la in l)
    total_req = sum(la.total_requests_in_window for la in l)
    all_errors = []
    for la in l:
        all_errors.extend(la.sample_error_messages)

    error_rate = round((error_cnt / total_req * 100) if total_req > 0 else 0, 2)
    severity = _assess_severity(report)
    dominant = _dominant_issue(report)
    correlated = bool(m and l)

    # Build a 2-3 sentence context narrative for the LLM prompt
    parts = []
    if m:
        parts.append(
            f"System metrics show {len(m)} anomalous data point(s): "
            f"avg CPU {avg_cpu}%, avg latency {avg_lat}ms (max {max_lat}ms)."
        )
    if l:
        parts.append(
            f"Log analysis over the last 5 minutes detected {error_cnt} errors, "
            f"{warn_cnt} warnings, and {slow_cnt} slow requests out of {total_req} total."
        )
    if correlated:
        parts.append("Both metric and log signals are anomalous simultaneously, "
                     "suggesting a systemic issue rather than a transient spike.")
    context_summary = " ".join(parts)

    return RCAEvidence(
        timestamp=report.generated_at,
        severity=severity,
        correlated=correlated,
        avg_cpu_pct=avg_cpu,
        max_cpu_pct=max_cpu,
        avg_mem_pct=avg_mem,
        avg_latency_ms=avg_lat,
        max_latency_ms=max_lat,
        metric_anomaly_count=len(m),
        error_count=error_cnt,
        warning_count=warn_cnt,
        slow_request_count=slow_cnt,
        total_requests_in_window=total_req,
        sample_error_messages=list(set(all_errors))[:5],
        log_anomaly_count=len(l),
        error_rate_pct=error_rate,
        dominant_issue=dominant,
        context_summary=context_summary,
    )