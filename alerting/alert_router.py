"""
alerting/alert_router.py
-------------------------
Alert Routing Module
====================
FUTURE WORK ITEM #4: Alert routing

Routes CRITICAL and HIGH severity alerts to:
  - Slack (via Incoming Webhook)
  - PagerDuty (via Events API v2)
  - Console (always, as fallback)

Configuration via environment variables:
  SLACK_WEBHOOK_URL       = https://hooks.slack.com/services/...
  PAGERDUTY_ROUTING_KEY   = your-pd-routing-key
  ALERT_MIN_SEVERITY      = HIGH   (minimum severity to route, default=HIGH)

Deduplication: Alerts with the same dominant_issue are deduplicated
within a 10-minute window to avoid flooding channels.
"""

import hashlib
import json
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ALERT_LOG        = Path("alerting/alert_history.json")
DEDUP_WINDOW_SEC = 600   # 10 minutes dedup window

# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class Alert:
    severity: str
    dominant_issue: str
    root_cause: str
    explanation: str
    suggested_fixes: list[str]
    confidence: str
    timestamp: str
    metric_evidence: dict


# ── Deduplication ─────────────────────────────────────────────────────────────

class AlertDeduplicator:
    """Prevents sending duplicate alerts for the same issue within a time window."""

    def __init__(self):
        self._sent: dict[str, float] = {}  # key → epoch time

    def _key(self, alert: Alert) -> str:
        raw = f"{alert.severity}:{alert.dominant_issue[:40]}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def should_send(self, alert: Alert) -> bool:
        key = self._key(alert)
        now = time.time()
        last_sent = self._sent.get(key, 0)
        if now - last_sent >= DEDUP_WINDOW_SEC:
            self._sent[key] = now
            return True
        remaining = int(DEDUP_WINDOW_SEC - (now - last_sent))
        print(f"[Alerting] Dedup suppressed — same issue alerted {DEDUP_WINDOW_SEC - remaining}s ago")
        return False


_dedup = AlertDeduplicator()


# ── Formatters ────────────────────────────────────────────────────────────────

def _severity_emoji(sev: str) -> str:
    return {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(sev, "⚪")


def _slack_payload(alert: Alert) -> dict:
    """Build Slack Block Kit message payload."""
    emoji = _severity_emoji(alert.severity)
    fixes_text = "\n".join(f"• {f}" for f in alert.suggested_fixes[:3])
    return {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} AIOps Alert — {alert.severity} Severity"
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Issue:*\n{alert.dominant_issue}"},
                    {"type": "mrkdwn", "text": f"*Confidence:*\n{alert.confidence}"},
                    {"type": "mrkdwn", "text": f"*Timestamp:*\n{alert.timestamp[:19]} UTC"},
                    {"type": "mrkdwn", "text": f"*CPU Peak:*\n{alert.metric_evidence.get('max_cpu_pct', 'N/A')}%"},
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Root Cause:*\n{alert.root_cause}"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Suggested Fixes:*\n{fixes_text}"}
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "⚠️ No auto-remediation performed. Human action required."}]
            }
        ]
    }


def _pagerduty_payload(alert: Alert, routing_key: str) -> dict:
    """Build PagerDuty Events API v2 payload."""
    severity_map = {"CRITICAL": "critical", "HIGH": "error",
                    "MEDIUM": "warning", "LOW": "info"}
    return {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": f"aiops-{alert.dominant_issue[:40].replace(' ', '-')}",
        "payload": {
            "summary": f"[{alert.severity}] {alert.dominant_issue}",
            "source": "aiops-agent",
            "severity": severity_map.get(alert.severity, "warning"),
            "timestamp": alert.timestamp,
            "custom_details": {
                "root_cause": alert.root_cause,
                "suggested_fixes": alert.suggested_fixes,
                "confidence": alert.confidence,
                "cpu_peak": alert.metric_evidence.get("max_cpu_pct"),
                "error_rate": alert.metric_evidence.get("error_rate_pct"),
            }
        }
    }


# ── Senders ───────────────────────────────────────────────────────────────────

def _http_post(url: str, payload: dict, headers: dict) -> bool:
    """Simple HTTP POST without requests library dependency."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201, 202)
    except urllib.error.HTTPError as e:
        print(f"[Alerting] HTTP error: {e.code} {e.reason}")
        return False
    except Exception as e:
        print(f"[Alerting] Network error: {e}")
        return False


def send_slack(alert: Alert) -> bool:
    """Send alert to Slack via Incoming Webhook."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("[Alerting] SLACK_WEBHOOK_URL not set — skipping Slack alert")
        return False

    payload = _slack_payload(alert)
    success = _http_post(webhook_url, payload, {"Content-Type": "application/json"})
    if success:
        print(f"[Alerting] ✅ Slack alert sent: [{alert.severity}] {alert.dominant_issue}")
    return success


def send_pagerduty(alert: Alert) -> bool:
    """Send alert to PagerDuty via Events API v2."""
    routing_key = os.environ.get("PAGERDUTY_ROUTING_KEY")
    if not routing_key:
        print("[Alerting] PAGERDUTY_ROUTING_KEY not set — skipping PagerDuty alert")
        return False

    payload = _pagerduty_payload(alert, routing_key)
    success = _http_post(
        "https://events.pagerduty.com/v2/enqueue",
        payload,
        {"Content-Type": "application/json", "Accept": "application/json"}
    )
    if success:
        print(f"[Alerting] ✅ PagerDuty alert sent: [{alert.severity}] {alert.dominant_issue}")
    return success


def _log_alert(alert: Alert, channels_sent: list[str]):
    """Persist alert to local history log."""
    ALERT_LOG.parent.mkdir(exist_ok=True)
    history = []
    if ALERT_LOG.exists():
        try:
            history = json.loads(ALERT_LOG.read_text())
        except Exception:
            history = []

    history.append({
        "timestamp": alert.timestamp,
        "severity": alert.severity,
        "dominant_issue": alert.dominant_issue,
        "root_cause": alert.root_cause,
        "channels_sent": channels_sent,
    })
    ALERT_LOG.write_text(json.dumps(history[-100:], indent=2))


# ── Main router ───────────────────────────────────────────────────────────────

class AlertRouter:
    """
    Routes RCA results to configured alert channels.
    Usage:
        router = AlertRouter()
        router.route(rca_result)
    """

    def __init__(self):
        # Minimum severity to trigger alerts (configurable via env var)
        min_sev = os.environ.get("ALERT_MIN_SEVERITY", "HIGH")
        self.severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        self.min_rank = self.severity_rank.get(min_sev, 3)

    def _should_alert(self, severity: str) -> bool:
        return self.severity_rank.get(severity, 0) >= self.min_rank

    def route(self, rca_result) -> list[str]:
        """
        Route an RCA result to appropriate alert channels.

        Args:
            rca_result: RCAResult from llm_reasoning.py

        Returns:
            List of channels that were successfully notified.
        """
        if not self._should_alert(rca_result.severity):
            print(f"[Alerting] Severity {rca_result.severity} below threshold — no alert sent")
            return []

        alert = Alert(
            severity=rca_result.severity,
            dominant_issue=rca_result.dominant_issue,
            root_cause=rca_result.root_cause,
            explanation=rca_result.explanation,
            suggested_fixes=rca_result.suggested_fixes,
            confidence=rca_result.confidence,
            timestamp=rca_result.timestamp,
            metric_evidence=rca_result.raw_evidence,
        )

        # Dedup check
        if not _dedup.should_send(alert):
            return []

        print(f"\n[Alerting] Routing {alert.severity} alert: {alert.dominant_issue}")

        channels_sent = []
        # Always log to console
        print(f"[Alerting] 📢 ALERT: [{alert.severity}] {alert.dominant_issue}")
        print(f"[Alerting]    Root Cause: {alert.root_cause}")
        channels_sent.append("console")

        # Send to Slack if configured
        if send_slack(alert):
            channels_sent.append("slack")

        # Send to PagerDuty if configured
        if send_pagerduty(alert):
            channels_sent.append("pagerduty")

        _log_alert(alert, channels_sent)
        return channels_sent


# Singleton router
alert_router = AlertRouter()