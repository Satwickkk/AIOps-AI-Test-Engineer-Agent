"""
client_integration/client_manager.py
--------------------------------------
Central Client Manager
========================
Registers a new client, verifies the connection, and starts
live monitoring (log pulling + metrics collection) — all in one call.

This is the only file you need to import to onboard a client.

Usage:
    from client_integration.client_manager import ClientManager

    mgr = ClientManager()

    client_id = mgr.onboard(
        company_name   = "Acme Corp",
        website_url    = "https://acme.com",
        server_host    = "203.0.113.10",
        server_port    = 22,
        server_user    = "ubuntu",
        ssh_key_path   = "~/.ssh/acme_key.pem",
        app_log_path   = "/var/log/acme/app.log",
        db_type        = "mysql",
        db_host        = "localhost",
        db_port        = 3306,
        db_name        = "acme_db",
        db_user        = "monitor_user",
        db_password    = "secret",
        app_health_url = "https://acme.com/health",
    )

    proof = mgr.get_proof(client_id)
    mgr.start_monitoring(client_id)
"""

from client_integration.client_config          import ClientConfig
from client_integration.server_connector        import ServerConnector
from client_integration.remote_log_collector    import RemoteLogCollector
from client_integration.remote_metrics_collector import RemoteMetricsCollector


class ClientManager:

    def __init__(self):
        self.config    = ClientConfig()
        self.connector = ServerConnector(self.config)
        self._log_collectors:     dict[str, RemoteLogCollector]     = {}
        self._metrics_collectors: dict[str, RemoteMetricsCollector] = {}

    # ── Onboarding ────────────────────────────────────────────────────────────

    def onboard(self, **kwargs) -> str:
        """
        Register + verify a new client in one step.
        Returns client_id.
        """
        client_id = self.config.add_client(**kwargs)
        print(f"\n[Manager] Onboarding {kwargs.get('company_name')} — ID: {client_id}")

        # Run full verification
        proof = self.connector.verify_client(client_id)

        if proof.get("connection_verified"):
            print(f"[Manager] ✅ {kwargs.get('company_name')} connected successfully")
        else:
            print(f"[Manager] ⚠️  Connection issues: {proof.get('errors', [])}")

        return client_id

    # ── Monitoring ────────────────────────────────────────────────────────────

    def start_monitoring(self, client_id: str):
        """Start log pulling and metrics collection for a client."""
        client = self.config.get_client(client_id)
        if not client:
            print(f"[Manager] Client {client_id} not found")
            return

        # Start log collector
        if client_id not in self._log_collectors:
            lc = RemoteLogCollector(self.config, client_id)
            lc.start()
            self._log_collectors[client_id] = lc

        # Start metrics collector
        if client_id not in self._metrics_collectors:
            mc = RemoteMetricsCollector(self.config, client_id)
            mc.start()
            self._metrics_collectors[client_id] = mc

        print(f"[Manager] Monitoring started for {client['company_name']}")

    def stop_monitoring(self, client_id: str):
        if client_id in self._log_collectors:
            self._log_collectors[client_id].stop()
            del self._log_collectors[client_id]
        if client_id in self._metrics_collectors:
            self._metrics_collectors[client_id].stop()
            del self._metrics_collectors[client_id]
        print(f"[Manager] Monitoring stopped for {client_id}")

    def get_monitoring_status(self, client_id: str) -> dict:
        return {
            "log_collector_running":     self._log_collectors.get(client_id, None) is not None
                                         and self._log_collectors[client_id].is_running(),
            "metrics_collector_running": self._metrics_collectors.get(client_id, None) is not None
                                         and self._metrics_collectors[client_id].is_running(),
        }

    # ── Proof & Status ────────────────────────────────────────────────────────

    def get_proof(self, client_id: str) -> dict | None:
        return self.connector.get_latest_proof(client_id)

    def verify_client(self, client_id: str) -> dict:
        return self.connector.verify_client(client_id)

    def list_clients(self) -> list[dict]:
        return self.config.get_all_clients()

    def remove_client(self, client_id: str):
        self.stop_monitoring(client_id)
        self.config.remove_client(client_id)
        print(f"[Manager] Client {client_id} removed")