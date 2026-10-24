# Changelog

All notable changes to **HA AI Brain** are documented in this file.

## 0.1.0

### Added
- **Autonomous Multi-Agent Architecture**: Real-time event streaming and periodic deep-think batch reasoning with specialized agents (Climate & Thermal Inertia, Lighting & Habit, Security, and Repair).
- **Multi-Provider AI Support**: Seamless support for Google Gemini (Free AI Studio & Vertex Express), OpenAI ChatGPT (`gpt-4o`, `gpt-4o-mini`), Anthropic Claude (`claude-3-5-sonnet`), OpenRouter, and Local Ollama (100% private & offline).
- **Deterministic Action Signatures**: Canonical signatures based on `(agent, domain.service, targets)` so "Always Allow" endorsements and explicit rejections reliably match future proposals regardless of LLM wording variance.
- **Proposal Dismissal**: Ability to dismiss pending approvals without executing them and without permanently blocking them (via dashboard "Dismiss" / "Dismiss all" and mobile notification action buttons).
- **Home Assistant Ingress Dashboard**: Modern 4-tab control plane (Approvals, Activity Traces & Insights, Memory & Rules, Settings & Telemetry) integrated directly into Home Assistant's sidebar.
- **Persistent Memory**: SQLite-backed episodic memory, repeatable rule management with one-click revocation, and unblocking of rejected suggestions.
- **Supervisor Integration**: Zero-configuration connection via `SUPERVISOR_TOKEN` and internal Home Assistant DNS.
