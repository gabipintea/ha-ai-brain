"""Port Interface for Commercial License Validation & Token Subscription Metering."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pydantic import BaseModel


class LicenseStatus(BaseModel):
    """Commercial license state for the Home Assistant instance."""

    valid: bool
    plan_tier: str  # e.g., "byok_lifetime", "pro_managed_monthly", "trial"
    max_custom_agents: int = 10
    managed_tokens_remaining: int | None = None
    tokens_used_this_period: int = 0
    message: str = ""


class LicensePort(ABC):
    """Validates instance license keys and meters token usage for billing."""

    @abstractmethod
    async def verify_license(self, license_key: str) -> LicenseStatus:
        """Check whether the current HA instance has an active license or subscription."""

    @abstractmethod
    async def record_token_usage(self, agent_id: str, prompt_tokens: int, completion_tokens: int) -> None:
        """Record LLM token consumption for cost observability and SaaS billing."""
