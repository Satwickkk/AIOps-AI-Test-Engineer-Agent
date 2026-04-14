"""
client_integration/remote_log_collector.py
--------------------------------------------
Remote Log Puller via SSH
===========================
Continuously pulls the client's app.log from their server
via SSH and stores it locally in logs_store/<client_id>/app.log
so the existing agent inference pipeline can read it without
any changes.

The agent treats this file exactly like the local app.log —
no other code needs to change.

Usage:
    from client_integration.remote_log_collector import RemoteLogCollector
    collector = RemoteLogCollector(client_config, client_id)
    collector.start()   # runs in background thread
    collector.stop()
"""

import threading
import time
from datetime import datetime
from pathlib import Path


class RemoteLogCollector:

    PULL_INTERVAL = 10   # seconds between each SSH pull

    def __init__(self, client_config, client_id: str):
        self.config    = client_config
        self.client_id = client_id
        self._stop     = threading.Event()
        self._thread   = None
        self._last_size = 0

        client = self.config.get_client(client_id)
        if not client:
            raise ValueError(f"Client {client_id} not found")
        self.client = client

        # Local destination log file — agent reads from here
        self.local_log = Path(f"logs_store/{client_id}/app.log")
        self.local_log.parent.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        """Start background SSH log pulling thread."""
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._pull_loop,
            name=f"LogPull-{self.client_id}",
            daemon=True,
        )
        self._thread.start()
        print(f"[RemoteLog] Started pulling logs for {self.client['company_name']}")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=15)
        print(f"[RemoteLog] Stopped for {self.client_id}")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Background loop ───────────────────────────────────────────────────────

    def _pull_loop(self):
        while not self._stop.is_set():
            try:
                self._pull_once()
            except Exception as e:
                print(f"[RemoteLog] Pull error for {self.client_id}: {e}")
            self._stop.wait(self.PULL_INTERVAL)

    def _pull_once(self):
        """Open SSH, pull new log lines since last pull, append locally."""
        try:
            import paramiko
        except ImportError:
            print("[RemoteLog] paramiko not installed. Run: pip install paramiko")
            return

        srv  = self.client["server"]
        app  = self.client["app"]
        log  = app["log_path"]

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = dict(
            hostname=srv["host"],
            port=int(srv["port"]),
            username=srv["user"],
            timeout=15,
        )
        if srv.get("ssh_key") and Path(srv["ssh_key"]).exists():
            connect_kwargs["key_filename"] = srv["ssh_key"]
        elif srv.get("password"):
            connect_kwargs["password"] = srv["password"]

        ssh.connect(**connect_kwargs)

        # Get current remote file size
        _, out, _ = ssh.exec_command(f"wc -c < {log} 2>/dev/null || echo 0", timeout=10)
        remote_size = int(out.read().decode().strip() or "0")

        if remote_size > self._last_size:
            # Pull only new bytes since last pull
            skip = self._last_size
            _, out, _ = ssh.exec_command(
                f"tail -c +{skip + 1} {log} 2>/dev/null",
                timeout=15,
            )
            new_data = out.read()
            if new_data:
                with open(self.local_log, "ab") as f:
                    f.write(new_data)
                lines = new_data.count(b"\n")
                print(f"[RemoteLog] {self.client_id} — pulled {lines} new lines "
                      f"({len(new_data)} bytes)")
            self._last_size = remote_size
        else:
            print(f"[RemoteLog] {self.client_id} — no new log data")

        ssh.close()

    # ── One-shot pull ─────────────────────────────────────────────────────────

    def pull_now(self) -> int:
        """Pull immediately (blocking). Returns number of new bytes pulled."""
        before = self.local_log.stat().st_size if self.local_log.exists() else 0
        self._pull_once()
        after  = self.local_log.stat().st_size if self.local_log.exists() else 0
        return after - before