"""Edge Signal Triage, Deadband Filtering, Causal Loop Prevention, Native Automation Attribution & Human Override Detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ha_ai_brain.domain.models import (
    AgentSpec,
    EntityState,
    EventOrigin,
    FeedbackEpisode,
    FeedbackPolarity,
    IgnoredTarget,
    SemanticEventFrame,
    StateChangedEvent,
)


class EdgeSignalTriage:
    """
    Pre-processes the raw Home Assistant state stream before waking up LLM agents:
    1. Prevents self-triggering causal loops by tracking AI-originated context_ids.
    2. Tracks native Home Assistant `automation_triggered` contexts (`context.parent_id`) so
       actions triggered by existing HA automations are never mistaken for manual human habits
       or human overrides.
    3. Detects Implicit Human Overrides when a human manually changes an AI-controlled entity.
    4. Applies deadbands / hysteresis to prevent token bankruptcy from sensor jitter.
    5. Assembles a corroborated SemanticEventFrame containing sibling area sensors, weather & existing automations.
    """

    DEFAULT_DEADBANDS: dict[str, float] = {
        "temperature": 0.6,   # °C
        "humidity": 2.5,      # %
        "illuminance": 100.0, # lx (indoor/low-light baseline; outdoor uses proportional >=15% & >=1500 lx)
        "power": 35.0,        # W
        "carbon_dioxide": 50.0,
    }

    ACTUATOR_DOMAINS = {"light", "switch", "climate", "cover", "fan", "humidifier", "lock", "valve", "water_heater"}

    def __init__(self, manual_override_cooldown_seconds: int = 900) -> None:
        self.manual_override_cooldown_seconds = manual_override_cooldown_seconds
        self._ai_context_ids: set[str] = set()
        # context_id -> automation_entity_id (e.g. "automation.morning_heating")
        self._automation_context_map: dict[str, str] = {}
        # entity_id -> {timestamp, agent_id, cause_category, signature, expected_state, service_called}
        self._recent_ai_actions: dict[str, dict[str, Any]] = {}
        # entity_id -> last value that woke an agent
        self._last_triggered_numeric: dict[str, float] = {}
        # entity_id -> previous numeric value that woke an agent (for detecting oscillating/flapping sensors)
        self._prev_triggered_numeric: dict[str, float] = {}
        # entity_id -> last timestamp that woke an agent (prevents flapping sensors from draining LLM quota)
        self._last_triggered_at: dict[str, datetime] = {}
        # entity_id -> cooldown expiration timestamp after human manual override
        self._manual_override_until: dict[str, datetime] = {}

    def register_ai_action(
        self,
        context_id: str,
        entity_ids: list[str],
        agent_id: str,
        cause_category: str,
        action_signature: str,
        service_called: str,
        service_data: dict[str, Any],
    ) -> None:
        """Record an outgoing AI action to recognize self-caused events and detect subsequent human overrides."""
        self._ai_context_ids.add(context_id)
        now = datetime.now(timezone.utc)
        for entity_id in entity_ids:
            self._recent_ai_actions[entity_id] = {
                "timestamp": now,
                "context_id": context_id,
                "agent_id": agent_id,
                "cause_category": cause_category,
                "action_signature": action_signature,
                "service_called": service_called,
                "service_data": service_data,
            }

    def register_ha_automation_trigger(self, context_id: str, automation_entity_id: str) -> None:
        """Record a context_id emitted by a native Home Assistant `automation_triggered` event."""
        if not context_id:
            return
        self._automation_context_map[context_id] = automation_entity_id
        # Keep map bounded
        if len(self._automation_context_map) > 2000:
            oldest_key = next(iter(self._automation_context_map))
            del self._automation_context_map[oldest_key]

    def classify_event_origin(self, event: StateChangedEvent) -> EventOrigin:
        """Determine whether a state transition came from AI Brain, a native HA Automation, a sensor, or a human."""
        if (event.context_id and event.context_id in self._ai_context_ids) or (
            event.context_parent_id and event.context_parent_id in self._ai_context_ids
        ):
            event.origin = EventOrigin.AI_BRAIN
            return EventOrigin.AI_BRAIN

        auto_id = (
            event.triggered_by_automation_id
            or (self._automation_context_map.get(event.context_id) if event.context_id else None)
            or (self._automation_context_map.get(event.context_parent_id) if event.context_parent_id else None)
        )
        if auto_id or event.origin == EventOrigin.HA_AUTOMATION:
            event.origin = EventOrigin.HA_AUTOMATION
            event.triggered_by_automation_id = auto_id or event.triggered_by_automation_id or "automation.unknown"
            # Also chain the child context_id so cascading state changes from the same automation are tracked
            if event.context_id and auto_id:
                self._automation_context_map[event.context_id] = auto_id
            return EventOrigin.HA_AUTOMATION

        if event.new_state.domain in ("sensor", "weather", "sun"):
            event.origin = EventOrigin.SENSOR_TELEMETRY
            return EventOrigin.SENSOR_TELEMETRY

        event.origin = EventOrigin.HUMAN_OR_PHYSICAL
        return EventOrigin.HUMAN_OR_PHYSICAL

    def is_entity_in_manual_override(self, entity_id: str) -> bool:
        """Check whether an entity is currently locked out because a human manually overrode the AI."""
        until = self._manual_override_until.get(entity_id)
        if not until:
            return False
        if datetime.now(timezone.utc) >= until:
            del self._manual_override_until[entity_id]
            return False
        return True

    def evaluate_event(
        self,
        event: StateChangedEvent,
        all_states: dict[str, EntityState],
        agents: list[AgentSpec],
        ignored_targets: list[IgnoredTarget] | None = None,
    ) -> tuple[list[SemanticEventFrame], FeedbackEpisode | None]:
        """
        Evaluate a single state_changed event.
        Returns:
          - List of SemanticEventFrames (one per matching agent) if the event is significant.
          - Optional FeedbackEpisode if an implicit human override was detected.
        """
        now = datetime.now(timezone.utc)
        origin = self.classify_event_origin(event)

        # 0. Check User-Managed Ignore List first (never wake agents for ignored entities/devices)
        if ignored_targets and any(t.matches(event.entity_id) for t in ignored_targets):
            return [], None

        # 1. Ignore self-originated AI actions (Causal Loop Prevention)
        if origin == EventOrigin.AI_BRAIN:
            return [], None

        # 2. Ignore actuator state transitions caused by Native HA Automations
        # so agents never mistake an automation's repetitive action for a human habit or fight native automations.
        if origin == EventOrigin.HA_AUTOMATION and event.new_state.domain in self.ACTUATOR_DOMAINS:
            return [], None

        # 3. Check for Implicit Human Override on recently AI-actuated entities
        recent = self._recent_ai_actions.get(event.entity_id)
        if recent and origin == EventOrigin.HUMAN_OR_PHYSICAL:
            elapsed = (now - recent["timestamp"]).total_seconds()
            # If changed within the override window by a human (or external physical switch, NOT an HA automation)
            if 2.0 < elapsed <= self.manual_override_cooldown_seconds:
                is_human = bool(event.context_user_id) or (event.context_id != recent["context_id"])
                if is_human and event.old_state and event.old_state.state != event.new_state.state:
                    self._manual_override_until[event.entity_id] = now + timedelta(
                        seconds=self.manual_override_cooldown_seconds
                    )
                    feedback = FeedbackEpisode(
                        agent_id=recent["agent_id"],
                        area_id=event.new_state.area_id,
                        cause_category=recent["cause_category"],
                        action_signature=recent["action_signature"],
                        target_entity_ids=[event.entity_id],
                        service_called=recent["service_called"],
                        service_data=recent["service_data"],
                        polarity=FeedbackPolarity.OVERRIDDEN_IMPLICIT,
                        human_note=(
                            f"Human manually changed {event.entity_id} from '{event.old_state.state}' "
                            f"to '{event.new_state.state}' {int(elapsed)}s after AI action. "
                            f"Entering {self.manual_override_cooldown_seconds}s cooldown."
                        ),
                        context_snapshot={
                            "old_state": event.old_state.state,
                            "new_state": event.new_state.state,
                            "elapsed_seconds": elapsed,
                        },
                    )
                    return [], feedback

        # 4. Deadband / Significance Filtering + Anti-Flap Oscillation Guard
        is_significant, reason = self._check_significance(event, now=now)
        if not is_significant:
            return [], None

        # 5. Route to matching specialized agents and corroborate with sibling area, weather & automation states
        frames: list[SemanticEventFrame] = []
        for agent in agents:
            if not agent.enabled:
                continue
            if self._matches_agent(event.new_state, agent):
                if agent.agent_id == "repair_diagnostics_agent":
                    # Rate-limit diagnostics runs per integration/prefix to at most once every 6 hours
                    obj_id = event.entity_id.split(".", 1)[-1]
                    integration_prefix = f"diag_prefix:{obj_id.split('_', 1)[0]}"
                    last_diag = self._last_triggered_at.get(integration_prefix)
                    if last_diag and (now - last_diag).total_seconds() < 21600.0:
                        continue
                    self._last_triggered_at[integration_prefix] = now
                corroborated = self._corroborate_context(
                    event.new_state,
                    all_states,
                    agent,
                    ignored_targets=ignored_targets,
                )
                frames.append(
                    SemanticEventFrame(
                        target_agent_id=agent.agent_id,
                        area_id=event.new_state.area_id,
                        trigger_events=[event],
                        corroborated_states=corroborated,
                        significance_reason=reason,
                    )
                )

        if frames:
            self._last_triggered_at[event.entity_id] = now

        return frames, None

    def _check_significance(self, event: StateChangedEvent, now: datetime | None = None) -> tuple[bool, str]:
        """Determine if the state transition exceeds deadband thresholds and is not a rapid sensor oscillation."""
        new_num = event.new_state.numeric_value
        if new_num is not None:
            dev_class = event.new_state.device_class or ""
            deadband = self.DEFAULT_DEADBANDS.get(dev_class, 0.5)
            prev_num = self._last_triggered_numeric.get(event.entity_id)
            if prev_num is None and event.old_state and event.old_state.numeric_value is not None:
                prev_num = event.old_state.numeric_value

            if prev_num is not None:
                delta = abs(new_num - prev_num)

                # Dynamic Proportional Deadbands for token conservation:
                effective_deadband = deadband
                if dev_class == "illuminance" or "illuminance" in event.entity_id:
                    if prev_num >= 500.0:
                        # Outdoor / Daylight lux fluctuates widely with wind/clouds; require >= 15% AND >= 1500 lx
                        effective_deadband = max(1500.0, prev_num * 0.15)
                    else:
                        effective_deadband = 100.0
                elif dev_class == "power" or "power" in event.entity_id:
                    if prev_num >= 100.0:
                        effective_deadband = max(50.0, prev_num * 0.20)

                if delta < effective_deadband:
                    return False, f"Delta {delta:.2f} below effective deadband {effective_deadband:.1f}"

                # Dwell / Debounce guard for high-frequency noisy telemetry (illuminance, power):
                # if this sensor triggered an agent < 10m ago, require >= 2x deadband
                if dev_class in ("illuminance", "power") or any(k in event.entity_id for k in ("illuminance", "power", "_lux", "_w")):
                    last_t = self._last_triggered_at.get(event.entity_id)
                    if now is not None and last_t is not None:
                        elapsed = (now - last_t).total_seconds()
                        if elapsed < 600.0 and delta < (effective_deadband * 2.0):
                            return False, f"Debounced: triggered {elapsed:.0f}s ago (<600s) and delta {delta:.1f} < 2x threshold ({effective_deadband * 2.0:.1f})"

                # Anti-flap guard: if the sensor is bouncing back to its previous triggered value within 30 min, ignore
                older_num = self._prev_triggered_numeric.get(event.entity_id)
                if (
                    older_num is not None
                    and abs(new_num - older_num) < 0.05
                    and now is not None
                    and last_t is not None
                    and (now - last_t).total_seconds() < 1800.0
                ):
                    return False, f"Oscillation bounce back to {new_num} suppressed"
                self._prev_triggered_numeric[event.entity_id] = prev_num
                self._last_triggered_numeric[event.entity_id] = new_num
                unit = event.new_state.unit_of_measurement or ""
                return True, f"{event.entity_id} changed by {new_num - prev_num:+.2f}{unit} (now {new_num}{unit})"

            self._last_triggered_numeric[event.entity_id] = new_num
            return True, f"Initial numeric reading on {event.entity_id}: {new_num}"

        # Discrete state change (e.g., on/off, heat/off, open/closed, unavailable)
        if event.old_state and event.old_state.state == event.new_state.state:
            return False, "Discrete state unchanged"

        old_s = event.old_state.state if event.old_state else "unknown"
        return True, f"{event.entity_id} transitioned '{old_s}' -> '{event.new_state.state}'"

    def _matches_agent(self, state: EntityState, agent: AgentSpec) -> bool:
        """Check if an entity state belongs to the specialty of the given agent."""
        if any(skip in state.entity_id for skip in ("gabis_mac", "andrada_s_iphone", "gabriels_iphone", "lenovo_")):
            return False
        if agent.agent_id == "repair_diagnostics_agent":
            return state.state in ("unavailable", "unknown")
        if state.domain in agent.monitored_domains:
            if not agent.monitored_device_classes or state.domain != "sensor":
                return True
            if state.device_class in agent.monitored_device_classes:
                return True
        return False

    def _corroborate_context(
        self,
        trigger_state: EntityState,
        all_states: dict[str, EntityState],
        agent: AgentSpec,
        ignored_targets: list[IgnoredTarget] | None = None,
    ) -> dict[str, EntityState]:
        """
        Gather all relevant sibling entities in the same area, plus global outdoor/weather entities
        and existing Home Assistant `automation.*` entities, excluding any user-ignored entities.
        """
        corroborated: dict[str, EntityState] = {trigger_state.entity_id: trigger_state}
        target_area = trigger_state.area_id

        # If trigger entity has no assigned area, infer a room prefix token (e.g., `bedroom` from `binary_sensor.bedroom_water_tank`)
        obj_id = trigger_state.entity_id.split(".", 1)[-1]
        prefix_token = obj_id.split("_", 1)[0] if "_" in obj_id else ""

        for entity_id, state in all_states.items():
            if ignored_targets and any(t.matches(entity_id) for t in ignored_targets):
                continue
            # 1. Include entities in the same room/area that are relevant to the agent
            if target_area and state.area_id == target_area:
                if state.domain in agent.monitored_domains or state.domain in agent.controllable_domains:
                    if state.state in ("unavailable", "unknown") and agent.agent_id != "repair_diagnostics_agent":
                        continue
                    corroborated[entity_id] = state
            elif not target_area and prefix_token and len(prefix_token) >= 4 and f".{prefix_token}_" in entity_id:
                if state.domain in agent.monitored_domains or state.domain in agent.controllable_domains:
                    if state.state in ("unavailable", "unknown") and agent.agent_id != "repair_diagnostics_agent":
                        continue
                    corroborated[entity_id] = state
            # 2. Include outdoor / weather / sun / existing HA automations
            elif state.domain in ("weather", "sun", "automation") or state.area_id in ("outdoor", "outside", "exterior"):
                if state.state in ("unavailable", "unknown") and agent.agent_id != "repair_diagnostics_agent":
                    continue
                corroborated[entity_id] = state
            elif any(k in entity_id for k in ("outdoor", "outside", "weather")):
                if state.state in ("unavailable", "unknown") and agent.agent_id != "repair_diagnostics_agent":
                    continue
                corroborated[entity_id] = state

        return corroborated
