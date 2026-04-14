"""
onboard_client.py
------------------
Quick Client Onboarding Script
================================
Run this once to register and verify a new client's server.
Edit the details below, then run:

    python onboard_client.py

After running, open the Streamlit dashboard and go to:
  🏢 Client Onboarding → Connection Proof
to see the full verification report.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from client_integration.client_manager import ClientManager

# ─────────────────────────────────────────────────────────────────────────────
# EDIT THESE DETAILS FOR YOUR CLIENT
# ─────────────────────────────────────────────────────────────────────────────

CLIENT = dict(
    # Basic info
    company_name    = "Acme Corp",                      # ← Client's company name
    website_url     = "https://acme.com",               # ← Their website

    # SSH / Server access
    server_host     = "203.0.113.10",                   # ← Their server IP or hostname
    server_port     = 22,                               # ← SSH port (usually 22)
    server_user     = "ubuntu",                         # ← SSH login username
    ssh_key_path    = "~/.ssh/acme_key.pem",            # ← Path to private key on YOUR machine
    server_password = "",                               # ← OR password if no key

    # App details
    app_log_path    = "/var/log/acme/app.log",          # ← Where their app writes logs
    metrics_endpoint= "",                               # ← Optional: Prometheus /metrics URL
    app_health_url  = "https://acme.com/health",        # ← Optional: their /health endpoint

    # Database
    db_type         = "mysql",                          # ← mysql | postgres | mongodb | sqlite
    db_host         = "localhost",                      # ← DB host (from server's perspective)
    db_port         = 3306,                             # ← DB port
    db_name         = "acme_production",                # ← Database name
    db_user         = "monitor_user",                   # ← Read-only DB user you created
    db_password     = "your_db_password",               # ← DB password

    # Alert routing
    slack_webhook   = "",                               # ← Optional Slack webhook
    pagerduty_key   = "",                               # ← Optional PagerDuty key
    contact_email   = "admin@acme.com",                 # ← Contact email
)

# ─────────────────────────────────────────────────────────────────────────────
# RUN ONBOARDING
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print(f"  AIOps Client Onboarding")
    print(f"  Company: {CLIENT['company_name']}")
    print(f"  Server:  {CLIENT['server_host']}:{CLIENT['server_port']}")
    print(f"  DB:      {CLIENT['db_type']} @ {CLIENT['db_host']}:{CLIENT['db_port']}")
    print("=" * 60)

    mgr = ClientManager()
    client_id = mgr.onboard(**CLIENT)

    print("\n" + "=" * 60)
    print(f"  Client ID: {client_id}")
    print("=" * 60)

    proof = mgr.get_proof(client_id)
    if proof:
        print(f"\n  SSH Connected:   {'✅' if proof.get('connection_verified') else '❌'}")
        print(f"  DB Connected:    {'✅' if proof.get('db_verified')         else '❌'}")
        print(f"  Log Found:       {'✅' if proof.get('log_verified')         else '❌'}")
        print(f"  Health OK:       {'✅' if proof.get('health_check_passed')  else '—'}")
        srv = proof.get("server_info", {})
        if srv.get("hostname"):
            print(f"\n  Server:  {srv.get('hostname')} | {srv.get('os_info','?')}")
            print(f"  CPU:     {srv.get('cpu_cores','?')} cores | RAM: {srv.get('memory_total','?')}")
        db = proof.get("db_info", {})
        if db:
            print(f"  DB:      {db.get('type','?')} | {db.get('table_count', db.get('collection_count','?'))} tables")
        if proof.get("errors"):
            print(f"\n  ⚠️  Errors:")
            for e in proof["errors"]:
                print(f"     - {e}")

    print(f"\n  Proof saved to: client_integration/proof_reports/{client_id}_*.json")
    print(f"\n  Next steps:")
    print(f"  1. Open dashboard: streamlit run dashboard/app.py")
    print(f"  2. Go to 🏢 Client Onboarding → Connection Proof")
    print(f"  3. Select '{CLIENT['company_name']}' to see full proof")
    print(f"  4. Click ▶ Start Monitoring to begin live log + metrics collection")
    print(f"  5. Run agent: python agent/agent_loop_v2.py")
    print("=" * 60)