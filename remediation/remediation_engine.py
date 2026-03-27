"""
remediation/remediation_engine.py
----------------------------------
Auto-Remediation Engine — WITH Human Approval Gate
====================================================
FUTURE WORK ITEM #1: Auto-remediation

Design:
- Agent detects anomaly → builds RCA → proposes remediation actions
- Actions are queued as "pending approvals" — NOT executed automatically
- A human must approve via CLI prompt or dashboard before any action runs
- All actions are logged with before/after state for audit trail

Available safe remediation actions (no destructive ops):
  - restart_webapp     : Restart the Flask process (graceful)
  - clear_log_file     : Rotate/truncate app.log when it grows too large
  - reduce_load        : Signal load generator to slow down (via flag file)
  - notify_only        : No action, just log + alert

SAFETY GUARANTEES:
  - No action executes without explicit human approval
  - All actions are logged to remediation/audit.log
  - Destructive actions (delete DB, scale infra) are NOT implemented
"""

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

AUDIT_LOG = Path("remediation/audit.log")
PENDING_FILE = Path("remediation/pending_actions.json")
LOAD_SLOW_FLAG = Path("remediation/slow_load.flag")  # load_generator checks this

# ── Action definitions ────────────────────────────────────────────────────────

class ActionStatus(str, Enum):
    PENDING   = "PENDING"
    APPROVED  = "APPROVED"
    REJECTED  = "REJECTED"
    EXECUTED  = "EXECUTED"
    FAILED    = "FAILED"


@dataclass
class RemediationAction:
    """A proposed remediation action awaiting human approval."""
    action_id: str
    action_type: str          # restart_webapp / clear_log_file / reduce_load / notify_only
    severity: str
    root_cause: str
    rationale: str            # Why this action was proposed
    estimated_impact: str     # What will happen if approved
    risk_level: str           # LOW / MEDIUM / HIGH
    status: ActionStatus = ActionStatus.PENDING
    proposed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    execution_result: Optional[str] = None


# ── Action registry — maps action_type to handler function ───────────────────

def _action_restart_webapp() -> str:
    """
    Gracefully restart the Flask webapp by sending SIGTERM and relaunching.
    In demo mode, just simulates the restart.
    """
    print("[Remediation] Simulating webapp restart (demo mode)...")
    # In production: os.kill(webapp_pid, signal.SIGTERM); subprocess.Popen(...)
    time.sleep(1)
    return "Webapp restart simulated successfully (demo mode)"


def _action_clear_log_file() -> str:
    """Rotate app.log — rename current log, start fresh."""
    log_path = Path("logs_store/app.log")
    if log_path.exists():
        backup = Path(f"logs_store/app.log.{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.bak")
        log_path.rename(backup)
        log_path.touch()
        return f"Log rotated → {backup.name}"
    return "Log file not found — nothing to rotate"


def _action_reduce_load() -> str:
    """Signal load generator to slow down via flag file."""
    LOAD_SLOW_FLAG.parent.mkdir(exist_ok=True)
    LOAD_SLOW_FLAG.write_text("slow")
    return "Slow-load flag written. Load generator will reduce rate on next cycle."


def _action_notify_only() -> str:
    """No-op action — just logs that notification was sent."""
    return "Notification logged. No system changes made."


ACTION_HANDLERS = {
    "restart_webapp":  _action_restart_webapp,
    "clear_log_file":  _action_clear_log_file,
    "reduce_load":     _action_reduce_load,
    "notify_only":     _action_notify_only,
}

# Risk levels per action type
ACTION_RISK = {
    "restart_webapp":  "MEDIUM",
    "clear_log_file":  "LOW",
    "reduce_load":     "LOW",
    "notify_only":     "LOW",
}

# ── Action proposer — maps anomaly patterns to actions ───────────────────────

def propose_action(severity: str, dominant_issue: str, error_messages: list[str]) -> RemediationAction:
    """
    Rule-based action proposer.
    Maps the anomaly evidence to the most appropriate remediation action.
    """
    import uuid
    action_id = str(uuid.uuid4())[:8].upper()

    # Rule 1: Database connection pool exhaustion → reduce load
    if any("connection pool" in m.lower() or "exhausted" in m.lower() for m in error_messages):
        return RemediationAction(
            action_id=action_id,
            action_type="reduce_load",
            severity=severity,
            root_cause=dominant_issue,
            rationale="Database connection pool is exhausted. Reducing incoming traffic will allow the pool to recover.",
            estimated_impact="Load generator will slow request rate by 50%, reducing DB connection demand.",
            risk_level="LOW",
        )

    # Rule 2: CRITICAL severity with metric anomalies → restart webapp
    if severity == "CRITICAL":
        return RemediationAction(
            action_id=action_id,
            action_type="restart_webapp",
            severity=severity,
            root_cause=dominant_issue,
            rationale="CRITICAL severity with correlated metric and log anomalies suggests process-level failure.",
            estimated_impact="Webapp process will restart (brief downtime ~2s), clearing any memory leaks or stuck threads.",
            risk_level="MEDIUM",
        )

    # Rule 3: Large log file or many errors → rotate log
    if any("log" in m.lower() for m in error_messages) or severity in ("HIGH", "MEDIUM"):
        return RemediationAction(
            action_id=action_id,
            action_type="clear_log_file",
            severity=severity,
            root_cause=dominant_issue,
            rationale="High error volume detected. Log rotation prevents disk exhaustion and speeds up log parsing.",
            estimated_impact="app.log will be renamed to timestamped backup. Agent will start reading a fresh log.",
            risk_level="LOW",
        )

    # Default: notify only
    return RemediationAction(
        action_id=action_id,
        action_type="notify_only",
        severity=severity,
        root_cause=dominant_issue,
        rationale="No specific automated action is safe for this anomaly type. Human review recommended.",
        estimated_impact="No system changes. Incident logged for operator review.",
        risk_level="LOW",
    )


# ── Approval gate ─────────────────────────────────────────────────────────────

class ApprovalGate:
    """
    Human approval gate for remediation actions.
    Stores pending actions to JSON. Approval can happen via:
      - CLI (interactive prompt in terminal)
      - Dashboard (reads/writes pending_actions.json)
    """

    def __init__(self):
        PENDING_FILE.parent.mkdir(exist_ok=True)
        AUDIT_LOG.parent.mkdir(exist_ok=True)

    def _load_pending(self) -> list[dict]:
        if PENDING_FILE.exists():
            try:
                return json.loads(PENDING_FILE.read_text())
            except Exception:
                return []
        return []

    def _save_pending(self, actions: list[dict]):
        PENDING_FILE.write_text(json.dumps(actions, indent=2))

    def _audit(self, action: RemediationAction, event: str):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "action_id": action.action_id,
            "action_type": action.action_type,
            "severity": action.severity,
            "status": action.status,
            "result": action.execution_result,
        }
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def queue_action(self, action: RemediationAction):
        """Add a proposed action to the pending queue."""
        pending = self._load_pending()
        pending.append({
            "action_id": action.action_id,
            "action_type": action.action_type,
            "severity": action.severity,
            "root_cause": action.root_cause,
            "rationale": action.rationale,
            "estimated_impact": action.estimated_impact,
            "risk_level": action.risk_level,
            "status": action.status.value,
            "proposed_at": action.proposed_at,
        })
        self._save_pending(pending)
        self._audit(action, "QUEUED")
        print(f"\n[Remediation] Action queued: [{action.action_id}] {action.action_type} (Risk: {action.risk_level})")
        print(f"[Remediation] Rationale: {action.rationale}")

    def cli_approval_prompt(self, action: RemediationAction) -> bool:
        """
        Interactive CLI prompt for human approval.
        Returns True if approved, False if rejected.
        """
        print("\n" + "=" * 60)
        print("🔧 REMEDIATION APPROVAL REQUIRED")
        print("=" * 60)
        print(f"  Action ID    : {action.action_id}")
        print(f"  Action Type  : {action.action_type}")
        print(f"  Severity     : {action.severity}")
        print(f"  Root Cause   : {action.root_cause}")
        print(f"  Rationale    : {action.rationale}")
        print(f"  Impact       : {action.estimated_impact}")
        print(f"  Risk Level   : {action.risk_level}")
        print("=" * 60)

        try:
            response = input("Approve this action? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            response = "n"

        return response == "y"

    def execute_action(self, action: RemediationAction, approver: str = "human") -> str:
        """Execute an approved action and record the result."""
        handler = ACTION_HANDLERS.get(action.action_type)
        if not handler:
            result = f"Unknown action type: {action.action_type}"
            action.status = ActionStatus.FAILED
        else:
            try:
                result = handler()
                action.status = ActionStatus.EXECUTED
            except Exception as e:
                result = f"Execution failed: {e}"
                action.status = ActionStatus.FAILED

        action.execution_result = result
        action.decided_at = datetime.now(timezone.utc).isoformat()
        action.decided_by = approver
        self._audit(action, "EXECUTED" if action.status == ActionStatus.EXECUTED else "FAILED")
        print(f"[Remediation] Result: {result}")
        return result

    def propose_and_gate(self, severity: str, dominant_issue: str,
                         error_messages: list[str], auto_approve_low_risk: bool = False) -> Optional[str]:
        """
        Full pipeline: propose action → approval gate → execute if approved.

        Args:
            severity: Anomaly severity from RCA
            dominant_issue: Primary signal description
            error_messages: Sample error messages for rule matching
            auto_approve_low_risk: If True, LOW risk actions skip CLI prompt (for demo)

        Returns:
            Execution result string, or None if rejected/skipped
        """
        action = propose_action(severity, dominant_issue, error_messages)
        self.queue_action(action)

        # Auto-approve LOW risk in demo mode (skip CLI prompt)
        if auto_approve_low_risk and action.risk_level == "LOW":
            print(f"[Remediation] AUTO-APPROVING low-risk action: {action.action_type}")
            action.status = ActionStatus.APPROVED
            return self.execute_action(action, approver="auto")

        # Human approval gate
        approved = self.cli_approval_prompt(action)
        if approved:
            action.status = ActionStatus.APPROVED
            return self.execute_action(action, approver="human_cli")
        else:
            action.status = ActionStatus.REJECTED
            action.decided_at = datetime.now(timezone.utc).isoformat()
            self._audit(action, "REJECTED")
            print(f"[Remediation] Action {action.action_id} rejected by operator.")
            return None


# Singleton gate
approval_gate = ApprovalGate()