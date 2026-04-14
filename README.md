# AIOps AI Test Engineer Agent 

> **Continuous Monitoring · Hybrid ML Anomaly Detection · LLM-Powered Root Cause Analysis · Auto-Remediation · Feedback Learning · Client Server Onboarding**
<img width="464" height="211" alt="image" src="https://github.com/user-attachments/assets/02ea0861-d0c2-411e-872b-9fd885f42d85" />
<img width="460" height="149" alt="image" src="https://github.com/user-attachments/assets/586cd9ba-cc51-461a-ac66-014e56892020" />
<img width="490" height="150" alt="image" src="https://github.com/user-attachments/assets/73150fea-970d-4e98-946f-92fc634497b2" />
<img width="488" height="213" alt="image" src="https://github.com/user-attachments/assets/121e50b3-dcf8-450e-aca5-cd62a5576785" />
<img width="488" height="224" alt="image" src="https://github.com/user-attachments/assets/6ae60630-a9f0-4619-a5be-1aed02186095" />

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
