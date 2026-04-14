"""
feedback/rlhf_loop.py
----------------------
RLHF-Inspired Prompt Tuning Loop
==================================
FUTURE WORK ITEM #7: RLHF loop

Implements a lightweight Reinforcement Learning from Human Feedback (RLHF)
inspired loop for prompt optimization.

Full RLHF requires:
  - A reward model trained on human preferences
  - PPO or similar RL algorithm
  - Thousands of labeled examples

This implementation uses a practical approximation:
  - Human feedback (RESOLVED/PARTIAL/UNRESOLVED) acts as reward signal
  - Prompt templates are scored and ranked
  - High-scoring prompt components are reinforced in future calls
  - Low-scoring components are de-emphasized or swapped out

Prompt components that can be tuned:
  - Tone (formal SRE / concise bullets / detailed analysis)
  - Context depth (minimal / standard / comprehensive)
  - Output format (JSON fields / markdown / structured)
  - Example injection (zero-shot / few-shot with past incidents)
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

RLHF_STORE = Path("feedback/rlhf_scores.json")
BEST_PROMPT_FILE = Path("feedback/best_prompt_config.json")


# ── Prompt templates ──────────────────────────────────────────────────────────

PROMPT_VARIANTS = {
    "tone_formal": (
        "You are a senior Site Reliability Engineer (SRE). "
        "Provide a precise technical root cause analysis."
    ),
    "tone_concise": (
        "You are an expert DevOps engineer. Be brief and direct. "
        "Focus on the most likely cause and most actionable fix."
    ),
    "tone_comprehensive": (
        "You are an AIOps expert with deep knowledge of distributed systems. "
        "Provide comprehensive analysis covering all possible causes."
    ),
    "context_minimal": "Analyze the following anomaly evidence:",
    "context_standard": (
        "A machine learning anomaly detection system has flagged the following evidence "
        "from a running web application. Analyze it:"
    ),
    "context_comprehensive": (
        "A production web application is experiencing issues. The following evidence "
        "was collected by ML-based monitors over a 5-minute sliding window. "
        "Consider all possible causes including cascading failures:"
    ),
    "output_json": (
        "Return ONLY valid JSON with: root_cause, explanation, "
        "suggested_fixes (list), prevention_steps (list), confidence."
    ),
    "output_structured": (
        "Structure your response as JSON with these exact fields: "
        "root_cause (1-2 sentences), explanation (3-5 sentences), "
        "suggested_fixes (3 specific actionable items), "
        "prevention_steps (2 proactive measures), "
        "confidence (HIGH/MEDIUM/LOW)."
    ),
}

# Default prompt config
DEFAULT_CONFIG = {
    "tone": "tone_formal",
    "context": "context_standard",
    "output_format": "output_structured",
    "use_few_shot": False,
    "use_causal": True,
    "use_history": True,
}


# ── RLHF scorer ───────────────────────────────────────────────────────────────

@dataclass
class PromptScore:
    """Tracks performance of a specific prompt configuration."""
    config_hash: str
    config: dict
    total_uses: int = 0
    reward_sum: float = 0.0
    resolved: int = 0
    partial: int = 0
    unresolved: int = 0

    @property
    def avg_reward(self) -> float:
        return self.reward_sum / self.total_uses if self.total_uses > 0 else 0.5

    @property
    def win_rate(self) -> float:
        if self.total_uses == 0:
            return 0.0
        return (self.resolved + 0.5 * self.partial) / self.total_uses


class RLHFPromptTuner:
    """
    Tracks prompt performance and selects the best-performing configuration.

    Reward signal:
      RESOLVED          → +1.0
      PARTIALLY_RESOLVED → +0.5
      NOT_RESOLVED      → -0.5
      UNKNOWN           → +0.0 (neutral)
    """

    REWARD_MAP = {
        "RESOLVED": 1.0,
        "PARTIALLY_RESOLVED": 0.5,
        "NOT_RESOLVED": -0.5,
        "UNKNOWN": 0.0,
    }

    def __init__(self):
        RLHF_STORE.parent.mkdir(exist_ok=True)
        self._scores: dict[str, PromptScore] = {}
        self._current_config = self._load_best_config()
        self._load_scores()

    def _config_hash(self, config: dict) -> str:
        """Simple hash for a config dict."""
        key = json.dumps(config, sort_keys=True)
        import hashlib
        return hashlib.md5(key.encode()).hexdigest()[:8]

    def _load_scores(self):
        if RLHF_STORE.exists():
            try:
                data = json.loads(RLHF_STORE.read_text())
                for entry in data:
                    ps = PromptScore(**entry)
                    self._scores[ps.config_hash] = ps
            except Exception:
                pass

    def _save_scores(self):
        data = [vars(ps) for ps in self._scores.values()]
        RLHF_STORE.write_text(json.dumps(data, indent=2))

    def _load_best_config(self) -> dict:
        if BEST_PROMPT_FILE.exists():
            try:
                return json.loads(BEST_PROMPT_FILE.read_text())
            except Exception:
                pass
        return DEFAULT_CONFIG.copy()

    def get_current_prompt_parts(self) -> dict[str, str]:
        """
        Return the current best-performing prompt components.
        Called by llm_reasoning.py to build the system prompt.
        """
        cfg = self._current_config
        return {
            "system_role": PROMPT_VARIANTS.get(cfg.get("tone", "tone_formal"), ""),
            "context_intro": PROMPT_VARIANTS.get(cfg.get("context", "context_standard"), ""),
            "output_instruction": PROMPT_VARIANTS.get(cfg.get("output_format", "output_structured"), ""),
            "use_few_shot": cfg.get("use_few_shot", False),
            "use_causal": cfg.get("use_causal", True),
            "use_history": cfg.get("use_history", True),
            "config_hash": self._config_hash(cfg),
        }

    def record_outcome(self, config_hash: str, outcome: str):
        """
        Record the outcome for a specific prompt configuration.
        Updates the running reward score.
        """
        reward = self.REWARD_MAP.get(outcome, 0.0)

        if config_hash not in self._scores:
            self._scores[config_hash] = PromptScore(
                config_hash=config_hash,
                config=self._current_config.copy(),
            )

        ps = self._scores[config_hash]
        ps.total_uses += 1
        ps.reward_sum += reward
        if outcome == "RESOLVED":
            ps.resolved += 1
        elif outcome == "PARTIALLY_RESOLVED":
            ps.partial += 1
        elif outcome == "NOT_RESOLVED":
            ps.unresolved += 1

        self._save_scores()
        print(f"[RLHF] Recorded outcome={outcome} reward={reward:+.1f} "
              f"for config {config_hash} (avg_reward={ps.avg_reward:.2f})")

        # Try to improve prompt if win rate is low
        if ps.total_uses >= 3 and ps.win_rate < 0.4:
            self._explore_new_config(ps)

    def _explore_new_config(self, poor_config: PromptScore):
        """
        If a config is performing poorly, try a variant.
        Simple epsilon-greedy exploration: swap one component.
        """
        import random
        new_config = self._current_config.copy()

        # Pick a random component to change
        component = random.choice(["tone", "context", "output_format"])
        options = {
            "tone": ["tone_formal", "tone_concise", "tone_comprehensive"],
            "context": ["context_minimal", "context_standard", "context_comprehensive"],
            "output_format": ["output_json", "output_structured"],
        }
        current_val = new_config.get(component)
        alternatives = [o for o in options[component] if o != current_val]
        if alternatives:
            new_config[component] = random.choice(alternatives)
            self._current_config = new_config

            # Save best config
            BEST_PROMPT_FILE.write_text(json.dumps(new_config, indent=2))
            print(f"[RLHF] Exploring new config: changed '{component}' "
                  f"from '{current_val}' to '{new_config[component]}'")

    def _update_best_config(self):
        """Set current config to the highest-performing scored config."""
        if not self._scores:
            return
        best = max(self._scores.values(),
                   key=lambda ps: ps.avg_reward if ps.total_uses >= 2 else -999)
        if best.avg_reward > 0.3:
            self._current_config = best.config
            BEST_PROMPT_FILE.write_text(json.dumps(best.config, indent=2))
            print(f"[RLHF] Best config updated: {best.config_hash} "
                  f"(avg_reward={best.avg_reward:.2f}, win_rate={best.win_rate:.0%})")

    def get_performance_report(self) -> str:
        """Return a human-readable RLHF performance report."""
        if not self._scores:
            return "No RLHF data collected yet."
        lines = ["RLHF Prompt Performance Report", "=" * 40]
        for ps in sorted(self._scores.values(),
                          key=lambda x: x.avg_reward, reverse=True):
            lines.append(
                f"  Config {ps.config_hash}: avg_reward={ps.avg_reward:.2f} "
                f"win_rate={ps.win_rate:.0%} uses={ps.total_uses} "
                f"tone={ps.config.get('tone', 'default')}"
            )
        return "\n".join(lines)


# Singleton
prompt_tuner = RLHFPromptTuner()