# HA AI Brain — Home Assistant Add-On

Autonomous Multi-Agent Cognitive Brain for Home Assistant. HA AI Brain continuously analyzes your home’s sensor streams, identifies energy waste, predicts thermal inertia and solar heat gain, suggests optimizations, and protects your home with guardrails and human co-pilot approvals.

---

## 🚀 Quick Start in 3 Easy Steps

1. **Install the Add-on**:
   - In Home Assistant, navigate to **Settings** → **Add-ons** → **Add-on Store**.
   - Click the three dots (top right) → **Repositories** → Add `https://github.com/gabipintea/ha-ai-brain`.
   - Select **HA AI Brain** and click **Install**.

2. **Start the Add-on**:
   - Enable **Show in sidebar** and click **Start**.

3. **Onboard & Activate AI**:
   - Click **AI Brain** in your Home Assistant left sidebar (via Ingress).
   - In the **Settings** tab, choose your preferred AI provider:
     * **Google Gemini** (Free AI Studio key or Vertex Express)
     * **OpenAI ChatGPT** (`gpt-4o` or `gpt-4o-mini`)
     * **Anthropic Claude** (`claude-3-5-sonnet` or `haiku`)
     * **OpenRouter** (Aggregator for 100+ open and proprietary models)
     * **Local Ollama** (100% private, offline, zero external cloud spend)
   - Paste your API key (if using cloud AI) and describe your property layout in **Site Context**.
   - Click **Save & Apply AI Settings**.

That's it! Your Home Assistant entities, areas, and devices are automatically discovered with zero configuration.

---

## 🤖 Supported AI Providers

HA AI Brain works seamlessly out of the box with all leading AI models via LiteLLM:

| Provider | Model Name Examples | API Key / Setup | Notes |
| :--- | :--- | :--- | :--- |
| **Google Gemini** | `gemini/gemini-3.6-flash`<br>`gemini/gemini-3.5-flash` | Free key from [aistudio.google.com](https://aistudio.google.com/) | High speed, generous free tier, automatic fallback rotation. |
| **OpenAI** | `openai/gpt-4o`<br>`openai/gpt-4o-mini`<br>`openai/o3-mini` | API key (`sk-...`) from platform.openai.com | High accuracy structured JSON reasoning and HTTP rate limit tracking. |
| **Anthropic** | `anthropic/claude-3-5-sonnet-20241022`<br>`anthropic/claude-3-5-haiku-20241022` | API key (`sk-ant-...`) from console.anthropic.com | Deep reasoning and prompt caching. |
| **OpenRouter** | `openrouter/anthropic/claude-3.5-sonnet`<br>`openrouter/meta-llama/llama-3.3-70b-instruct` | API key (`sk-or-...`) from openrouter.ai | Flexible single key for hundreds of models. |
| **Local Ollama** | `ollama/llama3.2`<br>`ollama/mistral` | **None** (Point to your Ollama host) | **100% Private, offline, zero cloud spend.** |

---

## 🛡️ Autonomy Modes

You are always in complete control of how HA AI Brain acts:

* **Co-Pilot (Recommended default)**:
  The AI monitors your home and formulates optimization hypotheses. When an action is proposed (e.g., lowering heat before solar peak), it sends an actionable approval notification to your phone and creates a pending approval on the dashboard.
* **Shadow (Observe only)**:
  The AI simulates actions, calculates hypothetical savings, and records advisory insights without ever touching your real switches or thermostats.
* **Autonomous**:
  The AI automatically executes low- and medium-risk optimizations (e.g. radiator setbacks), while critical safety actions (unlocking doors, dangerous temperature extremes) always require human approval.

---

## 📱 Mobile Approvals & Notifications

When an optimization requires approval, HA AI Brain sends a Home Assistant mobile notification with action buttons directly to your phone:
- **Approve once**: Runs this time only.
- **Always allow**: Executes now and creates an automatic endorsement rule.
- **Reject**: Blocks the proposal.

*Need to revoke an always-allowed rule?* Simply navigate to the **Memory & Rules** tab in the dashboard and click **Revoke**.

---

## 🏠 Site Context

Adding a short description of your home in **Settings → Site & Building Context** dramatically improves the AI's reasoning accuracy:
> *Example: "Family of 4, two adults, two toddlers. 2-storey house (120 sqm) with underfloor heating driven by gas condensing boiler. Large south-facing windows with motorized aluminium shutters. 200 sqm lawn with automated sprinkler system."*
