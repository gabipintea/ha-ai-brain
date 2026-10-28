# 🧠 HA AI Brain (`ha-ai-brain`)

[![Home Assistant Add-on](https://img.shields.io/badge/Home%20Assistant-Add--on-blue.svg?logo=home-assistant)](https://github.com/gabipintea/ha-ai-brain)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: Proprietary](https://img.shields.io/badge/license-Proprietary-green.svg)]()
[![Multi-Provider AI](https://img.shields.io/badge/AI%20Providers-Gemini%20%7C%20OpenAI%20%7C%20Claude%20%7C%20OpenRouter%20%7C%20Ollama-orange.svg)]()

**A background brain for Home Assistant.** It watches what happens in your home, learns what is normal for *your* house, turns your own recurring habits into native Home Assistant automations, tells you when something is unusual, and lets specialised AI agents think about the harder questions — always within safety limits you control.

> 📖 **The complete user manual (how everything works, every feature, settings, privacy, costs and an FAQ) is in [`ha_ai_brain/DOCS.md`](ha_ai_brain/DOCS.md)** and in the add-on's *Documentation* tab inside Home Assistant.

---

## What it does

**Understands your home by itself**
* Discovers entities, areas, devices, services and notification targets — nothing to configure.
* Imports your recent Home Assistant history and keeps its own compact long-term record of state changes and hourly sensor values.
* Knows who is home, the time of day, sun, weather and forecast, and electricity-price / solar-forecast sensors.
* You add context in plain words: a site description, permanent notes the AI must obey, and an ignore list.

**Learns locally — no AI tokens**
* Finds your **habits** ("this goes off around 23:00 on weekdays", "this follows that within minutes").
* Turns strong, un-automated habits into **native Home Assistant automations** — written by statistics, not by an AI call. A **Propose automation** button on any habit sends a weaker one to you for approval right away.
* **Backtests** every proposed automation against your own history before you see it.
* Learns what each sensor normally reads at each hour, and how long each device normally stays in each state.
* Reads your existing UI-made automations, so it does not propose what you already have.

**Tells you when something is unusual** (no device list to maintain)
* Broken routines, states that last far too long, entities that went silent, flapping devices, sensors far out of range, sensors that stopped reporting, many entities unavailable at once, automations that did not run, and "the house is open while everyone is away".
* Learns from your reactions: dismiss an alert and it waits longer, reject it and it stays muted.

**Your own automations in plain language**
* Describe an automation in a sentence; the AI writes a native Home Assistant automation, you review and edit the YAML, then create or cancel.

**Your own alerts in plain language (Watches)**
* Describe a condition in a sentence; the AI interprets it once, shows how it understood you and how often it would have fired on your history; from then on it runs locally for free.

**Specialised AI agents**
* Climate, Lighting, Security, Energy & Solar, Shading and Repair & Diagnostics agents, plus your own custom agents.
* **Regular analysis of the whole picture**: every few hours each agent studies your entities, trends and existing automations and proposes insights, recommendations and new automation ideas — even when nothing is wrong (for example condensation risk from indoor humidity/temperature and the outdoor temperature). Calculations run in a sandbox.
* Real-time reactions to unusual events.
* In real time, only called when local learning says it is worth it — routine events, normal readings and things already automated never reach the AI.
* Weekly **research homework**: each agent proposes practical knowledge for your equipment and setup, usable only after you approve it. Works with any AI provider; optional cited web research for Google Gemini.

**You stay in control**
* Shadow / Co-pilot / Autonomous — globally and per device type (for example lights autonomous, locks co-pilot).
* Hard guardrails the AI cannot override: temperature limits, blocked code-execution domains, approval always required for unlocking, disarming, garage doors, valves and restarts — also when they are hidden inside an automation an agent proposes.
* Approve from your phone: *Approve once*, *Always allow*, *Dismiss*, *Reject*. **Undo** button on everything it does by itself.
* Action rate limits, quiet hours, a daily token budget, a kill switch, and a privacy filter that hides people, phones and network identifiers from cloud AI.

**Light on tokens and hardware (Raspberry Pi friendly)**
* Skips agents with nothing to do, skips unchanged batches, coalesces event bursts, caches calculations and research, compact database with automatic clean-up and batched writes. Works the same with any AI provider.

**Transparent**
* Dashboard with approvals, a full activity log with the agents' reasoning, what it has learned, automation health reviews (problems listed first, with Disable / Enable / Delete for the automations it created), research waiting for your review, and a weekly digest.
* **Backup & restore**: export your decisions, rules and watches to a file and import them after a reinstall; the brain can also re-adopt its own automations by their `ai_brain_` id.

---

## How it works (in short)

1. **Observe** — live events plus imported history.
2. **Learn locally** — habits, normal ranges, routines (free).
3. **Decide** — filters and learned routines decide what deserves attention and what deserves the AI.
4. **Think** — the matching specialised agent analyses the situation.
5. **Act or ask** — deterministic safety checks, then shadow-log, ask you, or act (with Undo), and verify the result.

Read the details in [`DOCS.md`](ha_ai_brain/DOCS.md#3-how-it-works).

---

## 📦 Install as a Home Assistant add-on

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**, add `https://github.com/gabipintea/ha-ai-brain`.
2. Install **HA AI Brain**, enable **Show in sidebar**, **Start**.
3. Open **AI Brain** in the sidebar → *Settings*: choose an AI provider (Gemini, OpenAI, Anthropic, OpenRouter, a local Ollama model, or any other LiteLLM model), paste the key, describe your home, pick your phone as the notification target.

Connection to Home Assistant is automatic. Leave autonomy on **Co-pilot** at first and follow the [recommended rollout](ha_ai_brain/DOCS.md#7-recommended-rollout).

---

## ❓ FAQ (short version — the full FAQ is at the bottom of [`DOCS.md`](ha_ai_brain/DOCS.md#14-faq))

**Does it change my devices without asking?** Not in the default Co-pilot mode. In Autonomous mode low/medium-risk actions run by themselves with an Undo button; unlocking, disarming, garage doors, valves and restarts always need approval. Note: with approval notifications switched off, low/medium-risk actions run without asking even in Co-pilot.

**Does it need a cloud AI?** No. With a local Ollama model nothing leaves your network. Habit detection, backtesting, unusual-situation alerts and running your watches need no AI at all.

**How much does it cost?** Most of the work is local and free. Tokens are used by agent reactions to unusual events, one analysis per agent per interval (skipped when nothing changed), and a few research calls per week. A daily token budget caps it.

**How long until it is useful?** About 3 days of history; it imports your recent history at startup, so often almost immediately.

**What data does the AI see?** Entity IDs, names, states and statistics needed for the question, your site context and notes — never anything when no AI call happens. People, phones and network identifiers are replaced by aliases by default.

**What if it proposes something I already automate?** Automations written in YAML cannot be read in detail (only UI-made ones), so it may; reject the proposal and it will not return.

**Does the license key unlock anything?** Not in this version.

---

## 🛠️ Local development

```bash
git clone git@github.com:gabipintea/ha-ai-brain.git
cd ha-ai-brain
python3 -m venv .venv && source .venv/bin/activate
pip install -e "ha_ai_brain[dev]"
cp .env.example .env            # keep simulator mode, or add a Home Assistant token
.venv/bin/pytest -v             # run the tests
.venv/bin/uvicorn ha_ai_brain.api.app:create_app --factory --host 127.0.0.1 --port 8099
```

Open `http://localhost:8099`. Without a Home Assistant token the brain runs against a built-in simulated smart home.

**Architecture:** hexagonal (ports & adapters). `domain/` holds the pure logic (triage, guardrails, arbiter, habit mining, backtesting, anomaly detection, watches, research), `application/` the orchestrator, learning engine and LangGraph agent workflows, `adapters/` Home Assistant, SQLite, LiteLLM, notifications and the sandbox, `api/` the FastAPI service and dashboard.

---

## 📄 License & Maintainer

* **Author**: Gabriel Pintea ([@gabipintea](https://github.com/gabipintea))
* **Repository**: [https://github.com/gabipintea/ha-ai-brain](https://github.com/gabipintea/ha-ai-brain)
