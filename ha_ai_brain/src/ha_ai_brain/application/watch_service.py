"""Storage and plain-language compilation of user watches."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from ha_ai_brain.domain.models import EntityState
from ha_ai_brain.domain.promptfmt import dumps
from ha_ai_brain.domain.watches import WatchRule, build_entity_catalog, validate_watch
from ha_ai_brain.ports.llm import REASONING_OFF, LLMProviderPort
from ha_ai_brain.ports.memory import MemoryStorePort

logger = logging.getLogger(__name__)

PREFIX = "watch:"
MAX_WATCHES = 100

COMPILER_SYSTEM_PROMPT = (
    "You convert a homeowner's plain-language monitoring request into ONE structured watch rule for Home Assistant.\n"
    "Use ONLY entity ids that appear in `entities`; never invent entities. Pick every entity that the request clearly refers to.\n"
    "Return JSON: {\"watch\": {\"name\": short title, \"entity_ids\": [...], "
    "\"condition\": {\"kind\": \"state\"|\"numeric\"|\"silence\", \"state\": value to match (kind=state), \"negate\": true to fire when the value is NOT `state`, "
    "\"above\": number, \"below\": number (kind=numeric, in the entity's own unit - convert if the request uses another unit), "
    "\"attribute\": optional attribute name to evaluate instead of the state, \"for_minutes\": how long the condition must hold (0 if not stated; "
    "for kind=silence the minutes without any update/change)}, "
    "\"presence\": \"any\"|\"home\"|\"away\", \"window_start\": \"HH:MM\" or \"\", \"window_end\": \"HH:MM\" or \"\", "
    "\"weekdays\": [\"mon\"..\"sun\"] or [], \"severity\": \"info\"|\"warning\"|\"critical\", \"message\": the alert text to show, "
    "\"cooldown_minutes\": minimum minutes between repeated alerts}, "
    "\"explanation\": one sentence stating how you interpreted the request, including any assumption you made}.\n"
    "If the request cannot be expressed with these fields, return {\"error\": \"why\"}. When the request is ambiguous choose the "
    "safest reading and say so in `explanation`. Write `name`, `message` and `explanation` in the language of the request."
)


class WatchService:
    def __init__(self, memory: MemoryStorePort, llm: LLMProviderPort) -> None:
        self.memory = memory
        self.llm = llm
        self._cache: dict[str, WatchRule] | None = None

    async def _load(self) -> dict[str, WatchRule]:
        if self._cache is None:
            cache: dict[str, WatchRule] = {}
            for key, raw in (await self.memory.list_kv(PREFIX)).items():
                try:
                    rule = WatchRule.model_validate_json(raw)
                    cache[rule.watch_id] = rule
                except (ValidationError, ValueError) as exc:
                    logger.warning("Ignoring invalid stored watch %s: %s", key, exc)
            self._cache = cache
        return self._cache

    async def list(self) -> list[WatchRule]:
        return sorted((await self._load()).values(), key=lambda r: r.created_at)

    async def get(self, watch_id: str) -> WatchRule | None:
        return (await self._load()).get(watch_id)

    async def save(self, rule: WatchRule) -> WatchRule:
        cache = await self._load()
        if rule.watch_id not in cache and len(cache) >= MAX_WATCHES:
            raise ValueError(f"At most {MAX_WATCHES} watches are supported")
        await self.memory.set_kv(PREFIX + rule.watch_id, rule.model_dump_json())
        cache[rule.watch_id] = rule
        return rule

    async def delete(self, watch_id: str) -> bool:
        cache = await self._load()
        if watch_id not in cache:
            return False
        await self.memory.delete_kv(PREFIX + watch_id)
        del cache[watch_id]
        return True

    async def compile(self, text: str, states: dict[str, EntityState]) -> dict[str, Any]:
        """Turn a request into a validated draft rule (not saved). Costs one AI call; the rule then runs for free."""
        text = (text or "").strip()
        if len(text) < 5:
            return {"draft": None, "errors": ["Describe what you want to be told about."], "warnings": [], "explanation": ""}
        raw = await self.llm.generate_json(
            system_prompt=COMPILER_SYSTEM_PROMPT,
            user_prompt=dumps({"request": text, "entities": build_entity_catalog(text, states)}),
            use_fast_tier=True,
            context_hint={"task": "compile_watch", "agent_id": "watch_compiler", "reasoning": REASONING_OFF},
        )
        if not raw:
            return {"draft": None, "errors": ["No AI provider is configured or it did not answer. Configure one in Settings."], "warnings": [], "explanation": ""}
        if raw.get("error"):
            return {"draft": None, "errors": [str(raw["error"])], "warnings": [], "explanation": ""}
        payload = raw.get("watch")
        if not isinstance(payload, dict):
            return {"draft": None, "errors": ["The AI answer did not contain a watch rule. Try rephrasing."], "warnings": [], "explanation": ""}
        payload = {**payload, "description": text}
        try:
            rule = WatchRule.model_validate(payload)
        except ValidationError as exc:
            msgs = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
            return {"draft": None, "errors": msgs[:6], "warnings": [], "explanation": str(raw.get("explanation", ""))}
        errors, warnings = validate_watch(rule, states)
        return {
            "draft": rule.model_dump(mode="json"),
            "errors": errors,
            "warnings": warnings,
            "explanation": str(raw.get("explanation", "")),
        }
