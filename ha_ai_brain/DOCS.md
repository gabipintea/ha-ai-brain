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

## 🤖 Supported AI Providers & Model Selection Guide

HA AI Brain works seamlessly out of the box with all leading AI models via LiteLLM.

### Do Cheaper Models Perform Well in Home Assistant?
**Yes—compact "Flash / Mini" models are ideal for real-time smart home reflexes:**
* **Sub-Second Speed**: `gpt-4o-mini` and `gemini-2.5-flash` respond in **300–600ms**, allowing instant actuator reflexes.
* **Flawless JSON Schema Adherence**: Modern small models follow JSON schemas reliably for Home Assistant service calls.
* **Frontier Models for Batch**: Reserve flagship models (`claude-3-5-sonnet`, `gemini-2.5-pro`, `gpt-4o`) for scheduled Periodic Batch runs (every 6 hours) to author complex YAML automations and thermodynamic decay models.

### Recommended Models per Provider

| Provider | Primary Model (Real-Time & Sub-Agents) | Deep Batch Model (Periodic Audits & Automations) | Fallback Model | Est. Monthly Cost | Why This Combination? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Google Gemini** *(Free / Budget)* | `gemini/gemini-2.5-flash` | `gemini/gemini-2.5-pro` | `gemini/gemini-1.5-flash` | **$0.00** *(Free Tier)*<br>< $0.30/mo *(Paid)* | **Best for budget/free setups.** Very fast, massive context, free tier on Google AI Studio. |
| **OpenAI** *(Most Reliable)* | `openai/gpt-4o-mini` | `openai/gpt-4o` | `openai/gpt-4o-mini` | **~$0.20 – $0.50 / mo** | **Best for rock-solid stability.** Near-perfect schema adherence and high reliability. |
| **Anthropic Claude** *(Best Reasoning)* | `anthropic/claude-3-5-haiku-20241022` | `anthropic/claude-3-5-sonnet-20241022` | `openai/gpt-4o-mini` | **~$0.50 – $1.20 / mo** | **Highest intelligence.** Sonnet crafts the most sophisticated Home Assistant native automations. |
| **OpenRouter** *(Aggregator)* | `openrouter/google/gemini-2.5-flash` | `openrouter/anthropic/claude-3.5-sonnet` | `openrouter/openai/gpt-4o-mini` | **~$0.30 – $0.80 / mo** | **Maximum flexibility.** Use a single API key to mix Gemini for instant reflexes and Claude for deep batch audits. |
| **Local Ollama** *(100% Private)* | `ollama/qwen2.5:7b` *(or `llama3.2:3b`)* | `ollama/qwen2.5:14b` *(or `llama3.3:70b`)* | `ollama/qwen2.5:7b` | **$0.00** *(Zero cloud spend)* | **Best for strict privacy.** 100% offline, zero data leaves your local network. |

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
