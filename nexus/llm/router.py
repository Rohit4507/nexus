"""3-Tier LLM Router — adapted for RTX 3050 6GB (llama3.1:8b only).

Tier 1: llama3.1:8b — fast classification, slot filling, simple summarization
Tier 2: llama3.1:8b — complex reasoning via chain-of-thought prompting
Tier 3: MOCKED — no Anthropic key; logs warning and falls back to Tier 2

Tier selection is config-driven. Fallback chain: tier3→tier2→tier1.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger()


class LLMTier(Enum):
    LOCAL_FAST = "tier1"      # llama3.1:8b — simple prompts, fast
    LOCAL_REASON = "tier2"    # llama3.1:8b — chain-of-thought, detailed
    CLOUD_PREMIUM = "tier3"   # MOCKED — no API key


# ── Configurable tier routing ────────────────────────────────────────────────
DEFAULT_TASK_TIER_MAP: dict[str, str] = {
    # Tier 1 — fast, simple
    "intent_classification": "tier1",
    "request_routing": "tier1",
    "slot_filling": "tier1",
    "basic_summarization": "tier1",
    "status_check": "tier1",
    # Tier 2 — complex reasoning (same model, better prompts)
    "meeting_action_extraction": "tier2",
    "vendor_risk_scoring": "tier2",
    "policy_compliance_check": "tier2",
    "multi_step_reasoning": "tier2",
    "contract_clause_analysis": "tier2",
    # Tier 3 — mocked (would be cloud in production)
    "contract_clause_anomaly": "tier3",
    "legal_review_routing": "tier3",
    "high_stakes_approval": "tier3",
    "complex_risk_assessment": "tier3",
}

DEFAULT_TIER_CONFIG: dict[str, dict[str, Any]] = {
    "tier1": {
        "base_url": "http://localhost:11434",
        "model": "llama3.1:8b",
        "timeout": 30,
        "cost_per_1k_tokens": 0.0,
        "system_prefix": "",  # no chain-of-thought
    },
    "tier2": {
        "base_url": "http://localhost:11434",
        "model": "llama3.1:8b",
        "timeout": 120,
        "cost_per_1k_tokens": 0.0,
        "system_prefix": "Think step-by-step. ",  # chain-of-thought
        "confidence_threshold": 0.7,
        "latency_threshold_s": 15.0,
    },
    "tier3": {
        "model": "mocked",
        "timeout": 5,
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
    },
}

FALLBACK_CHAIN: dict[str, Optional[str]] = {
    "tier3": "tier2",
    "tier2": "tier1",
    "tier1": None,
}


@dataclass
class UsageRecord:
    """Single LLM call record — persisted to audit_logs via DB."""
    tier: str
    task_type: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float
    confidence: float | None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class UsageTracker:
    """Accumulates usage in-memory; flushes to PostgreSQL audit_logs."""

    def __init__(self, db_pool=None):
        self.records: list[UsageRecord] = []
        self.db = db_pool
        self.total_cost_usd: float = 0.0

    async def log(self, record: UsageRecord) -> None:
        self.records.append(record)
        self.total_cost_usd += record.cost_usd
        logger.info(
            "llm_usage_logged",
            tier=record.tier,
            task=record.task_type,
            latency_ms=record.latency_ms,
            tokens_in=record.input_tokens,
            tokens_out=record.output_tokens,
        )
        if self.db:
            await self.db.execute(
                "INSERT INTO audit_logs (agent_name, action, llm_tier, "
                "duration_ms, input_data, output_data, status, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                "llm_router", record.task_type, record.tier,
                record.latency_ms,
                json.dumps({"input_tokens": record.input_tokens}),
                json.dumps({"output_tokens": record.output_tokens,
                            "cost_usd": record.cost_usd}),
                "success", record.timestamp,
            )


class LLMRouter:
    """Routes tasks to the appropriate LLM tier.

    RTX 3050 6GB config:
      - Tier 1 & 2: Both use llama3.1:8b via Ollama
      - Tier 2 differentiated by chain-of-thought system prompt
      - Tier 3: MOCKED — returns placeholder, falls back to Tier 2

    Tier selection:
      1. Look up task_type in config map → initial tier
      2. Call that tier
      3. On failure → walk fallback chain (tier3→tier2→tier1)
    """

    def __init__(
        self,
        task_tier_map: dict[str, str] | None = None,
        tier_config: dict[str, dict] | None = None,
        db_pool=None,
    ):
        self.task_map = task_tier_map or DEFAULT_TASK_TIER_MAP
        self.tier_cfg = tier_config or DEFAULT_TIER_CONFIG
        self.http = httpx.AsyncClient(timeout=120)
        self.usage = UsageTracker(db_pool=db_pool)

    def route(self, task_type: str, complexity: float = 0.5) -> str:
        """Resolve initial tier. Complexity is advisory (0.0–1.0)."""
        tier = self.task_map.get(task_type, "tier1")
        if complexity > 0.9 and tier == "tier1":
            tier = "tier2"
        return tier

    async def generate(
        self,
        task_type: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        complexity: float = 0.5,
    ) -> dict:
        """Generate LLM response, with automatic fallback on failure."""
        tier = self.route(task_type, complexity)
        result = await self._try_with_fallback(
            tier, task_type, prompt, system, temperature
        )
        return result

    async def _try_with_fallback(
        self,
        tier: str,
        task_type: str,
        prompt: str,
        system: str,
        temperature: float,
    ) -> dict:
        current_tier = tier
        while current_tier is not None:
            try:
                start = time.monotonic()
                result = await self._call_tier(
                    current_tier, prompt, system, temperature
                )
                latency_ms = int((time.monotonic() - start) * 1000)

                # ── Track usage ──────────────────────────────────────
                cost = self._calc_cost(current_tier, result["tokens"])
                await self.usage.log(UsageRecord(
                    tier=current_tier,
                    task_type=task_type,
                    input_tokens=result["tokens"]["input"],
                    output_tokens=result["tokens"]["output"],
                    latency_ms=latency_ms,
                    cost_usd=cost,
                    confidence=result.get("confidence"),
                ))
                return {
                    "tier": current_tier,
                    "content": result["content"],
                    "tokens": result["tokens"],
                    "latency_ms": latency_ms,
                    "confidence": result.get("confidence"),
                }

            except Exception as e:
                logger.warning(
                    "llm_tier_failed",
                    tier=current_tier,
                    error=str(e),
                )
                current_tier = FALLBACK_CHAIN.get(current_tier)

        raise RuntimeError(f"All LLM tiers failed for task: {task_type}")

    async def _call_tier(
        self,
        tier: str,
        prompt: str,
        system: str,
        temperature: float,
    ) -> dict:
        cfg = self.tier_cfg[tier]

        if tier == "tier3":
            # ── MOCKED — no Anthropic key ────────────────────────
            logger.warning(
                "tier3_mocked",
                msg="No Anthropic API key. Falling back to tier2.",
            )
            raise RuntimeError("Tier 3 not available (no API key)")

        # ── Tier 1 & 2: Ollama ───────────────────────────────────
        sys_prefix = cfg.get("system_prefix", "")
        full_system = f"{sys_prefix}{system}" if system else sys_prefix

        resp = await self.http.post(
            f"{cfg['base_url']}/api/generate",
            json={
                "model": cfg["model"],
                "prompt": prompt,
                "system": full_system or "You are a precise enterprise AI assistant.",
                "options": {"temperature": temperature},
                "stream": False,
            },
            timeout=cfg["timeout"],
        )
        resp.raise_for_status()
        data = resp.json()

        return {
            "content": data["response"],
            "tokens": {
                "input": data.get("prompt_eval_count", 0),
                "output": data.get("eval_count", 0),
            },
            "confidence": None,
        }

    def _calc_cost(self, tier: str, tokens: dict) -> float:
        """All tiers are local/free on this setup."""
        return 0.0

    async def close(self) -> None:
        await self.http.aclose()
