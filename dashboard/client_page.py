"""
dashboard/client_page.py
--------------------------
Client Onboarding & Proof Dashboard Page
==========================================
A new tab/page in the Streamlit dashboard where you can:
  1. Register a new client (company name, server, DB, alerts)
  2. Run connection verification with live status
  3. See the PROOF that their server is connected
     (server info, DB tables, log sample, health check)
  4. Start/Stop live monitoring per client
  5. View all registered clients

Add to your existing dashboard/app.py like this:

    from dashboard.client_page import render_client_page
    # In your tab/page section:
    render_client_page()
"""

import json
import time
from pathlib import Path

import streamlit as st

# Lazy import so dashboard still works without client_integration installed
def _get_manager():
    try:
        from client_integration.client_manager import ClientManager
        if "client_manager" not in st.session_state:
            st.session_state.client_manager = ClientManager()
        return st.session_state.client_manager
    except ImportError as e:
        st.error(f"client_integration not installed: {e}")
        return None


def render_client_page():
    """Call this function inside a Streamlit tab to render the full client page."""

    st.header("🏢 Client Server Onboarding")
    st.caption("Register a client's server, verify the connection, and start live monitoring.")

    mgr = _get_manager()
    if not mgr:
        return

    tab_register, tab_clients, tab_proof = st.tabs([
        "➕ Register New Client",
        "📋 All Clients",
        "🔍 Connection Proof",
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — Register New Client
    # ══════════════════════════════════════════════════════════════════════════
    with tab_register:
        st.subheader("Register a New Client")

        with st.form("register_client_form"):
            st.markdown("#### 🏷️ Basic Info")
            col1, col2 = st.columns(2)
            company_name = col1.text_input("Company Name *", placeholder="Acme Corp")
            website_url  = col2.text_input("Website URL *",  placeholder="https://acme.com")

            st.markdown("#### 🖥️ Server / SSH Details")
            c1, c2, c3 = st.columns([3, 1, 2])
            server_host = c1.text_input("Server IP / Hostname *", placeholder="203.0.113.10")
            server_port = c2.number_input("SSH Port", value=22, min_value=1, max_value=65535)
            server_user = c3.text_input("SSH User *", placeholder="ubuntu")

            c4, c5 = st.columns(2)
            ssh_key_path     = c4.text_input("SSH Key Path (optional)", placeholder="~/.ssh/key.pem")
            server_password  = c5.text_input("SSH Password (optional)", type="password")

            st.markdown("#### 📄 App / Log Details")
            ca1, ca2, ca3 = st.columns(3)
            app_log_path     = ca1.text_input("App Log Path", value="/var/log/app/app.log")
            metrics_endpoint = ca2.text_input("Prometheus URL (optional)", placeholder="http://localhost:9090/metrics")
            app_health_url   = ca3.text_input("Health Check URL (optional)", placeholder="https://acme.com/health")

            st.markdown("#### 🗄️ Database Details")
            db_type = st.selectbox("DB Type", ["mysql", "postgres", "mongodb", "sqlite"])
            d1, d2, d3, d4 = st.columns(4)
            db_host     = d1.text_input("DB Host",     value="localhost")
            db_port_map = {"mysql": 3306, "postgres": 5432, "mongodb": 27017, "sqlite": 0}
            db_port     = d2.number_input("DB Port", value=db_port_map.get(db_type, 3306))
            db_name     = d3.text_input("DB Name",     placeholder="acme_db")
            db_user     = d4.text_input("DB User",     placeholder="monitor_user")
            db_password = st.text_input("DB Password", type="password")

            st.markdown("#### 🔔 Alert Channels (optional)")
            al1, al2, al3 = st.columns(3)
            slack_webhook  = al1.text_input("Slack Webhook URL")
            pagerduty_key  = al2.text_input("PagerDuty Routing Key")
            contact_email  = al3.text_input("Contact Email")

            submitted = st.form_submit_button("🚀 Register & Verify Connection", type="primary")

        if submitted:
            if not company_name or not server_host or not server_user:
                st.error("Please fill in Company Name, Server Host, and SSH User.")
            else:
                with st.spinner(f"Connecting to {server_host}... (may take 15-30 seconds)"):
                    try:
                        client_id = mgr.onboard(
                            company_name    = company_name,
                            website_url     = website_url,
                            server_host     = server_host,
                            server_port     = int(server_port),
                            server_user     = server_user,
                            ssh_key_path    = ssh_key_path,
                            server_password = server_password,
                            app_log_path    = app_log_path,
                            metrics_endpoint= metrics_endpoint,
                            app_health_url  = app_health_url,
                            db_type         = db_type,
                            db_host         = db_host,
                            db_port         = int(db_port),
                            db_name         = db_name,
                            db_user         = db_user,
                            db_password     = db_password,
                            slack_webhook   = slack_webhook,
                            pagerduty_key   = pagerduty_key,
                            contact_email   = contact_email,
                        )
                        proof = mgr.get_proof(client_id)
                        _show_proof_result(proof)
                        st.session_state["selected_client"] = client_id

                    except Exception as e:
                        st.error(f"Onboarding failed: {e}")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — All Clients
    # ══════════════════════════════════════════════════════════════════════════
    with tab_clients:
        st.subheader("Registered Clients")

        clients = mgr.list_clients()
        if not clients:
            st.info("No clients registered yet. Use the 'Register New Client' tab.")
        else:
            for client in clients:
                cid     = client["client_id"]
                name    = client["company_name"]
                url     = client["website_url"]
                status  = client["status"]
                reg_at  = client["registered_at"][:10]
                proof   = client.get("proof", {})
                mon_st  = mgr.get_monitoring_status(cid)

                # Status color
                status_icon = {"connected": "🟢", "pending": "🟡", "error": "🔴"}.get(status, "⚪")

                with st.expander(f"{status_icon} **{name}** — ID: `{cid}` | {url} | Registered: {reg_at}"):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Connection", "✅ OK" if proof.get("connection_verified") else "❌ Failed")
                    c2.metric("Database",   "✅ OK" if proof.get("db_verified")         else "❌ Failed")
                    c3.metric("Log File",   "✅ OK" if proof.get("log_verified")         else "❌ Failed")
                    c4.metric("Health URL", "✅ OK" if proof.get("health_check_passed")  else "—")

                    srv_info = proof.get("server_info", {})
                    if srv_info:
                        st.markdown(f"**Server:** `{srv_info.get('hostname','?')}` | "
                                    f"OS: `{srv_info.get('os_info','?')}` | "
                                    f"CPU cores: `{srv_info.get('cpu_cores','?')}` | "
                                    f"RAM: `{srv_info.get('memory_total','?')}` | "
                                    f"Uptime: {srv_info.get('uptime','?')}")

                    db_info = proof.get("db_info", {})
                    if db_info:
                        st.markdown(f"**DB:** `{db_info.get('type','?')}` | "
                                    f"Tables/Collections: `{db_info.get('table_count', db_info.get('collection_count','?'))}` | "
                                    f"Version: `{db_info.get('version','?')}`")

                    # Monitoring controls
                    col_m1, col_m2, col_m3, col_m4 = st.columns(4)

                    if col_m1.button("▶ Start Monitoring", key=f"start_{cid}"):
                        mgr.start_monitoring(cid)
                        st.success(f"Monitoring started for {name}")
                        st.rerun()

                    if col_m2.button("⏹ Stop Monitoring", key=f"stop_{cid}"):
                        mgr.stop_monitoring(cid)
                        st.warning(f"Monitoring stopped for {name}")
                        st.rerun()

                    if col_m3.button("🔄 Re-verify", key=f"verify_{cid}"):
                        with st.spinner("Verifying..."):
                            mgr.verify_client(cid)
                        st.rerun()

                    if col_m4.button("🗑️ Remove", key=f"remove_{cid}"):
                        mgr.remove_client(cid)
                        st.rerun()

                    mon_log = "🟢 Running" if mon_st["log_collector_running"] else "🔴 Stopped"
                    mon_met = "🟢 Running" if mon_st["metrics_collector_running"] else "🔴 Stopped"
                    st.caption(f"Log collector: {mon_log} | Metrics collector: {mon_met}")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 3 — Connection Proof
    # ══════════════════════════════════════════════════════════════════════════
    with tab_proof:
        st.subheader("Connection Proof Report")
        st.caption("This is the verifiable evidence that the client's server is connected.")

        clients = mgr.list_clients()
        if not clients:
            st.info("No clients registered yet.")
            return

        client_options = {f"{c['company_name']} ({c['client_id']})": c["client_id"] for c in clients}
        selected_label = st.selectbox("Select Client", list(client_options.keys()),
                                      index=0 if client_options else 0)
        selected_id = client_options.get(selected_label)

        if selected_id:
            proof = mgr.get_proof(selected_id)
            if proof:
                _show_proof_detail(proof)
            else:
                st.info("No proof report yet. Click 'Re-verify' in the All Clients tab.")


# ─────────────────────────────────────────────────────────────────────────────
# Proof display helpers
# ─────────────────────────────────────────────────────────────────────────────

def _show_proof_result(proof: dict):
    """Show compact proof result after onboarding."""
    ok = proof.get("connection_verified")
    if ok:
        st.success(f"✅ Successfully connected to **{proof.get('company_name')}**!")
    else:
        st.error(f"❌ Connection failed for {proof.get('company_name')}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("SSH Connection", "✅" if proof.get("connection_verified") else "❌")
    col2.metric("Database",       "✅" if proof.get("db_verified")         else "❌")
    col3.metric("Log File",       "✅" if proof.get("log_verified")         else "❌")
    col4.metric("Health URL",     "✅" if proof.get("health_check_passed")  else "—")

    srv = proof.get("server_info", {})
    if srv.get("hostname"):
        st.info(f"🖥️ Server: **{srv['hostname']}** | OS: {srv.get('os_info','?')} | "
                f"CPU: {srv.get('cpu_cores','?')} cores | RAM: {srv.get('memory_total','?')}")

    if proof.get("errors"):
        with st.expander("⚠️ Errors"):
            for e in proof["errors"]:
                st.warning(e)


def _show_proof_detail(proof: dict):
    """Show full detailed proof report."""
    st.markdown(f"### {proof.get('company_name')} — Proof Report")
    st.caption(f"Verified at: {proof.get('verified_at', '?')} UTC | Client ID: {proof.get('client_id')}")

    # Overview badges
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SSH Connection",  "✅ Connected"  if proof.get("connection_verified") else "❌ Failed")
    c2.metric("Database",        "✅ Connected"  if proof.get("db_verified")         else "❌ Failed")
    c3.metric("App Log",         "✅ Found"      if proof.get("log_verified")         else "❌ Not found")
    c4.metric("Health Endpoint", "✅ 200 OK"     if proof.get("health_check_passed")  else "—")

    # Server info
    srv = proof.get("server_info", {})
    if srv:
        st.markdown("---")
        st.markdown("#### 🖥️ Server Information")
        col_a, col_b, col_c = st.columns(3)
        col_a.markdown(f"**Hostname:** `{srv.get('hostname','?')}`")
        col_a.markdown(f"**OS:** {srv.get('os_info','?')}")
        col_a.markdown(f"**Kernel:** {srv.get('kernel','?')}")
        col_b.markdown(f"**CPU Cores:** {srv.get('cpu_cores','?')}")
        col_b.markdown(f"**RAM Total:** {srv.get('memory_total','?')}")
        col_b.markdown(f"**Disk Usage:** {srv.get('disk_usage','?')}")
        col_c.markdown(f"**Uptime:** {srv.get('uptime','?')}")
        col_c.markdown(f"**Python:** {srv.get('python_ver','?')}")

    # DB info
    db = proof.get("db_info", {})
    if db:
        st.markdown("---")
        st.markdown("#### 🗄️ Database Connection")
        col_x, col_y = st.columns(2)
        col_x.markdown(f"**Type:** `{db.get('type','?')}`")
        col_x.markdown(f"**Version:** {db.get('version','?')}")
        col_y.markdown(f"**Tables / Collections:** {db.get('table_count', db.get('collection_count','?'))}")
        tables = db.get("tables", db.get("collections", []))
        if tables:
            col_y.markdown(f"**Sample tables:** `{', '.join(tables[:5])}`")

    # Log info
    log = proof.get("log_info", {})
    if log:
        st.markdown("---")
        st.markdown("#### 📄 Application Log")
        col_l1, col_l2, col_l3 = st.columns(3)
        col_l1.markdown(f"**Path:** `{log.get('path','?')}`")
        col_l2.markdown(f"**Size:** {log.get('file_size','?')}")
        col_l3.markdown(f"**Lines:** {log.get('line_count','?')}")
        if log.get("tail_sample"):
            st.markdown("**Last 5 lines:**")
            st.code(log["tail_sample"], language="json")

    # Health info
    health = proof.get("health_info", {})
    if health:
        st.markdown("---")
        st.markdown("#### 🏥 Health Endpoint")
        col_h1, col_h2, col_h3 = st.columns(3)
        col_h1.markdown(f"**URL:** {health.get('url','?')}")
        col_h2.markdown(f"**HTTP Status:** `{health.get('status_code','?')}`")
        col_h3.markdown(f"**Response time:** {health.get('response_ms','?')} ms")
        if health.get("body_sample"):
            st.code(health["body_sample"], language="json")

    # Errors
    errors = proof.get("errors", [])
    if errors:
        st.markdown("---")
        st.markdown("#### ⚠️ Errors / Warnings")
        for e in errors:
            st.warning(e)

    # Raw JSON proof (collapsible)
    with st.expander("📥 Download Raw Proof JSON"):
        st.download_button(
            label="Download proof.json",
            data=json.dumps(proof, indent=2),
            file_name=f"proof_{proof.get('client_id','?')}_{proof.get('verified_at','?')[:10]}.json",
            mime="application/json",
        )
        st.json(proof)