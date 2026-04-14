"""
dashboard/app.py
----------------
Streamlit Dashboard — AIOps Agent Control Panel  (v2 + Client Onboarding)
==========================================================================
Tabs:
  1. 📊 Agent Monitor   — live metrics, RCA history, start/stop
  2. 🏢 Client Onboarding — register client servers, verify, see proof

Usage:
    streamlit run dashboard/app.py
"""

import json
import sys
import threading
import time
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.agent_loop import get_agent_state, run_agent
from metrics.collector import get_recent_metrics

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AIOps Agent Dashboard",
    page_icon="🤖",
    layout="wide",
)

RCA_OUTPUT_FILE = Path("logs_store/rca_results.json")

if "agent_thread" not in st.session_state:
    st.session_state.agent_thread = None
if "stop_event" not in st.session_state:
    st.session_state.stop_event = None


# ── Helpers ───────────────────────────────────────────────────────────────────
def load_rca_results() -> list:
    if RCA_OUTPUT_FILE.exists():
        try:
            return json.loads(RCA_OUTPUT_FILE.read_text())
        except Exception:
            return []
    return []


def severity_color(sev: str) -> str:
    return {"CRITICAL":"🔴","HIGH":"🟠","MEDIUM":"🟡","LOW":"🟢","NONE":"⚪"}.get(sev,"⚪")


def is_agent_running() -> bool:
    t = st.session_state.agent_thread
    return t is not None and t.is_alive()


# ── Page title ────────────────────────────────────────────────────────────────
st.title("🤖 AIOps AI Test Engineer — Dashboard")
st.caption("Continuous monitoring | Anomaly detection | LLM-powered RCA | Client onboarding")

# ── TABS ──────────────────────────────────────────────────────────────────────
tab_monitor, tab_client = st.tabs(["📊 Agent Monitor", "🏢 Client Onboarding"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — AGENT MONITOR
# ══════════════════════════════════════════════════════════════════════════════
with tab_monitor:

    st.divider()
    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([1, 1, 3])

    with col_ctrl1:
        if st.button("▶ Start Agent", type="primary", disabled=is_agent_running()):
            stop_event = threading.Event()
            agent_thread = threading.Thread(
                target=run_agent, args=(stop_event,),
                name="AgentLoop", daemon=True,
            )
            st.session_state.stop_event = stop_event
            st.session_state.agent_thread = agent_thread
            agent_thread.start()
            st.success("Agent started!")
            time.sleep(1)
            st.rerun()

    with col_ctrl2:
        if st.button("⏹ Stop Agent", type="secondary", disabled=not is_agent_running()):
            if st.session_state.stop_event:
                st.session_state.stop_event.set()
            st.warning("Stop signal sent.")
            time.sleep(2)
            st.rerun()

    with col_ctrl3:
        state = get_agent_state()
        running_badge = "🟢 RUNNING" if is_agent_running() else "🔴 STOPPED"
        st.markdown(f"**Agent Status:** {running_badge}")
        st.caption(f"Status: {state.get('status_message', 'N/A')}")

    st.divider()
    st.subheader("📊 Agent Statistics")
    stat_cols = st.columns(4)
    stat_cols[0].metric("Cycles Completed",  state.get("cycles_completed", 0))
    stat_cols[1].metric("Anomalies Detected", state.get("anomalies_detected", 0))
    stat_cols[2].metric("Last Cycle",         state.get("last_cycle_time","—")[:19]
                                              if state.get("last_cycle_time") else "—")
    last_rca = state.get("last_rca")
    if last_rca:
        stat_cols[3].metric(f"Last RCA {severity_color(last_rca.get('severity',''))}",
                            last_rca.get("severity","—"), help=last_rca.get("root_cause",""))
    else:
        stat_cols[3].metric("Last RCA", "None yet")

    st.divider()
    st.subheader("📈 Live System Metrics (last 3 min)")
    metrics_data = get_recent_metrics(36)
    if metrics_data:
        df = pd.DataFrame(metrics_data)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.set_index("timestamp").sort_index()
        chart_cols = st.columns(3)
        with chart_cols[0]:
            st.write("**CPU %**")
            st.line_chart(df[["cpu_pct"]], height=150)
        with chart_cols[1]:
            st.write("**Memory %**")
            st.line_chart(df[["mem_pct"]], height=150)
        with chart_cols[2]:
            st.write("**Latency (ms)**")
            st.line_chart(df[["latency_ms"]], height=150)
        latest = metrics_data[-1]
        m1, m2, m3 = st.columns(3)
        m1.metric("CPU",     f"{latest['cpu_pct']}%")
        m2.metric("Memory",  f"{latest['mem_pct']}%")
        m3.metric("Latency", f"{latest['latency_ms']}ms")
    else:
        st.info("No metrics yet. Start the agent or wait for samples.")

    st.divider()
    st.subheader("🔍 Root Cause Analysis Results")
    rca_results = load_rca_results()
    if not rca_results:
        st.info("No RCA results yet.")
    else:
        st.caption(f"Showing {len(rca_results)} RCA report(s) — most recent first")
        for result in reversed(rca_results[-20:]):
            sev  = result.get("severity","UNKNOWN")
            icon = severity_color(sev)
            ts   = result.get("timestamp","")[:19]
            issue= result.get("dominant_issue","Unknown issue")
            conf = result.get("confidence","—")
            with st.expander(f"{icon} [{sev}] {ts} — {issue}  (Confidence: {conf})"):
                tab1, tab2, tab3 = st.tabs(["📋 Root Cause","🛠️ Fixes","📊 Evidence"])
                with tab1:
                    st.markdown(f"**Root Cause:** {result.get('root_cause','—')}")
                    st.markdown("---")
                    st.markdown(f"**Explanation:**\n\n{result.get('explanation','—')}")
                with tab2:
                    st.markdown("**Suggested Fixes** *(No auto-remediation performed)*")
                    for fix in result.get("suggested_fixes", []):
                        st.markdown(f"- {fix}")
                    st.markdown("**Prevention Steps:**")
                    for step in result.get("prevention_steps", []):
                        st.markdown(f"- {step}")
                with tab3:
                    ev = result.get("raw_evidence", {})
                    ev_cols = st.columns(3)
                    ev_cols[0].metric("CPU Peak",     f"{ev.get('max_cpu_pct','—')}%")
                    ev_cols[1].metric("Latency Peak", f"{ev.get('max_latency_ms','—')}ms")
                    ev_cols[2].metric("Error Rate",   f"{ev.get('error_rate_pct','—')}%")
                    for msg in ev.get("error_messages", []):
                        st.code(msg, language=None)

    st.divider()
    if st.checkbox("🔄 Auto-refresh every 15s", value=False):
        time.sleep(15)
        st.rerun()
    st.caption("AIOps Agent | Academic + Industry Demo | No auto-remediation")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — CLIENT ONBOARDING
# ══════════════════════════════════════════════════════════════════════════════
with tab_client:
    from dashboard.client_page import render_client_page
    render_client_page()