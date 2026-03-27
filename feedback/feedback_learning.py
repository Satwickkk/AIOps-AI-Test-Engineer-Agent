"""
feedback/feedback_learning.py
------------------------------
Feedback Learning Module
========================
FUTURE WORK ITEM #2: Feedback learning

Tracks whether suggested fixes actually resolved incidents.
Uses feedback to:
  1. Improve LLM prompt quality over time (prompt scoring)
  2. Build a fix effectiveness database
  3. Provide historical context in future RCA prompts

Feedback loop:
  Anomaly detected → RCA generated → Fix suggested → Human marks outcome
  → Outcome stored → Next RCA prompt includes "what worked before"

Storage: feedback/feedback_store.json
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

FEEDBACK_STORE = Path("feedback/feedback_store.json")
PROMPT_SCORES  = Path("feedback/prompt_scores.json")


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class FixFeedback:
    """Records the outcome of a suggested fix."""
    feedback_id: str
    rca_timestamp: str
    severity: str
    dominant_issue: str
    root_cause: str
    suggested_fixes: list[str]
    applied_fix: str              # Which fix was actually applied
    outcome: str                  # RESOLVED / PARTIALLY_RESOLVED / NOT_RESOLVED / UNKNOWN
    notes: str = ""
    feedback_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolution_time_minutes: Optional[float] = None


@dataclass
class PromptScore:
    """Tracks quality score for a specific prompt pattern."""
    issue_pattern: str            # e.g. "database connection pool"
    total_uses: int = 0
    resolved_count: int = 0
    partial_count: int = 0
    unresolved_count: int = 0

    @property
    def effectiveness_pct(self) -> float:
        if self.total_uses == 0:
            return 0.0
        return round((self.resolved_count + 0.5 * self.partial_count) / self.total_uses * 100, 1)


# ── Feedback store ────────────────────────────────────────────────────────────

class FeedbackStore:
    """
    Persists fix feedback and computes effectiveness metrics.
    Used to enrich future LLM prompts with historical context.
    """

    def __init__(self):
        FEEDBACK_STORE.parent.mkdir(exist_ok=True)
        PROMPT_SCORES.parent.mkdir(exist_ok=True)

    def _load(self) -> list[dict]:
        if FEEDBACK_STORE.exists():
            try:
                return json.loads(FEEDBACK_STORE.read_text())
            except Exception:
                return []
        return []

    def _save(self, records: list[dict]):
        FEEDBACK_STORE.write_text(json.dumps(records, indent=2))

    def record_feedback(self, fb: FixFeedback):
        """Store a feedback record and update prompt scores."""
        records = self._load()
        records.append({
            "feedback_id": fb.feedback_id,
            "rca_timestamp": fb.rca_timestamp,
            "severity": fb.severity,
            "dominant_issue": fb.dominant_issue,
            "root_cause": fb.root_cause,
            "suggested_fixes": fb.suggested_fixes,
            "applied_fix": fb.applied_fix,
            "outcome": fb.outcome,
            "notes": fb.notes,
            "feedback_at": fb.feedback_at,
            "resolution_time_minutes": fb.resolution_time_minutes,
        })
        self._save(records)
        self._update_prompt_scores(fb)
        print(f"[Feedback] Recorded: {fb.outcome} for issue '{fb.dominant_issue}'")

    def _update_prompt_scores(self, fb: FixFeedback):
        """Update effectiveness counters for the issue pattern."""
        scores = {}
        if PROMPT_SCORES.exists():
            try:
                scores = json.loads(PROMPT_SCORES.read_text())
            except Exception:
                scores = {}

        key = fb.dominant_issue.lower()[:50]
        if key not in scores:
            scores[key] = {"total_uses": 0, "resolved_count": 0,
                           "partial_count": 0, "unresolved_count": 0}

        scores[key]["total_uses"] += 1
        if fb.outcome == "RESOLVED":
            scores[key]["resolved_count"] += 1
        elif fb.outcome == "PARTIALLY_RESOLVED":
            scores[key]["partial_count"] += 1
        else:
            scores[key]["unresolved_count"] += 1

        PROMPT_SCORES.write_text(json.dumps(scores, indent=2))

    def get_historical_context(self, dominant_issue: str, n: int = 3) -> str:
        """
        Build a historical context string for the LLM prompt.
        Finds past incidents with similar issues and their outcomes.

        Returns a string like:
        "Similar past incidents:
         - DB pool exhaustion (2024-01-15): Fix 'increase pool size' → RESOLVED in 12min
         - DB pool exhaustion (2024-01-10): Fix 'reduce load' → PARTIALLY_RESOLVED"
        """
        records = self._load()
        if not records:
            return ""

        # Find similar incidents (simple keyword matching)
        keywords = set(dominant_issue.lower().split())
        similar = []
        for r in reversed(records):
            issue_words = set(r.get("dominant_issue", "").lower().split())
            if keywords & issue_words:  # any keyword overlap
                similar.append(r)
            if len(similar) >= n:
                break

        if not similar:
            return ""

        lines = ["Historical context from similar past incidents:"]
        for r in similar:
            ts = r.get("rca_timestamp", "")[:10]
            fix = r.get("applied_fix", "unknown fix")[:60]
            outcome = r.get("outcome", "UNKNOWN")
            mins = r.get("resolution_time_minutes")
            time_str = f" in {mins:.0f}min" if mins else ""
            lines.append(f"  - {ts}: '{fix}' → {outcome}{time_str}")

        return "\n".join(lines)

    def get_effectiveness_report(self) -> str:
        """Return a human-readable effectiveness report."""
        if not PROMPT_SCORES.exists():
            return "No feedback data collected yet."

        try:
            scores = json.loads(PROMPT_SCORES.read_text())
        except Exception:
            return "Could not load scores."

        lines = ["Fix Effectiveness Report", "=" * 40]
        for pattern, s in sorted(scores.items(),
                                  key=lambda x: x[1].get("total_uses", 0), reverse=True):
            total = s.get("total_uses", 0)
            resolved = s.get("resolved_count", 0)
            partial = s.get("partial_count", 0)
            pct = round((resolved + 0.5 * partial) / total * 100, 1) if total > 0 else 0
            lines.append(f"  {pattern[:40]}: {pct}% effective ({total} incidents)")

        return "\n".join(lines)

    def collect_cli_feedback(self, rca_result) -> Optional[FixFeedback]:
        """
        Interactive CLI to collect feedback after an incident.
        Called by agent_loop after a cooldown period.
        """
        print("\n" + "=" * 60)
        print("📋 FEEDBACK COLLECTION — Did the fix resolve the issue?")
        print("=" * 60)
        print(f"  Issue: {rca_result.dominant_issue}")
        print(f"  Root cause: {rca_result.root_cause}")
        print("  Suggested fixes:")
        for i, fix in enumerate(rca_result.suggested_fixes):
            print(f"    {i+1}. {fix}")
        print("=" * 60)

        try:
            outcome_input = input("Outcome? [1=RESOLVED / 2=PARTIAL / 3=NOT_RESOLVED / 4=SKIP]: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

        outcome_map = {"1": "RESOLVED", "2": "PARTIALLY_RESOLVED",
                       "3": "NOT_RESOLVED", "4": None}
        outcome = outcome_map.get(outcome_input)
        if not outcome:
            return None

        try:
            fix_idx = input(f"Which fix was applied? [1-{len(rca_result.suggested_fixes)}, or 0=none]: ").strip()
            fix_idx = int(fix_idx) - 1
            applied = rca_result.suggested_fixes[fix_idx] if 0 <= fix_idx < len(rca_result.suggested_fixes) else "none"
        except Exception:
            applied = "none"

        try:
            mins_str = input("Resolution time in minutes (or Enter to skip): ").strip()
            mins = float(mins_str) if mins_str else None
        except Exception:
            mins = None

        fb = FixFeedback(
            feedback_id=str(uuid.uuid4())[:8],
            rca_timestamp=rca_result.timestamp,
            severity=rca_result.severity,
            dominant_issue=rca_result.dominant_issue,
            root_cause=rca_result.root_cause,
            suggested_fixes=rca_result.suggested_fixes,
            applied_fix=applied,
            outcome=outcome,
            resolution_time_minutes=mins,
        )
        self.record_feedback(fb)
        return fb


# Singleton
feedback_store = FeedbackStore()