# Changelog

All notable changes to **HA AI Brain** are documented in this file.

## 0.1.8 - 2026-10-25

### Fixed & Generalized
- **Zero Personal Entity Leakage**:
  - Removed all hardcoded personal devices, names, and manufacturer-specific entity tokens from `orchestrator.py`, `triage.py`, `notification_ha.py`, and test suites.
  - Implemented generic `matches_device_class_or_heuristics()` using standard Home Assistant device classes, standard units (`°C`, `%`, `lx`, `W`, `kWh`, `ppm`), and universal domain naming patterns.
  - Added regression test `test_13_codebase_zero_personal_entity_leakage` to strictly enforce zero personal entity string presence in public source code.

- **Configurable Batch Analysis Lookback Window**:
  - Explicitly clarified and documented the role of `smart_home.get_all_states()` as the live entity discovery/inventory catalog, followed by `smart_home.get_history()` across the analyzed time window.
  - Added `batch_lookback_hours` (default: 24h, configurable up to 168h / 7 days) in settings, supervisor add-on schema, translations, and API.
  - Emitted structured timestamps and entity counts in logs upon starting batch analysis.

- **Full Multi-Agent Suite & Multi-Agent Batch Scheduler**:
  - `_periodic_batch_scheduler_loop()` now iterates through **all active specialized agents** in the registry (Climate, Lighting, Security, Energy, Covers, Diagnostics, Custom), allowing each domain specialist to synthesize insights and native automations.
  - Expanded built-in suite with `energy_efficiency_agent` (Solar PV, vampire loads, load shifting) and `cover_shading_agent` (passive solar heat gain & envelope protection).
  - Generalized StateGraph architecture (`SpecializedAgentGraph` / `AgentGraphState`) to run any domain agent persona polymorphically.
  - Added support in `/api/batch/analyze` and the Web UI to run batch analysis across all active agents or specific agents on demand.

## 0.1.7 - 2026-10-24

### Improved
- **Compact Mobile Notification Cards & Full-Fidelity Web UI**:
  - **Phone Notification Optimization**: Push notification titles and messages are now formatted specifically for mobile lockscreen banners and notification cards (<= 44 chars for titles, leading directly with the actionable recommendation and concise context).
  - **Tap to Open Dashboard**: Push notifications now carry deep link parameters (`url: "/ha_ai_brain"` and `clickAction: "/ha_ai_brain"`) and iOS category subtitles, allowing homeowners to tap the notification and jump straight to the Brain dashboard.
  - **Preserved Web UI Fidelity**: The Web UI continues to display 100% of the comprehensive multi-paragraph physical rationale, sensor readings, and psychrometric formulas with formatted line breaks (`white-space: pre-wrap`), discovery timestamps, category pills, and impact estimates.
  - **Prompt Guidance**: Instructed batch reasoning agents to generate crisp 4-8 word insight titles and direct homeowner actions while keeping in-depth physics in `finding_details`.

## 0.1.6 - 2026-10-24

### Fixed & Improved
- **Smart Notification Service Resolution & Fallback**:
  - Automatically resolves notification service names (e.g. `notify.gabriels_iphone` $\rightarrow$ `notify.mobile_app_gabriels_iphone`) using discovered Home Assistant notify services, eliminating 400 Bad Request errors when users omit the `mobile_app_` prefix.
  - Automatically falls back to `notify.notify` if an invalid, unregistered, or renamed device target is encountered.
  - Hardened periodic batch scheduler and alert dispatch in `orchestrator.py`: notification delivery failures (e.g. 400 Bad Request or unreachable mobile clients) are logged gracefully and will never halt background audits or prevent insights and automations from persisting into episodic memory.
  - Clarified Home Assistant Add-on configuration documentation and translations for `notification_service`.

## 0.1.5 - 2026-10-24

### Fixed & Aligned
- **Updated Google Gemini Models to Live Supported API Versions (`gemini-3.8-flash` & `gemini-3.5-flash`)**:
  - Legacy `gemini-2.5`, `gemini-2.0`, and `gemini-1.5` endpoints have been retired by Google API with HTTP 404 (*"This model is no longer available. Please update your code to use models/gemini-3.8-flash"*).
  - Configured `gemini/gemini-3.8-flash` as the default Primary Deep Batch Model and `gemini/gemini-3.5-flash` as the Fast Reflex Model across documentation, Add-on configuration schema, supervisor options, and quota monitor fallback chains.

## 0.1.4 - 2026-10-24

### Fixed
- **Resolved `UnboundLocalError: 'last_t'` in Triage Engine**:
  - Initialized `last_t` across all numeric telemetry so non-illuminance/non-power entities (e.g. air purifier `pm2_5`, network bandwidth `upload_speed`, battery, CO2, etc.) evaluate deadband and anti-flap guards smoothly without raising an unbound local variable exception.
  - Added unit test `test_11_triage_generic_numeric_sensors_debounce_and_antiflap_no_unbound_error` to prevent regression.

## 0.1.3 - 2026-10-24

### Fixed & Aligned
- **Aligned Add-on Configuration Defaults with Official Recommendations**:
  - Replaced placeholder defaults with officially recommended Google Gemini models matching documentation:
    - **Primary / Deep Batch Model**: `gemini/gemini-2.5-pro` (or `gemini/gemini-2.5-flash`).
    - **Fast Reflex Model**: `gemini/gemini-2.5-flash` (or `gemini/gemini-1.5-flash`).
  - **Added Official Home Assistant Add-On Translations (`translations/en.yaml`)**: The Home Assistant UI now renders clear, user-friendly labels and field descriptions (e.g., *"Primary / Deep Batch Model"*, *"Fast Reflex Model"*, *"LLM API Key"*) instead of raw internal keys.
  - **Updated Dashboard & Fallback Chains**: Synchronized control plane presets, quota monitor fallbacks, and documentation to use real, production-ready Google Gemini models (`gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-1.5-flash`, `gemini-2.0-flash`).

## 0.1.2 - 2026-10-24

### Added & Improved
- **Unified Multi-Candidate In-Flight Fallback Across All Providers**:
  - **Zero Action Drops on HTTP 429**: When any provider (OpenAI, Anthropic Claude, OpenRouter, Google Gemini) encounters a rate limit (HTTP 429) or transient provider error, the adapter automatically rotates mid-flight to secondary candidate models without aborting the reasoning turn or dropping Home Assistant actions.
  - **Provider-Specific Default Fallback Chains**:
    - **OpenAI**: `gpt-4o-mini` $\leftrightarrow$ `gpt-4o` $\leftrightarrow$ `gpt-3.5-turbo`.
    - **Anthropic Claude**: `claude-3-5-haiku-20241022` $\leftrightarrow$ `claude-3-5-sonnet-20241022` $\leftrightarrow$ `claude-3-haiku-20240307`.
    - **OpenRouter**: `google/gemini-2.5-flash` $\leftrightarrow$ `openai/gpt-4o-mini` $\leftrightarrow$ `anthropic/claude-3.5-sonnet`.
    - **Google Gemini**: `gemini-3.6-flash` $\leftrightarrow$ `gemini-3.5-flash` $\leftrightarrow$ `gemini-3.1-flash-lite` $\leftrightarrow$ `gemini-3.8-flash`.
  - **Symmetric Candidate Anchoring**: Fast-tier reflex calls and deep periodic audits correctly anchor their respective requested model as Candidate 0 while preserving healthy fallback ordering.
  - **Multi-Header Reset & Retry-After Parser**: Extracts backoff windows from standard HTTP `Retry-After`, `retry-after-ms`, `x-ratelimit-reset-requests`, and `anthropic-ratelimit-requests-reset` headers as well as provider regex error payloads.
  - **Automatic Primary Cooldown Recovery**: As soon as a cooled-down model's backoff timer expires, requests transparently resume using the primary model.
  - **Fast Fail on Auth Errors**: Aborts candidate iteration immediately on HTTP 401/403 to prevent burning quota across candidates on invalid API keys.

## 0.1.1 - 2026-10-24

### Changed & Optimized
- **95%+ Token Spend Reduction**:
  - **Dynamic Proportional Deadbands & Debounce**: Replaced fixed 80 lx deadband with proportional thresholds ($\ge 15\%$ AND $\ge 1,500\text{ lx}$ for outdoor daylight) and a 10-minute sensor debounce window in `triage.py`. Drops trigger frequency by ~90%.
  - **Sub-Agent Physics & Code Caching**: Reuses validated research findings and executes cached sandbox Python code during real-time stream mode with **0 LLM calls**, eliminating ~4,300 tokens per trigger.
  - **Real-Time Telemetry & Prompt Compaction**: Scopes sensor states to the active area + outdoor environment and strips 50+ Home Assistant native automations from real-time prompts, slashing prompt size from ~8,800 to ~1,200 tokens.
  - **Fast-Tier Reflex Routing**: Routed real-time reactions and code generation to `use_fast_tier=True` (`gemini-3.5-flash` or `gpt-4o-mini`), reserving heavy models exclusively for periodic deep-think batch audits.

## 0.1.0 - 2026-10-24

### Added
- **Official Home Assistant Add-On Distribution**: Complete Add-On repository structure with Home Assistant Ingress support, auto-start, and configuration schema via `SUPERVISOR_TOKEN`.
- **Autonomous Multi-Agent Architecture**: Real-time event streaming and periodic deep-think batch reasoning with specialized agents (Climate & Thermal Inertia, Lighting & Habit, Security, and Repair).
- **Multi-Provider AI Support**: Seamless support for Google Gemini (Free AI Studio & Vertex Express), OpenAI ChatGPT (`gpt-4o`, `gpt-4o-mini`), Anthropic Claude (`claude-3-5-sonnet`), OpenRouter, and Local Ollama (100% private & offline).
- **Decoupled WebSocket Engine**: Non-blocking concurrent WebSocket event reader preventing keepalive ping timeouts during heavy LLM inference.
- **Instant Mobile Notification Actions**: Sub-millisecond callback execution for iOS and Android actionable push notification button taps (`Approve Once`, `Always Allow`, `Dismiss`, `Reject`).
- **Two-Way Notification Synchronization**: Automatically dismisses mobile push notifications from the lock screen when approvals are resolved or dismissed via the Web UI.
- **In-Flight Proposal Deduplication & Conflict Prevention**: Suppresses redundant in-flight proposals for the same entities and blocks contradictory proposals (e.g. `open_cover` vs `close_cover`).
- **Current State Awareness (No-Op Suppression)**: Prevents redundant proposals when target entities are already in the intended state (e.g., closing already-closed covers).
- **Deterministic & Generalized Action Signatures**: Canonical signatures based on `(agent, domain.service, targets)` with multi-target subset expansion for user-endorsed repeatable rules.
- **Modern Responsive Ingress Dashboard**: Full-featured 4-tab control plane (Approvals, Activity Traces & Insights, Memory & Rules, Settings & Telemetry) integrated directly into Home Assistant's sidebar.
- **Persistent Memory & Rules**: SQLite-backed episodic memory, repeatable rule management with one-click revocation, and unblocking of rejected suggestions.
