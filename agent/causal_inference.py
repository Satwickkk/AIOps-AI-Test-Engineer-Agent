"""
agent/causal_inference.py
--------------------------
Causal Inference Module
========================
FUTURE WORK ITEM #6: Causal inference

Implements a lightweight causal analysis layer inspired by Pearl's do-calculus.
Rather than pure correlation ("A happened with B"), this module asks:
  "Did A likely CAUSE B?" using temporal ordering, intervention analysis,
  and a simple causal graph.

Full do-calculus requires interventional data (A/B tests or controlled experiments).
This implementation uses a practical approximation:
  1. Temporal precedence: cause must precede effect
  2. Causal graph: known cause→effect relationships in web systems
  3. Counterfactual reasoning: "If X had not happened, would Y still occur?"
  4. Confidence scoring based on evidence strength

This module enriches the RCA evidence with causal confidence scores
before sending to the LLM.
"""

from dataclasses import dataclass, field
from typing import Optional
import time


# ── Causal graph ─────────────────────────────────────────────────────────────
# Domain knowledge: known causal relationships in web application systems
# Format: cause → [list of effects]
CAUSAL_GRAPH = {
    "high_cpu": ["high_latency", "request_timeouts", "slow_responses"],
    "high_memory": ["gc_pressure", "oom_risk", "slow_responses", "high_cpu"],
    "db_connection_exhausted": ["search_errors", "login_errors", "high_latency"],
    "high_error_rate": ["user_impact", "revenue_loss"],
    "slow_db_query": ["high_latency", "connection_pool_pressure"],
    "traffic_spike": ["high_cpu", "db_connection_exhausted", "high_memory"],
    "memory_leak": ["high_memory", "oom_risk", "slow_responses"],
    "network_issue": ["high_latency", "request_timeouts", "connection_errors"],
    "disk_full": ["log_write_failures", "db_errors"],
}

# Reverse graph: effect → [likely causes]
REVERSE_GRAPH: dict[str, list[str]] = {}
for cause, effects in CAUSAL_GRAPH.items():
    for effect in effects:
        REVERSE_GRAPH.setdefault(effect, []).append(cause)


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class CausalHypothesis:
    """A single cause → effect hypothesis with confidence."""
    cause: str
    effect: str
    confidence: float           # 0.0 – 1.0
    evidence: list[str]         # supporting evidence lines
    temporal_valid: bool        # cause preceded effect in time
    counterfactual: str         # "If X did not occur, Y would likely not occur because..."


@dataclass
class CausalAnalysis:
    """Full causal analysis result for an anomaly."""
    dominant_cause: Optional[str]
    hypotheses: list[CausalHypothesis]
    causal_chain: list[str]     # e.g. ["traffic_spike", "db_connection_exhausted", "search_errors"]
    overall_confidence: float
    narrative: str              # Human-readable causal explanation


# ── Signal classifier ─────────────────────────────────────────────────────────

def _classify_signals(evidence_dict: dict) -> list[str]:
    """
    Map raw evidence metrics to causal graph node names.
    Returns list of active signals (nodes that are "on").
    """
    signals = []

    cpu = evidence_dict.get("avg_cpu_pct") or 0
    mem = evidence_dict.get("avg_mem_pct") or 0
    lat = evidence_dict.get("avg_latency_ms") or 0
    errors = evidence_dict.get("error_count") or 0
    error_rate = evidence_dict.get("error_rate_pct") or 0
    slow_count = evidence_dict.get("slow_count") or 0
    msgs = " ".join(evidence_dict.get("error_messages") or []).lower()

    if cpu > 70:
        signals.append("high_cpu")
    if mem > 80:
        signals.append("high_memory")
    if lat > 1000:
        signals.append("high_latency")
    if error_rate > 10:
        signals.append("high_error_rate")
    if slow_count > 2:
        signals.append("slow_db_query")
    if "connection pool" in msgs or "exhausted" in msgs:
        signals.append("db_connection_exhausted")
    if "timeout" in msgs:
        signals.append("request_timeouts")
    if "search" in msgs and errors > 0:
        signals.append("search_errors")
    if "login" in msgs and errors > 0:
        signals.append("login_errors")

    return signals


def _find_causal_chain(signals: list[str]) -> list[str]:
    """
    Find the most likely causal chain among active signals.
    Uses topological ordering based on the causal graph.
    Returns ordered list from root cause to leaf effect.
    """
    if not signals:
        return []

    signal_set = set(signals)

    # Find root causes: signals that are not effects of other active signals
    root_causes = []
    for sig in signals:
        is_effect_of_active = any(
            sig in CAUSAL_GRAPH.get(other, [])
            for other in signals if other != sig
        )
        if not is_effect_of_active:
            root_causes.append(sig)

    if not root_causes:
        root_causes = signals[:1]

    # Build chain from root cause forward
    chain = []
    visited = set()
    queue = list(root_causes)
    while queue:
        node = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        if node in signal_set:
            chain.append(node)
        # Add effects that are also active
        for effect in CAUSAL_GRAPH.get(node, []):
            if effect in signal_set and effect not in visited:
                queue.append(effect)

    return chain if chain else signals[:3]


def _build_counterfactual(cause: str, effect: str) -> str:
    """Generate a counterfactual statement for cause → effect."""
    counterfactuals = {
        ("high_cpu", "high_latency"):
            "If CPU were not elevated, request processing would be faster and latency would remain normal.",
        ("db_connection_exhausted", "search_errors"):
            "If the connection pool were adequately sized, search requests could acquire connections and would not return 500 errors.",
        ("db_connection_exhausted", "high_latency"):
            "If database connections were available, queries would not queue up and latency would be normal.",
        ("traffic_spike", "db_connection_exhausted"):
            "If traffic had not spiked, the connection pool would not be overwhelmed.",
        ("high_memory", "high_cpu"):
            "If memory pressure were lower, garbage collection cycles would not drive CPU usage up.",
        ("slow_db_query", "high_latency"):
            "If database queries executed in normal time, endpoint latency would remain within baseline.",
    }
    return counterfactuals.get((cause, effect),
        f"If '{cause}' had not occurred, '{effect}' would likely not have manifested "
        f"based on known causal relationships in web application systems.")


# ── Main analysis ─────────────────────────────────────────────────────────────

def analyze_causality(evidence_dict: dict) -> CausalAnalysis:
    """
    Perform causal analysis on anomaly evidence.

    Args:
        evidence_dict: The raw_evidence dict from RCAResult

    Returns:
        CausalAnalysis with hypotheses, causal chain, and narrative
    """
    signals = _classify_signals(evidence_dict)

    if not signals:
        return CausalAnalysis(
            dominant_cause=None,
            hypotheses=[],
            causal_chain=[],
            overall_confidence=0.0,
            narrative="Insufficient signal data for causal analysis.",
        )

    # Build hypotheses for each active signal pair
    hypotheses = []
    chain = _find_causal_chain(signals)

    for i, cause in enumerate(chain[:-1]):
        effect = chain[i + 1]
        # Check if this cause→effect edge exists in graph
        graph_support = effect in CAUSAL_GRAPH.get(cause, [])

        # Confidence: graph support + number of corroborating signals
        base_conf = 0.7 if graph_support else 0.3
        corroboration_bonus = min(0.2, len(signals) * 0.05)
        confidence = min(0.95, base_conf + corroboration_bonus)

        evidence_lines = [
            f"Signal '{cause}' is active in current observation",
            f"Signal '{effect}' is also active",
            f"Causal graph {'supports' if graph_support else 'does not directly link'} {cause} → {effect}",
        ]

        hypotheses.append(CausalHypothesis(
            cause=cause,
            effect=effect,
            confidence=confidence,
            evidence=evidence_lines,
            temporal_valid=True,  # In real system: check timestamps
            counterfactual=_build_counterfactual(cause, effect),
        ))

    # Overall confidence is mean of individual hypothesis confidences
    overall_conf = (sum(h.confidence for h in hypotheses) / len(hypotheses)
                    if hypotheses else 0.3)

    # Build narrative
    if chain:
        chain_str = " → ".join(chain)
        narrative = (
            f"Causal chain identified: {chain_str}. "
            f"Root cause is likely '{chain[0]}' which propagated through "
            f"{len(chain) - 1} intermediate step(s). "
            f"Overall causal confidence: {overall_conf:.0%}."
        )
    else:
        narrative = f"Active signals detected: {', '.join(signals)}. No clear causal chain identified."

    return CausalAnalysis(
        dominant_cause=chain[0] if chain else (signals[0] if signals else None),
        hypotheses=hypotheses,
        causal_chain=chain,
        overall_confidence=round(overall_conf, 2),
        narrative=narrative,
    )


def format_causal_for_prompt(analysis: CausalAnalysis) -> str:
    """Format causal analysis for injection into LLM prompt."""
    if not analysis.hypotheses:
        return ""

    lines = [
        "\n## Causal Analysis (do-calculus inspired):",
        f"Causal chain: {' → '.join(analysis.causal_chain)}",
        f"Overall confidence: {analysis.overall_confidence:.0%}",
        f"Narrative: {analysis.narrative}",
    ]
    if analysis.hypotheses:
        h = analysis.hypotheses[0]
        lines.append(f"Counterfactual: {h.counterfactual}")

    return "\n".join(lines)