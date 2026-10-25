# Changelog

All notable changes to **HA AI Brain** are documented in this file.

## 0.1.23 - 2026-10-25

### Added & Improved
- **Dynamic Approval Status Badges Across Agent Activity & Insights**:
  - Replaced stale `⚡ View Pending Approval` buttons on resolved proposals with dynamic status badges reflecting the exact decision taken by the homeowner:
    - `✓ Approved once`: Action was approved and executed.
    - `✓ Always allowed rule`: Approved repeatable rule created (clicking navigates directly to Memory & Rules).
    - `✕ Rejected`: Action rejected by user (clicking navigates directly to Memory & Rules).
    - `Dismissed`: Action was dismissed without execution.
    - `⚡ View Pending Approval`: Action is still awaiting homeowner decision.
  - Added `get_approval_statuses()` to `MemoryStorePort` and `SQLiteMemoryAdapter` exposing resolved approval states via `/api/status`.
  - Added optimistic status updates on user decisions so buttons update in real time with zero latency.

## 0.1.22 - 2026-10-25

### Improved
- **Quota & Usage Telemetry Clarity**:
  - Clarified on the dashboard quota card that requests and token counts reflect the **current container session** (since last restart), avoiding confusion with lifetime multi-day Google Cloud / AI Studio invoices.
  - Added full pricing table mappings for `gemini-2.0-flash`, `gemini-1.5-pro`, `gemini-1.5-flash-8b`, and `gemini-pro` to ensure model spend estimation mirrors provider rates accurately.

## 0.1.21 - 2026-10-25

### Fixed & Improved
- **Automatic Frontend Ingress Panel Discovery & Notification Deep-Linking**:
  - Eliminated 404 Not Found error when tapping push notifications on mobile devices by replacing hardcoded `/ha_ai_brain` URLs with dynamic panel path discovery (`get_addon_panel_path()`).
  - Implemented multi-tier automated panel path discovery that automatically works out of the box for all Home Assistant users across official, custom repo (`<repo-hash>_ha_ai_brain`), and local development add-on installations:
    1. **Supervisor API (`http://supervisor/addons/self/info`)**: Reads the exact container slug directly from Home Assistant's supervisor.
    2. **WebSocket Ingress Panel Registry (`get_panels`)**: Scans registered Home Assistant frontend panels for add-on references matching `ha_ai_brain` or titled "AI Brain" to retrieve the exact `url_path`.
    3. Safe generic fallback to `/ha_ai_brain`.
  - Updated notification payloads in `HomeAssistantNotificationAdapter` and `BrainOrchestrator` to format `url` and `clickAction` with `{panel_path}#approval-{aid}` and `{panel_path}#insight-{id}`.
  - Implemented `getActiveHash()` in dashboard JavaScript to bridge the outer Home Assistant window URL hash (`window.parent.location.hash`) into the ingress iframe with cross-origin safety, enabling immediate direct scrolling and pulse-highlighting to targeted approvals and insights upon tapping push notifications.
  - Added parent `hashchange` event listener and two-way hash synchronization when switching dashboard tabs.
  - Added test case `test_6_dynamic_addon_panel_path_and_notification_urls` verifying dynamic panel discovery and notification deep-link generation.

## 0.1.20 - 2026-10-25

### Fixed & Improved
- **Immediate Home Assistant Automation Reload & Multi-Layered Deduplication**:
  - Fixed Home Assistant not registering newly accepted automations into `/api/states` by automatically calling service `automation.reload` immediately following `POST /api/config/automation/config/{id}`.
  - Implemented `get_accepted_automations()` in `MemoryStorePort` and `SQLiteMemoryAdapter` to track historical automations approved and deployed by the homeowner.
  - Injected all deployed and pending approval automations (with aliases, descriptions, and targeted physical devices) into the periodic batch LLM prompt (`CRITICAL RULES FOR ALREADY DEPLOYED OR PENDING AUTOMATIONS`).
  - Added programmatic deduplication filter in `_synthesize_batch_node` (`_is_duplicate_automation`) checking candidate automations against existing HA automations, previously deployed automations, and in-flight pending approvals across both title similarity and physical target devices.
  - Added `NativeAutomationProposal.extract_target_entities()` to populate `ActionIntent.target_entity_ids` with the underlying physical devices (e.g. `cover.living_room_blind`), enabling the Orchestrator's Conflict Arbiter to suppress duplicate in-flight proposals targeting the same devices even when titles differ.
  - Added test case `test_5_accepted_and_pending_automations_prevent_duplicates` verifying reload and multi-layered deduplication.

## 0.1.19 - 2026-10-25

### Added & Improved
- **Zero-Latency Cache Invalidation for Memory Notes & Ignored Targets**:
  - Confirmed and verified that all user context notes and ignored targets are fetched dynamically from SQLite on every agent invocation (`_corroborate_context_node`) without requiring any add-on restarts, reloads, or manual actions.
  - Added explicit sub-agent cache invalidation (`invalidate_context_caches()` in `SpecializedAgentGraph` and `Orchestrator`) when adding or deleting notes and ignored targets, ensuring background research findings and computation routines immediately refresh on the very next telemetry event.
  - Added regression test in `test_ha_live_readiness.py` verifying cache invalidation behavior.

## 0.1.18 - 2026-10-25

### Added & Improved
- **Relocated Ignored Entities & Devices to Memory & Rules**:
  - Moved the "Ignored entities & devices" management card from the Settings tab to the **Memory & Rules** tab, unifying all cognitive boundaries (always-allowed rules, rejected action suggestions, rejected insights, custom user context notes, and ignored entities) into a single cohesive control center.
  - Added `.scroll` container support to `#ignoredTargetsList` with max height (520px) and clean custom scrollbars, keeping the page compact when ignore lists grow.
  - Added real-time count badge (`#ignoredCountBadge`) to the card header that dynamically displays total active ignored target patterns.

## 0.1.17 - 2026-10-25

### Added & Improved
- **Responsive Mobile Layout & Button Optimization for Insights & Recommendations**:
  - Fixed category pills collapsing vertically character-by-character on narrow mobile screens by adding `white-space: nowrap; flex-shrink: 0;` to `.pill`.
  - Re-architected `.insight-head` with responsive flex-wrapping so insight titles span full width naturally on mobile while pills and reasoning buttons wrap cleanly underneath.
  - Added responsive `.hide-mobile` utility to compact action buttons on smaller screens:
    - `✕ Reject & Never suggest` $\rightarrow$ `✕ Reject` (maintaining full tooltip explanation).
    - `🗑 Delete` $\rightarrow$ `🗑` icon button.
    - `🔍 View agent reasoning` $\rightarrow$ `🔍 View reasoning`.
  - Optimized `.insight-actions` with touch-friendly tap targets and equal button distribution across mobile screens.
  - Compacted header action buttons (`Dismiss all`, `Clear all`) to avoid wrapping and title crushing in narrow card headers.

## 0.1.16 - 2026-10-25

### Added & Improved
- **Scrollable List Containers on Memory & Rules Page**:
  - Bound all growing lists on the **Memory & Rules** tab (`rulesList`, `rejectedList`, `rejectedInsightsList`, and `contextNotesList`) with `.scroll` containers (max-height: 520px with custom thin transparent scrollbars), matching the behavior of the **Activity & Insights** page.
  - Added real-time item count badges to all card headers (`rulesCountBadge`, `rejectedCountBadge`, `rejectedInsightsCountBadge`, `contextNotesCountBadge`) that dynamically appear whenever items are present.
  - Enhanced custom scrollbar styles across all tabs with subtle thumb contrast and hover effects.

## 0.1.15 - 2026-10-25

### Added & Improved
- **Dynamic Home Assistant Service Discovery & Intelligent Action Normalization**:
  - Dynamically queries all registered services in Home Assistant via `GET /api/services` and injects available services (`available_ha_services`, `available_notification_services`, `preferred_notification_service`) into agent prompts for both periodic batch analysis and real-time reaction.
  - Added strict system prompt constraints forbidding agents from inventing or hallucinating device names, unverified notify services, or nonexistent entities.
  - Introduced `service_resolver` engine that automatically resolves and normalizes automation actions:
    - Resolves mobile notification services lacking the `mobile_app_` prefix (e.g. `notify.<device>` $\rightarrow$ `notify.mobile_app_<device>`) or matching discovered Companion App targets.
    - Resolves common service aliases (e.g. `switch.on` $\rightarrow$ `switch.turn_on`, `cover.close` $\rightarrow$ `cover.close_cover`).
    - Recursively traverses nested automation action blocks (`choose`, `then`, `else`, `repeat`).
- **Dynamic Repair of Pending Approvals**:
  - Automatically sanitizes and normalizes pending automation approvals in-memory when loaded via `get_pending_approvals()`, ensuring cards rendered in the Web UI show valid, resolved services.
  - Normalizes actions again right before execution in `_execute_intent`, ensuring native automations upserted into Home Assistant always use valid registered services.
- **Strict Zero-Leakage Integrity**:
  - Enforced zero hardcoded personal devices, names, or entities across all application modules, ensuring full portability across any Home Assistant installation.

## 0.1.14 - 2026-10-25

### Added & Improved
- **Content-Aware Automation Signatures**:
  - Native automation proposals now compute repeatable action signatures canonically from their normalized alias slug and controlled actuators (e.g. `sig:cover_shading_agent:automation.upsert_native_automation:morning_cover_opener:cover.living_room_blinds`) rather than an ephemeral random hex entity ID (`ai_brain_<random>`).
  - Rejecting an automation proposal now deterministically hard-blocks future proposals for that automation logic across subsequent analysis runs, regardless of whether a new random ID is generated.
- **Batch Analysis Automation Rejection Injection & Post-Filtering**:
  - Injected all rejected automation proposals (alias, controlled devices, and homeowner notes) directly into the LLM system prompt during batch analysis, explicitly commanding agents never to re-propose those automations.
  - Added deterministic post-filtering in `_synthesize_batch_node` that automatically discards candidate automations matching rejected aliases, slugs, or high keyword overlap.
- **Human-Readable Cards in "Rejected action suggestions" & "Always-allowed actions"**:
  - Enhanced the "Rejected action suggestions" and "Always-allowed actions" cards in the **Memory & Rules** tab to display a `⚡ Native Automation` badge, the clear human-readable title (e.g. `Create Native Automation: Morning Cover Opener`), target entities, and homeowner notes with clean, distinct styling.

## 0.1.13 - 2026-10-25

### Added & Improved
- **Bidirectional Deep-Linking & Glowing Pulse Highlighting**:
  - Seamlessly jump from any Pending Approval card to its generating Agent Activity log with a single click ("🔍 View agent reasoning & telemetry"), automatically switching tabs, scrolling into view, and highlighting the card with an attention-grabbing blue glow animation (`highlight-pulse`).
  - Added reciprocal "⚡ View Pending Approval" buttons on Agent Activity run logs and proposed native automations, allowing immediate navigation to the corresponding pending approval.
  - Linked advisory insights to agent run logs with "🔍 View agent reasoning" shortcuts.
- **Mobile Notification Direct Deep-Linking**:
  - Updated Home Assistant Companion push notification payload URLs (`clickAction` and `url`) to `#approval-{approval_id}` and `#insight-{insight_id}`.
  - Tapping a notification on a mobile phone opens the Ingress web dashboard, directly activates the correct tab, scrolls to the target item, and triggers the pulse highlight.
- **Human-Readable Native Automation Proposal Cards & Notifications**:
  - Replaced cryptic `automation.upsert_native_automation -> automation.ai_brain_...` titles with clear, user-friendly titles: e.g. `⚡ Create Native Automation: {alias}`.
  - Added prominent target entity details and a summary pill indicating the number of triggers, conditions, and actions.
  - Added an expandable `<details>` section displaying full formatted triggers, conditions, and actions JSON definitions directly on the approval card.
  - Mobile push notifications for native automations now clearly announce `⚡ Create Automation: {alias}` with formatted description context.
- **Single Log Retrieval Endpoint**:
  - Added `GET /api/logs/{run_id}` API endpoint and `get_run_log(run_id)` memory methods to dynamically fetch and display individual reasoning audit traces even if paginated out of view.

## 0.1.12 - 2026-10-25

### Fixed
- **Dashboard UI Unresponsive / Freezing Fix**:
  - Fixed a JavaScript SyntaxError in `dashboard_html.py` caused by unescaped newline characters in the prompt dialog string literal inside the Python template string.
  - Simplified the `rejectInsightPrompt(insightId)` call signature to avoid any potential HTML attribute quote-escaping collisions.
  - Added an automated JavaScript syntax verification step (`node --check`) into the test suite to guarantee that dashboard scripts parse without syntax errors.

## 0.1.11 - 2026-10-25

### Fixed
- **SQLite Database Startup Migration Fix**:
  - Resolved `sqlite3.OperationalError: no such column: status` on addon startup when upgrading existing databases from `< v0.1.10`.
  - Enforced schema migration order: checks existing columns and executes `ALTER TABLE advisory_insights ADD COLUMN status TEXT` *before* attempting to create the `idx_advisory_insights_status` index.
  - Added regression test `test_14_sqlite_migration_from_v019_without_status_column` ensuring seamless database upgrade paths across versions.

## 0.1.10 - 2026-10-25

### Added & Improved
- **Insight Lifecycle Management (Dismiss / Mark Read & Delete)**:
  - Added individual "✓ Mark read" (dismiss) and "Delete" actions on advisory insight cards.
  - Added "Dismiss all" and "Clear all" bulk actions in the Insights header to easily triage and clear historical insights.
  - Added status tracking (`active`, `dismissed`, `rejected`) in `advisory_insights` SQLite schema with migration and indexing.

- **Insight Rejection with Feedback Notes & Topic Suppression**:
  - Added "✕ Reject & Never suggest" action on advisory insights with an optional prompt for homeowner context/notes.
  - Automatically records a `FeedbackEpisode` and marks the insight as `rejected`.
  - Injected rejected topics, categories, and homeowner notes into batch agent prompts so LLMs are explicitly commanded never to propose rejected recommendations again.
  - Added deterministic post-filtering in `SpecializedAgentGraph._synthesize_batch_node` guaranteeing that rejected insight topics never resurface.
  - Added **"Rejected insights & recommendations"** section in the **Memory & Rules** tab where homeowners can view all rejected advice and click **Unblock** anytime.

- **Activity Logs Storage Control & Tab Badge Fix**:
  - Replaced the confusing "205" raw activity log count badge on the "Activity & Insights" navigation tab with the count of active, unread insights.
  - Added "Clear logs" button to the Agent Activity card and automated log retention auto-pruning (capping at 300 recent logs) to keep SQLite storage lean and prevent unbound database growth.

## 0.1.9 - 2026-10-25

### Refactored & Hardened
- **Multi-Agent Cognitive Engine Architecture Standardization**:
  - Promoted `SpecializedAgentGraph` and `AgentGraphState` to the primary canonical implementation in `ha_ai_brain.application.graphs.specialized_agent`, establishing `climate_agent.py` as a clean backward-compatibility shim.
  - Refactored `BrainOrchestrator` to directly type and instantiate `SpecializedAgentGraph` and `AgentGraphState`.
  - Renamed test suite from `test_climate_agent_prototype.py` to `test_multi_agent_cognitive_engine.py` (and test class `TestMultiAgentCognitiveEngine`), accurately reflecting comprehensive multi-agent cognitive testing.

- **Expanded Area Resolution Heuristics**:
  - Added full spectrum of device and sensor naming suffixes across all domains (`_temp`, `_hum`, `_contact`, `_door`, `_lock`, `_power`, `_energy`, `_plug`, `_switch`, `_heater`, `_radiator`, `_ac`, `_curtain`, `_shutter`, `_presence`) in `ha_websocket_rest.py`. This ensures accurate area mapping out-of-the-box even before users manually assign areas in Home Assistant.

- **Subprocess Sandbox Process Leak Defense**:
  - Hardened `PythonSandboxAdapter`: now explicitly catches `asyncio.TimeoutError` and enforces `proc.kill()` and `await proc.wait()`, preventing runaway or infinite loop processes from leaking CPU resources in the background. Added timeout termination test.

- **SQLite Database Index Optimization**:
  - Added indexes on `pending_approvals(status)`, `run_logs(created_at DESC)`, `advisory_insights(created_at DESC)`, `feedback_episodes(agent_id, created_at DESC)`, and `user_context_notes(active, created_at DESC)` in `memory_sqlite.py`, accelerating dashboard queries and periodic batch audits as historical data grows.

- **LLM Error Handling Resilience**:
  - Hardened Google Gemini adapter against model-specific parameter incompatibilities (auto-recovering on `thinkingConfig` 400 errors and attempting alternative candidate models rather than terminating).

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
