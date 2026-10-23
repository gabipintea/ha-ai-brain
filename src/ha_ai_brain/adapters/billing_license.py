"""Commercial License & SaaS Subscription Metering Adapter."""

from __future__ import annotations

from ha_ai_brain.ports.billing import LicensePort, LicenseStatus


class CommercialLicenseAdapter(LicensePort):
    """
    Validates BYOK One-Time Licenses or Monthly Managed AI Subscriptions and tracks
    per-agent token consumption so users can monitor cost savings from Mode B / Automation Crystallization.
    """

    def __init__(self, initial_license_key: str = "DEV-TRIAL-KEY") -> None:
        self.license_key = initial_license_key
        self._agent_token_usage: dict[str, dict[str, int]] = {}
        self._total_tokens_used = 0

    async def verify_license(self, license_key: str) -> LicenseStatus:
        key = (license_key or self.license_key or "").strip()
        if key.startswith("PRO-MONTHLY-"):
            return LicenseStatus(
                valid=True,
                plan_tier="pro_managed_monthly",
                max_custom_agents=50,
                managed_tokens_remaining=max(0, 2_000_000 - self._total_tokens_used),
                tokens_used_this_period=self._total_tokens_used,
                message="Active Pro Managed AI Monthly Subscription (All-Inclusive LLM Proxy).",
            )
        if key.startswith("BYOK-LIFETIME-"):
            return LicenseStatus(
                valid=True,
                plan_tier="byok_lifetime",
                max_custom_agents=25,
                managed_tokens_remaining=None,
                tokens_used_this_period=self._total_tokens_used,
                message="Active Lifetime BYOK License (Unlimited Local & Bring-Your-Own-Key Usage).",
            )
        return LicenseStatus(
            valid=True,
            plan_tier="trial",
            max_custom_agents=5,
            managed_tokens_remaining=max(0, 100_000 - self._total_tokens_used),
            tokens_used_this_period=self._total_tokens_used,
            message="Evaluation / Trial Mode Active.",
        )

    async def record_token_usage(self, agent_id: str, prompt_tokens: int, completion_tokens: int) -> None:
        bucket = self._agent_token_usage.setdefault(
            agent_id,
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "invocations": 0},
        )
        total = prompt_tokens + completion_tokens
        bucket["prompt_tokens"] += prompt_tokens
        bucket["completion_tokens"] += completion_tokens
        bucket["total_tokens"] += total
        bucket["invocations"] += 1
        self._total_tokens_used += total

    def get_usage_breakdown(self) -> dict[str, dict[str, int]]:
        return dict(self._agent_token_usage)
