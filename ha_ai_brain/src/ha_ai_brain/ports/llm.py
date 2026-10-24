"""Port Interface for LLM Reasoning, Structured Output Generation & Provider Quota/Usage Telemetry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field


class LLMQuotaAndUsageSnapshot(BaseModel):
    """Normalized provider-agnostic quota, rate-limit cooldown, fallback routing, and token/cost telemetry."""

    provider: str = "unknown"  # e.g., "google_gemini", "openai", "anthropic", "openrouter", "ollama", "simulator"
    model: str = ""
    primary_model: str = ""
    active_model: str = ""
    using_fallback_model: bool = False
    fallback_policy: str = "auto"  # "auto" | "confirm" | "disabled"
    fallback_models: list[str] = Field(default_factory=list)
    available_fallback_models: list[str] = Field(default_factory=list)
    awaiting_fallback_confirmation: bool = False
    user_confirmed_fallback_model: str | None = None
    primary_cooldown_until: datetime | None = None
    model_cooldowns: dict[str, str] = Field(default_factory=dict)  # short_model -> ISO cooldown_until
    quota_exhausted: bool = False
    quota_metric: str = ""  # e.g., "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "requests_per_minute"
    quota_limit: int | str | None = None
    quota_remaining: int | str | None = None
    cooldown_until: datetime | None = None
    last_error_message: str = ""
    requests_succeeded_session: int = 0
    requests_rate_limited_session: int = 0
    prompt_tokens_session: int = 0
    completion_tokens_session: int = 0
    estimated_spend_usd_session: float = 0.0
    billing_limit_usd: float | None = None
    external_usage_url: str = ""
    raw_provider_headers: dict[str, str] = Field(default_factory=dict)

    @property
    def cooldown_seconds_remaining(self) -> int:
        if not self.cooldown_until:
            return 0
        rem = int((self.cooldown_until - datetime.now(timezone.utc)).total_seconds())
        return max(0, rem)

    @property
    def primary_cooldown_seconds_remaining(self) -> int:
        if not self.primary_cooldown_until:
            return 0
        rem = int((self.primary_cooldown_until - datetime.now(timezone.utc)).total_seconds())
        return max(0, rem)

    def to_status_dict(self) -> dict[str, Any]:
        rem = self.cooldown_seconds_remaining
        prim_rem = self.primary_cooldown_seconds_remaining
        is_cooling_down = self.quota_exhausted and rem > 0
        data = self.model_dump(mode="json")
        data["quota_exhausted"] = is_cooling_down
        data["cooldown_seconds_remaining"] = rem
        data["primary_cooldown_seconds_remaining"] = prim_rem
        return data


class LLMQuotaMonitorPort(ABC):
    """
    Hexagonal Port Interface for inspecting and parsing LLM provider quota limits,
    rate-limit cooldown windows, and actual/estimated spend across providers
    (Gemini, OpenAI, Anthropic, OpenRouter, Ollama).
    """

    @abstractmethod
    def record_success(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Record a successful LLM response, updating token spend and rate-limit headers."""

    @abstractmethod
    def record_quota_or_rate_limit_error(
        self,
        model: str,
        status_code: int,
        error_body: str,
        headers: dict[str, str] | None = None,
    ) -> LLMQuotaAndUsageSnapshot:
        """Parse a provider 429/quota error payload and headers to compute the exact cooldown window and quota limit."""

    @abstractmethod
    async def get_quota_and_usage_snapshot(self) -> LLMQuotaAndUsageSnapshot:
        """Return the current quota/cooldown state and session/remote spend."""


class LLMProviderPort(ABC):
    """Abstracts multi-provider LLM reasoning calls (OpenAI, Anthropic, Gemini, Ollama, Managed Proxy)."""

    @abstractmethod
    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        use_fast_tier: bool = False,
        context_hint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a structured JSON response from the LLM (with token accounting)."""

    async def get_quota_status(self) -> LLMQuotaAndUsageSnapshot:
        """Return current provider quota, cooldown, and spend telemetry."""
        return LLMQuotaAndUsageSnapshot()

    def reconfigure(
        self,
        model: str | None = None,
        fast_model: str | None = None,
        api_key: str | None = None,
        fallback_policy: str | None = None,
    ) -> None:
        """Dynamically reconfigure provider model settings at runtime."""
        pass
