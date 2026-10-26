"""Research agenda: grounded web research, citation handling, topic planning, approval flow and prompt injection."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

from ha_ai_brain.adapters.ha_websocket_rest import HomeAssistantAdapter
from ha_ai_brain.adapters.llm_litellm import LiteLLMAdapter, parse_grounded_response
from ha_ai_brain.api.app import build_orchestrator, create_app
from ha_ai_brain.application.research_agenda import ResearchAgenda, approved_knowledge_for
from ha_ai_brain.config import BrainSettings
from ha_ai_brain.domain.models import AgentSpec
from ha_ai_brain.domain.research import (
    ResearchTopic,
    capability_profile,
    device_seed_topics,
    is_similar_title,
    parse_findings,
    parse_topics,
    source_trust,
    valid_http_url,
)
from ha_ai_brain.ports.llm import LLMProviderPort, ResearchResult

UTC = timezone.utc

AGENT = AgentSpec(
    agent_id="climate_thermal_agent", name="Climate Agent", specialty="Building physics",
    description="d", monitored_domains=["sensor", "climate"], controllable_domains=["climate", "notify", "automation"],
    goals=["g1"],
)
INVENTORY = [
    {"manufacturer": "Acme", "model": "X-100", "integrations": ["acme"], "domains": ["climate", "sensor"], "device_count": 1, "entity_count": 4},
    {"manufacturer": "Acme", "model": "Lamp", "integrations": ["acme"], "domains": ["light"], "device_count": 3, "entity_count": 3},
    {"manufacturer": "", "model": "NoMaker", "integrations": [], "domains": ["climate"], "device_count": 1, "entity_count": 1},
]

GROUNDED_RESPONSE = {
    "candidates": [
        {
            "content": {"parts": [{"text": json.dumps({"findings": [{"title": "T", "summary": "S"}]})}]},
            "groundingMetadata": {
                "webSearchQueries": ["q1", "q2"],
                "groundingChunks": [
                    {"web": {"uri": "https://docs.example.org/a", "title": "docs.example.org"}},
                    {"web": {"uri": "https://docs.example.org/a", "title": "dup"}},
                    {"web": {"uri": "javascript:alert(1)", "title": "bad"}},
                    {"web": {"uri": "https://www.reddit.com/r/x", "title": "reddit.com"}},
                ],
                "groundingSupports": [{"segment": {"startIndex": 0, "endIndex": 20}}],
            },
        }
    ],
    "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 50},
}


class ScriptedLLM(LLMProviderPort):
    """LLM stand-in: plans topics, answers from 'knowledge' and optionally from grounded web search, with no network."""

    def __init__(self, searchable: bool = False, grounded: bool = True, available: bool = True, knows: bool = True) -> None:
        self.searchable = searchable
        self.grounded = grounded
        self.available = available
        self.knows = knows
        self.planned = 0
        self.researched: list[str] = []
        self.web_calls = 0

    @property
    def is_available(self) -> bool:
        return self.available

    @property
    def supports_web_search(self) -> bool:
        return self.searchable

    async def generate_json(self, system_prompt: str, user_prompt: str, use_fast_tier: bool = False, context_hint: dict[str, Any] | None = None) -> dict[str, Any]:
        task = (context_hint or {}).get("task")
        if task == "plan_research_topics":
            self.planned += 1
            n = self.planned
            return {"topics": [{"title": f"Planned topic zeta{n}k about unique subject qx{n}z", "question": "q", "search_queries": ["a", "b"], "rationale": "r"}]}
        if task == "knowledge_research":
            topic = json.loads(user_prompt)["topic"]["title"]
            self.researched.append(topic)
            if not self.knows:
                return {}
            return {"findings": [{"title": f"Advice for {topic}", "summary": "Practical expert advice.", "key_points": ["p1"], "how_to_apply": "Do x", "confidence": "medium", "references": ["A well known guideline"]}]}
        return {}

    async def generate_research(self, system_prompt: str, user_prompt: str, context_hint: dict[str, Any] | None = None) -> ResearchResult:
        self.web_calls += 1
        topic = json.loads(user_prompt)["topic"]["title"]
        self.researched.append(topic)
        if not self.grounded:
            return ResearchResult()
        return ResearchResult(
            grounded=True,
            parsed={"findings": [{"title": f"Finding for {topic}", "summary": "Something useful and sourced.", "key_points": ["p1", "p2"], "how_to_apply": "Do x", "confidence": "high"}]},
            citations=[{"url": "https://docs.example.org/a", "title": "Docs"}],
            coverage=0.8,
        )


class TestGroundedParsing(unittest.TestCase):
    def test_citations_are_deduplicated_validated_and_coverage_measured(self) -> None:
        res = parse_grounded_response(GROUNDED_RESPONSE)
        self.assertTrue(res.grounded)
        self.assertEqual([c["url"] for c in res.citations], ["https://docs.example.org/a", "https://www.reddit.com/r/x"])
        self.assertEqual(res.queries, ["q1", "q2"])
        self.assertEqual(res.parsed["findings"][0]["title"], "T")
        self.assertGreater(res.coverage, 0.1)
        self.assertFalse(parse_grounded_response({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}).grounded)
        self.assertFalse(parse_grounded_response({}).grounded)


class TestGeminiGroundedCall(unittest.IsolatedAsyncioTestCase):
    async def test_request_shape_privacy_and_usage_accounting(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            captured["url"] = str(request.url)
            return httpx.Response(200, json=GROUNDED_RESPONSE)

        real_client = httpx.AsyncClient
        adapter = LiteLLMAdapter(model="gemini/gemini-3.8-flash", fast_model="gemini/gemini-3.5-flash", api_key="AIzaFAKE")
        self.assertTrue(adapter.supports_web_search)
        with patch("httpx.AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
            res = await adapter.generate_research("persona", json.dumps({"who": "person.jane at jane@example.com"}), {"agent_id": "a"})
        body = captured["body"]
        self.assertIn("gemini-3.8-flash:generateContent", captured["url"])
        self.assertEqual(body["tools"], [{"google_search": {}}])
        self.assertNotIn("responseMimeType", body["generationConfig"])
        sent = body["contents"][0]["parts"][0]["text"]
        self.assertNotIn("jane", sent)
        self.assertTrue(res.grounded)
        snap = await adapter.get_quota_status()
        self.assertEqual((snap.prompt_tokens_session, snap.completion_tokens_session), (100, 50))

    def test_only_gemini_without_proxy_supports_search(self) -> None:
        self.assertFalse(LiteLLMAdapter("openai/gpt-4o", "openai/gpt-4o-mini", api_key="sk-x").supports_web_search)
        self.assertFalse(LiteLLMAdapter("gemini/g", "gemini/g", api_key="").supports_web_search)
        self.assertFalse(LiteLLMAdapter("gemini/g", "gemini/g", api_key="k", managed_proxy_url="http://p").supports_web_search)


class TestResearchDomain(unittest.TestCase):
    def test_trust_urls_and_title_similarity(self) -> None:
        self.assertEqual(source_trust("https://www.reddit.com/r/a"), "low")
        self.assertEqual(source_trust("https://old.reddit.com/r/a"), "low")
        self.assertEqual(source_trust("https://docs.example.org/x"), "normal")
        self.assertEqual(source_trust("https://notreddit.com/x"), "normal")
        self.assertTrue(valid_http_url("https://a.b/c"))
        self.assertFalse(valid_http_url("javascript:alert(1)"))
        self.assertTrue(is_similar_title("Heating setback savings and schedules", "Schedules and savings for heating setback"))
        self.assertFalse(is_similar_title("Boiler efficiency", "Window condensation"))

    def test_model_knowledge_findings_need_no_sources(self) -> None:
        topic = ResearchTopic(topic_id="t", agent_id="a", title="Topic")
        raw = {"findings": [{"title": "F", "summary": "S", "confidence": "high", "references": ["Some guideline", "Another"]}, {"summary": ""}, "junk"]}
        items = parse_findings(raw, topic)
        self.assertEqual([(i.basis, i.confidence, i.status, i.sources) for i in items], [("model_knowledge", "high", "proposed", [])])
        self.assertEqual(items[0].references, ["Some guideline", "Another"])
        self.assertEqual(parse_findings({"findings": [{"summary": "x", "confidence": "bogus"}]}, topic)[0].confidence, "medium")
        self.assertEqual(parse_findings({}, topic), [])

    def test_web_findings_need_sources_and_confidence_follows_evidence(self) -> None:
        topic = ResearchTopic(topic_id="t", agent_id="a", title="Topic")
        raw = {"findings": [{"title": "F", "summary": "S", "confidence": "high"}]}
        cite = [{"url": "https://docs.example.org/a", "title": "d"}]
        self.assertEqual(parse_findings(raw, topic, [], 0.9, grounded=True), [])  # claims to be web research but has no sources
        good = parse_findings(raw, topic, cite, 0.9, grounded=True)
        self.assertEqual([(i.basis, i.confidence) for i in good], [("web_sources", "high")])
        self.assertEqual(parse_findings(raw, topic, cite, 0.2, grounded=True)[0].confidence, "low")
        self.assertEqual(parse_findings(raw, topic, cite, 0.5, grounded=True)[0].confidence, "medium")
        self.assertEqual(parse_findings(raw, topic, [{"url": "https://www.reddit.com/r/a"}], 0.9, grounded=True)[0].confidence, "low")
        self.assertEqual(parse_findings(raw, topic, [{"url": "javascript:x"}], 0.9, grounded=True), [])

    def test_device_seed_topics_use_the_actual_inventory_generically(self) -> None:
        seeds = device_seed_topics(INVENTORY, AGENT)
        self.assertEqual([t.title.split(":")[0] for t in seeds], ["Acme X-100"])  # lamp is outside this agent's field, no maker -> skipped
        self.assertIn("Acme X-100 recommended settings", seeds[0].queries)
        self.assertEqual(device_seed_topics(INVENTORY, AGENT, known=[seeds[0].title]), [])

    def test_parse_topics_is_defensive(self) -> None:
        topics = parse_topics({"topics": [{"title": "A real topic", "search_queries": "single"}, {"nope": 1}, "x"]}, "agent")
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0].queries, ["single"])
        self.assertEqual(parse_topics({}, "agent"), [])

    def test_inventory_builder_groups_devices_by_model(self) -> None:
        devices = [
            {"id": "d1", "manufacturer": "Acme", "model": "X-100"},
            {"id": "d2", "manufacturer": "Acme", "model": "X-100"},
            {"id": "d3", "manufacturer": "Hub", "model": "Svc", "entry_type": "service"},
            {"id": "d4", "manufacturer": "Off", "model": "Disabled", "disabled_by": "user"},
            {"id": "d5", "manufacturer": None, "model": None},
        ]
        entities = [
            {"entity_id": "climate.a", "device_id": "d1", "platform": "acme"},
            {"entity_id": "sensor.a", "device_id": "d1", "platform": "acme"},
            {"entity_id": "climate.b", "device_id": "d2", "platform": "acme"},
            {"entity_id": "sensor.s", "device_id": "d3", "platform": "hub"},
            {"entity_id": "sensor.d", "device_id": "d4", "platform": "off"},
            {"entity_id": "sensor.n", "device_id": "d5", "platform": "x"},
            {"entity_id": "sensor.off", "device_id": "d1", "platform": "acme", "disabled_by": "user"},
        ]
        inv = HomeAssistantAdapter._build_inventory(devices, entities)
        self.assertEqual(len(inv), 1)
        self.assertEqual((inv[0]["manufacturer"], inv[0]["device_count"], inv[0]["entity_count"], inv[0]["domains"]), ("Acme", 2, 3, ["climate", "sensor"]))


class TestResearchAgenda(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.orch = build_orchestrator(BrainSettings(use_simulator=True, db_path=str(Path(self._tmp.name) / "t.db"), custom_agents_dir=self._tmp.name, timezone="UTC"))

        async def inventory() -> list[dict[str, Any]]:
            return INVENTORY

        self.orch.smart_home.get_device_inventory = inventory
        self.llm = ScriptedLLM()
        self.agenda = ResearchAgenda(self.orch.settings, self.llm, self.orch.memory, self.orch.smart_home, self.orch.registry, self._ok)
        self.budget_left = True

    async def _ok(self) -> bool:
        return self.budget_left

    async def asyncTearDown(self) -> None:
        self.orch.memory._conn.close()
        self.orch.telemetry.close()
        self._tmp.cleanup()

    async def test_default_research_uses_any_provider_knowledge_and_never_repeats_topics(self) -> None:
        self.assertFalse(self.llm.supports_web_search)  # a provider without any search feature
        summary = await self.agenda.run(["climate_thermal_agent"])
        self.assertEqual((summary["status"], summary["topics_researched"], summary["findings"]), ("completed", 1, 1))
        titles = [t.title for t in await self.agenda.store.topics()]
        self.assertTrue(any(t.startswith("Acme X-100") for t in titles))  # concrete equipment from the registry
        self.assertTrue(any(t.startswith("Planned topic") for t in titles))  # the agent's own planning
        item = (await self.agenda.store.items(status="proposed"))[0]
        self.assertEqual((item.basis, item.sources, item.references), ("model_knowledge", [], ["A well known guideline"]))
        self.assertEqual(self.llm.web_calls, 0)

        await self.agenda.run(["climate_thermal_agent"])
        researched = list(self.llm.researched)
        self.assertEqual(len(researched), len(set(researched)))
        self.assertEqual(len(researched), 2)

    async def test_unavailable_empty_and_budget_cases(self) -> None:
        self.llm.knows = False
        summary = await self.agenda.run(["climate_thermal_agent"])
        self.assertEqual((summary["findings"], summary["skipped"]), (0, 1))
        self.assertEqual(await self.agenda.store.items(), [])
        self.assertEqual(len([t for t in await self.agenda.store.topics() if t.status == "skipped"]), 1)

        self.llm.available = False
        self.assertEqual((await self.agenda.run())["status"], "unavailable")
        self.llm.available = True
        self.budget_left = False
        self.assertEqual((await self.agenda.run())["status"], "stopped_budget")

    async def test_optional_web_mode_adds_cited_sources_and_falls_back_to_knowledge(self) -> None:
        self.llm.searchable = True
        self.assertEqual(self.llm.web_calls, 0)
        await self.agenda.run(["climate_thermal_agent"])  # web switch is off by default: still the normal path
        self.assertEqual(self.llm.web_calls, 0)

        self.orch.settings.research_web_search = True
        self.orch.settings.research_topics_per_agent = 1
        await self.agenda.run(["climate_thermal_agent"])
        web_items = [i for i in await self.agenda.store.items() if i.basis == "web_sources"]
        self.assertEqual(len(web_items), 1)
        self.assertEqual(web_items[0].sources[0].url, "https://docs.example.org/a")
        self.assertEqual(self.llm.web_calls, 1)

        self.llm.grounded = False  # the search returned nothing: the AI's own knowledge still answers
        await self.agenda.run(["climate_thermal_agent"])
        self.assertEqual(self.llm.web_calls, 2)
        self.assertEqual(len([i for i in await self.agenda.store.items() if i.basis == "model_knowledge"]), 2)

        self.llm.searchable = False  # switch on but provider cannot search -> normal research
        await self.agenda.run(["climate_thermal_agent"])
        self.assertEqual(self.llm.web_calls, 2)

    async def test_approval_flow_feeds_only_the_owning_agent_and_rejection_blocks_repeats(self) -> None:
        await self.agenda.run(["climate_thermal_agent"])
        item = (await self.agenda.store.items(status="proposed"))[0]
        self.assertEqual(await approved_knowledge_for(self.orch.memory, "climate_thermal_agent"), [])  # not before approval
        await self.agenda.decide(item.item_id, "approve")
        knowledge = await approved_knowledge_for(self.orch.memory, "climate_thermal_agent")
        self.assertEqual(len(knowledge), 1)
        self.assertEqual((knowledge[0]["source"], knowledge[0]["origin"]), ("A well known guideline", "approved AI expertise"))
        self.assertEqual(await approved_knowledge_for(self.orch.memory, "security_safety_agent"), [])

        # the approved finding reaches the agent's prompt context
        graph = self.orch.agent_graph
        out = await graph._corroborate_context_node({"agent_spec": self.orch.registry.get_agent("climate_thermal_agent"), "mode": "realtime_stream", "corroborated_states": {}})
        self.assertIn(f"research:{item.item_id}", [k["id"] for k in out["reference_knowledge"]])

        await self.agenda.decide(item.item_id, "reject")
        self.assertEqual(await approved_knowledge_for(self.orch.memory, "climate_thermal_agent"), [])
        self.assertIn(item.title, await self.agenda.store.known_titles())  # rejected subjects are never researched again
        with self.assertRaises(ValueError):
            await self.agenda.decide(item.item_id, "maybe")
        self.assertIsNone(await self.agenda.decide("missing", "approve"))

    async def test_capability_profile_contains_no_names_only_kinds_of_things(self) -> None:
        states = await self.orch.smart_home.get_all_states()
        profile = capability_profile(states, INVENTORY, AGENT)
        flat = json.dumps(profile)
        self.assertIn("Acme", flat)
        self.assertIn("humidity", profile["device_classes_present"])
        self.assertNotIn("master_bedroom", flat)  # area / room names are not sent

    async def test_first_run_is_deferred_by_a_day_so_an_upgrade_never_spends_tokens_immediately(self) -> None:
        self.orch.llm = self.llm
        self.orch.research.llm = self.llm
        self.assertFalse(self.llm.supports_web_search)  # no search needed: any configured provider can research
        self.assertIsNone(await self.orch.research.last_run())
        await self.orch._maybe_start_research()
        nxt = await self.orch.research.next_run_at()
        assert nxt is not None
        delta = nxt - datetime.now(UTC)
        self.assertTrue(timedelta(hours=23) < delta < timedelta(hours=25), delta)
        self.assertFalse(await self.orch.research.due(datetime.now(UTC)))
        self.assertTrue(await self.orch.research.due(datetime.now(UTC) + timedelta(days=2)))
        self.assertEqual(self.llm.researched, [])


class TestResearchApi(unittest.IsolatedAsyncioTestCase):
    async def test_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(BrainSettings(use_simulator=True, db_path=str(Path(tmp) / "t.db"), custom_agents_dir=tmp, timezone="UTC"))
            orch = app.state.orchestrator
            llm = ScriptedLLM()
            orch.llm = llm
            orch.research.llm = llm
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
                data = (await client.get("/api/research")).json()
                for key in ("enabled", "can_research", "supports_web_search", "web_search_enabled", "proposed", "approved", "backlog", "next_run", "agent_names"):
                    self.assertIn(key, data)
                await orch.research.run(["climate_thermal_agent"])
                data = (await client.get("/api/research")).json()
                self.assertEqual(len(data["proposed"]), 1)
                self.assertEqual((await client.get("/api/status")).json()["research_pending_review"], 1)
                item_id = data["proposed"][0]["item_id"]
                self.assertEqual((await client.post(f"/api/research/items/{item_id}/decision", json={"decision": "bogus"})).status_code, 422)
                self.assertEqual((await client.post(f"/api/research/items/{item_id}/decision", json={"decision": "approve"})).json()["status"], "approved")
                self.assertEqual(len((await client.get("/api/research")).json()["approved"]), 1)
                self.assertEqual((await client.delete(f"/api/research/items/{item_id}")).status_code, 200)
                self.assertEqual((await client.delete(f"/api/research/items/{item_id}")).status_code, 404)
                self.assertTrue((await client.get("/api/research")).json()["can_research"])
                llm.available = False
                self.assertEqual((await client.post("/api/research/run")).json()["status"], "unavailable")
                self.assertFalse((await client.get("/api/research")).json()["can_research"])
                settings = await client.post("/api/settings", json={"research_enabled": False, "research_interval_days": 14})
                self.assertEqual(settings.status_code, 200)
                self.assertEqual((await client.get("/api/status")).json()["settings"]["research_interval_days"], 14)
            orch.memory._conn.close()
            orch.telemetry.close()


if __name__ == "__main__":
    unittest.main()
