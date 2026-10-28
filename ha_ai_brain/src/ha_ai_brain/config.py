"""Configuration management for HA AI Brain (Add-on, Docker, or Local Dev)."""

from __future__ import annotations

import logging
import os
from enum import Enum
from typing import ClassVar, TypeVar

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_E = TypeVar("_E", bound=Enum)

DEFAULT_SITE_CONTEXT = (
    "Smart property managed by Home Assistant. Discover the building layout, areas, "
    "sensor modalities, and controllable actuators directly from the entity states."
)
DEFAULT_FALLBACK_MODELS: tuple[str, ...] = (
    "gemini/gemini-3.8-flash",
    "gemini/gemini-3.6-flash",
    "gemini/gemini-3.5-flash",
    "gemini/gemini-3.1-flash-lite",
)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using default %d", name, raw, default)
        return default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_enum(name: str, enum_cls: type[_E], default: _E) -> _E:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return enum_cls(raw.strip().lower())
    except ValueError:
        logger.warning("Invalid value for %s=%r; using default %r", name, raw, default.value)
        return default




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
        default_factory=lambda: list(DEFAULT_FALLBACK_MODELS),
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
        default=DEFAULT_SITE_CONTEXT,
        description="Global World Context describing the physical premise (e.g. residential home, beer brewery, solar microgrid)",
    )

    notifications_enabled: bool = Field(default=True)
    notification_service: str = Field(default="notify.notify")
    batch_interval_minutes: int = Field(default=360)
    batch_lookback_hours: int = Field(
        default=24,
        description="Number of past hours of historical telemetry analyzed by agents during batch audits (e.g. 24 for 1 day, 168 for 1 week)",
    )
    manual_override_cooldown_seconds: int = Field(default=900, description="15 min backoff when human overrides an agent")
    db_path: str = Field(default="ha_ai_brain.db")
    timezone: str = Field(default="", description="IANA timezone for time-of-day patterns (auto-discovered from Home Assistant when empty)")
    custom_agents_dir: str = Field(default="agents", description="Writable directory where user-defined agents are persisted")
    bundled_agents_dir: str = Field(default="", description="Optional read-only directory with agent definitions shipped with the add-on")

    # --- Learning, gating and safety -------------------------------------------------------------
    realtime_gating: bool = Field(
        default=True,
        description="Once enough history is learned, only wake LLM agents for genuinely unusual events (saves tokens)",
    )
    baseline_min_days: int = Field(default=3, description="Days of recorded history before gating / exception detection activates")
    store_retention_days: int = Field(default=90, description="Days of compact telemetry kept for pattern mining")
    store_backfill_hours: int = Field(default=240, description="Hours of Home Assistant recorder history imported at startup")
    history_max_entities: int = Field(default=300, description="Max entities whose history is imported / analysed per run")
    deterministic_automations: bool = Field(
        default=True,
        description="Propose automations for strong recurring habits straight from statistics, without any LLM call",
    )
    max_new_automations_per_cycle: int = Field(default=3)
    exception_detection: bool = Field(default=True, description="Detect deviations from learned routines / existing automations")
    research_enabled: bool = Field(default=True, description="Agents regularly research their field and propose knowledge for your approval (works with any AI provider)")
    research_web_search: bool = Field(
        default=False,
        description="Optional: use web search with cited sources for research (Gemini only, noticeably more tokens)",
    )
    research_interval_days: int = Field(default=7, description="Days between research runs")
    research_topics_per_agent: int = Field(default=1, description="Topics researched per agent per run")
    max_exceptions_per_cycle: int = Field(default=5, description="Max new unusual-situation alerts per 5-minute check")
    max_exceptions_per_day: int = Field(default=20, description="Non-critical unusual-situation alerts per day (critical ones are never capped)")
    daily_token_budget: int = Field(default=0, description="Max LLM tokens per UTC day (0 = unlimited)")
    realtime_coalesce_seconds: int = Field(
        default=90, description="Events in the same area wake an agent at most once per this many seconds (0 = off)"
    )
    max_agent_wakeups_per_hour: int = Field(default=6, description="Max real-time AI wake-ups per agent per hour (0 = unlimited)")
    max_actions_per_hour: int = Field(default=30)
    max_actions_per_entity_per_hour: int = Field(default=3)
    quiet_hours_start: str = Field(default="", description="HH:MM local time; low-severity pushes are held during quiet hours")
    quiet_hours_end: str = Field(default="")
    critical_openings: str = Field(
        default="",
        description="Comma-separated extra entities, wildcards or words (for example 'cover.driveway, *carport*, barn') that always need approval to open",
    )
    log_level: str = Field(default="INFO", description="DEBUG | INFO | WARNING - DEBUG logs every single state change")
    paused: bool = Field(default=False, description="Kill switch: observe and learn only, never act or call the LLM in real time")
    domain_autonomy: dict[str, AutonomyLevel] = Field(
        default_factory=dict,
        description="Per-domain autonomy overrides, e.g. {'light': 'autonomous', 'lock': 'copilot'}",
    )
    notify_autonomous_actions: bool = Field(default=True, description="Send a heads-up with an Undo button when the brain acts on its own")
    knowledge_dir: str = Field(default="", description="Optional directory with extra expert reference files (*.yaml)")
    privacy_scrub: bool = Field(default=True, description="Replace people / phones / network identifiers before data leaves for a cloud LLM")

    # Fields that must never be returned by the HTTP API.
    SECRET_FIELDS: ClassVar[tuple[str, ...]] = ("llm_api_key", "ha_token", "license_key")

    def public_dict(self) -> dict[str, object]:
        """Settings safe to expose over HTTP: secrets are removed and replaced with presence flags / a masked API key."""
        data = self.model_dump(mode="json")
        for name in self.SECRET_FIELDS:
            data.pop(name, None)
        raw_key = self.llm_api_key
        data["has_api_key"] = bool(raw_key)
        data["masked_api_key"] = mask_secret(raw_key)
        data["has_license_key"] = bool(self.license_key) and self.license_key != "DEV-TRIAL-KEY"
        return data

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
        use_simulator = _env_bool("BRAIN_USE_SIMULATOR", default=not bool(ha_token))

        fallback_env = os.getenv("BRAIN_LLM_FALLBACK_MODELS", ",".join(DEFAULT_FALLBACK_MODELS))
        fallback_models = [m.strip() for m in fallback_env.split(",") if m.strip()]

        custom_agents_dir = os.getenv("BRAIN_CUSTOM_AGENTS_DIR", "")
        bundled_agents_dir = os.getenv("BRAIN_BUNDLED_AGENTS_DIR", "")
        if not custom_agents_dir:
            custom_agents_dir = "agents" if os.path.isdir("agents") else (
                "ha_ai_brain/agents" if os.path.isdir("ha_ai_brain/agents") else "agents"
            )

        return cls(
            ha_url=ha_url,
            ha_ws_url=ha_ws_url,
            ha_token=ha_token,
            use_simulator=use_simulator,
            operating_mode=_env_enum("BRAIN_OPERATING_MODE", OperatingMode, OperatingMode.HYBRID),
            default_autonomy=_env_enum("BRAIN_DEFAULT_AUTONOMY", AutonomyLevel, AutonomyLevel.COPILOT),
            llm_model=os.getenv("BRAIN_LLM_MODEL") or "openai/gpt-4o",
            llm_fast_model=os.getenv("BRAIN_LLM_FAST_MODEL") or "openai/gpt-4o-mini",
            llm_fallback_models=fallback_models,
            llm_fallback_policy=_env_enum("BRAIN_LLM_FALLBACK_POLICY", FallbackPolicy, FallbackPolicy.AUTO_SWITCH_AND_RECOVER),
            llm_api_key=(os.getenv("BRAIN_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip(),
            managed_proxy_url=os.getenv("BRAIN_MANAGED_PROXY_URL", "").strip(),
            license_key=os.getenv("BRAIN_LICENSE_KEY") or "DEV-TRIAL-KEY",
            site_context=os.getenv("BRAIN_SITE_CONTEXT") or DEFAULT_SITE_CONTEXT,
            notifications_enabled=_env_bool("BRAIN_NOTIFICATIONS_ENABLED", True),
            notification_service=os.getenv("BRAIN_NOTIFICATION_SERVICE") or "notify.notify",
            batch_interval_minutes=_env_int("BRAIN_BATCH_INTERVAL_MINUTES", 360, minimum=15, maximum=10080),
            batch_lookback_hours=_env_int("BRAIN_BATCH_LOOKBACK_HOURS", 24, minimum=1, maximum=720),
            db_path=os.getenv("BRAIN_DB_PATH") or "ha_ai_brain.db",
            timezone=os.getenv("BRAIN_TIMEZONE") or os.getenv("TZ") or "",
            realtime_gating=_env_bool("BRAIN_REALTIME_GATING", True),
            baseline_min_days=_env_int("BRAIN_BASELINE_MIN_DAYS", 3, minimum=1, maximum=30),
            store_retention_days=_env_int("BRAIN_STORE_RETENTION_DAYS", 90, minimum=7, maximum=730),
            store_backfill_hours=_env_int("BRAIN_STORE_BACKFILL_HOURS", 240, minimum=0, maximum=2160),
            history_max_entities=_env_int("BRAIN_HISTORY_MAX_ENTITIES", 300, minimum=20, maximum=2000),
            deterministic_automations=_env_bool("BRAIN_DETERMINISTIC_AUTOMATIONS", True),
            max_new_automations_per_cycle=_env_int("BRAIN_MAX_NEW_AUTOMATIONS", 3, minimum=0, maximum=20),
            exception_detection=_env_bool("BRAIN_EXCEPTION_DETECTION", True),
            research_enabled=_env_bool("BRAIN_RESEARCH_ENABLED", True),
            research_web_search=_env_bool("BRAIN_RESEARCH_WEB_SEARCH", False),
            research_interval_days=_env_int("BRAIN_RESEARCH_INTERVAL_DAYS", 7, minimum=1, maximum=90),
            research_topics_per_agent=_env_int("BRAIN_RESEARCH_TOPICS_PER_AGENT", 1, minimum=1, maximum=5),
            max_exceptions_per_cycle=_env_int("BRAIN_MAX_EXCEPTIONS_PER_CYCLE", 5, minimum=1, maximum=50),
            max_exceptions_per_day=_env_int("BRAIN_MAX_EXCEPTIONS_PER_DAY", 20, minimum=1, maximum=500),
            daily_token_budget=_env_int("BRAIN_DAILY_TOKEN_BUDGET", 0, minimum=0),
            realtime_coalesce_seconds=_env_int("BRAIN_REALTIME_COALESCE_SECONDS", 90, minimum=0, maximum=3600),
            max_agent_wakeups_per_hour=_env_int("BRAIN_MAX_AGENT_WAKEUPS_PER_HOUR", 6, minimum=0, maximum=1000),
            max_actions_per_hour=_env_int("BRAIN_MAX_ACTIONS_PER_HOUR", 30, minimum=1, maximum=1000),
            max_actions_per_entity_per_hour=_env_int("BRAIN_MAX_ACTIONS_PER_ENTITY_PER_HOUR", 3, minimum=1, maximum=100),
            quiet_hours_start=os.getenv("BRAIN_QUIET_HOURS_START", "").strip(),
            quiet_hours_end=os.getenv("BRAIN_QUIET_HOURS_END", "").strip(),
            log_level=(os.getenv("BRAIN_LOG_LEVEL") or "INFO").strip().upper() if (os.getenv("BRAIN_LOG_LEVEL") or "INFO").strip().upper() in ("DEBUG", "INFO", "WARNING", "ERROR") else "INFO",
            paused=_env_bool("BRAIN_PAUSED", False),
            notify_autonomous_actions=_env_bool("BRAIN_NOTIFY_AUTONOMOUS_ACTIONS", True),
            privacy_scrub=_env_bool("BRAIN_PRIVACY_SCRUB", True),
            knowledge_dir=os.getenv("BRAIN_KNOWLEDGE_DIR", "").strip(),
            custom_agents_dir=custom_agents_dir,
            bundled_agents_dir=bundled_agents_dir,
        )


def mask_secret(secret: str) -> str:
    """Return a display-safe hint for a secret; short secrets are fully masked so they cannot be reconstructed."""
    if not secret:
        return ""
    if len(secret) < 20:
        return "••••••••"
    return f"{secret[:4]}••••••••{secret[-4:]}"
