# 🧠 HA AI Brain (`ha-ai-brain`)

**Autonomous Multi-Agent Cognitive Layer for Home Assistant** built with **Python, LangGraph, FastAPI, and Hexagonal Architecture (Ports & Adapters)**.

Instead of manually conceiving and writing Home Assistant automations, specialized AI agents (**Climate & Thermal**, **Lighting & Habit**, **Security & Safety**, **Repair & Diagnostics**, and **User-Defined Custom Agents** such as **Solar Energy** or **Craft Beer Brewery**) observe Home Assistant telemetry, delegate scientific research and Python math computations to sub-agents, and autonomously react or synthesize native Home Assistant automations.

---

## ✨ Key Capabilities Implemented

1. **Hexagonal Architecture (Ports & Adapters)**
   * **Domain Core (`src/ha_ai_brain/domain/`)**:
     * [`EdgeSignalTriage`](src/ha_ai_brain/domain/triage.py): Deadband/hysteresis filtering (prevents token bankruptcy from sensor micro-jitter), causal loop prevention (`context_id` tracking), implicit human override detection ("never fight the human"), and spatial context corroboration.
     * [`ConflictArbiter`](src/ha_ai_brain/domain/arbiter.py): Priority hierarchy (`Life/Security > Explicit Human Override > Equipment/Structural Protection >Habit Prediction > Comfort > Energy`) and entity lease management to prevent multi-agent "thermostat/window wars".
     * [`GuardrailEngine`](src/ha_ai_brain/domain/guardrails.py): Deterministic physical bounds (`12°C–28°C` HVAC limits, critical lock/alarm protection) and **Repeatable Approval Signatures** (`sig:...`) so once a user endorses a repeatable reaction, it executes automatically in the future without asking again.
   * **Application & LangGraph Workflows (`src/ha_ai_brain/application/`)**:
     * [`ClimateAgentGraph`](src/ha_ai_brain/application/graphs/climate_agent.py): Full `langgraph.graph.StateGraph` supporting both **Mode A (`realtime_stream`)** and **Mode B (`periodic_batch`)**.
     * [`ResearchSubAgent` & `ComputationSubAgent`](src/ha_ai_brain/application/graphs/subagents.py): Discovers building-physics/psychrometric formulas and runs Python scientific calculations inside [`PythonSandboxAdapter`](src/ha_ai_brain/adapters/sandbox_python.py) (computing Magnus-Tetens Dew Point, interior glass temperature, condensation margin, solar heat gain index, and thermal decay rate $dT/dt$).
   * **Ports (`src/ha_ai_brain/ports/`) & Adapters (`src/ha_ai_brain/adapters/`)**:
     * [`HomeAssistantAdapter`](src/ha_ai_brain/adapters/ha_websocket_rest.py) (live WebSocket + REST + Supervisor auto-auth) & [`SmartHomeSimulatorAdapter`](src/ha_ai_brain/adapters/ha_simulator.py) (Digital Twin for testing).
     * [`LiteLLMAdapter`](src/ha_ai_brain/adapters/llm_litellm.py) (OpenAI, Anthropic, Gemini, Ollama, Managed SaaS Proxy, plus offline scientific reasoner).
     * [`SQLiteMemoryAdapter`](src/ha_ai_brain/adapters/memory_sqlite.py) (episodic feedback memory, endorsed repeatable rules, pending approvals, advisory insights, and closed-loop outcome checks).
     * [`ExtensibleMcpClientAdapter`](src/ha_ai_brain/adapters/mcp_router.py) (Router DHCP/ARP MCP tools for the Repair & Diagnostics Agent).
     * [`CommercialLicenseAdapter`](src/ha_ai_brain/adapters/billing_license.py) (BYOK Lifetime License & Monthly Managed AI Subscription token metering).

2. **Home Assistant Add-on & Docker Packaging**
   * Ready-to-install Home Assistant Add-on ([`config.yaml`](config.yaml), [`Dockerfile`](Dockerfile), [`run.sh`](run.sh), [`repository.yaml`](repository.yaml), [`docker-compose.yml`](docker-compose.yml)) with HA Ingress sidebar panel support (`port 8099`).

3. **Declarative Custom Domain Agents (`agents/*.yaml`)**
   * Includes [`agents/solar_energy_agent.yaml`](agents/solar_energy_agent.yaml) and [`agents/beer_brewery_agent.yaml`](agents/beer_brewery_agent.yaml).

---

## 🚀 Quickstart (Local Development & Testing)

```bash
# 1. Run the automated verification suite
.venv/bin/pytest -v

# 2. Launch the HA Ingress Control Plane & Interactive Simulator Dashboard
.venv/bin/uvicorn ha_ai_brain.api.app:create_app --factory --port 8099
```

Then open `http://localhost:8099` in your browser to test live **Window Condensation** events, **Solar Gain + UFH Thermal Inertia** events, **Repeatable Guardrail Approvals**, and **Periodic Batch Analysis**.
