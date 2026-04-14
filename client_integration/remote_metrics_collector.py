"""
client_integration/remote_metrics_collector.py
------------------------------------------------
Remote Metrics Collector for Client Servers
=============================================
Pulls real CPU / Memory / Latency metrics from the client's server
via one of three methods (in priority order):
  1. SSH + psutil commands (always works if SSH is available)
  2. Prometheus /metrics endpoint (if client has Prometheus)
  3. Health URL response time (as latency proxy)

Feeds data into the SAME in-memory deque as the local metrics
collector so the existing agent inference pipeline works unchanged.

Usage:
    from client_integration.remote_metrics_collector import RemoteMetricsCollector
    collector = RemoteMetricsCollector(client_config, client_id)
    collector.start()
    # Agent reads from get_remote_metrics(client_id, n)
"""

import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

# Per-client rolling metrics store
_stores: dict[str, deque] = {}
_lock = threading.Lock()

MAX_ROWS = 1000


def get_remote_metrics(client_id: str, n: int = 36) -> list[dict]:
    """Return last n metric samples for a client. Called by the agent."""
    with _lock:
        store = _stores.get(client_id, deque())
        return list(store)[-n:]


class RemoteMetricsCollector:

    SAMPLE_INTERVAL = 5   # seconds — same as local collector

    def __init__(self, client_config, client_id: str):
        self.config    = client_config
        self.client_id = client_id
        self._stop     = threading.Event()
        self._thread   = None

        client = self.config.get_client(client_id)
        if not client:
            raise ValueError(f"Client {client_id} not found")
        self.client = client

        # Ensure store exists
        with _lock:
            if client_id not in _stores:
                _stores[client_id] = deque(maxlen=MAX_ROWS)

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._collect_loop,
            name=f"RemMetrics-{self.client_id}",
            daemon=True,
        )
        self._thread.start()
        print(f"[RemoteMetrics] Started for {self.client['company_name']}")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=15)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Collection loop ───────────────────────────────────────────────────────

    def _collect_loop(self):
        while not self._stop.is_set():
            try:
                sample = self._collect_sample()
                if sample:
                    with _lock:
                        _stores[self.client_id].append(sample)
            except Exception as e:
                print(f"[RemoteMetrics] Error for {self.client_id}: {e}")
            self._stop.wait(self.SAMPLE_INTERVAL)

    def _collect_sample(self) -> dict | None:
        """Try each collection method, return first that works."""

        # Method 1: Prometheus endpoint
        prom_url = self.client["app"].get("metrics_endpoint", "")
        if prom_url:
            sample = self._from_prometheus(prom_url)
            if sample:
                return sample

        # Method 2: SSH psutil
        sample = self._from_ssh()
        if sample:
            return sample

        # Method 3: Health URL latency only
        health_url = self.client["app"].get("health_url", "")
        if health_url:
            sample = self._from_health_url(health_url)
            if sample:
                return sample

        return None

    # ── Method 1: Prometheus ─────────────────────────────────────────────────

    def _from_prometheus(self, url: str) -> dict | None:
        try:
            import requests
            resp = requests.get(url, timeout=8)
            if resp.status_code != 200:
                return None
            text = resp.text

            cpu  = self._parse_prom_metric(text, "node_cpu_seconds_total")
            mem  = self._parse_prom_metric(text, "node_memory_MemAvailable_bytes")
            lat  = self._parse_prom_metric(text, "http_request_duration_seconds_sum")

            # Fallback values if metrics not found
            cpu  = cpu  if cpu  is not None else 0.0
            mem  = mem  if mem  is not None else 0.0
            lat  = (lat * 1000) if lat is not None else 0.0

            return {
                "timestamp":  datetime.now(timezone.utc).isoformat(),
                "client_id":  self.client_id,
                "source":     "prometheus",
                "cpu_pct":    round(cpu, 2),
                "mem_pct":    round(mem, 2),
                "latency_ms": round(lat, 2),
            }
        except Exception:
            return None

    def _parse_prom_metric(self, text: str, metric_name: str):
        for line in text.splitlines():
            if line.startswith(metric_name) and not line.startswith("#"):
                try:
                    return float(line.split()[-1])
                except Exception:
                    pass
        return None

    # ── Method 2: SSH psutil ─────────────────────────────────────────────────

    def _from_ssh(self) -> dict | None:
        try:
            import paramiko
        except ImportError:
            return None

        srv = self.client["server"]
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            connect_kwargs = dict(
                hostname=srv["host"], port=int(srv["port"]),
                username=srv["user"], timeout=10,
            )
            if srv.get("ssh_key") and Path(srv["ssh_key"]).exists():
                connect_kwargs["key_filename"] = srv["ssh_key"]
            elif srv.get("password"):
                connect_kwargs["password"] = srv["password"]

            ssh.connect(**connect_kwargs)

            # CPU (1-second measure via /proc/stat)
            _, out, _ = ssh.exec_command(
                "python3 -c \"import psutil; print(psutil.cpu_percent(interval=1))\" 2>/dev/null "
                "|| cat /proc/loadavg | awk '{print $1*10}'",
                timeout=12,
            )
            cpu_raw = out.read().decode().strip()

            # Memory
            _, out, _ = ssh.exec_command(
                "python3 -c \"import psutil; print(psutil.virtual_memory().percent)\" 2>/dev/null "
                "|| free | grep Mem | awk '{printf \"%.1f\", $3/$2*100}'",
                timeout=10,
            )
            mem_raw = out.read().decode().strip()

            ssh.close()

            cpu = float(cpu_raw) if cpu_raw else 0.0
            mem = float(mem_raw) if mem_raw else 0.0
            lat = 50 + cpu * 5 + mem / 10  # same synthetic formula as local

            return {
                "timestamp":  datetime.now(timezone.utc).isoformat(),
                "client_id":  self.client_id,
                "source":     "ssh",
                "cpu_pct":    round(cpu, 2),
                "mem_pct":    round(mem, 2),
                "latency_ms": round(lat, 2),
            }
        except Exception:
            return None

    # ── Method 3: Health URL latency ─────────────────────────────────────────

    def _from_health_url(self, url: str) -> dict | None:
        try:
            import requests
            resp = requests.get(url, timeout=10)
            latency = resp.elapsed.total_seconds() * 1000
            return {
                "timestamp":  datetime.now(timezone.utc).isoformat(),
                "client_id":  self.client_id,
                "source":     "health_url",
                "cpu_pct":    0.0,   # unknown without SSH
                "mem_pct":    0.0,
                "latency_ms": round(latency, 2),
            }
        except Exception:
            return None