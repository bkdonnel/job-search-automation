"""Tracks OpenAI token usage and estimated cost across a Lambda invocation."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

# Prices in USD per 1M tokens (as of May 2026)
_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.150, "output": 0.600},
    "text-embedding-3-small": {"input": 0.020, "output": 0.0},
}


@dataclass
class _ModelUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


_usage: dict[str, _ModelUsage] = {}


def reset() -> None:
    """Clear all counters. Call once at the start of each Lambda invocation."""
    _usage.clear()


def record(model: str, usage: object) -> None:
    """Record token usage from an OpenAI response usage object."""
    if model not in _usage:
        _usage[model] = _ModelUsage()

    entry = _usage[model]
    entry.calls += 1

    input_tokens = getattr(usage, "prompt_tokens", 0) or getattr(usage, "total_tokens", 0)
    output_tokens = getattr(usage, "completion_tokens", 0)

    entry.input_tokens += input_tokens
    entry.output_tokens += output_tokens

    pricing = _PRICING.get(model, {"input": 0.0, "output": 0.0})
    entry.cost_usd += (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated cost in USD for a single model call."""
    pricing = _PRICING.get(model, {"input": 0.0, "output": 0.0})
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


def log_summary(logger: logging.Logger) -> None:
    """Emit one structured cost summary line to CloudWatch."""
    if not _usage:
        return

    total_cost = sum(m.cost_usd for m in _usage.values())
    total_calls = sum(m.calls for m in _usage.values())

    breakdown = {
        model: {
            "calls": m.calls,
            "input_tokens": m.input_tokens,
            "output_tokens": m.output_tokens,
            "cost_usd": round(m.cost_usd, 6),
        }
        for model, m in _usage.items()
    }

    logger.info(
        "COST_SUMMARY total_calls=%d total_cost_usd=%.6f breakdown=%s",
        total_calls,
        total_cost,
        breakdown,
    )
