"""Domain model and pure helpers for the research agenda (topics, cited findings, prompts, validation)."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ha_ai_brain.domain.models import AgentSpec, EntityState
from ha_ai_brain.domain.promptfmt import dumps

# User-generated-content hosts are shown, but never count as a reliable source on their own.
LOW_TRUST_HOSTS = (
    "reddit.com", "youtube.com", "youtu.be", "facebook.com", "pinterest.com", "quora.com",
    "tiktok.com", "twitter.com", "x.com", "instagram.com", "answers.yahoo.com",
)
GENERIC_DOMAINS = frozenset({"notify", "automation", "homeassistant", "script", "scene", "persistent_notification"})
MAX_ITEM_TEXT = 1500
TITLE_SIMILARITY = 0.6


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def valid_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def source_trust(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return "low" if any(host == h or host.endswith("." + h) for h in LOW_TRUST_HOSTS) else "normal"


class ResearchSource(BaseModel):
    url: str
    title: str = ""
    trust: str = "normal"  # normal | low


class ResearchTopic(BaseModel):
    topic_id: str
    agent_id: str
    title: str
    question: str = ""
    queries: list[str] = Field(default_factory=list)
    rationale: str = ""
    origin: str = "ai_planned"  # device_seed | ai_planned
    status: str = "pending"  # pending | done | skipped
    note: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class KnowledgeItem(BaseModel):
    item_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_id: str
    topic_id: str = ""
    topic_title: str = ""
    title: str
    summary: str
    key_points: list[str] = Field(default_factory=list)
    how_to_apply: str = ""
    caveats: str = ""
    basis: str = "model_knowledge"  # model_knowledge (the AI's own expertise) | web_sources (cited, optional deep research)
    references: list[str] = Field(default_factory=list)  # named standards / documents the model says it draws on (unverified)
    sources: list[ResearchSource] = Field(default_factory=list)
    grounding_coverage: float = 0.0
    confidence: str = "medium"  # high | medium | low
    status: str = "proposed"  # proposed | approved | rejected
    created_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = None


def _unlist(text: str) -> str:
    """Older findings stored a list answer as its Python repr, e.g. "['Do this', 'Then that']": turn it back into numbered steps."""
    raw = text.strip()
    if raw.startswith("[") and raw.endswith("]"):
        try:
            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return text
        if isinstance(parsed, list) and all(isinstance(p, str) for p in parsed):
            return " ".join(f"{i}) {p.strip()}" for i, p in enumerate((p for p in parsed if p.strip()), 1))
    return text


def repair_item(item: KnowledgeItem) -> KnowledgeItem:
    """Bring a finding stored by an older version up to the current rules (list text, no 'high' badge without sources)."""
    update: dict[str, Any] = {}
    for name in ("how_to_apply", "caveats"):
        value = getattr(item, name)
        fixed = _unlist(value) if value else value
        if fixed != value:
            update[name] = fixed
    if item.basis != "web_sources" and item.confidence == "high":
        update["confidence"] = "medium"
    return item.model_copy(update=update) if update else item


# ---------------------------------------------------------------------------------------------- titles
_WORD = re.compile(r"[a-z0-9]{3,}")


def title_tokens(title: str) -> frozenset[str]:
    return frozenset(_WORD.findall(title.lower()))


def is_same_open_insight(title: str, agent_id: str, active: list[Any]) -> bool:
    """True when `active` (insights still in the homeowner's list) already holds the same finding from the same agent.

    An insight left in the list works as a to-do item, so a new one saying the same thing is not added."""
    t = title.strip().lower()
    for other in active:
        if other.agent_id != agent_id:
            continue
        o = other.title.strip().lower()
        if o == t or (len(o) >= 12 and (o in t or t in o)) or is_similar_title(title, other.title):
            return True
    return False


def is_similar_title(a: str, b: str) -> bool:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return a.strip().lower() == b.strip().lower()
    return len(ta & tb) / len(ta | tb) >= TITLE_SIMILARITY


def topic_id_for(agent_id: str, title: str) -> str:
    return hashlib.sha1(f"{agent_id}|{' '.join(sorted(title_tokens(title)))}".encode()).hexdigest()[:12]


def _clip(text: Any, limit: int = MAX_ITEM_TEXT) -> str:
    if isinstance(text, (list, tuple)):  # some models answer a text field with a list of steps
        text = " ".join(f"{i}) {str(t).strip()}" for i, t in enumerate((t for t in text if str(t).strip()), 1))
    return str(text or "").strip()[:limit]


def _strings(value: Any, limit: int = 8) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [_clip(v, 400) for v in value[:limit] if str(v).strip()] if isinstance(value, list) else []


# ---------------------------------------------------------------------------------------------- parsing
def parse_topics(raw: dict[str, Any], agent_id: str, origin: str = "ai_planned", limit: int = 8) -> list[ResearchTopic]:
    topics: list[ResearchTopic] = []
    items = raw.get("topics") if isinstance(raw, dict) else None
    for item in (items if isinstance(items, list) else [])[:limit]:
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            continue
        title = _clip(item["title"], 160)
        topics.append(
            ResearchTopic(
                topic_id=topic_id_for(agent_id, title),
                agent_id=agent_id,
                title=title,
                question=_clip(item.get("question"), 400),
                queries=_strings(item.get("search_queries"), 4),
                rationale=_clip(item.get("rationale"), 400),
                origin=origin,
            )
        )
    return topics


def parse_findings(
    raw: dict[str, Any],
    topic: ResearchTopic,
    citations: list[dict[str, str]] | None = None,
    coverage: float = 0.0,
    limit: int = 3,
    grounded: bool = False,
) -> list[KnowledgeItem]:
    """
    Turn a model answer into reviewable findings.

    * Default (`grounded=False`): the AI's own expertise. No sources are required; the finding is labelled as such and the
      model's own confidence is kept, capped at "medium" (nothing was verified).
    * Web research (`grounded=True`): findings are kept only when real sources came back, and confidence is capped by the
      evidence (low grounding coverage or only user-generated sources can never yield 'high').
    """
    sources = [
        ResearchSource(url=c["url"], title=c.get("title", ""), trust=source_trust(c["url"]))
        for c in (citations or [])
        if valid_http_url(c.get("url", ""))
    ]
    if grounded and not sources:
        return []
    reliable = [s for s in sources if s.trust == "normal"]
    items: list[KnowledgeItem] = []
    findings = raw.get("findings") if isinstance(raw, dict) else None
    for f in (findings if isinstance(findings, list) else [])[:limit]:
        if not isinstance(f, dict) or not str(f.get("summary") or "").strip():
            continue
        claimed = str(f.get("confidence") or "medium").lower()
        confidence = claimed if claimed in ("high", "medium", "low") else "medium"
        if not grounded and confidence == "high":
            confidence = "medium"  # nothing was checked against a source, so it never earns a 'high' badge
        if grounded:
            if not reliable or coverage < 0.3:
                confidence = "low"
            elif coverage < 0.6 and confidence == "high":
                confidence = "medium"
        items.append(
            KnowledgeItem(
                agent_id=topic.agent_id,
                topic_id=topic.topic_id,
                topic_title=topic.title,
                title=_clip(f.get("title") or topic.title, 160),
                summary=_clip(f["summary"]),
                key_points=_strings(f.get("key_points")),
                how_to_apply=_clip(f.get("how_to_apply"), 800),
                caveats=_clip(f.get("caveats"), 600),
                basis="web_sources" if grounded else "model_knowledge",
                references=_strings(f.get("references"), 5) if not grounded else [],
                sources=sources if grounded else [],
                grounding_coverage=round(coverage, 2) if grounded else 0.0,
                confidence=confidence,
            )
        )
    return items


# ---------------------------------------------------------------------------------------------- profile & seeds
def agent_domains(agent: AgentSpec) -> set[str]:
    return (set(agent.monitored_domains) | set(agent.controllable_domains)) - GENERIC_DOMAINS


def capability_profile(states: dict[str, EntityState], inventory: list[dict[str, Any]], agent: AgentSpec) -> dict[str, Any]:
    """What this home contains, as far as this agent's specialty is concerned (no names of people or places)."""
    domains = agent_domains(agent)
    by_domain: dict[str, int] = {}
    classes: set[str] = set()
    units: set[str] = set()
    for st in states.values():
        by_domain[st.domain] = by_domain.get(st.domain, 0) + 1
        if st.domain in domains or st.domain == "sensor":
            if st.device_class:
                classes.add(st.device_class)
            if st.unit_of_measurement:
                units.add(st.unit_of_measurement)
    relevant = [d for d in inventory if domains & set(d.get("domains", []))]
    return {
        "entity_counts_by_domain": dict(sorted(by_domain.items(), key=lambda kv: -kv[1])[:25]),
        "device_classes_present": sorted(classes)[:40],
        "units_present": sorted(units)[:30],
        "devices": [
            {k: d.get(k) for k in ("manufacturer", "model", "integrations", "domains", "device_count")}
            for d in relevant[:40]
        ],
    }


def device_seed_topics(inventory: list[dict[str, Any]], agent: AgentSpec, limit: int = 2, known: list[str] | None = None) -> list[ResearchTopic]:
    """Deterministic topics for concrete equipment found in the device registry (manufacturer + model)."""
    domains = agent_domains(agent)
    topics: list[ResearchTopic] = []
    for dev in inventory:
        manufacturer, model = str(dev.get("manufacturer") or "").strip(), str(dev.get("model") or "").strip()
        if not (manufacturer and model) or not (domains & set(dev.get("domains", []))):
            continue
        name = f"{manufacturer} {model}"
        title = f"{name}: recommended settings, known issues and efficiency tips"
        if any(is_similar_title(title, k) for k in (known or [])) or any(is_similar_title(title, t.title) for t in topics):
            continue
        topics.append(
            ResearchTopic(
                topic_id=topic_id_for(agent.agent_id, title),
                agent_id=agent.agent_id,
                title=title,
                question=f"What do the manufacturer and independent sources recommend for getting the best and safest results from a {name} in a Home Assistant setup?",
                queries=[f"{name} recommended settings", f"{name} common problems troubleshooting", f"{name} Home Assistant integration tips"],
                rationale="This exact model is installed in the home.",
                origin="device_seed",
            )
        )
        if len(topics) >= limit:
            break
    return topics


# ---------------------------------------------------------------------------------------------- prompts
def _persona(agent: AgentSpec) -> str:
    goals = "; ".join(agent.goals[:5])
    return f"You are the {agent.name}: {agent.specialty}." + (f" Your goals: {goals}." if goals else "")


def build_planning_prompts(agent: AgentSpec, profile: dict[str, Any], researched: list[str], count: int, site_context: str) -> tuple[str, str]:
    system = (
        f"{_persona(agent)}\n"
        f"Plan a research agenda: propose up to {count} research questions that a real specialist in this field would investigate "
        "for THIS home. Each question must (1) be specific to the equipment and data in `home_profile`, "
        "(2) be answerable from reputable public sources such as manufacturer documentation, standards bodies, government or energy agencies, "
        "universities and Home Assistant documentation, and (3) lead to something concrete: a setting, a schedule, an automation idea, "
        "a maintenance task or a purchase decision. Prefer questions a specialist would ask that a generalist would not; "
        "avoid textbook basics and avoid anything similar to `already_researched`. "
        "Return JSON: {\"topics\": [{\"title\": short, \"question\": one sentence, \"search_queries\": [2-3 web search queries], "
        "\"rationale\": why this matters for this home}]}."
    )
    user = dumps({"site_context": site_context[:600], "already_researched": researched[:60], "home_profile": profile})
    return system, user


_FINDING_FORMAT = (
    "{\"findings\": [{\"title\": short, \"summary\": at most 120 words, \"key_points\": [concrete facts, with numbers and units when you are confident of them], "
    "\"how_to_apply\": concrete steps in Home Assistant terms (which kinds of entities, settings, helpers or automations, relevant to `home_profile`), "
    "\"caveats\": limits and conditions where this does not apply, \"confidence\": \"high\"|\"medium\"|\"low\" (be honest), "
    "\"references\": [names of standards, guidelines or manufacturer documents you are drawing on - names only, never URLs, and only if you are sure they exist]}]}"
)


def build_research_prompts(agent: AgentSpec, topic: ResearchTopic, profile: dict[str, Any], web: bool = False) -> tuple[str, str]:
    if web:
        system = (
            f"{_persona(agent)}\n"
            "Research the given topic using web search and report what reliable sources say. Return ONLY JSON: "
            + _FINDING_FORMAT
            + " with 1 to 3 findings. Rules: state only what your sources support; never invent figures, standards or product behaviour; "
            "if sources disagree say so; prefer manufacturer, standards, government and academic sources; "
            "if you cannot find reliable information return {\"findings\": []}."
        )
    else:
        system = (
            f"{_persona(agent)}\n"
            "Answer as the expert you are, from your own knowledge: explain what a specialist would tell this homeowner about the given topic. "
            "Return ONLY JSON: " + _FINDING_FORMAT + " with 1 to 3 findings. Rules: be concrete and practical; give typical numbers only when "
            "you are confident of them and say when something depends on the specific model or installation; never invent product behaviour or "
            "standards; if you are not sure, say so in `caveats` and lower `confidence`; if you know nothing useful return {\"findings\": []}."
        )
    user = dumps(
        {
            "home_profile": profile,
            "topic": {"title": topic.title, "question": topic.question, "suggested_queries": topic.queries},
        }
    )
    return system, user
