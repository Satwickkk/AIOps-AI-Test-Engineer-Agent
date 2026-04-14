"""
client_integration/server_connector.py
----------------------------------------
SSH Server Connector + Connection Proof Generator
===================================================
Connects to a client's server via SSH, verifies:
  - Server is reachable and SSH works
  - App log file exists and is readable
  - Database connection is valid
  - Health endpoint responds
Then writes a timestamped proof report.

Requirements:
    pip install paramiko pymysql psycopg2-binary pymongo requests

Usage:
    from client_integration.server_connector import ServerConnector
    from client_integration.client_config import ClientConfig

    cfg = ClientConfig()
    connector = ServerConnector(cfg)
    proof = connector.verify_client("ABC12345")
"""

import json
import socket
import threading
import time
from datetime import datetime
from pathlib import Path

PROOF_DIR = Path("client_integration/proof_reports")


class ServerConnector:

    def __init__(self, client_config):
        self.config = client_config
        PROOF_DIR.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC: Full verification for one client
    # ──────────────────────────────────────────────────────────────────────────

    def verify_client(self, client_id: str) -> dict:
        """
        Run all verification checks for a client.
        Returns a proof dict and saves a JSON report.
        """
        client = self.config.get_client(client_id)
        if not client:
            return {"error": f"Client {client_id} not found"}

        print(f"\n[Connector] Starting verification for {client['company_name']} ({client_id})")

        proof = {
            "client_id":            client_id,
            "company_name":         client["company_name"],
            "website_url":          client["website_url"],
            "verified_at":          datetime.utcnow().isoformat(),
            "connection_verified":  False,
            "db_verified":          False,
            "log_verified":         False,
            "health_check_passed":  False,
            "server_info":          {},
            "db_info":              {},
            "log_info":             {},
            "health_info":          {},
            "errors":               [],
        }

        # 1. SSH connection check
        ssh_ok, ssh_info, ssh_client = self._check_ssh(client, proof)

        # 2. Server info (hostname, OS, uptime, disk)
        if ssh_ok and ssh_client:
            self._collect_server_info(ssh_client, proof)

        # 3. Log file verification
        if ssh_ok and ssh_client:
            self._check_log_file(ssh_client, client, proof)

        # 4. Database connection
        self._check_database(client, proof)

        # 5. Health endpoint check (does not need SSH)
        self._check_health_url(client, proof)

        # 6. Close SSH
        if ssh_client:
            try:
                ssh_client.close()
            except Exception:
                pass

        # 7. Save proof report
        self._save_proof_report(client_id, proof)

        # 8. Update config with proof
        self.config.update_proof(client_id, proof)

        status = "✅ CONNECTED" if proof["connection_verified"] else "❌ FAILED"
        print(f"[Connector] Verification complete: {status}")
        return proof

    # ──────────────────────────────────────────────────────────────────────────
    # SSH CHECK
    # ──────────────────────────────────────────────────────────────────────────

    def _check_ssh(self, client: dict, proof: dict):
        """Try SSH connection. Returns (success, info, ssh_client_or_None)."""
        try:
            import paramiko
        except ImportError:
            msg = "paramiko not installed. Run: pip install paramiko"
            proof["errors"].append(msg)
            print(f"[Connector] {msg}")
            return False, {}, None

        srv = client["server"]
        print(f"[Connector] SSH → {srv['user']}@{srv['host']}:{srv['port']}")

        try:
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
            proof["connection_verified"] = True
            print(f"[Connector] SSH OK ✅")
            return True, {}, ssh

        except Exception as e:
            proof["errors"].append(f"SSH failed: {e}")
            proof["connection_verified"] = False
            print(f"[Connector] SSH FAILED ❌ — {e}")
            return False, {}, None

    # ──────────────────────────────────────────────────────────────────────────
    # SERVER INFO COLLECTION
    # ──────────────────────────────────────────────────────────────────────────

    def _collect_server_info(self, ssh, proof: dict):
        """Collect hostname, OS, uptime, CPU count, disk usage."""
        commands = {
            "hostname":    "hostname",
            "os_info":     "cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"' 2>/dev/null || uname -s",
            "kernel":      "uname -r",
            "uptime":      "uptime -p 2>/dev/null || uptime",
            "cpu_cores":   "nproc",
            "disk_usage":  "df -h / | tail -1",
            "memory_total":"free -h | grep Mem | awk '{print $2}'",
            "python_ver":  "python3 --version 2>&1",
            "pip_packages":"pip3 list 2>/dev/null | grep -E 'flask|psutil|groq|streamlit' | head -10",
        }
        info = {}
        for key, cmd in commands.items():
            try:
                _, stdout, _ = ssh.exec_command(cmd, timeout=10)
                info[key] = stdout.read().decode().strip()
            except Exception as e:
                info[key] = f"error: {e}"

        proof["server_info"] = info
        print(f"[Connector] Server: {info.get('hostname','?')} | OS: {info.get('os_info','?')}")

    # ──────────────────────────────────────────────────────────────────────────
    # LOG FILE CHECK
    # ──────────────────────────────────────────────────────────────────────────

    def _check_log_file(self, ssh, client: dict, proof: dict):
        """Check if the app log file exists and tail last 5 lines."""
        log_path = client["app"]["log_path"]
        print(f"[Connector] Checking log: {log_path}")
        try:
            # Check file exists
            _, out, _ = ssh.exec_command(f"test -f {log_path} && echo EXISTS || echo MISSING", timeout=10)
            result = out.read().decode().strip()
            if "MISSING" in result:
                proof["errors"].append(f"Log file not found: {log_path}")
                proof["log_verified"] = False
                print(f"[Connector] Log MISSING ❌")
                return

            # Get file size
            _, out, _ = ssh.exec_command(f"du -sh {log_path} 2>/dev/null", timeout=10)
            file_size = out.read().decode().strip()

            # Tail last 5 lines
            _, out, _ = ssh.exec_command(f"tail -5 {log_path} 2>/dev/null", timeout=10)
            tail_lines = out.read().decode().strip()

            # Line count
            _, out, _ = ssh.exec_command(f"wc -l < {log_path} 2>/dev/null", timeout=10)
            line_count = out.read().decode().strip()

            proof["log_info"] = {
                "path":       log_path,
                "exists":     True,
                "file_size":  file_size,
                "line_count": line_count,
                "tail_sample": tail_lines[:500],
            }
            proof["log_verified"] = True
            print(f"[Connector] Log OK ✅ — {file_size}, {line_count} lines")

        except Exception as e:
            proof["errors"].append(f"Log check failed: {e}")
            print(f"[Connector] Log check error: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # DATABASE CHECK
    # ──────────────────────────────────────────────────────────────────────────

    def _check_database(self, client: dict, proof: dict):
        """Try connecting to the client's database."""
        db = client["database"]
        db_type = db.get("type", "").lower()
        print(f"[Connector] DB check: {db_type} @ {db['host']}:{db['port']}")

        try:
            if db_type == "mysql":
                self._check_mysql(db, proof)
            elif db_type in ("postgres", "postgresql"):
                self._check_postgres(db, proof)
            elif db_type == "mongodb":
                self._check_mongo(db, proof)
            elif db_type == "sqlite":
                self._check_sqlite(db, proof)
            else:
                # Generic TCP port check for unknown DB types
                self._check_tcp_port(db["host"], int(db["port"]), proof, label=db_type)
        except Exception as e:
            proof["errors"].append(f"DB check error: {e}")
            proof["db_verified"] = False
            print(f"[Connector] DB error: {e}")

    def _check_mysql(self, db: dict, proof: dict):
        try:
            import pymysql
            conn = pymysql.connect(
                host=db["host"], port=int(db["port"]),
                user=db["user"], password=db["password"],
                database=db["name"], connect_timeout=10
            )
            cur = conn.cursor()
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
            cur.execute("SHOW TABLES")
            tables = [r[0] for r in cur.fetchall()]
            conn.close()
            proof["db_info"]  = {"type": "mysql", "version": version, "tables": tables[:10], "table_count": len(tables)}
            proof["db_verified"] = True
            print(f"[Connector] MySQL OK ✅ — v{version}, {len(tables)} tables")
        except ImportError:
            proof["errors"].append("pymysql not installed: pip install pymysql")
        except Exception as e:
            proof["errors"].append(f"MySQL: {e}")
            proof["db_verified"] = False
            print(f"[Connector] MySQL FAILED ❌ — {e}")

    def _check_postgres(self, db: dict, proof: dict):
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=db["host"], port=int(db["port"]),
                user=db["user"], password=db["password"],
                dbname=db["name"], connect_timeout=10
            )
            cur = conn.cursor()
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            tables = [r[0] for r in cur.fetchall()]
            conn.close()
            proof["db_info"]  = {"type": "postgres", "version": version[:60], "tables": tables[:10], "table_count": len(tables)}
            proof["db_verified"] = True
            print(f"[Connector] PostgreSQL OK ✅ — {len(tables)} tables")
        except ImportError:
            proof["errors"].append("psycopg2 not installed: pip install psycopg2-binary")
        except Exception as e:
            proof["errors"].append(f"PostgreSQL: {e}")
            proof["db_verified"] = False
            print(f"[Connector] PostgreSQL FAILED ❌ — {e}")

    def _check_mongo(self, db: dict, proof: dict):
        try:
            import pymongo
            uri = f"mongodb://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['name']}"
            client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=10000)
            client.server_info()
            collections = client[db["name"]].list_collection_names()
            proof["db_info"]  = {"type": "mongodb", "collections": collections[:10], "collection_count": len(collections)}
            proof["db_verified"] = True
            client.close()
            print(f"[Connector] MongoDB OK ✅ — {len(collections)} collections")
        except ImportError:
            proof["errors"].append("pymongo not installed: pip install pymongo")
        except Exception as e:
            proof["errors"].append(f"MongoDB: {e}")
            proof["db_verified"] = False
            print(f"[Connector] MongoDB FAILED ❌ — {e}")

    def _check_sqlite(self, db: dict, proof: dict):
        import sqlite3
        db_path = db.get("name", "")
        if not Path(db_path).exists():
            proof["errors"].append(f"SQLite file not found: {db_path}")
            return
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        conn.close()
        proof["db_info"]  = {"type": "sqlite", "tables": tables, "table_count": len(tables)}
        proof["db_verified"] = True
        print(f"[Connector] SQLite OK ✅ — {len(tables)} tables")

    def _check_tcp_port(self, host: str, port: int, proof: dict, label=""):
        try:
            sock = socket.create_connection((host, port), timeout=10)
            sock.close()
            proof["db_info"]  = {"type": label, "host": host, "port": port, "reachable": True}
            proof["db_verified"] = True
            print(f"[Connector] {label} port {port} OK ✅")
        except Exception as e:
            proof["errors"].append(f"TCP {label}: {e}")
            proof["db_verified"] = False

    # ──────────────────────────────────────────────────────────────────────────
    # HEALTH URL CHECK
    # ──────────────────────────────────────────────────────────────────────────

    def _check_health_url(self, client: dict, proof: dict):
        url = client["app"].get("health_url", "")
        if not url:
            return
        print(f"[Connector] Health check: {url}")
        try:
            import requests
            resp = requests.get(url, timeout=10)
            proof["health_info"] = {
                "url":         url,
                "status_code": resp.status_code,
                "response_ms": round(resp.elapsed.total_seconds() * 1000, 1),
                "body_sample": resp.text[:200],
            }
            proof["health_check_passed"] = (resp.status_code == 200)
            icon = "✅" if proof["health_check_passed"] else "⚠️"
            print(f"[Connector] Health {icon} — HTTP {resp.status_code}")
        except Exception as e:
            proof["errors"].append(f"Health URL: {e}")
            print(f"[Connector] Health FAILED ❌ — {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # SAVE PROOF REPORT
    # ──────────────────────────────────────────────────────────────────────────

    def _save_proof_report(self, client_id: str, proof: dict):
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        report_path = PROOF_DIR / f"{client_id}_{ts}.json"
        report_path.write_text(json.dumps(proof, indent=2))
        print(f"[Connector] Proof saved → {report_path}")

    def get_latest_proof(self, client_id: str) -> dict | None:
        """Load the most recent proof report for a client."""
        reports = sorted(PROOF_DIR.glob(f"{client_id}_*.json"), reverse=True)
        if reports:
            return json.loads(reports[0].read_text())
        return None