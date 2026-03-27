"""
agent/llm_reasoning.py
-----------------------
LLM Reasoning Module (Groq backend)
=====================================
Calls the Groq API to generate:
  - Root cause hypothesis
  - Plain-English explanation
  - Suggested fixes (NO auto-remediation)
  - Prevention steps

Called ONLY when anomalies are confirmed by the ML models (anomaly-gated LLM calls).

Safety note: This module ONLY suggests fixes. It never executes commands.
"""

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from groq import Groq

from agent.rca_builder import RCAEvidence


@dataclass
class RCAResult:
    """Final RCA output: LLM-generated analysis + metadata."""
    timestamp: str
    severity: str
    dominant_issue: str
    root_cause: str
    explanation: str
    suggested_fixes: list[str]
    prevention_steps: list[str]
    confidence: str        # HIGH / MEDIUM / LOW — self-reported by LLM
    raw_evidence: dict     # Serialized RCAEvidence for dashboard display


def _evidence_to_prompt(evidence: RCAEvidence) -> str:
    """
    Build a structured prompt for the LLM.
    Provides all evidence in a clean, structured format.
    """
    error_msgs_str = "\n".join(
        f"  - {msg}" for msg in evidence.sample_error_messages
    ) or "  (none captured)"

    return f"""You are an expert Site Reliability Engineer (SRE) and AIOps analyst.
A machine learning anomaly detection system has flagged the following evidence from a running web application.

## Anomaly Report
- Timestamp: {evidence.timestamp}
- Severity: {evidence.severity}
- Correlated (metrics + logs both anomalous): {evidence.correlated}
- Primary Signal: {evidence.dominant_issue}

## System Metrics (anomalous samples)
- Anomalous metric points: {evidence.metric_anomaly_count}
- Average CPU: {evidence.avg_cpu_pct}%
- Peak CPU: {evidence.max_cpu_pct}%
- Average Memory: {evidence.avg_mem_pct}%
- Average Latency: {evidence.avg_latency_ms}ms
- Peak Latency: {evidence.max_latency_ms}ms

## Log Analysis (last 5 minutes)
- Total requests: {evidence.total_requests_in_window}
- Error count: {evidence.error_count}
- Warning count: {evidence.warning_count}
- Slow requests (>1s): {evidence.slow_request_count}
- Error rate: {evidence.error_rate_pct}%

## Sample Error Messages
{error_msgs_str}

## Context
{evidence.context_summary}

---
Based on this evidence, provide a Root Cause Analysis in the following JSON format:
{{
  "root_cause": "<1-2 sentence concise root cause>",
  "explanation": "<3-5 sentence detailed explanation of what is happening and why>",
  "suggested_fixes": [
    "<Fix 1 - specific and actionable>",
    "<Fix 2>",
    "<Fix 3>"
  ],
  "prevention_steps": [
    "<Prevention step 1>",
    "<Prevention step 2>"
  ],
  "confidence": "<HIGH|MEDIUM|LOW based on evidence quality>"
}}

IMPORTANT:
- Do NOT suggest any auto-remediation scripts or destructive actions.
- Focus on explanatory fixes (config changes, code fixes, scaling hints).
- Be specific to the observed symptoms.
- Return ONLY valid JSON, no markdown code blocks.
"""


def analyze_with_llm(evidence: RCAEvidence) -> RCAResult:
    """
    Run LLM-based root cause analysis using Groq.

    Args:
        evidence: Structured anomaly evidence from rca_builder.py
    Returns:
        RCAResult with full RCA output.

    Raises:
        RuntimeError if GROQ_API_KEY is not set.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY environment variable not set.\n"
            "Set it with:  $env:GROQ_API_KEY = 'gsk_your-key-here'"
        )

    # Build prompt first (before client call)
    prompt = _evidence_to_prompt(evidence)

    client = Groq(api_key=api_key)

    print(f"[LLM] Sending RCA request to Groq... (severity={evidence.severity})")

    chat_completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        max_tokens=1024,
        temperature=0.3,
        messages=[
            {
                "role": "system",
                "content": "You are an expert SRE. Always respond with valid JSON only. No markdown, no explanation outside the JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
    )

    raw_response = chat_completion.choices[0].message.content.strip()

    # Parse JSON response from LLM
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        # Strip markdown fences and retry
        clean = re.sub(r"```(?:json)?|```", "", raw_response).strip()
        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', clean, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
            else:
                parsed = {
                    "root_cause": "LLM response could not be parsed as JSON.",
                    "explanation": raw_response[:500],
                    "suggested_fixes": ["Review raw LLM output manually."],
                    "prevention_steps": [],
                    "confidence": "LOW",
                }

    return RCAResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        severity=evidence.severity,
        dominant_issue=evidence.dominant_issue,
        root_cause=parsed.get("root_cause", "Unknown"),
        explanation=parsed.get("explanation", ""),
        suggested_fixes=parsed.get("suggested_fixes", []),
        prevention_steps=parsed.get("prevention_steps", []),
        confidence=parsed.get("confidence", "LOW"),
        raw_evidence={
            "avg_cpu_pct": evidence.avg_cpu_pct,
            "max_cpu_pct": evidence.max_cpu_pct,
            "avg_mem_pct": evidence.avg_mem_pct,
            "avg_latency_ms": evidence.avg_latency_ms,
            "max_latency_ms": evidence.max_latency_ms,
            "error_count": evidence.error_count,
            "warning_count": evidence.warning_count,
            "slow_count": evidence.slow_request_count,
            "error_rate_pct": evidence.error_rate_pct,
            "error_messages": evidence.sample_error_messages,
            "dominant_issue": evidence.dominant_issue,
            "correlated": evidence.correlated,
            "severity": evidence.severity,
        },
    )


def format_rca_for_console(result: RCAResult) -> str:
    """Pretty-print RCA result to terminal."""
    sep = "=" * 70
    fixes = "\n".join(f"  {i+1}. {f}" for i, f in enumerate(result.suggested_fixes))
    prevention = "\n".join(f"  {i+1}. {p}" for i, p in enumerate(result.prevention_steps))
    return f"""
{sep}
ROOT CAUSE ANALYSIS  [{result.timestamp}]
{sep}
Severity   : {result.severity}
Confidence : {result.confidence}
Issue      : {result.dominant_issue}

ROOT CAUSE:
  {result.root_cause}

EXPLANATION:
  {result.explanation}

SUGGESTED FIXES:
{fixes}

PREVENTION STEPS:
{prevention}
{sep}
NOTE: No auto-remediation performed. All fixes are suggestions only.
{sep}
"""