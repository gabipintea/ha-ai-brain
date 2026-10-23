"""Production Multi-Provider LLM Adapter (Gemini AI Studio / Vertex Express + LiteLLM)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ha_ai_brain.adapters.quota_monitor import BaseQuotaMonitorAdapter, create_quota_monitor_for_model
from ha_ai_brain.ports.billing import LicensePort
from ha_ai_brain.ports.llm import LLMProviderPort, LLMQuotaAndUsageSnapshot

logger = logging.getLogger(__name__)


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
    ) -> None:
        import asyncio

        self.model = model
        self.fast_model = fast_model
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

    def approve_fallback_model(self, model: str | None = None) -> str | None:
        return self.quota_monitor.approve_fallback_model(model)

    def reject_fallback_and_wait_for_primary(self) -> None:
        self.quota_monitor.reject_fallback_and_wait_for_primary()

    async def generate_json(
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
            )

        in_cooldown, cooldown_rem = self.quota_monitor.is_in_cooldown()
        if in_cooldown:
            logger.warning(
                "LiteLLMAdapter: Skipping %s (%s) — AI model quota cooldown active for %ds more.",
                task_name,
                chosen_model,
                cooldown_rem,
            )
            return {}

        import litellm

        kwargs: dict[str, Any] = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.managed_proxy_url:
            kwargs["api_base"] = self.managed_proxy_url

        try:
            resp = await litellm.acompletion(**kwargs)
        except Exception as exc:
            status_code = int(getattr(exc, "status_code", 429 if "429" in str(exc) else 500))
            self.quota_monitor.record_quota_or_rate_limit_error(
                model=chosen_model,
                status_code=status_code,
                error_body=str(exc),
                headers=getattr(exc, "llm_provider_response_headers", None),
            )
            logger.error("LiteLLM call failed for %s: %s", chosen_model, exc)
            return {}

        usage = getattr(resp, "usage", None)
        p_tok = int(getattr(usage, "prompt_tokens", 0)) if usage else 0
        c_tok = int(getattr(usage, "completion_tokens", 0)) if usage else 0
        self.quota_monitor.record_success(
            model=chosen_model,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            headers=getattr(resp, "_response_headers", None),
        )
        if usage and self.license_port:
            await self.license_port.record_token_usage(
                agent_id=agent_id,
                prompt_tokens=p_tok,
                completion_tokens=c_tok,
            )
        content = resp.choices[0].message.content
        return self._parse_json_safely(content)

    async def _call_google_gemini(
        self,
        chosen_model: str,
        system_prompt: str,
        user_prompt: str,
        agent_id: str,
        task_name: str,
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
                "thinkingConfig": {"thinkingBudget": 1024},
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

            async with httpx.AsyncClient(timeout=90.0) as client:
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
                            c_tok = int(usage_meta.get("candidatesTokenCount", 0))
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
                        break
                    if resp is not None and resp.status_code not in (404, 429, 503):
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
