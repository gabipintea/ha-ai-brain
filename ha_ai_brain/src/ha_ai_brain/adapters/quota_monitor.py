"""Provider-Specific LLM Quota, Rate-Limit Cooldown & Spend Monitor Adapters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any

from ha_ai_brain.ports.llm import LLMQuotaAndUsageSnapshot, LLMQuotaMonitorPort


# Approximate USD per 1M tokens for session spend calculation
MODEL_PRICING_PER_1M: dict[str, tuple[float, float]] = {
    # (input_usd_per_1m, output_usd_per_1m)
    "gemini-3-flash-preview": (0.15, 0.60),
    "gemini-3.8-flash": (0.15, 0.60),
    "gemini-3.6-flash": (0.15, 0.60),
    "gemini-3.5-flash": (0.15, 0.60),
    "gemini-3.1-flash-lite": (0.075, 0.30),
    "gemini-3.1-pro-preview": (1.25, 5.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
}


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    short_m = model.split("/", 1)[-1]
    in_rate, out_rate = MODEL_PRICING_PER_1M.get(short_m, (0.15, 0.60))
    return round((prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000.0, 6)


class BaseQuotaMonitorAdapter(LLMQuotaMonitorPort):
    """Base tracker maintaining cumulative token usage, estimated spend, active cooldown state, and fallback routing."""

    def __init__(
        self,
        provider: str,
        default_model: str,
        external_usage_url: str = "",
        fallback_models: list[str] | None = None,
        fallback_policy: str = "auto",
    ) -> None:
        short_primary = default_model.split("/", 1)[-1]
        short_fallbacks = [
            m.split("/", 1)[-1]
            for m in (fallback_models or [])
            if m.split("/", 1)[-1] != short_primary
        ]
        self._snapshot = LLMQuotaAndUsageSnapshot(
            provider=provider,
            model=short_primary,
            primary_model=short_primary,
            active_model=short_primary,
            fallback_policy=fallback_policy,
            fallback_models=short_fallbacks,
            available_fallback_models=list(short_fallbacks),
            external_usage_url=external_usage_url,
        )
        self._model_cooldowns: dict[str, datetime] = {}

    def set_primary_model(self, model: str) -> None:
        short_m = model.split("/", 1)[-1]
        self._snapshot.primary_model = short_m
        self._snapshot.model = short_m
        self._refresh_routing_state()

    def set_fallback_policy(self, policy: str) -> None:
        self._snapshot.fallback_policy = policy
        if policy == "auto":
            self._snapshot.awaiting_fallback_confirmation = False
        self._refresh_routing_state()

    def approve_fallback_model(self, model: str | None = None) -> str | None:
        """Record user confirmation to use an available fallback model while the primary model cools down."""
        self._refresh_routing_state()
        available = self._snapshot.available_fallback_models
        if model:
            short_m = model.split("/", 1)[-1]
            chosen = short_m
        else:
            chosen = available[0] if available else None
        self._snapshot.user_confirmed_fallback_model = chosen
        self._snapshot.awaiting_fallback_confirmation = False
        if chosen:
            self._snapshot.active_model = chosen
            self._snapshot.using_fallback_model = (chosen != self._snapshot.primary_model)
            self._snapshot.quota_exhausted = False
        return chosen

    def reject_fallback_and_wait_for_primary(self) -> None:
        """User chose not to switch to fallback; stay paused until primary model cooldown expires."""
        self._snapshot.user_confirmed_fallback_model = "__WAIT_PRIMARY__"
        self._snapshot.awaiting_fallback_confirmation = False
        self._refresh_routing_state()

    def _refresh_routing_state(self) -> None:
        """
        Recompute per-model cooldowns, automatic primary recovery, and whether user confirmation
        is required before switching to a fallback model.
        """
        now = datetime.now(timezone.utc)
        expired = [m for m, until in self._model_cooldowns.items() if (until - now).total_seconds() <= 0]
        for m in expired:
            del self._model_cooldowns[m]

        self._snapshot.model_cooldowns = {
            m: until.isoformat() for m, until in self._model_cooldowns.items()
        }
        primary = self._snapshot.primary_model
        primary_until = self._model_cooldowns.get(primary)
        self._snapshot.primary_cooldown_until = primary_until

        available_fallbacks = [
            m for m in self._snapshot.fallback_models if m not in self._model_cooldowns
        ]
        self._snapshot.available_fallback_models = available_fallbacks

        if primary_until is None:
            # Primary model is healthy / cooldown expired -> AUTOMATICALLY SWITCH BACK TO PRIMARY!
            self._snapshot.active_model = primary
            self._snapshot.model = primary
            self._snapshot.using_fallback_model = False
            self._snapshot.awaiting_fallback_confirmation = False
            self._snapshot.user_confirmed_fallback_model = None
            self._snapshot.quota_exhausted = False
            self._snapshot.cooldown_until = None
            return

        # Primary model is currently in cooldown!
        policy = self._snapshot.fallback_policy
        if policy == "disabled" or not available_fallbacks:
            self._snapshot.active_model = primary
            self._snapshot.model = primary
            self._snapshot.using_fallback_model = False
            self._snapshot.awaiting_fallback_confirmation = False
            self._snapshot.quota_exhausted = True
            self._snapshot.cooldown_until = primary_until
            return

        if policy == "auto":
            chosen = available_fallbacks[0]
            self._snapshot.active_model = chosen
            self._snapshot.model = chosen
            self._snapshot.using_fallback_model = True
            self._snapshot.awaiting_fallback_confirmation = False
            self._snapshot.quota_exhausted = False
            self._snapshot.cooldown_until = primary_until
            return

        # policy == "confirm"
        confirmed = self._snapshot.user_confirmed_fallback_model
        if confirmed == "__WAIT_PRIMARY__":
            self._snapshot.active_model = primary
            self._snapshot.model = primary
            self._snapshot.using_fallback_model = False
            self._snapshot.awaiting_fallback_confirmation = False
            self._snapshot.quota_exhausted = True
            self._snapshot.cooldown_until = primary_until
        elif confirmed and confirmed in available_fallbacks:
            self._snapshot.active_model = confirmed
            self._snapshot.model = confirmed
            self._snapshot.using_fallback_model = True
            self._snapshot.awaiting_fallback_confirmation = False
            self._snapshot.quota_exhausted = False
            self._snapshot.cooldown_until = primary_until
        else:
            # Waiting for user confirmation before switching to fallback
            self._snapshot.active_model = primary
            self._snapshot.model = primary
            self._snapshot.using_fallback_model = False
            self._snapshot.awaiting_fallback_confirmation = True
            self._snapshot.quota_exhausted = True
            self._snapshot.cooldown_until = primary_until

    def select_execution_candidates(self, requested_model: str) -> list[str]:
        """
        Return the ordered list of models allowed to execute right now according to:
        1) Whether the primary model's cooldown has ended (always prefers primary first when healthy)
        2) The configured fallback policy ('auto' vs 'confirm' vs 'disabled')
        """
        self._refresh_routing_state()
        req_short = requested_model.split("/", 1)[-1]
        primary = self._snapshot.primary_model or req_short

        # If primary is healthy, try primary first; if policy == 'auto', also allow fallbacks on mid-call 429
        if not self.is_model_in_cooldown(primary)[0]:
            if self._snapshot.fallback_policy == "auto":
                return [primary] + [m for m in self._snapshot.available_fallback_models if m != primary]
            return [primary]

        # Primary is in cooldown
        if self._snapshot.fallback_policy == "auto":
            return list(self._snapshot.available_fallback_models)
        if self._snapshot.fallback_policy == "confirm":
            confirmed = self._snapshot.user_confirmed_fallback_model
            if confirmed and confirmed != "__WAIT_PRIMARY__" and not self.is_model_in_cooldown(confirmed)[0]:
                return [confirmed] + [m for m in self._snapshot.available_fallback_models if m != confirmed]
            return []
        return []

    def is_model_in_cooldown(self, model: str) -> tuple[bool, int]:
        short_m = model.split("/", 1)[-1]
        until = self._model_cooldowns.get(short_m)
        if not until:
            return False, 0
        rem = int((until - datetime.now(timezone.utc)).total_seconds())
        if rem <= 0:
            del self._model_cooldowns[short_m]
            self._refresh_routing_state()
            return False, 0
        return True, rem

    def is_in_cooldown(self) -> tuple[bool, int]:
        self._refresh_routing_state()
        rem = self._snapshot.cooldown_seconds_remaining
        if self._snapshot.quota_exhausted and rem > 0:
            return True, rem
        return False, 0

    def record_success(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        headers: dict[str, str] | None = None,
    ) -> None:
        short_m = model.split("/", 1)[-1]
        self._snapshot.model = short_m
        self._snapshot.active_model = short_m
        self._snapshot.using_fallback_model = (short_m != self._snapshot.primary_model)
        self._snapshot.last_error_message = ""
        self._snapshot.requests_succeeded_session += 1
        self._snapshot.prompt_tokens_session += prompt_tokens
        self._snapshot.completion_tokens_session += completion_tokens
        self._snapshot.estimated_spend_usd_session = round(
            self._snapshot.estimated_spend_usd_session + _estimate_cost(model, prompt_tokens, completion_tokens),
            6,
        )
        if headers:
            self._parse_headers(headers)
        self._refresh_routing_state()

    def _parse_headers(self, headers: dict[str, str]) -> None:
        """Hook for subclasses to extract rate-limit headers from normal 200 responses."""

    def record_quota_or_rate_limit_error(
        self,
        model: str,
        status_code: int,
        error_body: str,
        headers: dict[str, str] | None = None,
    ) -> LLMQuotaAndUsageSnapshot:
        short_m = model.split("/", 1)[-1]
        self._snapshot.model = short_m
        self._snapshot.requests_rate_limited_session += 1
        if status_code == 429:
            self._snapshot.quota_exhausted = True
        if headers:
            self._parse_headers(headers)
        self._parse_error_payload(status_code, error_body, headers or {})
        self._refresh_routing_state()
        return self._snapshot

    def _parse_error_payload(
        self,
        status_code: int,
        error_body: str,
        headers: dict[str, str],
    ) -> None:
        """Hook for provider-specific error body & Retry-After parsing."""

    async def get_quota_and_usage_snapshot(self) -> LLMQuotaAndUsageSnapshot:
        self._refresh_routing_state()
        return self._snapshot


class GeminiQuotaMonitorAdapter(BaseQuotaMonitorAdapter):
    """
    Google Gemini (`generativelanguage.googleapis.com` / Vertex Express) implementation of `LLMQuotaMonitorPort`.

    What Gemini API exposes directly in HTTP 429 responses:
    - `error.details[]` -> `google.rpc.RetryInfo.retryDelay` (e.g., `"42s"`, `"58.421s"`) or prose `"Please retry in Xs."`
    - `error.details[]` -> `google.rpc.QuotaFailure.violations[]`:
        - `quotaMetric` (e.g., `generativelanguage.googleapis.com/generate_content_free_tier_requests`)
        - `quotaId` (e.g., `GenerateRequestsPerDayPerProjectPerModel-FreeTier` or `GenerateRequestsPerMinutePerProjectPerModel-FreeTier`)
        - `quotaValue` (the exact numerical limit enforced by Google, e.g., `"20"` or `"15"`)

    Note: Google AI Studio API keys do not expose an unauthenticated REST endpoint to query
    historical monthly dollar invoice totals, so live usage is tracked locally from `usageMetadata`
    and paired with the direct link to `https://ai.dev/rate-limit`.
    """

    def __init__(
        self,
        default_model: str = "gemini-3-flash-preview",
        fallback_models: list[str] | None = None,
        fallback_policy: str = "auto",
    ) -> None:
        default_fallbacks = fallback_models or [
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.8-flash",
            "gemini-3-flash-preview",
        ]
        super().__init__(
            provider="google_gemini",
            default_model=default_model,
            external_usage_url="https://ai.dev/rate-limit",
            fallback_models=default_fallbacks,
            fallback_policy=fallback_policy,
        )

    def _parse_error_payload(
        self,
        status_code: int,
        error_body: str,
        headers: dict[str, str],
    ) -> None:
        now = datetime.now(timezone.utc)
        retry_seconds: float | None = None
        quota_metric = ""
        quota_limit: int | str | None = None
        short_msg = f"HTTP {status_code} Quota / Rate Limit Reached"

        # 1. Check standard HTTP Retry-After header if present
        retry_after_hdr = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after_hdr:
            try:
                retry_seconds = float(retry_after_hdr)
            except ValueError:
                pass

        # 2. Parse Google RPC JSON error payload (`RetryInfo` and `QuotaFailure`)
        try:
            data = json.loads(error_body)
            err_obj = data.get("error", {}) if isinstance(data, dict) else {}
            raw_msg = str(err_obj.get("message", ""))
            if raw_msg:
                short_msg = raw_msg.split("\n")[0].strip()

            for detail in err_obj.get("details", []) or []:
                if not isinstance(detail, dict):
                    continue
                dtype = str(detail.get("@type", ""))
                if "RetryInfo" in dtype and "retryDelay" in detail:
                    delay_str = str(detail["retryDelay"]).rstrip("s")
                    try:
                        retry_seconds = float(delay_str)
                    except ValueError:
                        pass
                elif "QuotaFailure" in dtype:
                    violations = detail.get("violations") or []
                    if violations and isinstance(violations[0], dict):
                        v = violations[0]
                        quota_metric = str(v.get("quotaId") or v.get("quotaMetric") or "")
                        if "quotaValue" in v:
                            quota_limit = v["quotaValue"]

            # 3. Also regex-match prose message fallback (e.g., "Please retry in 38.45s." or "limit: 20")
            if retry_seconds is None and raw_msg:
                m_retry = re.search(r"retry in\s+([0-9]+(?:\.[0-9]+)?)s", raw_msg, re.IGNORECASE)
                if m_retry:
                    retry_seconds = float(m_retry.group(1))
            if quota_limit is None and raw_msg:
                m_limit = re.search(r"limit:\s*([0-9]+)", raw_msg, re.IGNORECASE)
                if m_limit:
                    quota_limit = int(m_limit.group(1))
            if not quota_metric and raw_msg:
                m_metric = re.search(r"quota_metric:\s*\"([^\"]+)\"", raw_msg)
                if m_metric:
                    quota_metric = m_metric.group(1)
        except Exception:
            pass

        if retry_seconds is None:
            # Default cooldown if Google didn't include RetryInfo
            retry_seconds = 60.0 if "PerDay" in quota_metric else 30.0

        self._snapshot.quota_exhausted = True
        self._snapshot.cooldown_until = now + timedelta(seconds=max(5.0, retry_seconds))
        short_m = self._snapshot.model.split("/", 1)[-1]
        if short_m and self._snapshot.cooldown_until:
            self._model_cooldowns[short_m] = self._snapshot.cooldown_until
        if quota_metric:
            self._snapshot.quota_metric = quota_metric
        if quota_limit is not None:
            self._snapshot.quota_limit = quota_limit
        self._snapshot.quota_remaining = 0
        self._snapshot.last_error_message = short_msg


class OpenAIAnthropicHeadersQuotaMonitorAdapter(BaseQuotaMonitorAdapter):
    """
    OpenAI / Anthropic / OpenRouter implementation of `LLMQuotaMonitorPort`.
    Extracts live quota limits, remaining requests/tokens, and reset timers directly from:
    - OpenAI headers: `x-ratelimit-limit-requests`, `x-ratelimit-remaining-requests`, `x-ratelimit-reset-requests`
    - Anthropic headers: `anthropic-ratelimit-requests-limit`, `anthropic-ratelimit-requests-remaining`, `anthropic-ratelimit-requests-reset`
    - OpenRouter `GET https://openrouter.ai/api/v1/auth/key` credit balance endpoint (when applicable).
    """

    def __init__(
        self,
        provider: str,
        default_model: str,
        api_key: str = "",
        fallback_models: list[str] | None = None,
        fallback_policy: str = "auto",
    ) -> None:
        ext_url = {
            "openai": "https://platform.openai.com/settings/organization/usage",
            "anthropic": "https://console.anthropic.com/settings/plans",
            "openrouter": "https://openrouter.ai/activity",
        }.get(provider, "")
        super().__init__(
            provider=provider,
            default_model=default_model,
            external_usage_url=ext_url,
            fallback_models=fallback_models,
            fallback_policy=fallback_policy,
        )
        self.api_key = api_key

    def _parse_headers(self, headers: dict[str, str]) -> None:
        lower = {k.lower(): v for k, v in headers.items()}
        # OpenAI / OpenRouter headers
        if "x-ratelimit-limit-requests" in lower:
            self._snapshot.quota_limit = lower["x-ratelimit-limit-requests"]
            self._snapshot.quota_metric = "requests_per_window"
        if "x-ratelimit-remaining-requests" in lower:
            self._snapshot.quota_remaining = lower["x-ratelimit-remaining-requests"]
        # Anthropic headers
        if "anthropic-ratelimit-requests-limit" in lower:
            self._snapshot.quota_limit = lower["anthropic-ratelimit-requests-limit"]
            self._snapshot.quota_metric = "anthropic_requests_limit"
        if "anthropic-ratelimit-requests-remaining" in lower:
            self._snapshot.quota_remaining = lower["anthropic-ratelimit-requests-remaining"]

        self._snapshot.raw_provider_headers = {
            k: v for k, v in lower.items() if "ratelimit" in k or "retry-after" in k
        }

    def _parse_error_payload(
        self,
        status_code: int,
        error_body: str,
        headers: dict[str, str],
    ) -> None:
        now = datetime.now(timezone.utc)
        lower = {k.lower(): v for k, v in headers.items()}
        retry_seconds = 30.0
        if "retry-after" in lower:
            try:
                retry_seconds = float(lower["retry-after"])
            except ValueError:
                pass
        self._snapshot.quota_exhausted = True
        self._snapshot.cooldown_until = now + timedelta(seconds=max(5.0, retry_seconds))
        short_m = self._snapshot.model.split("/", 1)[-1]
        if short_m and self._snapshot.cooldown_until:
            self._model_cooldowns[short_m] = self._snapshot.cooldown_until
        self._snapshot.quota_remaining = 0
        self._snapshot.last_error_message = error_body[:240]


def create_quota_monitor_for_model(
    model: str,
    api_key: str = "",
    fallback_models: list[str] | None = None,
    fallback_policy: str = "auto",
) -> BaseQuotaMonitorAdapter:
    """Factory that returns the appropriate provider-specific `LLMQuotaMonitorPort` implementation."""
    if model.startswith(("gemini/", "vertex_ai/")) or api_key.startswith(("AQ.", "AIza")):
        return GeminiQuotaMonitorAdapter(
            default_model=model,
            fallback_models=fallback_models,
            fallback_policy=fallback_policy,
        )
    if model.startswith("anthropic/"):
        return OpenAIAnthropicHeadersQuotaMonitorAdapter(
            provider="anthropic",
            default_model=model,
            api_key=api_key,
            fallback_models=fallback_models,
            fallback_policy=fallback_policy,
        )
    if model.startswith("openrouter/"):
        return OpenAIAnthropicHeadersQuotaMonitorAdapter(
            provider="openrouter",
            default_model=model,
            api_key=api_key,
            fallback_models=fallback_models,
            fallback_policy=fallback_policy,
        )
    if model.startswith("ollama/"):
        return BaseQuotaMonitorAdapter(
            provider="ollama_local",
            default_model=model,
            fallback_models=fallback_models,
            fallback_policy=fallback_policy,
        )
    return OpenAIAnthropicHeadersQuotaMonitorAdapter(
        provider="openai",
        default_model=model,
        api_key=api_key,
        fallback_models=fallback_models,
        fallback_policy=fallback_policy,
    )
