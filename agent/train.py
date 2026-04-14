"""
agent/train.py
--------------
OFFLINE TRAINING PHASE
======================
Trains two Isolation Forest models:
  1. metrics_model  — detects anomalies in system metrics (cpu, mem, latency)
  2. log_model      — detects anomalies in log patterns (error rates, warning rates, slow counts)

Run this once BEFORE starting the agent loop.
The trained models are saved to models/ directory.

Usage:
    python agent/train.py

Notes:
- Training data comes from metrics/metrics.csv and logs_store/app.log
- If insufficient real data exists, synthetic "normal" data is auto-generated
- Isolation Forest is unsupervised; no labels needed
- contamination=0.1 means we expect ~10% of points to be anomalous
"""

import json
import os
import pickle
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

MODELS_DIR = Path("models")
METRICS_CSV = Path("metrics/metrics.csv")
APP_LOG = Path("logs_store/app.log")

# ── Feature engineering helpers ───────────────────────────────────────────────

def load_metrics_features(csv_path: Path) -> np.ndarray:
    """
    Load metrics CSV and return feature matrix [cpu_pct, mem_pct, latency_ms].
    Falls back to synthetic normal data if file has < 20 rows.
    """
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        cols = ["cpu_pct", "mem_pct", "latency_ms"]
        df = df.dropna(subset=cols)
        if len(df) >= 20:
            print(f"[Train] Loaded {len(df)} metric rows from {csv_path}")
            return df[cols].values

    print("[Train] Insufficient metrics data — generating synthetic normal training set.")
    # Generate synthetic "normal" baseline
    rng = np.random.default_rng(42)
    n = 500
    cpu = rng.normal(loc=30, scale=10, size=n).clip(5, 90)
    mem = rng.normal(loc=45, scale=8, size=n).clip(20, 80)
    latency = rng.normal(loc=200, scale=40, size=n).clip(50, 500)
    return np.stack([cpu, mem, latency], axis=1)


def parse_log_windows(log_path: Path, window_minutes: int = 1) -> np.ndarray:
    """
    Parse app.log into per-window feature vectors:
      [error_count, warning_count, slow_count (latency > 1000ms), total_requests]
    
    Returns shape (n_windows, 4) array.
    Falls back to synthetic data if insufficient logs.
    """
    records = []
    if log_path.exists():
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    records.append(rec)
                except json.JSONDecodeError:
                    continue

    if len(records) < 30:
        print("[Train] Insufficient log data — generating synthetic normal log features.")
        rng = np.random.default_rng(42)
        n = 300
        errors   = rng.integers(0, 2, size=n)          # 0-1 errors per window normally
        warnings = rng.integers(0, 3, size=n)
        slow     = rng.integers(0, 2, size=n)
        total    = rng.integers(5, 20, size=n)
        return np.stack([errors, warnings, slow, total], axis=1).astype(float)

    # Build windowed features from real logs
    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    df["window"] = df["timestamp"].dt.floor(f"{window_minutes}min")

    features = []
    for _, grp in df.groupby("window"):
        error_count   = (grp["level"] == "ERROR").sum()
        warning_count = (grp["level"] == "WARNING").sum()
        slow_count    = (grp["latency_ms"].fillna(0) > 1000).sum()
        total         = len(grp)
        features.append([error_count, warning_count, slow_count, total])

    print(f"[Train] Extracted {len(features)} log windows from {log_path}")
    return np.array(features, dtype=float)


# ── Training routines ─────────────────────────────────────────────────────────

def train_metrics_model(X: np.ndarray):
    """Train Isolation Forest on metric features and save model + scaler."""
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(
        n_estimators=200,
        contamination=0.1,   # expect 10% anomaly rate in normal traffic
        random_state=42,
        max_samples="auto",
    )
    model.fit(X_scaled)

    MODELS_DIR.mkdir(exist_ok=True)
    with open(MODELS_DIR / "metrics_model.pkl", "wb") as f:
        pickle.dump({"model": model, "scaler": scaler}, f)
    print(f"[Train] metrics_model saved → {MODELS_DIR}/metrics_model.pkl")


def train_log_model(X: np.ndarray):
    """Train Isolation Forest on log-derived features and save model + scaler."""
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = IsolationForest(
        n_estimators=200,
        contamination=0.15,
        random_state=42,
        max_samples="auto",
    )
    model.fit(X_scaled)

    MODELS_DIR.mkdir(exist_ok=True)
    with open(MODELS_DIR / "log_model.pkl", "wb") as f:
        pickle.dump({"model": model, "scaler": scaler}, f)
    print(f"[Train] log_model saved → {MODELS_DIR}/log_model.pkl")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("AIOps Agent — Offline Training Phase")
    print("=" * 60)

    # Train metrics model
    X_metrics = load_metrics_features(METRICS_CSV)
    train_metrics_model(X_metrics)

    # Train log anomaly model
    X_logs = parse_log_windows(APP_LOG)
    train_log_model(X_logs)

    print("\n[Train] Training complete. Models saved to models/")
    print("[Train] You can now start the agent: python agent/agent_loop.py")