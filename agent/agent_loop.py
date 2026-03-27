"""
agent/agent_loop.py
-------------------
AI Test Engineer / AIOps Agent — Main Loop
==========================================
Orchestrates all components:
  1. Starts metrics collector in background thread
  2. Every AGENT_CYCLE_SECONDS:
     a. Fetches recent metrics
     b. Runs inference (Isolation Forest)
     c. If anomalies detected → builds RCA evidence → calls LLM
     d. Saves RCA results to JSON file for dashboard
  3. Runs until Ctrl+C or stop_event is set

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python agent/agent_loop.py
"""

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on path when running directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.inference import model_store, run_inference
from agent.llm_reasoning import RCAResult, analyze_with_llm, format_rca_for_console
from agent.rca_builder import build_evidence
from metrics.collector import get_recent_metrics, run_collector

# ── Configuration ─────────────────────────────────────────────────────────────
AGENT_CYCLE_SECONDS = 30       # How often to run an inference cycle
METRICS_WINDOW_SIZE = 36       # ~3 min of metrics at 5s sampling
LOG_WINDOW_MINUTES  = 5        # Sliding log window
RCA_OUTPUT_FILE     = Path("logs_store/rca_results.json")  # Dashboard reads this
COOLDOWN_AFTER_RCA  = 60       # seconds to wait after LLM call (avoid spamming)

# Shared state for dashboard integration
_agent_state = {
    "running": False,
    "cycles_completed": 0,
    "anomalies_detected": 0,
    "last_rca": None,                 # RCAResult dict
    "last_cycle_time": None,
    "status_message": "Not started",
}
_state_lock = threading.Lock()

def get_agent_state() -> dict:
    """Thread-safe read of agent state (used by Streamlit dashboard)."""
    with _state_lock:
        return dict(_agent_state)

def _update_state(**kwargs):
    with _state_lock:
        _agent_state.update(kwargs)


# ── RCA persistence ───────────────────────────────────────────────────────────

def _save_rca_result(result: RCAResult):
    """Append RCA result to JSON file for dashboard consumption."""
    RCA_OUTPUT_FILE.parent.mkdir(exist_ok=True)

    # Load existing results
    existing = []
    if RCA_OUTPUT_FILE.exists():
        try:
            with open(RCA_OUTPUT_FILE) as f:
                existing = json.load(f)
        except Exception:
            existing = []

    # Append new result
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

    # Keep last 50 RCA results
    existing = existing[-50:]

    with open(RCA_OUTPUT_FILE, "w") as f:
        json.dump(existing, f, indent=2)


# ── Main agent loop ───────────────────────────────────────────────────────────

def run_agent(stop_event: threading.Event | None = None):
    """
    Main agent loop. Blocks until stop_event is set or KeyboardInterrupt.
    
    Args:
        stop_event: Optional threading.Event to stop from another thread (dashboard).
    """
    print("\n" + "=" * 60)
    print("🤖 AIOps AI Test Engineer — Starting")
    print("=" * 60)

    # Load trained models
    try:
        model_store.load()
    except FileNotFoundError as e:
        print(f"\n[Agent] ERROR: {e}")
        print("[Agent] Run: python agent/train.py   first.\n")
        _update_state(running=False, status_message="Error: models not trained")
        return

    # Start metrics collector in background
    collector_stop = threading.Event()
    collector_thread = threading.Thread(
        target=run_collector,
        args=(collector_stop,),
        name="MetricsCollector",
        daemon=True,
    )
    collector_thread.start()

    _update_state(running=True, status_message="Running — monitoring active")
    print(f"[Agent] Cycle interval: {AGENT_CYCLE_SECONDS}s | Log window: {LOG_WINDOW_MINUTES}min")
    print("[Agent] Press Ctrl+C to stop.\n")

    last_rca_time = 0.0   # epoch seconds of last LLM call

    while True:
        # Check external stop signal (from dashboard)
        if stop_event and stop_event.is_set():
            print("[Agent] Stop signal received. Shutting down.")
            break

        cycle_start = time.time()

        try:
            print(f"\n[Agent] ── Cycle #{_agent_state['cycles_completed'] + 1} "
                  f"@ {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC ──")

            # 1. Fetch recent metrics from in-memory store
            recent_metrics = get_recent_metrics(METRICS_WINDOW_SIZE)
            print(f"[Agent] Fetched {len(recent_metrics)} metric samples")

            # 2. Run ML inference
            report = run_inference(recent_metrics, LOG_WINDOW_MINUTES)

            if not report.has_anomalies:
                print("[Agent] ✅ No anomalies detected. System healthy.")
                _update_state(
                    status_message="Healthy — no anomalies",
                    last_cycle_time=datetime.now(timezone.utc).isoformat(),
                )
            else:
                n_metric = len(report.metric_anomalies)
                n_log = len(report.log_anomalies)
                print(f"[Agent] ⚠️  Anomalies detected: {n_metric} metric, {n_log} log")

                # 3. Build structured RCA evidence
                evidence = build_evidence(report)

                # Increment counter
                with _state_lock:
                    _agent_state["anomalies_detected"] += 1

                if evidence is None:
                    print("[Agent] Evidence builder returned None (edge case). Skipping.")
                else:
                    print(f"[Agent] Severity: {evidence.severity} | Issue: {evidence.dominant_issue}")

                    # 4. Call LLM (with cooldown to avoid spam)
                    time_since_rca = time.time() - last_rca_time
                    if time_since_rca >= COOLDOWN_AFTER_RCA:
                        try:
                            rca_result = analyze_with_llm(evidence)
                            last_rca_time = time.time()

                            # Print to console
                            print(format_rca_for_console(rca_result))

                            # Save to file for dashboard
                            _save_rca_result(rca_result)

                            # Update shared state
                            _update_state(
                                last_rca={
                                    "timestamp": rca_result.timestamp,
                                    "severity": rca_result.severity,
                                    "root_cause": rca_result.root_cause,
                                    "confidence": rca_result.confidence,
                                },
                                status_message=f"RCA completed — {rca_result.severity} severity",
                                last_cycle_time=datetime.now(timezone.utc).isoformat(),
                            )
                        except Exception as e:
                            print(f"[Agent] LLM call failed: {e}")
                            _update_state(status_message=f"LLM error: {e}")
                    else:
                        remaining = int(COOLDOWN_AFTER_RCA - time_since_rca)
                        print(f"[Agent] LLM cooldown: {remaining}s remaining. Skipping RCA call.")
                        _update_state(status_message=f"Anomaly detected (LLM cooldown {remaining}s)")

        except KeyboardInterrupt:
            print("\n[Agent] Interrupted by user.")
            break
        except Exception as e:
            print(f"[Agent] Unexpected error in cycle: {e}")
            import traceback
            traceback.print_exc()

        # Update cycle counter
        with _state_lock:
            _agent_state["cycles_completed"] += 1
            _agent_state["last_cycle_time"] = datetime.now(timezone.utc).isoformat()

        # Sleep until next cycle (accounting for processing time)
        elapsed = time.time() - cycle_start
        sleep_time = max(0, AGENT_CYCLE_SECONDS - elapsed)
        print(f"[Agent] Cycle done in {elapsed:.1f}s. Next cycle in {sleep_time:.0f}s.")

        # Interruptible sleep
        for _ in range(int(sleep_time)):
            if stop_event and stop_event.is_set():
                break
            time.sleep(1)

    # Cleanup
    collector_stop.set()
    _update_state(running=False, status_message="Stopped")
    print("[Agent] Stopped. Goodbye.")


if __name__ == "__main__":
    run_agent()