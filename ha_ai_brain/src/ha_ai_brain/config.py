"""Configuration management for HA AI Brain (Add-on, Docker, or Local Dev)."""

from __future__ import annotations

import os
from enum import Enum
from pydantic import BaseModel, Field


class OperatingMode(str, Enum):
    """Execution mode for the AI Brain."""

    REALTIME_STREAM = "realtime_stream"  # 24/7 WebSocket event watcher
    PERIODIC_BATCH = "periodic_batch"    # Low-token scheduled / manual analysis & automation synthesizer
    HYBRID = "hybrid"                    # Both live stream reactive + periodic deep pattern analysis


class AutonomyLevel(str, Enum):
    """Graduated autonomy level per agent or system-wide."""

    SHADOW = "shadow"          # Observe, compute derived signals, and log what it would do without acting
    COPILOT = "copilot"        # Propose actions via notifications; auto-execute only user-endorsed repeatable rules
    AUTONOMOUS = "autonomous"  # Execute safe actions automatically; require confirmation only for high-risk actions


class FallbackPolicy(str, Enum):
    """Policy when the primary chosen LLM model reaches its quota/rate limit."""

    AUTO_SWITCH_AND_RECOVER = "auto"      # Automatically switch to next available fallback model and auto-return when primary cooldown ends
    ASK_CONFIRMATION = "confirm"          # Pause & prompt user (UI + HA notification) to approve switching to an available fallback model
    DISABLED = "disabled"                 # Never use fallback models; wait strictly for primary model cooldown to expire



class BrainSettings(BaseModel):
    """Runtime settings loaded from HA Add-on options or environment variables."""

    ha_url: str = Field(default="http://localhost:8123", description="Home Assistant base REST URL")
    ha_ws_url: str = Field(default="ws://localhost:8123/api/websocket", description="Home Assistant WebSocket URL")
    ha_token: str = Field(default="", description="Home Assistant Long-Lived Access Token or SUPERVISOR_TOKEN")
    use_simulator: bool = Field(
        default=True,
        description="Use built-in Digital Twin Smart Home Simulator when no live HA token is provided",
    )

    operating_mode: OperatingMode = Field(default=OperatingMode.HYBRID)
    default_autonomy: AutonomyLevel = Field(default=AutonomyLevel.COPILOT)

    llm_model: str = Field(default="openai/gpt-4o", description="Primary reasoning model (LiteLLM format)")
    llm_fast_model: str = Field(default="openai/gpt-4o-mini", description="Fast/cheap model for triage & sub-tasks")
    llm_fallback_models: list[str] = Field(
        default_factory=lambda: [
            "gemini/gemini-3.8-flash",
            "gemini/gemini-3.6-flash",
            "gemini/gemini-3.5-flash",
            "gemini/gemini-3.1-flash-lite",
        ],
        description="Ordered fallback models used when primary model is in quota cooldown",
    )
    llm_fallback_policy: FallbackPolicy = Field(
        default=FallbackPolicy.AUTO_SWITCH_AND_RECOVER,
        description="Whether to auto-switch to fallback & auto-return to primary ('auto'), ask user confirmation ('confirm'), or disable fallback ('disabled')",
    )
    llm_api_key: str = Field(default="", description="API Key for BYOK mode")
    managed_proxy_url: str = Field(default="", description="Optional commercial SaaS Managed AI Proxy endpoint")
    license_key: str = Field(default="DEV-TRIAL-KEY", description="Commercial license or subscription key")

    site_context: str = Field(
        default=(
            "Smart property managed by Home Assistant. Discover the building layout, areas, "
            "sensor modalities, and controllable actuators directly from the entity states."
        ),
        description="Global World Context describing the physical premise (e.g. residential home, beer brewery, solar microgrid)",
    )

    notifications_enabled: bool = Field(default=True)
    notification_service: str = Field(default="notify.notify")
    batch_interval_minutes: int = Field(default=360)
    manual_override_cooldown_seconds: int = Field(default=900, description="15 min backoff when human overrides an agent")
    db_path: str = Field(default="ha_ai_brain.db")
    custom_agents_dir: str = Field(default="agents")

    @classmethod
    def from_env(cls) -> "BrainSettings":
        """Load settings from `.env` file and environment variables (supporting HA Supervisor auto-discovery)."""
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        supervisor_token = os.getenv("SUPERVISOR_TOKEN", "")
        ha_token = os.getenv("BRAIN_HA_TOKEN", supervisor_token)
        ha_url = os.getenv("BRAIN_HA_URL", "http://supervisor/core" if supervisor_token else "http://localhost:8123").rstrip("/")

        default_ws = (
            "ws://supervisor/core/websocket"
            if supervisor_token
            else ("wss://" if ha_url.startswith("https://") else "ws://") + ha_url.split("://", 1)[-1] + "/api/websocket"
        )
        ha_ws_url = os.getenv("BRAIN_HA_WS_URL", default_ws)
        use_sim_env = os.getenv("BRAIN_USE_SIMULATOR")
        use_simulator = (use_sim_env.lower() == "true") if use_sim_env is not None else (not bool(ha_token))

        fallback_env = os.getenv(
            "BRAIN_LLM_FALLBACK_MODELS",
            "gemini/gemini-3.8-flash,gemini/gemini-3.6-flash,gemini/gemini-3.5-flash,gemini/gemini-3.1-flash-lite",
        )
        fallback_models = [m.strip() for m in fallback_env.split(",") if m.strip()]

        return cls(
            ha_url=ha_url,
            ha_ws_url=ha_ws_url,
            ha_token=ha_token,
            use_simulator=use_simulator,
            operating_mode=OperatingMode(os.getenv("BRAIN_OPERATING_MODE", "hybrid")),
            default_autonomy=AutonomyLevel(os.getenv("BRAIN_DEFAULT_AUTONOMY", "copilot")),
            llm_model=os.getenv("BRAIN_LLM_MODEL", "openai/gpt-4o"),
            llm_fast_model=os.getenv("BRAIN_LLM_FAST_MODEL", "openai/gpt-4o-mini"),
            llm_fallback_models=fallback_models,
            llm_fallback_policy=FallbackPolicy(os.getenv("BRAIN_LLM_FALLBACK_POLICY", "auto")),
            llm_api_key=os.getenv("BRAIN_LLM_API_KEY", os.getenv("OPENAI_API_KEY", "")),
            managed_proxy_url=os.getenv("BRAIN_MANAGED_PROXY_URL", ""),
            license_key=os.getenv("BRAIN_LICENSE_KEY", "DEV-TRIAL-KEY"),
            site_context=os.getenv(
                "BRAIN_SITE_CONTEXT",
                "Smart property managed by Home Assistant. Discover the building layout, areas, "
                "sensor modalities, and controllable actuators directly from the entity states.",
            ),
            notifications_enabled=os.getenv("BRAIN_NOTIFICATIONS_ENABLED", "true").lower() == "true",
            notification_service=os.getenv("BRAIN_NOTIFICATION_SERVICE", "notify.notify"),
            batch_interval_minutes=int(os.getenv("BRAIN_BATCH_INTERVAL_MINUTES", "360")),
            db_path=os.getenv("BRAIN_DB_PATH", "ha_ai_brain.db"),
            custom_agents_dir=os.getenv(
                "BRAIN_CUSTOM_AGENTS_DIR",
                "agents" if os.path.isdir("agents") else ("ha_ai_brain/agents" if os.path.isdir("ha_ai_brain/agents") else "agents"),
            ),
        )
