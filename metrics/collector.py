"""
metrics/collector.py
--------------------
Lightweight system metrics collector.
Samples:
  - CPU usage (%)
  - Memory usage (%)
  - Simulated request latency per endpoint (from app log)

Stores metrics in a rolling in-memory deque AND appends to metrics/metrics.csv
Sampling interval: 5 seconds

Usage (standalone):
    python metrics/collector.py
"""

import csv
import os
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import psutil

# ── Configuration ─────────────────────────────────────────────────────────────
SAMPLE_INTERVAL = 5          # seconds
MAX_MEMORY_ROWS = 1000       # rolling window in memory (~83 min at 5s)
METRICS_CSV = Path("metrics/metrics.csv")

# Thread-safe rolling store accessible by the agent
_lock = threading.Lock()
_metrics_store: deque = deque(maxlen=MAX_MEMORY_ROWS)


def _write_csv_row(row: dict):
    """Append a single metrics row to CSV (create with header if needed)."""
    METRICS_CSV.parent.mkdir(exist_ok=True)
    file_exists = METRICS_CSV.exists()
    with open(METRICS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def collect_sample() -> dict:
    """
    Collect one metrics snapshot.
    Returns a dict with timestamp, cpu_pct, mem_pct, and a synthetic latency value
    derived from recent /proc stats (or psutil network io as a proxy).
    """
    cpu = psutil.cpu_percent(interval=1)        # blocking 1-second measure
    mem = psutil.virtual_memory().percent
    disk_io = psutil.disk_io_counters()
    net_io = psutil.net_io_counters()

    # Synthetic "app latency" proxy:
    # In a real system you'd read from a metrics endpoint or time-series db.
    # Here we simulate it as a function of CPU load for demo purposes.
    synthetic_latency_ms = 50 + cpu * 5 + (mem / 10)

    row = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "cpu_pct": round(cpu, 2),
        "mem_pct": round(mem, 2),
        "latency_ms": round(synthetic_latency_ms, 2),
        "bytes_sent": net_io.bytes_sent if net_io else 0,
        "bytes_recv": net_io.bytes_recv if net_io else 0,
    }
    return row


def get_recent_metrics(n: int = 60) -> list[dict]:
    """
    Return the last `n` metric samples (thread-safe).
    Called by the agent during inference.
    """
    with _lock:
        return list(_metrics_store)[-n:]


def run_collector(stop_event: threading.Event | None = None):
    """
    Main collection loop. Runs in background thread.
    Stores samples in memory deque and CSV.

    Args:
        stop_event: Optional threading.Event; set it to stop the loop.
    """
    print(f"[MetricsCollector] Started. Sampling every {SAMPLE_INTERVAL}s → {METRICS_CSV}")
    while True:
        if stop_event and stop_event.is_set():
            print("[MetricsCollector] Stopped.")
            break
        try:
            sample = collect_sample()
            with _lock:
                _metrics_store.append(sample)
            _write_csv_row(sample)
            print(f"  [Metrics] cpu={sample['cpu_pct']}% mem={sample['mem_pct']}% "
                  f"latency={sample['latency_ms']}ms")
        except Exception as e:
            print(f"[MetricsCollector] Error: {e}")
        time.sleep(SAMPLE_INTERVAL - 1)  # subtract the 1s cpu_percent interval


if __name__ == "__main__":
    os.makedirs("metrics", exist_ok=True)
    run_collector()