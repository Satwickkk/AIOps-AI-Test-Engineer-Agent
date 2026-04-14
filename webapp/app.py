"""
webapp/app.py
-------------
Test target: A simple Flask app with intentional faults for demo purposes.
- /health  : always fast and OK
- /login   : occasionally slow (simulated DB delay)
- /search  : occasionally throws 500 errors
- /data    : CPU-intensive endpoint (intentionally slow)

Logs structured JSON to ../logs_store/app.log
"""

import json
import logging
import random
import time
import uuid
from datetime import datetime

from flask import Flask, jsonify, request

# ── Structured JSON logger ──────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "endpoint": getattr(record, "endpoint", "app"),
            "message": record.getMessage(),
            "latency_ms": getattr(record, "latency_ms", None),
            "status_code": getattr(record, "status_code", None),
            "request_id": getattr(record, "request_id", None),
        }
        return json.dumps(log_record)


logger = logging.getLogger("aiops_webapp")
logger.setLevel(logging.DEBUG)

# File handler — agent reads this file
file_handler = logging.FileHandler("logs_store/app.log")
file_handler.setFormatter(JsonFormatter())
logger.addHandler(file_handler)

# Console handler for visibility while running
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(console_handler)

# ── App factory ─────────────────────────────────────────────────────────────
app = Flask(__name__)

# Counters for error injection cycling
_request_counters: dict[str, int] = {"login": 0, "search": 0, "data": 0}


def _log_request(endpoint: str, status_code: int, latency_ms: float, msg: str, level="info"):
    """Helper: emit a structured log line."""
    extra = {
        "endpoint": endpoint,
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "request_id": str(uuid.uuid4())[:8],
    }
    getattr(logger, level)(msg, extra=extra)


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    """Always healthy — baseline for anomaly detection."""
    t0 = time.time()
    latency = (time.time() - t0) * 1000
    _log_request("/health", 200, latency, "Health check OK")
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Simulates a login endpoint.
    - Every 5th request is intentionally slow (DB timeout simulation).
    - Occasional auth failures logged as WARNING.
    """
    t0 = time.time()
    _request_counters["login"] += 1
    n = _request_counters["login"]

    # Inject slowness every 5th request
    if n % 5 == 0:
        delay = random.uniform(2.0, 4.5)   # Slow DB query
        time.sleep(delay)
        latency = (time.time() - t0) * 1000
        _log_request("/login", 200, latency,
                     f"Login slow response: DB query took {delay:.2f}s",
                     level="warning")
        return jsonify({"status": "ok", "note": "slow login"}), 200

    # Inject auth failure every 7th request
    if n % 7 == 0:
        latency = (time.time() - t0) * 1000
        _log_request("/login", 401, latency,
                     "Login failed: invalid credentials",
                     level="warning")
        return jsonify({"error": "Unauthorized"}), 401

    latency = (time.time() - t0) * 1000
    _log_request("/login", 200, latency, "Login successful")
    return jsonify({"status": "ok", "user": "demo_user"})


@app.route("/search")
def search():
    """
    Simulates a search endpoint.
    - Every 4th request crashes with 500 (e.g., DB connection lost).
    - Random small jitter on all requests.
    """
    t0 = time.time()
    _request_counters["search"] += 1
    n = _request_counters["search"]

    # Random jitter to make latency noisy
    time.sleep(random.uniform(0.05, 0.3))

    # Inject 500 error every 4th request
    if n % 4 == 0:
        latency = (time.time() - t0) * 1000
        _log_request("/search", 500, latency,
                     "Search failed: database connection pool exhausted",
                     level="error")
        return jsonify({"error": "Internal Server Error"}), 500

    query = request.args.get("q", "demo")
    latency = (time.time() - t0) * 1000
    _log_request("/search", 200, latency, f"Search OK for query='{query}'")
    return jsonify({"results": [f"Result for {query}", "Sample item 2"], "count": 2})


@app.route("/data")
def data():
    """
    CPU-heavy endpoint — simulates data processing.
    Always slow; used to trigger CPU metric anomalies.
    """
    t0 = time.time()
    _request_counters["data"] += 1

    # Burn CPU intentionally
    result = sum(i * i for i in range(200_000))

    latency = (time.time() - t0) * 1000
    _log_request("/data", 200, latency, f"Data processed (result={result % 1000})")
    return jsonify({"status": "ok", "latency_ms": round(latency, 2)})
@app.route("/")
def index():
    return jsonify({
        "app": "AIOps Demo Target",
        "endpoints": ["/health", "/login", "/search", "/data"]
    })


if __name__ == "__main__":
    import os
    os.makedirs("logs_store", exist_ok=True)
    logger.info("Starting AIOps demo web app on port 5050", extra={
        "endpoint": "startup", "status_code": None, "latency_ms": 0, "request_id": "boot"
    })
    app.run(host="0.0.0.0", port=5050, debug=False)