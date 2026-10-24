# Changelog

All notable changes to **HA AI Brain** are documented in this file.

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
