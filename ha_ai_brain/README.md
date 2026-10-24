# 🧠 HA AI Brain (`ha-ai-brain`)

[![Home Assistant Add-on](https://img.shields.io/badge/Home%20Assistant-Add--on-blue.svg?logo=home-assistant)](https://github.com/gabipintea/ha-ai-brain)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: Proprietary](https://img.shields.io/badge/license-Proprietary-green.svg)]()
[![Multi-Provider AI](https://img.shields.io/badge/AI%20Providers-Gemini%20%7C%20OpenAI%20%7C%20Claude%20%7C%20Ollama-orange.svg)]()

**Autonomous Multi-Agent Cognitive Layer for Home Assistant** built with **Python, LangGraph, FastAPI, and Hexagonal Architecture**.

Instead of manually crafting fragile automations, specialized AI agents (**Climate & Thermal Inertia**, **Lighting & Habit**, **Security & Safety**, **Repair & Diagnostics**, and **Custom User Agents** like **Solar Energy & Battery**) continuously observe Home Assistant telemetry, discover physics and psychrometric formulas, and formulate proactive optimizations with built-in human co-pilot approvals and deterministic safety guardrails.

---

## 📦 Production: Installing as a Home Assistant OS Add-on

You can install HA AI Brain directly onto your Home Assistant OS instance (Green, Yellow, Raspberry Pi 4/5, x86/ODROID):

1. In Home Assistant, open **Settings** → **Add-ons** → **Add-on Store**.
2. Click the **⋮** menu (top right) → **Repositories**.
3. Paste the repository URL:
   ```text
   https://github.com/gabipintea/ha-ai-brain
   ```
4. Click **Add**, close the modal, and refresh the store.
5. Click on **HA AI Brain** → **Install**.
6. Turn on **Show in sidebar**, then click **Start**.
7. Click **AI Brain** in your Home Assistant left sidebar to open the Ingress dashboard and complete initial onboarding!

### 🎯 Zero-Friction Onboarding in Home Assistant
When running as an add-on, **connection to Home Assistant is 100% automatic** (via Supervisor internal token). You never need to copy Long-Lived Access Tokens or configure local network URLs.

In the dashboard **Settings** tab:
* **Pick your AI Provider**: Google Gemini (free AI Studio key), OpenAI ChatGPT (`sk-...`), Anthropic Claude (`sk-ant-...`), OpenRouter, or 100% local offline Ollama (`ollama/llama3.2`).
* **Describe your home**: Add a few lines in **Site & Building Context** (rooms, heating type, window orientation, occupants).
* **Select your phone**: Choose your device from the discovered notification services list (`notify.mobile_app_...`).

---

## 🛠️ Local Development & Testing Environment

You can continue developing and testing locally on your Mac/Linux workstation while running production on your Home Assistant machine:

```bash
# 1. Clone & activate virtual environment
git clone git@github.com:gabipintea/ha-ai-brain.git
cd ha-ai-brain
python3 -m venv .venv
source .venv/bin/activate
pip install -e ha_ai_brain

# 2. Configure development environment (.env)
cp .env.example .env  # Add your live HA Nabu Casa token or keep simulator mode

# 3. Run all unit and integration tests
.venv/bin/pytest -v

# 4. Launch local dev server with hot reload
.venv/bin/uvicorn ha_ai_brain.api.app:create_app --factory --host 0.0.0.0 --port 8099
```

Open `http://localhost:8099` to access your local development dashboard.

---

## ✨ Architecture & Core Capabilities

1. **Hexagonal Architecture (Ports & Adapters)**
   - **Domain Core**: Signal triage, deadband jitter filtering, causal loop prevention, conflict arbitration hierarchy (`Life > Human > Equipment > Comfort > Energy`), and deterministic physical guardrails.
   - **LangGraph Workflows**: Real-time event streaming + periodic batch deep-think analysis with sub-agents running sandbox calculations (Dew point, window condensation risk, solar heat gain index, and thermal decay rate $dT/dt$).
   - **Multi-Provider AI**: Google Gemini, OpenAI, Claude, OpenRouter, and Ollama with live rate-limit tracking, session spend accounting, and automatic fallback cooldown rotation.
   - **SQLite Episodic Memory**: Rejection tracking, user context notes, repeatable approval rules, and advisory insights.

2. **Human Co-Pilot & Actionable Approvals**
   - Actionable mobile notifications with **Approve once**, **Always allow** (creates an automatic endorsement rule), and **Reject**.
   - Manage and revoke endorsed rules or unblock rejected actions at any time via the dashboard.

---

## 📄 License & Maintainer

* **Author**: Gabriel Pintea ([@gabipintea](https://github.com/gabipintea))
* **Repository**: [https://github.com/gabipintea/ha-ai-brain](https://github.com/gabipintea/ha-ai-brain)
