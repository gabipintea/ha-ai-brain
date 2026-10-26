"""Research agenda: every specialised agent keeps discovering, citing and (after approval) reusing new knowledge."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from ha_ai_brain.application.agent_registry import AgentRegistry
from ha_ai_brain.config import BrainSettings
from ha_ai_brain.domain.agent_scope import agent_has_scope
from ha_ai_brain.domain.models import AgentSpec
from ha_ai_brain.domain.research import (
    KnowledgeItem,
    ResearchTopic,
    build_planning_prompts,
    build_research_prompts,
    capability_profile,
    device_seed_topics,
    is_similar_title,
    parse_findings,
    parse_topics,
    repair_item,
    utc_now,
)
from ha_ai_brain.ports.llm import REASONING_DEFAULT, REASONING_OFF, LLMProviderPort
from ha_ai_brain.ports.memory import MemoryStorePort
from ha_ai_brain.ports.smart_home import SmartHomePort

logger = logging.getLogger(__name__)

ITEM_PREFIX = "know:"
TOPIC_PREFIX = "rtopic:"
LAST_RUN_KEY = "research:last_run"
LAST_SUMMARY_KEY = "research:last_summary"
PLAN_BATCH = 6


class KnowledgeStore:
    """Persistence of research topics and cited findings (key/value, no schema migration needed)."""

    def __init__(self, memory: MemoryStorePort) -> None:
        self.memory = memory

    async def items(self, status: str | None = None, agent_id: str | None = None) -> list[KnowledgeItem]:
        out: list[KnowledgeItem] = []
        for raw in (await self.memory.list_kv(ITEM_PREFIX)).values():
            try:
                item = repair_item(KnowledgeItem.model_validate_json(raw))
            except ValueError:
                continue
            if (status is None or item.status == status) and (agent_id is None or item.agent_id == agent_id):
                out.append(item)
        return sorted(out, key=lambda i: i.created_at, reverse=True)

    async def get_item(self, item_id: str) -> KnowledgeItem | None:
        raw = await self.memory.get_kv(ITEM_PREFIX + item_id)
        return repair_item(KnowledgeItem.model_validate_json(raw)) if raw else None

    async def save_item(self, item: KnowledgeItem) -> None:
        await self.memory.set_kv(ITEM_PREFIX + item.item_id, item.model_dump_json())

    async def delete_item(self, item_id: str) -> bool:
        if await self.memory.get_kv(ITEM_PREFIX + item_id) is None:
            return False
        await self.memory.delete_kv(ITEM_PREFIX + item_id)
        return True

    async def topics(self, status: str | None = None, agent_id: str | None = None) -> list[ResearchTopic]:
        out: list[ResearchTopic] = []
        for raw in (await self.memory.list_kv(TOPIC_PREFIX)).values():
            try:
                topic = ResearchTopic.model_validate_json(raw)
            except ValueError:
                continue
            if (status is None or topic.status == status) and (agent_id is None or topic.agent_id == agent_id):
                out.append(topic)
        return sorted(out, key=lambda t: t.created_at)

    async def save_topic(self, topic: ResearchTopic) -> None:
        await self.memory.set_kv(TOPIC_PREFIX + topic.topic_id, topic.model_dump_json())

    async def known_titles(self) -> list[str]:
        """Everything ever researched or rejected: new topics must differ from these."""
        titles = [t.title for t in await self.topics()]
        titles += [i.title for i in await self.items()] + [i.topic_title for i in await self.items() if i.topic_title]
        return titles


async def approved_knowledge_for(memory: MemoryStorePort, agent_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """Approved, cited findings in the compact form used inside agent prompts."""
    out: list[dict[str, Any]] = []
    for item in (await KnowledgeStore(memory).items(status="approved", agent_id=agent_id))[:limit]:
        points = " ".join(f"- {p}" for p in item.key_points[:5])
        guidance = f"{item.summary} {points} Apply: {item.how_to_apply}".strip()[:900]
        hosts = sorted({s.url.split("/")[2] for s in item.sources if s.url.count("/") >= 2})[:3]
        origin = "approved web research" if item.basis == "web_sources" else "approved AI expertise"
        out.append(
            {
                "id": f"research:{item.item_id}",
                "title": item.title,
                "guidance": guidance,
                "source": ", ".join(hosts or item.references[:3]) or "AI general knowledge",
                "origin": origin,
            }
        )
    return out


class ResearchAgenda:
    def __init__(
        self,
        settings: BrainSettings,
        llm: LLMProviderPort,
        memory: MemoryStorePort,
        smart_home: SmartHomePort,
        registry: AgentRegistry,
        budget_ok: Callable[[], Awaitable[bool]],
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.memory = memory
        self.smart_home = smart_home
        self.registry = registry
        self.budget_ok = budget_ok
        self.store = KnowledgeStore(memory)
        self.running = False

    # ------------------------------------------------------------------ schedule
    async def last_run(self) -> datetime | None:
        raw = await self.memory.get_kv(LAST_RUN_KEY)
        try:
            return datetime.fromisoformat(raw) if raw else None
        except ValueError:
            return None

    async def next_run_at(self) -> datetime | None:
        last = await self.last_run()
        interval = timedelta(days=max(1, self.settings.research_interval_days))
        return (last + interval) if last else None

    async def due(self, now: datetime) -> bool:
        if not self.settings.research_enabled or self.running or not self.llm.is_available:
            return False
        nxt = await self.next_run_at()
        return nxt is None or now >= nxt

    # --------------------------------------------------------------------- run
    async def run(self, agent_ids: list[str] | None = None) -> dict[str, Any]:
        if self.running:
            return {"status": "already_running"}
        if not self.llm.is_available:
            return {"status": "unavailable", "message": "Research needs an AI provider. Configure one in Settings."}
        self.running = True
        summary: dict[str, Any] = {"status": "completed", "topics_planned": 0, "topics_researched": 0, "findings": 0, "skipped": 0}
        try:
            states = await self.smart_home.get_all_states()
            inventory = await self.smart_home.get_device_inventory()
            for agent in self.registry.get_active_agents():
                if agent_ids and agent.agent_id not in agent_ids:
                    continue
                if not agent_has_scope(agent, states)[0]:
                    continue  # nothing in this home for that specialist to research
                if not await self.budget_ok():
                    summary["status"] = "stopped_budget"
                    break
                profile = capability_profile(states, inventory, agent)
                pending = await self.store.topics("pending", agent.agent_id)
                if len(pending) < self.settings.research_topics_per_agent:
                    summary["topics_planned"] += await self.plan_topics(agent, profile, inventory)
                    pending = await self.store.topics("pending", agent.agent_id)
                for topic in pending[: self.settings.research_topics_per_agent]:
                    if not await self.budget_ok():
                        summary["status"] = "stopped_budget"
                        break
                    found = await self.research_topic(agent, topic, profile)
                    summary["topics_researched"] += 1
                    summary["findings"] += found
                    summary["skipped"] += 1 if found == 0 else 0
            await self.memory.set_kv(LAST_RUN_KEY, utc_now().isoformat())
            await self.memory.set_kv(LAST_SUMMARY_KEY, json.dumps({**summary, "at": utc_now().isoformat()}))
        finally:
            self.running = False
        return summary

    async def plan_topics(self, agent: AgentSpec, profile: dict[str, Any], inventory: list[dict[str, Any]]) -> int:
        known = await self.store.known_titles()
        fresh: list[ResearchTopic] = device_seed_topics(inventory, agent, limit=2, known=known)
        raw = await self.llm.generate_json(
            *build_planning_prompts(agent, profile, known, PLAN_BATCH, self.settings.site_context),
            use_fast_tier=True,
            context_hint={"task": "plan_research_topics", "agent_id": agent.agent_id, "reasoning": REASONING_OFF},
        )
        for topic in parse_topics(raw or {}, agent.agent_id):
            if not any(is_similar_title(topic.title, k) for k in known + [t.title for t in fresh]):
                fresh.append(topic)
        for topic in fresh:
            await self.store.save_topic(topic)
        return len(fresh)

    @property
    def web_search_active(self) -> bool:
        """The optional, costlier cited-sources mode (Gemini only)."""
        return self.settings.research_web_search and self.llm.supports_web_search

    async def research_topic(self, agent: AgentSpec, topic: ResearchTopic, profile: dict[str, Any]) -> int:
        known = [i.title for i in await self.store.items()]
        items: list[KnowledgeItem] = []
        grounded_answer = False
        if self.web_search_active:
            result = await self.llm.generate_research(
                *build_research_prompts(agent, topic, profile, web=True),
                {"task": "web_research", "agent_id": agent.agent_id},
            )
            grounded_answer = result.grounded
            if grounded_answer:
                items = parse_findings(result.parsed, topic, result.citations, result.coverage, grounded=True)
        if not grounded_answer:
            # The normal path - and the fallback when a web search returned nothing: the model's own expertise.
            raw = await self.llm.generate_json(
                *build_research_prompts(agent, topic, profile, web=False),
                use_fast_tier=False,
                context_hint={"task": "knowledge_research", "agent_id": agent.agent_id, "reasoning": REASONING_DEFAULT},
            )
            items = parse_findings(raw or {}, topic)
        items = [i for i in items if not any(is_similar_title(i.title, k) for k in known)]
        for item in items:
            await self.store.save_item(item)
        topic.status = "done" if items else "skipped"
        topic.note = "" if items else "The AI had nothing useful to add on this topic."
        await self.store.save_topic(topic)
        return len(items)

    # ---------------------------------------------------------------- decisions
    async def decide(self, item_id: str, decision: str) -> KnowledgeItem | None:
        item = await self.store.get_item(item_id)
        if item is None:
            return None
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be 'approve' or 'reject'")
        item.status = "approved" if decision == "approve" else "rejected"
        item.decided_at = utc_now()
        await self.store.save_item(item)
        return item

    async def status(self) -> dict[str, Any]:
        topics = await self.store.topics()
        try:
            last_summary = json.loads(await self.memory.get_kv(LAST_SUMMARY_KEY) or "null")
        except ValueError:
            last_summary = None
        nxt = await self.next_run_at()
        return {
            "enabled": self.settings.research_enabled,
            "can_research": self.llm.is_available,
            "supports_web_search": self.llm.supports_web_search,
            "web_search_enabled": self.settings.research_web_search,
            "running": self.running,
            "interval_days": self.settings.research_interval_days,
            "topics_per_agent": self.settings.research_topics_per_agent,
            "last_run": (await self.last_run()).isoformat() if await self.last_run() else None,
            "next_run": nxt.isoformat() if nxt else None,
            "last_summary": last_summary,
            "backlog": [
                {"topic_id": t.topic_id, "agent_id": t.agent_id, "title": t.title, "origin": t.origin}
                for t in topics
                if t.status == "pending"
            ][:30],
            "researched_topics": sum(1 for t in topics if t.status != "pending"),
        }
