# AIOps AI Test Engineer Agent — v2.0

> **Continuous Monitoring · Hybrid ML Anomaly Detection · LLM-Powered Root Cause Analysis · Auto-Remediation · Feedback Learning · Client Server Onboarding**

---

## What is This?

The **AIOps AI Test Engineer Agent** is an end-to-end intelligent operations platform built entirely in Python. It monitors a web application continuously, detects anomalies using a hybrid machine learning pipeline, generates explainable root cause analysis (RCA) using LLaMA3-70B via Groq, proposes safe remediation actions, improves its own reasoning through feedback learning, and — new in this version — **connects directly to any client's live server and database** so you can offer this as a service to real websites and companies.

### What it does in one sentence per feature

| Feature | What happens |
|---|---|
| **Hybrid ML detection** | Isolation Forest catches multivariate spikes; Rolling Z-Score catches gradual drift |
| **LLM Root Cause Analysis** | Groq LLaMA3-70B generates structured RCA with root cause, explanation, fixes, prevention |
| **Causal inference** | 18-node domain graph traces cause → effect chains with counterfactual statements |
| **RLHF prompt tuning** | 18 prompt configs scored; low-performers auto-replaced based on operator feedback |
| **Vector memory** | FAISS stores past incidents; similar events retrieved to enrich future LLM prompts |
| **Alert routing** | HIGH/CRITICAL events sent to Slack and PagerDuty with 10-minute deduplication |
| **Auto-remediation** | Proposes safe actions (reduce load, rotate log, restart) — requires human y/N approval |
| **Client onboarding** | SSH into any client server, verify DB + logs + health endpoint, pull live data |

---

## Project Structure

```
aiops_agent/
│
├── webapp/
│   ├── app.py                      # Flask test target — 4 endpoints with injected faults
│   └── load_generator.py           # Continuous traffic simulator
│
├── metrics/
│   ├── collector.py                # psutil sampler — CPU, memory, latency every 5 seconds
│   └── metrics.csv                 # Runtime-generated
│
├── agent/
│   ├── train.py                    # OFFLINE: trains two Isolation Forest models
│   ├── inference.py                # RUNTIME: sliding-window anomaly detection
│   ├── rca_builder.py              # Structures anomaly evidence for LLM
│   ├── llm_reasoning.py            # Groq LLaMA3-70B API integration
│   ├── baseline_detector.py        # Rolling Z-Score drift detector
│   ├── causal_inference.py         # Do-calculus inspired causal chain analysis
│   ├── agent_loop.py               # v1: original simple 30-second loop
│   └── agent_loop_v2.py            # v2: all 8 modules integrated
│
├── remediation/
│   └── remediation_engine.py       # Rule-based proposer + human approval gate
│
├── feedback/
│   ├── feedback_learning.py        # Fix outcome tracking and effectiveness DB
│   └── rlhf_loop.py                # Prompt variant scoring and auto-exploration
│
├── alerting/
│   └── alert_router.py             # Slack + PagerDuty routing with deduplication
│
├── memory/
│   └── vector_memory.py            # FAISS vector incident store + keyword fallback
│
├── client_integration/             # ← NEW: Client server onboarding module
│   ├── client_config.py            # Stores client server/DB/alert details
│   ├── server_connector.py         # SSH verifier — proof of connection
│   ├── remote_log_collector.py     # Pulls client app.log via SSH every 10 seconds
│   ├── remote_metrics_collector.py # Pulls CPU/memory via SSH or Prometheus
│   └── client_manager.py           # Single entry point for all client operations
│
├── dashboard/
│   ├── app.py                      # Streamlit dashboard — Agent Monitor + Client tabs
│   └── client_page.py              # ← NEW: Client onboarding and proof page
│
├── onboard_client.py               # ← NEW: Run once to register a client from terminal
│
├── models/                         # Created by train.py
│   ├── metrics_model.pkl
│   └── log_model.pkl
│
├── logs_store/                     # Created at runtime
│   ├── app.log
│   ├── rca_results.json
│   └── <client_id>/app.log         # Per-client pulled logs
│
├── client_integration/             # Created at runtime
│   ├── clients.json                # All registered client details
│   └── proof_reports/              # Per-client JSON proof files
│
├── remediation/                    # Created at runtime
│   ├── pending_actions.json
│   └── audit.log
│
├── feedback/                       # Created at runtime
│   ├── feedback_store.json
│   └── best_prompt_config.json
│
├── memory/                         # Created at runtime
│   └── incidents.json
│
├── alerting/                       # Created at runtime
│   └── alert_history.json
│
├── requirements.txt
└── README.md
```

---

## Quick Start — Run Locally (Demo Mode)

### Step 1 — Create all directories

```bash
cd aiops_agent

mkdir logs_store models metrics remediation feedback memory alerting
mkdir -p client_integration/proof_reports
```

### Step 2 — Install dependencies

```bash
# Core (always required)
pip install -r requirements.txt

# Optional but recommended — enables semantic vector search
pip install sentence-transformers faiss-cpu

# Required only for client server onboarding
pip install paramiko pymysql psycopg2-binary pymongo
```

### Step 3 — Set environment variables

```bash
# Required
export GROQ_API_KEY="gsk_your-key-here"

# Optional — alert routing
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
export PAGERDUTY_ROUTING_KEY="your-pd-routing-key"
export ALERT_MIN_SEVERITY="HIGH"
```

> **Windows PowerShell:**
> ```powershell
> $env:GROQ_API_KEY = "gsk_your-key-here"
> ```

### Step 4 — Open 4 terminals and run in order

```
Terminal 1:   python webapp/app.py
              Wait for: * Running on http://0.0.0.0:5050

Terminal 2:   python webapp/load_generator.py
              Wait 2 full minutes before training

Terminal 3:   python agent/train.py
              Then run one of:
              python agent/agent_loop.py        ← v1, simple demo
              python agent/agent_loop_v2.py     ← v2, full system (recommended)

Terminal 4:   streamlit run dashboard/app.py
              Opens at http://localhost:8501
```

### Step 5 — Watch the agent work

After about 3 minutes you will see:

```
[Agent v2] -- Cycle #2 @ 13:25:17 UTC --
[Agent v2] Anomalies: 6 metric, 1 log | Severity: CRITICAL

ROOT CAUSE ANALYSIS  [2026-02-18T13:25:20]
Severity   : CRITICAL  |  Confidence: HIGH
Root Cause : Database connection pool exhaustion caused by traffic surge.

Suggested Fixes:
  1. Increase the database connection pool size.
  2. Implement dynamic connection pool scaling.
  3. Monitor pool metrics proactively.

[Alerting] ALERT: [CRITICAL] sent to console
[Memory]   Stored incident: A3F2B1C4
[Remediation] Approve reduce_load? [y/N]:
```

---

## v1 vs v2 — Which to Run?

| | `agent_loop.py` (v1) | `agent_loop_v2.py` (v2) |
|---|---|---|
| Anomaly detection | Isolation Forest only | IForest + Rolling Z-Score |
| LLM context | Base evidence only | + memory + causal chain + RLHF |
| Alerts | Console only | Console + Slack + PagerDuty |
| Remediation | None | Human-approval engine |
| Learning | None | Feedback + RLHF tuning |
| Memory | None | FAISS vector store |
| Best for | First demo, simple test | Full demo, client delivery |

Both use the same trained models and same logs. Switch anytime — no re-setup needed.

---

## Client Server Onboarding — New Feature

When a company approaches you to monitor their website, use this module to connect to their live server and generate a verifiable proof of connection that you can show them.

### What the client gives you

```
Server IP or hostname          e.g.  203.0.113.10
SSH port                       usually 22
SSH username                   e.g.  ubuntu / ec2-user / root
SSH private key OR password
Path to their app log          e.g.  /var/log/myapp/app.log
Database type                  mysql / postgres / mongodb / sqlite
Database host, port, name      usually localhost:3306/mydb
Database read-only username + password
Health check URL (optional)    e.g.  https://theirsite.com/health
```

### What you get after onboarding

- SSH connection proof — server hostname, OS, CPU cores, RAM, uptime
- Database proof — DB version, table names, connection confirmed
- Log file proof — file path, size, line count, last 5 lines
- Health endpoint proof — HTTP status code, response time
- Downloadable JSON report to hand to the client as evidence

---

### Option A — Onboard from terminal (fastest)

**1. Edit `onboard_client.py` with the client's details:**

```python
CLIENT = dict(
    company_name    = "Acme Corp",
    website_url     = "https://acme.com",
    server_host     = "203.0.113.10",
    server_port     = 22,
    server_user     = "ubuntu",
    ssh_key_path    = "~/.ssh/acme_key.pem",
    server_password = "",
    app_log_path    = "/var/log/acme/app.log",
    metrics_endpoint= "",
    app_health_url  = "https://acme.com/health",
    db_type         = "mysql",
    db_host         = "localhost",
    db_port         = 3306,
    db_name         = "acme_production",
    db_user         = "monitor_user",
    db_password     = "their_db_password",
    slack_webhook   = "",
    pagerduty_key   = "",
    contact_email   = "admin@acme.com",
)
```

**2. Run it:**

```bash
python onboard_client.py
```

**3. Expected output:**

```
============================================================
  AIOps Client Onboarding
  Company: Acme Corp
  Server:  203.0.113.10:22
============================================================

[Connector] SSH → ubuntu@203.0.113.10:22
[Connector] SSH OK ✅
[Connector] Server: acme-prod-01 | Ubuntu 22.04.3 LTS
[Connector] MySQL OK ✅ — v8.0.35, 24 tables
[Connector] Log OK ✅ — 48M, 92847 lines
[Connector] Health ✅ — HTTP 200

  Client ID : AB12CD34
  SSH        : ✅
  Database   : ✅  (mysql, 24 tables)
  Log file   : ✅  (48M, 92847 lines)
  Health URL : ✅  (200 OK, 142ms)

  Proof saved → client_integration/proof_reports/AB12CD34_*.json

  Next steps:
  1. streamlit run dashboard/app.py
  2. Go to 🏢 Client Onboarding → Connection Proof
  3. Select Acme Corp → full proof with all verified details
  4. Click ▶ Start Monitoring to begin live log + metrics collection
  5. python agent/agent_loop_v2.py
============================================================
```

---

### Option B — Onboard from the dashboard (no terminal needed)

```bash
streamlit run dashboard/app.py
```

Go to **🏢 Client Onboarding → ➕ Register New Client**

Fill in the form and click **Register & Verify Connection**. The proof appears immediately.

---

### Start live monitoring for a client

After onboarding, go to **All Clients → ▶ Start Monitoring**.

This starts two background threads:
- `RemoteLogCollector` — SSH-pulls their app.log every 10 seconds into `logs_store/<client_id>/app.log`
- `RemoteMetricsCollector` — SSH-pulls or Prometheus-polls CPU/memory every 5 seconds

Then run the agent normally:

```bash
python agent/agent_loop_v2.py
```

The agent reads the client's logs and metrics automatically.

---

## Dashboard Pages

### 📊 Agent Monitor tab

- Start / Stop agent with one click
- Live CPU, memory, latency charts updated every 15 seconds
- RCA timeline — every detected incident with severity badge, root cause, fixes, evidence
- Agent statistics — cycles completed, anomalies detected, last RCA severity

### 🏢 Client Onboarding tab

**➕ Register New Client**
- Form for company name, SSH details, database credentials, alert channels
- Live connection verification on submit — results shown immediately

**📋 All Clients**
- All registered clients with SSH/DB/log/health status badges
- Per-client controls: ▶ Start Monitoring / ⏹ Stop Monitoring / 🔄 Re-verify / 🗑️ Remove
- Shows server hostname, OS, table count, monitoring thread status

**🔍 Connection Proof**
- Full verification report for any selected client
- Server info — hostname, OS, kernel, CPU, RAM, disk, uptime
- Database — type, version, table names
- Log file — path, size, line count, last 5 lines preview
- Health endpoint — URL, HTTP status, response time, response preview
- Download proof as JSON to share with the client

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | **Yes** | Free at https://console.groq.com/keys |
| `SLACK_WEBHOOK_URL` | No | Slack Incoming Webhook URL |
| `PAGERDUTY_ROUTING_KEY` | No | PagerDuty Events API v2 routing key |
| `ALERT_MIN_SEVERITY` | No | `HIGH` or `CRITICAL` — default: HIGH |

---

## Security Notes for Client Onboarding

**Create a read-only database user** on the client's server before entering credentials:

```sql
-- MySQL
CREATE USER 'aiops_monitor'@'%' IDENTIFIED BY 'strong_password';
GRANT SELECT ON client_db.* TO 'aiops_monitor'@'%';

-- PostgreSQL
CREATE USER aiops_monitor WITH PASSWORD 'strong_password';
GRANT CONNECT ON DATABASE client_db TO aiops_monitor;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO aiops_monitor;
```

**Use SSH key authentication** — avoid storing passwords where possible.

**Add to `.gitignore`:**

```
client_integration/clients.json
client_integration/proof_reports/
feedback/
memory/
models/
logs_store/
```

SSH keys are only referenced by path — never copied or stored by the system. Proof reports contain no passwords and are safe to share with clients.

---

## Re-Training the Models

```bash
# Delete old models
rm models/metrics_model.pkl
rm models/log_model.pkl

# Run at least 2 minutes of load generator first, then:
python agent/train.py
```

Retrain whenever you deploy to a new server environment for best accuracy.

---

## Complete Feature List

### v1 Core
- Flask test app with 4 endpoints and deterministic fault injection (HTTP 500, slow responses, CPU load)
- Structured JSON logging — one JSON object per line in app.log
- psutil metrics collection every 5 seconds with thread-safe rolling deque
- Offline Isolation Forest training — metrics model (contamination=0.10) + log model (contamination=0.15)
- Synthetic training data fallback — 500 auto-generated samples when real data is insufficient
- Runtime sliding-window anomaly inference — 36-sample metric window, 5-minute log window
- 4-level severity: LOW / MEDIUM / HIGH / CRITICAL with correlated signal detection
- Groq LLaMA3-70B at temperature=0.3 — deterministic JSON output
- Anomaly-gated LLM calls — never called on healthy cycles
- 60-second LLM cooldown to prevent API flooding
- RCA JSON persistence — last 50 results in logs_store/rca_results.json
- Streamlit dashboard with live charts and RCA timeline

### v2 Extensions
- Rolling Z-Score baseline detector — Welford's online algorithm, 60-sample window, 2.5σ threshold
- Hybrid OR/AND detector combination
- Causal inference — 18-node domain graph, topological traversal, counterfactual generation
- Human-approval remediation — 4 safe actions (reduce_load, clear_log, restart, notify), full audit log
- Fix outcome tracking — RESOLVED / PARTIALLY_RESOLVED / NOT_RESOLVED with effectiveness rates
- RLHF prompt tuning — 18 configurations, epsilon-greedy exploration, persisted best config
- Slack Block Kit alerts + PagerDuty Events API v2 + 10-minute MD5 deduplication
- FAISS vector memory with all-MiniLM-L6-v2 embeddings + automatic Jaccard fallback

### Client Integration (New)
- Register any client's server via terminal script or Streamlit form
- SSH connection verification with full server info collection
- MySQL, PostgreSQL, MongoDB, and SQLite database verification
- App log file discovery, size check, and 5-line preview
- Health endpoint HTTP response check
- Remote log pulling every 10 seconds via SSH — feeds directly into agent pipeline
- Remote metrics collection via SSH psutil or Prometheus /metrics endpoint
- Timestamped JSON proof reports saved per client
- Full proof viewer in Streamlit dashboard with download option
- All clients listed with live monitoring status indicators