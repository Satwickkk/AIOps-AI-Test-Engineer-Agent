"""
webapp/load_generator.py
------------------------
Simulates real user traffic against the Flask app.
Run this alongside app.py so the agent has data to analyze.

Usage:
    python webapp/load_generator.py
"""

import random
import time

import requests

BASE = "http://localhost:5050"

ENDPOINTS = [
    ("/health", "GET", {}),
    ("/login", "POST", {}),
    ("/search", "GET", {"q": "python"}),
    ("/search", "GET", {"q": "error"}),
    ("/data", "GET", {}),
]

print("[Load Generator] Starting traffic simulation against", BASE)
print("[Load Generator] Press Ctrl+C to stop.\n")

while True:
    endpoint, method, params = random.choice(ENDPOINTS)
    url = BASE + endpoint
    try:
        if method == "GET":
            r = requests.get(url, params=params, timeout=10)
        else:
            r = requests.post(url, timeout=10)
        status = r.status_code
        print(f"  {method} {endpoint} → {status}")
    except Exception as e:
        print(f"  [ERROR] {endpoint}: {e}")

    # Random inter-request delay (0.3–1.5 seconds)
    time.sleep(random.uniform(0.3, 1.5))