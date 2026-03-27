# AIOps AI Test Engineer Agent 
### Continuous Monitoring | Hybrid ML Anomaly Detection | LLM-Powered Root Cause Analysis | Auto-Remediation | Feedback Learning

<img width="464" height="211" alt="image" src="https://github.com/user-attachments/assets/c1de2e58-18fe-49fb-9ace-286cef4a5fb2" />
<img width="460" height="149" alt="image" src="https://github.com/user-attachments/assets/3a42181e-c7db-4297-ae83-591d67a093bd" />
<img width="490" height="150" alt="image" src="https://github.com/user-attachments/assets/dfcfb7bf-50d3-4a98-8978-e60bffb72dc6" />


---

## What is This?

The AIOps AI Test Engineer Agent is an end-to-end intelligent operations system built entirely in Python. It continuously monitors a running web application, detects system anomalies using a hybrid machine learning pipeline, performs automated root cause analysis (RCA) using a large language model (LLaMA3-70B via Groq), proposes safe remediation actions with human approval, and improves its own reasoning quality over time through feedback learning.



## How to Run — Complete Procedure

### Step 1: Create Required Directories

```bash
cd aiops_agent

mkdir logs_store
mkdir models
mkdir metrics
mkdir remediation
mkdir feedback
mkdir memory
mkdir alerting
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt

# Optional: enable semantic vector search (recommended)
# Without this, keyword search is used automatically — no errors
pip install sentence-transformers faiss-cpu
```

### Step 3: Set Environment Variables

```bash
# Required
export GROQ_API_KEY="gsk_your-key-here"

# Optional — Slack alerts
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

# Optional — PagerDuty alerts
export PAGERDUTY_ROUTING_KEY="your-pd-routing-key"

# Optional — minimum severity to alert (default: HIGH)
export ALERT_MIN_SEVERITY="HIGH"
```

> **Windows PowerShell:**
> ```powershell
> $env:GROQ_API_KEY = "gsk_your-key-here"
> ```

### Step 4: Open 4 Terminals and Run in Order

**Terminal 1 — Web App**
```bash
python webapp/app.py
# Wait for: * Running on http://0.0.0.0:5050
```

**Terminal 2 — Load Generator**
```bash
python webapp/load_generator.py
# Wait 2 FULL MINUTES before training — need enough data
```

**Terminal 3 — Train Models (once), then Start Agent**
```bash
python agent/train.py
# Then choose your version:

# v1 — simple core pipeline
python agent/agent_loop.py

# v2 — all 8 modules active (recommended)
python agent/agent_loop_v2.py
```

**Terminal 4 — Dashboard (optional)**
```bash
streamlit run dashboard/app.py
# Opens at http://localhost:8501
```

---

## Which Agent Version to Run?

| Version | Command | When to Use |
|---|---|---|
| **v1** | `python agent/agent_loop.py` | Simple demo, testing, showing core concept |
| **v2** | `python agent/agent_loop_v2.py` | Full demo, all 8 modules, final evaluation |

Both versions use the **same trained models, same logs, same output file**. You can switch between them at any time with no re-setup.


---

## All Implemented Features

### v1 Core Features
- Flask web app with 4 endpoints + injected faults (slow responses, 401, 500, CPU load)
- Structured JSON logging to `logs_store/app.log`
- psutil-based metrics collection every 5 seconds
- Thread-safe rolling in-memory metrics store
- Offline Isolation Forest training (metrics model + log model)
- Synthetic training data fallback (auto-generated if insufficient real data)
- Runtime sliding-window anomaly inference
- 4-level severity assessment (LOW / MEDIUM / HIGH / CRITICAL)
- Correlated signal detection (metric + log simultaneous fire = systemic failure)
- Groq LLM integration (LLaMA3-70B, temperature=0.3 for consistent JSON output)
- Anomaly-gated LLM calls — LLM only called when ML confirms anomaly
- 60-second LLM cooldown to prevent API spam
- RCA results persisted to `logs_store/rca_results.json`
- Streamlit dashboard with live charts and RCA history

### v2 Extended Features (All 8 Future Work Items — Now Implemented)
- **Rolling Z-Score detector** — Welford's online algorithm, 60-sample window, detects gradual drift
- **Hybrid detection** — Isolation Forest + Z-Score combined via OR/AND configurable logic
- **Causal inference** — 18-node domain causal graph, topological chain traversal, counterfactual generation
- **Human-approval remediation** — 4 safe actions, JSON audit log, y/N CLI gate before execution
- **Feedback learning** — Fix outcome tracking (RESOLVED/PARTIAL/NOT_RESOLVED), effectiveness DB
- **RLHF prompt tuning** — 18 prompt configurations scored, epsilon-greedy exploration, auto-improves
- **Slack + PagerDuty alerts** — Block Kit format, Events API v2, 10-minute deduplication window
- **FAISS vector memory** — sentence-transformer embeddings, semantic similar incident retrieval, keyword fallback

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Groq API key from console.groq.com/keys |
| `SLACK_WEBHOOK_URL` | No | Slack Incoming Webhook URL for alerts |
| `PAGERDUTY_ROUTING_KEY` | No | PagerDuty Events API v2 routing key |
| `ALERT_MIN_SEVERITY` | No | Minimum severity to route alerts (default: HIGH) |

---

## Technologies

| Library | Purpose |
|---|---|
| Flask | Test target web application |
| psutil | System metrics collection |
| scikit-learn | Isolation Forest anomaly detection |
| NumPy / Pandas | Feature matrix and data processing |
| Groq SDK | LLaMA3-70B LLM inference |
| Streamlit | Real-time monitoring dashboard |
| FAISS (optional) | Vector similarity search for incident memory |
| sentence-transformers (optional) | Text embeddings for incident vectorization |

---

## Re-Training the Models

Delete the existing models and retrain anytime with fresh data:

```bash
rm models/metrics_model.pkl
rm models/log_model.pkl
python agent/train.py
```

Best practice: retrain after collecting 10+ minutes of clean baseline traffic for highest accuracy.

---

## Get a Free Groq API Key

1. Go to https://console.groq.com/keys
2. Sign up (free, no credit card required)
3. Create a new API key
4. Copy and set as `GROQ_API_KEY`

The free tier supports 30 requests per minute — sufficient for the agent's 60-second LLM cooldown.
