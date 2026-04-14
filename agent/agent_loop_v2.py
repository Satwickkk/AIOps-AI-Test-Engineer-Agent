"""
agent/agent_loop_v2.py
-----------------------
AIOps Agent Loop v2 — All Future Work Items Integrated
=======================================================
Integrates all 8 future work modules:
  1. Remediation engine     (with human approval gate)
  2. Feedback learning      (fix outcome tracking)
  3. Multi-service support  (extensible endpoint monitoring)
  4. Alert routing          (Slack / PagerDuty)
  5. Historical baseline    (Rolling Z-score + Isolation Forest)
  6. Causal inference       (do-calculus inspired analysis)
  7. RLHF loop              (prompt tuning from feedback)
  8. Vector store memory    (similar incident retrieval)

Usage:
    export GROQ_API_KEY=gsk_...
    export SLACK_WEBHOOK_URL=https://hooks.slack.com/...   (optional)
    export PAGERDUTY_ROUTING_KEY=...                        (optional)
    python agent/agent_loop_v2.py
"""

import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Core modules
from agent.inference import model_store, run_inference
from agent.rca_builder import build_evidence
from agent.llm_reasoning import analyze_with_llm, format_rca_for_console

# NEW: Future work modules
from agent.baseline_detector import rolling_detector, combine_detectors
from agent.causal_inference import analyze_causality, format_causal_for_prompt
from alerting.alert_router import alert_router
from feedback.feedback_learning import feedback_store
from feedback.rlhf_loop import prompt_tuner
from memory.vector_memory import incident_memory
from remediation.remediation_engine import approval_gate
from metrics.collector import get_recent_metrics, run_collector

# ── Configuration ─────────────────────────────────────────────────────────────
AGENT_CYCLE_SECONDS  = 30
METRICS_WINDOW_SIZE  = 36        # 36 × 5s = 3 min
LOG_WINDOW_MINUTES   = 5
RCA_OUTPUT_FILE      = Path("logs_store/rca_results.json")
COOLDOWN_AFTER_RCA   = 60        # seconds between LLM calls
FEEDBACK_DELAY       = 120       # seconds after RCA before asking for feedback
ENABLE_REMEDIATION   = True      # Set False to disable remediation prompts
AUTO_APPROVE_LOW_RISK = False     # Set True for demo (skips CLI prompt for LOW risk)

# Shared state
_agent_state = {
    "running": False,
    "cycles_completed": 0,
    "anomalies_detected": 0,
    "rca_count": 0,
    "last_rca": None,
    "last_cycle_time": None,
    "status_message": "Not started",
    "memory_stats": {},
    "baseline_stats": {},
}
_state_lock = threading.Lock()


def get_agent_state() -> dict:
    with _state_lock:
        return dict(_agent_state)


def _update_state(**kwargs):
    with _state_lock:
        _agent_state.update(kwargs)


# ── RCA persistence ────────────────────────────────────────────────────────────

def _save_rca_result(result):
    RCA_OUTPUT_FILE.parent.mkdir(exist_ok=True)
    existing = []
    if RCA_OUTPUT_FILE.exists():
        try:
            existing = json.loads(RCA_OUTPUT_FILE.read_text())
        except Exception:
            existing = []

    entry = {
        "timestamp": result.timestamp,
        "severity": result.severity,
        "confidence": result.confidence,
        "dominant_issue": result.dominant_issue,
        "root_cause": result.root_cause,
        "explanation": result.explanation,
        "suggested_fixes": result.suggested_fixes,
        "prevention_steps": result.prevention_steps,
        "raw_evidence": result.raw_evidence,
    }
    existing.append(entry)
    RCA_OUTPUT_FILE.write_text(json.dumps(existing[-50:], indent=2))


# ── Enhanced LLM call with all context injected ───────────────────────────────

def _call_llm_with_full_context(evidence, recent_metrics: list) -> object:
    """
    Calls the LLM with enriched context from:
      - RLHF-tuned prompt components
      - Similar past incidents (vector memory)
      - Causal analysis
      - Feedback history context
    """
    # 1. Get RLHF-tuned prompt config
    prompt_parts = prompt_tuner.get_current_prompt_parts()

    # 2. Retrieve similar incidents from vector memory
    similar = incident_memory.search(
        evidence.dominant_issue,
        n=3
    )
    memory_context = incident_memory.format_for_prompt(similar)

    # 3. Run causal analysis
    causal = analyze_causality(evidence.raw_evidence if hasattr(evidence, 'raw_evidence')
                               else vars(evidence))
    causal_context = format_causal_for_prompt(causal)

    # 4. Get historical feedback context
    history_context = feedback_store.get_historical_context(evidence.dominant_issue)

    # Inject all context into evidence object for LLM
    # We extend the context_summary with additional context
    original_summary = evidence.context_summary
    extra_context = "\n".join(filter(None, [
        memory_context,
        causal_context,
        history_context,
    ]))
    if extra_context:
        evidence.context_summary = original_summary + "\n\n" + extra_context

    print(f"[Agent v2] LLM context enriched:")
    print(f"  - Similar incidents: {len(similar)}")
    print(f"  - Causal chain: {' → '.join(causal.causal_chain) if causal.causal_chain else 'N/A'}")
    print(f"  - RLHF config: {prompt_parts['config_hash']}")

    result = analyze_with_llm(evidence)

    # Restore original summary
    evidence.context_summary = original_summary
    return result, prompt_parts["config_hash"]


# ── Main agent loop v2 ────────────────────────────────────────────────────────

def run_agent_v2(stop_event: threading.Event = None):
    """
    Full AIOps Agent v2 with all future work items integrated.
    """
    print("\n" + "=" * 70)
    print("🤖 AIOps AI Test Engineer v2 — Starting (All Modules Active)")
    print("=" * 70)
    print("Active modules:")
    print("  ✅ Isolation Forest anomaly detection")
    print("  ✅ Rolling Z-score baseline detector")
    print("  ✅ Causal inference (do-calculus inspired)")
    print("  ✅ Vector memory store (similar incident retrieval)")
    print("  ✅ RLHF prompt tuning")
    print("  ✅ Alert routing (Slack/PagerDuty if configured)")
    print("  ✅ Human-approval remediation engine")
    print("  ✅ Feedback learning")
    print("=" * 70)

    # Load trained models
    try:
        model_store.load()
    except FileNotFoundError as e:
        print(f"\n[Agent v2] ERROR: {e}")
        print("[Agent v2] Run: python agent/train.py  first.\n")
        return

    # Start metrics collector in background
    collector_stop = threading.Event()
    threading.Thread(
        target=run_collector, args=(collector_stop,),
        name="MetricsCollector", daemon=True
    ).start()

    _update_state(running=True, status_message="Running — v2 active")
    print(f"[Agent v2] Cycle: {AGENT_CYCLE_SECONDS}s | Log window: {LOG_WINDOW_MINUTES}min\n")

    last_rca_time = 0.0
    last_feedback_rca = None   # RCA result awaiting feedback collection

    while True:
        if stop_event and stop_event.is_set():
            break

        cycle_start = time.time()
        cycle_num = _agent_state["cycles_completed"] + 1

        try:
            print(f"\n[Agent v2] ── Cycle #{cycle_num} @ "
                  f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC ──")

            # ── 1. Collect metrics ──────────────────────────────────────────
            recent_metrics = get_recent_metrics(METRICS_WINDOW_SIZE)
            print(f"[Agent v2] Fetched {len(recent_metrics)} metric samples")

            # ── 2. Update rolling Z-score baseline ─────────────────────────
            if recent_metrics:
                latest = recent_metrics[-1]
                rolling_detector.add_sample(latest)
                zscore_report = rolling_detector.check_latest()
                baseline_stats = rolling_detector.get_current_baselines()
                _update_state(baseline_stats=baseline_stats)
                if zscore_report.has_anomalies:
                    print(f"[Agent v2] Z-score: {zscore_report.anomaly_summary}")
            else:
                zscore_report = None

            # ── 3. Run Isolation Forest inference ───────────────────────────
            report = run_inference(recent_metrics, LOG_WINDOW_MINUTES)

            # ── 4. Combine detectors (OR mode = more sensitive) ─────────────
            iforest_anomaly = report.has_anomalies
            zscore_anomaly  = zscore_report.has_anomalies if zscore_report else False
            combined_anomaly = combine_detectors(iforest_anomaly, zscore_report or type('R', (), {'has_anomalies': False})(), mode="OR")

            # ── 5. Handle pending feedback (non-blocking) ───────────────────
            if last_feedback_rca and (time.time() - last_rca_time) > FEEDBACK_DELAY:
                print(f"\n[Agent v2] Collecting feedback for last RCA...")
                fb = feedback_store.collect_cli_feedback(last_feedback_rca)
                if fb:
                    # Update vector memory outcome
                    incident_memory.update_outcome(
                        last_feedback_rca.timestamp[:8], fb.outcome
                    )
                    # Update RLHF scores
                    if hasattr(last_feedback_rca, '_prompt_hash'):
                        prompt_tuner.record_outcome(last_feedback_rca._prompt_hash, fb.outcome)
                last_feedback_rca = None

            if not combined_anomaly:
                print("[Agent v2] ✅ No anomalies (both detectors clean). System healthy.")
                _update_state(status_message="Healthy", last_cycle_time=datetime.now(timezone.utc).isoformat())
            else:
                # ── 6. Build RCA evidence ────────────────────────────────────
                evidence = build_evidence(report)
                with _state_lock:
                    _agent_state["anomalies_detected"] += 1

                if not evidence:
                    print("[Agent v2] Evidence builder returned None.")
                else:
                    print(f"[Agent v2] ⚠️  Severity: {evidence.severity} | {evidence.dominant_issue}")

                    # Z-score enrichment: add to context if z-score also fired
                    if zscore_anomaly and zscore_report:
                        evidence.context_summary += f" Z-score also flagged: {zscore_report.anomaly_summary}."

                    # ── 7. LLM call (with cooldown) ──────────────────────────
                    time_since_rca = time.time() - last_rca_time
                    if time_since_rca >= COOLDOWN_AFTER_RCA:
                        try:
                            rca_result, prompt_hash = _call_llm_with_full_context(evidence, recent_metrics)
                            rca_result._prompt_hash = prompt_hash
                            last_rca_time = time.time()

                            print(format_rca_for_console(rca_result))
                            _save_rca_result(rca_result)

                            # ── 8. Store in vector memory ─────────────────────
                            incident_memory.add_incident(rca_result)

                            # ── 9. Route alerts ───────────────────────────────
                            channels = alert_router.route(rca_result)
                            if channels:
                                print(f"[Agent v2] Alerts sent to: {', '.join(channels)}")

                            # ── 10. Propose remediation ───────────────────────
                            if ENABLE_REMEDIATION:
                                approval_gate.propose_and_gate(
                                    severity=rca_result.severity,
                                    dominant_issue=rca_result.dominant_issue,
                                    error_messages=evidence.sample_error_messages,
                                    auto_approve_low_risk=AUTO_APPROVE_LOW_RISK,
                                )

                            # Queue for feedback collection next cycle
                            last_feedback_rca = rca_result

                            with _state_lock:
                                _agent_state["rca_count"] += 1
                                _agent_state["last_rca"] = {
                                    "timestamp": rca_result.timestamp,
                                    "severity": rca_result.severity,
                                    "root_cause": rca_result.root_cause,
                                    "confidence": rca_result.confidence,
                                }

                            _update_state(
                                status_message=f"RCA done — {rca_result.severity}",
                                last_cycle_time=datetime.now(timezone.utc).isoformat(),
                                memory_stats=incident_memory.stats(),
                            )

                        except Exception as e:
                            print(f"[Agent v2] LLM call failed: {e}")
                            import traceback; traceback.print_exc()
                    else:
                        remaining = int(COOLDOWN_AFTER_RCA - time_since_rca)
                        print(f"[Agent v2] LLM cooldown: {remaining}s remaining.")

        except KeyboardInterrupt:
            print("\n[Agent v2] Interrupted.")
            break
        except Exception as e:
            print(f"[Agent v2] Cycle error: {e}")
            import traceback; traceback.print_exc()

        with _state_lock:
            _agent_state["cycles_completed"] += 1
            _agent_state["last_cycle_time"] = datetime.now(timezone.utc).isoformat()

        elapsed = time.time() - cycle_start
        sleep_time = max(0, AGENT_CYCLE_SECONDS - elapsed)
        print(f"[Agent v2] Cycle done in {elapsed:.1f}s. Next in {sleep_time:.0f}s.")

        for _ in range(int(sleep_time)):
            if stop_event and stop_event.is_set():
                break
            time.sleep(1)

    collector_stop.set()
    _update_state(running=False, status_message="Stopped")
    print("[Agent v2] Stopped.")

    # Print final reports
    print("\n" + feedback_store.get_effectiveness_report())
    print("\n" + prompt_tuner.get_performance_report())


if __name__ == "__main__":
    run_agent_v2()