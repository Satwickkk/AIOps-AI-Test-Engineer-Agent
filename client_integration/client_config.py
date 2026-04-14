"""
client_integration/client_config.py
-------------------------------------
Client Server Configuration Manager
======================================
Stores and manages connection details for client servers.
Each client gets a unique ID, and their DB + server details
are saved to client_integration/clients.json

Usage:
    from client_integration.client_config import ClientConfig
    cfg = ClientConfig()
    cfg.add_client(...)
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

CLIENTS_FILE = Path("client_integration/clients.json")


class ClientConfig:

    def __init__(self):
        CLIENTS_FILE.parent.mkdir(exist_ok=True)
        self._clients: dict = self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if CLIENTS_FILE.exists():
            try:
                return json.loads(CLIENTS_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self):
        CLIENTS_FILE.write_text(json.dumps(self._clients, indent=2))

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def add_client(
        self,
        company_name: str,
        website_url: str,
        # Server / SSH details
        server_host: str,
        server_port: int,
        server_user: str,
        ssh_key_path: str = "",          # path to private key OR leave blank for password
        server_password: str = "",       # optional password-based SSH
        # Application / log details
        app_log_path: str = "/var/log/app/app.log",
        metrics_endpoint: str = "",      # e.g. http://localhost:9090/metrics
        app_health_url: str = "",        # e.g. https://yoursite.com/health
        # Database details
        db_type: str = "mysql",          # mysql | postgres | mongodb | sqlite
        db_host: str = "localhost",
        db_port: int = 3306,
        db_name: str = "",
        db_user: str = "",
        db_password: str = "",
        # Alerts
        slack_webhook: str = "",
        pagerduty_key: str = "",
        contact_email: str = "",
    ) -> str:
        """Register a new client. Returns the generated client_id."""
        client_id = str(uuid.uuid4())[:8].upper()
        self._clients[client_id] = {
            "client_id":       client_id,
            "company_name":    company_name,
            "website_url":     website_url,
            "registered_at":   datetime.utcnow().isoformat(),
            "status":          "pending",   # pending | connected | error
            "server": {
                "host":        server_host,
                "port":        server_port,
                "user":        server_user,
                "ssh_key":     ssh_key_path,
                "password":    server_password,
            },
            "app": {
                "log_path":       app_log_path,
                "metrics_endpoint": metrics_endpoint,
                "health_url":     app_health_url,
            },
            "database": {
                "type":     db_type,
                "host":     db_host,
                "port":     db_port,
                "name":     db_name,
                "user":     db_user,
                "password": db_password,
            },
            "alerts": {
                "slack_webhook":   slack_webhook,
                "pagerduty_key":   pagerduty_key,
                "contact_email":   contact_email,
            },
            "proof": {
                "connection_verified": False,
                "verified_at":         None,
                "db_verified":         False,
                "log_verified":        False,
                "health_check_passed": False,
                "server_info":         {},
            }
        }
        self._save()
        print(f"[ClientConfig] Registered: {company_name} → ID: {client_id}")
        return client_id

    def get_client(self, client_id: str) -> dict | None:
        return self._clients.get(client_id)

    def get_all_clients(self) -> list[dict]:
        return list(self._clients.values())

    def update_proof(self, client_id: str, proof_data: dict):
        """Update connection proof fields after verification."""
        if client_id in self._clients:
            self._clients[client_id]["proof"].update(proof_data)
            self._clients[client_id]["status"] = (
                "connected" if proof_data.get("connection_verified") else "error"
            )
            self._save()

    def update_status(self, client_id: str, status: str):
        if client_id in self._clients:
            self._clients[client_id]["status"] = status
            self._save()

    def remove_client(self, client_id: str):
        if client_id in self._clients:
            del self._clients[client_id]
            self._save()