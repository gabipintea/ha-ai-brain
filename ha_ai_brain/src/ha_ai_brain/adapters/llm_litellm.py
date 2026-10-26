"""Production Multi-Provider LLM Adapter (Gemini AI Studio / Vertex Express + LiteLLM)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ha_ai_brain.domain.privacy import PrivacyScrubber
from ha_ai_brain.adapters.quota_monitor import BaseQuotaMonitorAdapter, create_quota_monitor_for_model
from ha_ai_brain.ports.billing import LicensePort
from ha_ai_brain.ports.llm import REASONING_DEFAULT, REASONING_LOW, REASONING_OFF, LLMProviderPort, LLMQuotaAndUsageSnapshot, ResearchResult

logger = logging.getLogger(__name__)

LLM_REQUEST_TIMEOUT_SECONDS = 90.0

# Gemini's native transport can bound hidden "thinking" tokens; the generic `reasoning` hint maps to a budget here.
# Other providers keep their own defaults (their reported completion tokens already include any reasoning).
GEMINI_THINKING_BUDGET = {REASONING_OFF: 0, REASONING_LOW: 256, REASONING_DEFAULT: 1024}


def _output_tokens(usage_meta: dict[str, Any]) -> int:
    """Billable output = visible answer + hidden thinking tokens (the latter used to be missing from spend and budgets)."""
    return int(usage_meta.get("candidatesTokenCount", 0)) + int(usage_meta.get("thoughtsTokenCount", 0))


def parse_grounded_response(data: dict[str, Any]) -> ResearchResult:
    """Extract answer text, cited web sources and how much of the answer they back from a grounded Gemini response."""
    candidates = data.get("candidates") or []
    if not candidates:
        return ResearchResult()
    cand = candidates[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict) and not p.get("thought"))
    meta = cand.get("groundingMetadata") or {}

    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    for chunk in meta.get("groundingChunks") or []:
        web = chunk.get("web") if isinstance(chunk, dict) else None
        url = str((web or {}).get("uri") or "")
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            citations.append({"url": url, "title": str((web or {}).get("title") or "")})

    covered: set[int] = set()
    for support in meta.get("groundingSupports") or []:
        seg = support.get("segment") or {}
        covered.update(range(int(seg.get("startIndex", 0) or 0), int(seg.get("endIndex", 0) or 0)))
    total = max(1, len(text.encode("utf-8")))
    return ResearchResult(
        grounded=bool(citations),
        text=text,
        parsed=LiteLLMAdapter._parse_json_safely(text),
        citations=citations[:10],
        coverage=min(1.0, len(covered) / total),
        queries=[str(q) for q in (meta.get("webSearchQueries") or [])][:8],
    )


class LiteLLMAdapter(LLMProviderPort):
    """
    Pure LLM reasoning adapter with zero hardcoded domain scripts or pre-baked signals.
    All hypotheses, derived-signal Python scripts, and action proposals come directly
    from the configured LLM analyzing the Home Assistant entity schema and telemetry.

    Supports:
    - Google Gemini via Vertex AI Express Mode (`AQ....` keys) & Google AI Studio (`AIza...` keys)
    - OpenAI, Anthropic, OpenRouter, Ollama, and Managed Proxy via LiteLLM
    """

    def __init__(
        self,
        model: str,
        fast_model: str,
        api_key: str = "",
        managed_proxy_url: str = "",
        license_port: LicensePort | None = None,
        fallback_models: list[str] | None = None,
        fallback_policy: str = "auto",
        privacy_scrub: bool = True,
    ) -> None:
        import asyncio

        self.privacy_scrub = privacy_scrub
        self.model = model
        self.fast_model = fast_model
        self._fallback_models = list(fallback_models or [])
        self.api_key = api_key.strip()
        self.managed_proxy_url = managed_proxy_url
        self.license_port = license_port
        self.quota_monitor: BaseQuotaMonitorAdapter = create_quota_monitor_for_model(
            model=model,
            api_key=self.api_key,
            fallback_models=fallback_models,
            fallback_policy=fallback_policy,
        )
        self._gemini_lock = asyncio.Lock()

    async def get_quota_status(self) -> LLMQuotaAndUsageSnapshot:
        return await self.quota_monitor.get_quota_and_usage_snapshot()

    def set_fallback_policy(self, policy: str) -> None:
        self.quota_monitor.set_fallback_policy(policy)

    def reconfigure(
        self,
        model: str | None = None,
        fast_model: str | None = None,
        api_key: str | None = None,
        fallback_policy: str | None = None,
    ) -> None:
        """Dynamically reconfigure LLM model, fast model, and API key at runtime."""
        if model:
            self.model = model.strip()
        if fast_model:
            self.fast_model = fast_model.strip()
        if api_key is not None:
            self.api_key = api_key.strip()
        previous = self.quota_monitor._snapshot
        self.quota_monitor = create_quota_monitor_for_model(
            model=self.model,
            api_key=self.api_key,
            fallback_models=self._fallback_models,
            fallback_policy=fallback_policy or previous.fallback_policy or "auto",
        )
        # Reconfiguring must not reset the session usage counters shown in the dashboard.
        for counter in (
            "requests_succeeded_session",
            "requests_rate_limited_session",
            "prompt_tokens_session",
            "completion_tokens_session",
            "estimated_spend_usd_session",
        ):
            setattr(self.quota_monitor._snapshot, counter, getattr(previous, counter))
        logger.info("LiteLLMAdapter reconfigured to model=%s, fast_model=%s (has_key=%s)", self.model, self.fast_model, bool(self.api_key))

    def approve_fallback_model(self, model: str | None = None) -> str | None:
        return self.quota_monitor.approve_fallback_model(model)

    def reject_fallback_and_wait_for_primary(self) -> None:
        self.quota_monitor.reject_fallback_and_wait_for_primary()

    def _format_litellm_model(self, model: str) -> str:
        provider = getattr(self.quota_monitor, "_snapshot", None) and self.quota_monitor._snapshot.provider or ""
        if provider == "openrouter":
            return model if model.startswith("openrouter/") else f"openrouter/{model}"
        if provider == "anthropic":
            if model.startswith("anthropic/"):
                return model
            if "/" not in model:
                return f"anthropic/{model}"
            return model
        if provider == "openai":
            if model.startswith("openai/"):
                return model
            if "/" not in model:
                return f"openai/{model}"
            return model
        if provider in ("ollama", "ollama_local"):
            return model if model.startswith("ollama/") else f"ollama/{model}"
        return model

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        use_fast_tier: bool = False,
        context_hint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke the configured LLM; personal identifiers are aliased on the way out and restored on the way back."""
        if not self.privacy_scrub:
            return await self._generate_json_raw(system_prompt, user_prompt, use_fast_tier, context_hint)
        scrubber = PrivacyScrubber()
        result = await self._generate_json_raw(
            scrubber.scrub_text(system_prompt),
            scrubber.scrub_prompt(user_prompt),
            use_fast_tier,
            context_hint,
        )
        restored = scrubber.restore(result)
        return restored if isinstance(restored, dict) else {}

    async def _generate_json_raw(
        self,
        system_prompt: str,
        user_prompt: str,
        use_fast_tier: bool = False,
        context_hint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke the configured LLM and parse its structured JSON response."""
        if not (self.api_key or self.managed_proxy_url or self.model.startswith("ollama/")):
            logger.warning(
                "LiteLLMAdapter: No BRAIN_LLM_API_KEY or local ollama/* model configured. "
                "Configure an LLM API key so agents can analyze your Home Assistant entities."
            )
            return {}

        chosen_model = self.fast_model if use_fast_tier else self.model
        task_name = str((context_hint or {}).get("task", "reasoning"))
        agent_id = str((context_hint or {}).get("agent_id", "climate_thermal_agent"))

        # Native handling for Google Gemini (supports both `AQ.` Vertex Express keys and `AIza` AI Studio keys)
        if chosen_model.startswith(("gemini/", "vertex_ai/")) or self.api_key.startswith(("AQ.", "AIza")):
            return await self._call_google_gemini(
                chosen_model=chosen_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                agent_id=agent_id,
                task_name=task_name,
                reasoning=str((context_hint or {}).get("reasoning", REASONING_DEFAULT)),
            )

        available_models = self.quota_monitor.select_execution_candidates(chosen_model)
        if not available_models:
            snap = await self.quota_monitor.get_quota_and_usage_snapshot()
            if snap.awaiting_fallback_confirmation:
                logger.warning(
                    "[LITELLM] Pausing %s — primary model %s is in cooldown (%ds remaining) and fallback_policy='confirm' is waiting for user approval to switch to %s.",
                    task_name,
                    snap.primary_model,
                    snap.primary_cooldown_seconds_remaining,
                    snap.available_fallback_models,
                )
            else:
                logger.warning(
                    "[LITELLM] Skipping %s (%s) — no eligible AI models available (cooldown active for %ds more, policy=%s).",
                    task_name,
                    chosen_model,
                    snap.cooldown_seconds_remaining,
                    snap.fallback_policy,
                )
            return {}

        import litellm

        last_err = ""
        for m_id in available_models:
            litellm_model = self._format_litellm_model(m_id)
            kwargs: dict[str, Any] = {
                "model": litellm_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
                "timeout": LLM_REQUEST_TIMEOUT_SECONDS,
                "drop_params": True,
            }
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.managed_proxy_url:
                kwargs["api_base"] = self.managed_proxy_url

            try:
                resp = await litellm.acompletion(**kwargs)
            except Exception as exc:
                status_code = int(getattr(exc, "status_code", 429 if "429" in str(exc) else 500))
                raw_hdrs = getattr(exc, "llm_provider_response_headers", None) or getattr(exc, "headers", None)
                headers_dict = dict(raw_hdrs) if isinstance(raw_hdrs, dict) else {}
                snap = self.quota_monitor.record_quota_or_rate_limit_error(
                    model=m_id,
                    status_code=status_code,
                    error_body=str(exc),
                    headers=headers_dict,
                )
                last_err = f"{litellm_model} -> {status_code}: {exc}"
                logger.warning(
                    "[LITELLM %s] Call failed on %s (status=%d, cooldown=%ds): %s",
                    litellm_model,
                    task_name,
                    status_code,
                    snap.cooldown_seconds_remaining,
                    exc,
                )
                if status_code in (401, 403):
                    break
                continue

            usage = getattr(resp, "usage", None)
            p_tok = int(getattr(usage, "prompt_tokens", 0)) if usage else 0
            c_tok = int(getattr(usage, "completion_tokens", 0)) if usage else 0
            resp_hdrs = getattr(resp, "_response_headers", None)
            headers_dict = dict(resp_hdrs) if isinstance(resp_hdrs, dict) else {}
            self.quota_monitor.record_success(
                model=m_id,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
                headers=headers_dict,
            )
            if usage and self.license_port:
                await self.license_port.record_token_usage(
                    agent_id=agent_id,
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                )
            choices = getattr(resp, "choices", []) or []
            content = choices[0].message.content if choices else ""
            parsed = self._parse_json_safely(content or "")
            logger.info(
                "[LITELLM %s] task=%s tokens=%d (prompt=%d, completion=%d) keys=%s",
                litellm_model,
                task_name,
                p_tok + c_tok,
                p_tok,
                c_tok,
                list(parsed.keys()),
            )
            return parsed

        logger.error("LiteLLM call failed on all candidate models for %s: %s", chosen_model, last_err)
        return {}

    @property
    def is_available(self) -> bool:
        return bool(self.api_key or self.managed_proxy_url or self.model.startswith("ollama/"))

    @property
    def supports_web_search(self) -> bool:
        """Optional extra: Google Search grounding (Gemini) for cited, deeper research."""
        return not self.managed_proxy_url and bool(self.api_key) and (
            self.model.startswith(("gemini/", "vertex_ai/")) or self.api_key.startswith(("AQ.", "AIza"))
        )

    async def generate_research(
        self,
        system_prompt: str,
        user_prompt: str,
        context_hint: dict[str, Any] | None = None,
    ) -> ResearchResult:
        if not self.supports_web_search:
            return ResearchResult()
        scrubber = PrivacyScrubber() if self.privacy_scrub else None
        system = scrubber.scrub_text(system_prompt) if scrubber else system_prompt
        user = scrubber.scrub_prompt(user_prompt) if scrubber else user_prompt
        agent_id = str((context_hint or {}).get("agent_id", "research"))
        result = await self._call_gemini_grounded(self.model.split("/", 1)[-1], system, user, agent_id)
        if scrubber and result.parsed:
            restored = scrubber.restore(result.parsed)
            result.parsed = restored if isinstance(restored, dict) else {}
        return result

    async def _call_gemini_grounded(self, model_id: str, system_prompt: str, user_prompt: str, agent_id: str) -> ResearchResult:
        import asyncio
        import httpx

        # Search grounding cannot be combined with a forced JSON mime type, so JSON is requested in the prompt instead.
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0.2},
        }
        candidates = self.quota_monitor.select_execution_candidates(model_id)
        if not candidates:
            logger.warning("[GEMINI research] skipped: no eligible model (quota cooldown).")
            return ResearchResult()
        async with httpx.AsyncClient(timeout=150.0) as client:
            for m_id in candidates:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_id}:generateContent"
                for attempt in range(2):
                    try:
                        resp = await client.post(url, headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"}, json=payload)
                    except httpx.HTTPError as exc:
                        logger.warning("[GEMINI research %s] HTTP error: %s", m_id, exc)
                        break
                    if resp.status_code == 200:
                        data = resp.json()
                        usage = data.get("usageMetadata", {})
                        p_tok, c_tok = int(usage.get("promptTokenCount", 0)), _output_tokens(usage)
                        self.quota_monitor.record_success(model=m_id, prompt_tokens=p_tok, completion_tokens=c_tok, headers=dict(resp.headers))
                        if self.license_port:
                            await self.license_port.record_token_usage(agent_id=agent_id, prompt_tokens=p_tok, completion_tokens=c_tok)
                        result = parse_grounded_response(data)
                        logger.info(
                            "[GEMINI research %s] tokens=%d sources=%d coverage=%.0f%%",
                            m_id, p_tok + c_tok, len(result.citations), result.coverage * 100,
                        )
                        return result
                    if resp.status_code == 429:
                        self.quota_monitor.record_quota_or_rate_limit_error(model=m_id, status_code=429, error_body=resp.text, headers=dict(resp.headers))
                        break
                    if resp.status_code == 503 and attempt == 0:
                        await asyncio.sleep(3.5)
                        continue
                    logger.warning("[GEMINI research %s] %s: %s", m_id, resp.status_code, resp.text[:200])
                    if resp.status_code in (401, 403, 400):
                        return ResearchResult()
                    break
        return ResearchResult()

    async def _call_google_gemini(
        self,
        chosen_model: str,
        system_prompt: str,
        user_prompt: str,
        agent_id: str,
        task_name: str,
        reasoning: str = REASONING_DEFAULT,
    ) -> dict[str, Any]:
        import asyncio
        import httpx

        model_id = chosen_model.split("/", 1)[-1]

        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingBudget": GEMINI_THINKING_BUDGET.get(reasoning, GEMINI_THINKING_BUDGET[REASONING_DEFAULT])},
            },
        }

        last_err = ""
        async with self._gemini_lock:
            available_models = self.quota_monitor.select_execution_candidates(model_id)
            if not available_models:
                snap = await self.quota_monitor.get_quota_and_usage_snapshot()
                if snap.awaiting_fallback_confirmation:
                    logger.warning(
                        "[GEMINI] Pausing %s — primary model %s is in cooldown (%ds remaining) and fallback_policy='confirm' is waiting for user approval to switch to %s.",
                        task_name,
                        snap.primary_model,
                        snap.primary_cooldown_seconds_remaining,
                        snap.available_fallback_models,
                    )
                else:
                    logger.warning(
                        "[GEMINI] Skipping %s — no eligible Gemini models available (cooldown=%ds remaining, policy=%s).",
                        task_name,
                        snap.cooldown_seconds_remaining,
                        snap.fallback_policy,
                    )
                return {}

            async with httpx.AsyncClient(timeout=LLM_REQUEST_TIMEOUT_SECONDS) as client:
                for m_id in available_models:
                    aistudio_url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_id}:generateContent"
                    resp = None
                    for attempt in range(2):
                        try:
                            resp = await client.post(
                                aistudio_url,
                                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                                json=payload,
                            )
                        except httpx.HTTPError as exc:
                            last_err = f"{m_id} -> HTTPError({type(exc).__name__}): {exc}"
                            logger.warning("[GEMINI %s] task=%s HTTP error (attempt %d): %s", m_id, task_name, attempt + 1, exc)
                            if attempt == 0:
                                await asyncio.sleep(2.5)
                                continue
                            break
                        if resp.status_code == 200:
                            data = resp.json()
                            usage_meta = data.get("usageMetadata", {})
                            p_tok = int(usage_meta.get("promptTokenCount", 0))
                            c_tok = _output_tokens(usage_meta)
                            self.quota_monitor.record_success(
                                model=m_id,
                                prompt_tokens=p_tok,
                                completion_tokens=c_tok,
                                headers=dict(resp.headers),
                            )
                            if self.license_port:
                                await self.license_port.record_token_usage(
                                    agent_id=agent_id,
                                    prompt_tokens=p_tok,
                                    completion_tokens=c_tok,
                                )
                            candidates = data.get("candidates") or []
                            if candidates:
                                parts = (candidates[0].get("content") or {}).get("parts") or []
                                text = "".join(str(p.get("text", "")) for p in parts)
                                parsed = self._parse_json_safely(text)
                                logger.info(
                                    "[GEMINI %s] task=%s tokens=%d (prompt=%d, completion=%d) keys=%s",
                                    m_id,
                                    task_name,
                                    p_tok + c_tok,
                                    p_tok,
                                    c_tok,
                                    list(parsed.keys()),
                                )
                                return parsed
                        if resp.status_code == 429:
                            snap = self.quota_monitor.record_quota_or_rate_limit_error(
                                model=m_id,
                                status_code=429,
                                error_body=resp.text,
                                headers=dict(resp.headers),
                            )
                            logger.warning(
                                "[GEMINI %s] Quota / Rate Limit Reached on %s (metric=%s, limit=%s, cooldown=%ds): %s",
                                m_id,
                                task_name,
                                snap.quota_metric or "unknown",
                                snap.quota_limit,
                                snap.cooldown_seconds_remaining,
                                snap.last_error_message,
                            )
                        last_err = f"{m_id} -> {resp.status_code}: {resp.text[:300]}"
                        if resp.status_code == 503 and attempt == 0:
                            await asyncio.sleep(3.5)
                            continue
                        if resp.status_code == 400 and "thinking" in resp.text.lower() and attempt == 0:
                            payload["generationConfig"].pop("thinkingConfig", None)
                            continue
                        break
                    if resp is not None and resp.status_code in (401, 403):
                        break

        logger.error("Gemini API call failed on all endpoints for %s: %s", model_id, last_err)
        return {}

    @staticmethod
    def _parse_json_safely(raw_text: str) -> dict[str, Any]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            obj = json.loads(cleaned)
            return obj if isinstance(obj, dict) else {"result": obj}
        except Exception:
            match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
            if match:
                try:
                    obj = json.loads(match.group(0))
                    return obj if isinstance(obj, dict) else {"result": obj}
                except Exception:
                    pass
            return {}
