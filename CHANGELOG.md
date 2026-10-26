# Changelog

All notable changes to **HA AI Brain** are documented in this file.

## 0.2.2 - 2026-10-26

### Fixed
- The next scheduled batch now follows the time shown in the header: a manual "Run analysis now" really postpones it, and the countdown no longer drifts.
- Habit proposals: one device is proposed once per scan (a light/switch pair sharing one id, or two same-named entities at the same time), and a habit is no longer reported as "already automated" by a threshold-triggered automation such as an overheat cut-off. Light/switch twins of an automated device now count as automated.
- Automations created by the brain carry a single "[AI Brain]" prefix, even when the model wrote one itself; older doubled prefixes are collapsed when shown.
- Research findings stored by older versions are repaired when read: list answers show as numbered steps and unsourced findings no longer carry a "high" badge.
- Agents describe built-in guidance as a "built-in reference" and only say "research" for approved research.
- Deployed-automation health says "too new" instead of "healthy" for automations under 3 days old that have not run yet.
- Backtest text uses ± instead of +-.
- Quiet hours show whether they are on or off, with a "Clear quiet hours" button.

## 0.2.0 - 2026-10-26

### Added — per-sensor minimum change
- Optional, user-defined minimum change for named numeric sensors (Memory & Rules); smaller moves do not count as significant live events.
- Fixed: false "has not reported" alerts for change-only sensors that are normally silent at that time of day; unverified research findings are capped at medium confidence.

### Added — performance (tokens, database, CPU)
- **Tokens**: agents with nothing to look at or operate in your home are skipped; batches are skipped when nothing relevant changed, with back-off when recent runs produced nothing; real-time bursts are coalesced (`realtime_coalesce_seconds`) and capped per agent (`max_agent_wakeups_per_hour`); calculation code is cached (7 days) and reused; research is cached by equipment types (14 days); leaner prompts with the static part first (provider prefix caching); provider-neutral `reasoning` hint (only mapped by the Gemini transport) and hidden thinking tokens counted in usage.
- **Database**: compact telemetry layout with automatic in-place migration, auto-vacuum + WAL checkpointing, compressed run logs without duplicated code, daily retention for approvals, insights, feedback, outcomes and caches.
- **CPU**: habit clustering is O(n log n) (90k transitions: 8.7 s to 0.3 s), buffered telemetry writes, cached ignore list, per-event logs at DEBUG; new `log_level` option.

### Added — local learning (no AI tokens)
- **Telemetry store** (SQLite, WAL): state transitions + hourly sensor aggregates, 90-day retention, recorder history imported at startup (switchables 240 h, sensors 96 h as hourly aggregates). History queries are no longer capped at 60 entities (default 300, configurable).
- **Habit miner**: time-of-day habits (weekday/weekend aware, circular-time clustering) and "A then B" sequences (support, confidence, lift). Strong, un-automated habits become native-automation proposals **without any LLM call**; unlocking/disarming is never proposed.
- **Automation understanding**: real triggers/actions of existing HA automations are parsed (old and new HA config syntax) and used for coverage, duplicate detection and expected-state rules.
- **Backtesting** of every proposed automation against recorded history, shown on the approval card; automations contradicting the household's behaviour are dropped.
- **Exception detection** every 5 min: open/unlocked house while away, broken learned routine, time-based automation that did not run. Alerts (urgent for security) and a targeted agent run only when something is off.
- **Real-time gating**: once enough history exists, only unusual events wake an agent (z-score vs. hour-of-day baseline, routine/automated actuator changes are skipped). Security-relevant events always wake.
- **Batch savings**: unchanged inputs skip the whole batch; research findings are cached persistently per entity-set signature; the code-writing step now receives locally computed statistics for every entity instead of 4 points of 15 entities.
- **Household context & real data**: presence, part of day, sun, weather + hourly forecast, tariff and solar-forecast sensors; curated, versioned reference knowledge (user-extensible) replaces LLM recall.
- **Closed loops**: expected outcomes are verified (feedback written), deployed automations reviewed daily (never fired / overridden / disabled / missing), trust-promotion suggestions after repeated approvals, weekly digest.

### Added — safety & control
- Per-domain autonomy, kill switch ("Pause brain"), hourly action caps (global + per entity, excess goes to approval), quiet hours (security alerts exempt), daily token budget, **Undo** for autonomous actions (notification button + dashboard, 24 h), reversible privacy scrubbing of people/phones/network identifiers for cloud LLMs.
- Dashboard: **Learned** tab (progress, habits, automation health, savings, undo list), **Learning & Safety** settings card, backtest box on approvals, pause banner. New `GET /api/learned`, `POST /api/undo/{id}`, `POST /api/exceptions/check`.

### Added — generic exception detection, watches and research (0.2.0)
- **Exceptions are learned, not enumerated.** The fixed list of checks is gone. Every tracked entity gets a profile from its own history (how long it stays in each state, how often it changes, what range a sensor has at each hour) and these generic detectors run for *all* of them: broken routine, abnormally long dwell in a non-resting state, a normally busy entity gone silent, flapping, a sensor far out of range for two consecutive readings, a sensor that stopped reporting, entities stuck unavailable (collapsed into one finding on mass outages), automations that did not run, and the perimeter-open-while-away safety net. Safety relevance (Home Assistant's own domains / device classes) and presence only change the *severity*. Cumulative counters are ignored; alerts are capped per check and per day, and calm findings are suppressed while the home is empty.
- **The brain learns from your reactions to alerts.** Dismissing an alert doubles that entity's quiet period (up to 14 days); rejecting mutes it until you unmute it in the Learned tab.
- **Watches**: describe any condition in your own words (Memory & Rules tab). The AI interprets it once into a structured rule (state / numeric / silence, duration, presence, time window, weekdays, severity) that is validated against your real entities, replayed over your history ("would have alerted 3 times in the last 12 days"), and then evaluated locally every minute at zero token cost.
- **Research agenda (works with any AI provider)**: each agent thinks like a specialist in its field and proposes practical knowledge for *your* setup, using the normal chat completion of whatever model you configured — no search feature, citations or special API required. Topics come from your real equipment (manufacturer + model from the device registry) and from the agent planning what a specialist would investigate for this home; topics already researched or rejected are never repeated. Findings are labelled "AI knowledge" (with the model's own honest confidence and any standards it says it relies on, flagged as unverified). **Nothing reaches an agent until you approve it** (new Research tab). Weekly by default, first run one day after upgrade, respects the daily token budget.
- **Optional deep research (Gemini only, off by default)**: a switch adds Google Search grounding with cited sources, a "% sourced" figure and evidence-capped confidence. It costs noticeably more tokens; if the search returns nothing, the normal knowledge-based research answers instead.
- Built-in reference guidance is now labelled as unverified seed guidance; approved research is listed ahead of it in agent prompts.
- New API: `/api/watches*`, `/api/research*`, `/api/exceptions/unmute`.

- **User-editable files moved to the Home Assistant config folder**: custom agents and extra reference knowledge now live in `/config/ha_ai_brain/agents/` and `/config/ha_ai_brain/knowledge/` (reachable with the File editor, Samba or SSH add-ons and included in config backups) instead of the add-on's private `/data`.
- **Documentation rewritten**: `DOCS.md` is now the complete user manual (how it works, every feature, dashboard tour, settings reference, rollout plan, privacy, costs, troubleshooting, limitations and a 30-question FAQ); the README is a concise overview.

- **Critical unusual situations** now also push their corrective-action approval ("lock it now?") through quiet hours, and every autonomous action is announced — also those that cannot be undone, such as locks (without an Undo button).

### Changed
- Batch lookback maximum raised from 168 h to 720 h. Real `last_changed` timestamps are now read from Home Assistant (needed to know how long a state has persisted).
- Two different automations may now target the same device (e.g. "on at 18:00" and "off at 23:00"); only equivalent ones are treated as duplicates.
- Habit automations fire slightly *before* the typical manual action so they get there first.

## 0.1.26 - 2026-10-26

### Security
- **Ingress-only access inside the add-on**: when running under the Supervisor, requests from anything other than the Supervisor proxy are rejected (override with `BRAIN_TRUSTED_PROXIES` / `BRAIN_ALLOW_ANY_CLIENT`). `/api/health` stays open for the watchdog.
- **Settings API no longer leaks secrets**: `ha_token` and `license_key` were previously returned by `/api/status`; short API keys are now fully masked.
- **Arbitrary-code domains blocked**: `shell_command`, `python_script`, `pyscript`, `command_line`, `rest_command`, `hassio`, `script`, `recorder` can never be called from an LLM proposal.
- **Agents are confined to their declared `controllable_domains`**; proposals targeting unknown (hallucinated) entities are rejected before execution.
- LLM-proposed priorities are capped below human-override / life-safety tiers, so an agent cannot out-rank the Conflict Arbiter.
- Custom `agent_id` is validated (no path traversal when persisted to disk); request bodies have length limits.
- Computation sandbox runs with a scrubbed environment and CPU/memory limits; failed generated code is no longer cached.
- `docker-compose` publishes the unauthenticated dashboard on `127.0.0.1` only.

### Fixed
- Boolean add-on options (`enable_actionable_notifications: false`) were silently turned back into `true` by `jq '// default'`; `batch_lookback_hours` was never passed to the app.
- Environment parsing is tolerant (invalid ints/enums fall back to defaults, ranges are clamped, `BRAIN_USE_SIMULATOR=1` works, empty site context uses the default).
- Approvals could be executed twice (e.g. notification button + dashboard); they now resolve exactly once. Unanswered approvals expire after 24 h (previously they suppressed identical proposals forever).
- Guardrail rejection matching used substring checks (`light.kitchen` also blocked `light.kitchen_ceiling`); now exact. Closing a garage door/gate no longer requires approval; opening still does.
- `light.turn_on` with brightness/colour on an already-on light was dropped as "redundant".
- Fallback model list defaulted to Gemini models even for OpenAI/Anthropic/OpenRouter keys, and OpenRouter defaults lost their vendor segment. Auth errors (401/403) no longer start a fake "quota cooldown". Changing the model in the UI no longer resets usage counters or the fallback list.
- Event stream: reconnect no longer spins when the socket closes cleanly; one malformed frame no longer drops the connection; notification-button tasks are no longer garbage collected mid-flight.
- `nan`/`inf` sensor states are no longer treated as numeric readings; `_w` substring matched any entity containing `_w`.
- `clear_notification` is only sent to Companion App targets (it showed up as text on other notify services).
- Malformed `expected_outcome` from the LLM dropped the whole proposed action.
- Custom agents persisted by the UI were written inside the container image and lost on every add-on update; they now live in `/data/agents`.
- MCP adapter returned fabricated device data; it now reports `unavailable` unless a connector is registered.
- Removed a personal device name from the changelog and personal tokens from the leakage test (replaced by generic IP/MAC/e-mail/home-path pattern checks).

### Improved
- Shared pooled HTTP client for Home Assistant REST calls; WebSocket subscribes only to the 4 event types it consumes instead of every event on the bus; bounded memory for AI context ids and sent-notification history.
- Scheduled batches honor the previous run after a restart (no token spend on every restart) and are skipped during a quota cooldown.
- SQLite runs in WAL mode; prompts cap the number of entities sent to the LLM; LLM calls have a request timeout.
- Added `/api/health` + Supervisor watchdog; exposed `managed_cloud_proxy_url` / `license_key` options; declared the `python-dotenv` dependency.

## 0.1.25 - 2026-10-25

### Added & Improved
- **Scheduled Next Batch Execution Indicators Across UI**:
  - Added real-time tracking and relative countdown formatting (`formatRelativeSchedule`) for the next scheduled periodic batch analysis across 3 locations in the interface:
    1. **Top Header**: Directly beneath the status controls (`Next batch: Today at 20:59 (in 5h 25m)`).
    2. **Activity & Insights Tab**: Sub-header on the Agent Activity card.
    3. **Settings Tab**: Summary card inside Operating Settings showing next scheduled batch time, batch interval (e.g. `every 6h`), and last completed batch execution.
  - Implemented `get_next_batch_run_at()` and `get_last_batch_run_at()` on `BrainOrchestrator` with SQLite run log lookup (`get_last_batch_run_time()`).
  - Added `next_batch_run_at`, `last_batch_run_at`, and `batch_interval_minutes` to `/api/status`.

## 0.1.24 - 2026-10-25

### Fixed & Improved
- **Automatic Removal of Resolved Automations from Insights & Recommendations**:
  - Filtered proposed automations in the "Insights and recommendations" column so only actively pending proposals awaiting homeowner decision are displayed.
  - Automatically clears automations from the recommendations feed as soon as they are approved, rejected, or dismissed, eliminating ghost items that could not be cleared with `Dismiss all` or `Clear all`.
  - Added direct quick-action buttons (`⚡ Review in Approvals`, `✕ Reject`, `Dismiss`) on pending automation cards in the Insights view.
  - Updated activity tab and card badge counters to accurately reflect total active unread items (active advisory insights + pending automation proposals).

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
  - Automatically resolves notification service names (e.g. `notify.my_phone` $\rightarrow$ `notify.mobile_app_my_phone`) using discovered Home Assistant notify services, eliminating 400 Bad Request errors when users omit the `mobile_app_` prefix.
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
