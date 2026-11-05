# Contributing to HA AI Brain

Thank you for your interest in contributing to **HA AI Brain**! 🎉

HA AI Brain is a generic, privacy-focused, multi-agent cognitive brain for Home Assistant. It learns habits locally (costing zero tokens), proposes native Home Assistant automations backed by backtests, flags anomalies, and leverages LLM agents for complex reasoning within hard safety guardrails.

This guide explains how to report bugs, suggest features, and contribute code.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)
- [Contributing Code (Pull Requests)](#contributing-code-pull-requests)
  - [Branching & Review Workflow](#branching--review-workflow)
  - [Development Environment](#development-environment)
  - [Running the Test Suite](#running-the-test-suite)
  - [Architectural Principles](#architectural-principles)
- [Community & Discussions](#community--discussions)

---

## Code of Conduct

Please follow our [Code of Conduct](CODE_OF_CONDUCT.md) in all interactions within this project. Be respectful, constructive, and welcoming.

---

## Reporting Bugs

Before reporting a bug:
1. Check the [Documentation](ha_ai_brain/DOCS.md) and [FAQ](ha_ai_brain/DOCS.md#14-faq).
2. Search [Existing Issues](https://github.com/gabipintea/ha-ai-brain/issues) to make sure it hasn't already been reported or solved.

When you are ready to report:
1. Go to [New Issue](https://github.com/gabipintea/ha-ai-brain/issues/new/choose) and select **🐛 Bug Report**.
2. Complete all form fields:
   - **HA AI Brain version** (from Home Assistant → Settings → Add-ons → HA AI Brain).
   - **Home Assistant Core & OS version**.
   - **Installation type** (HAOS, Supervised, Container, etc.) and hardware.
   - **AI Provider & Model** (e.g., Gemini, OpenAI, Claude, local Ollama).
   - **Steps to reproduce** the issue consistently.
   - **Expected vs. actual behavior**.
   - **Add-on logs**: Copy relevant logs from Home Assistant → Settings → Add-ons → HA AI Brain → *Log* tab.
   > 🔒 **Privacy Reminder:** HA AI Brain includes a built-in privacy scrubber that automatically replaces people and phone names, but please double-check your logs before posting to ensure no external IP addresses, private credentials, or API keys are exposed.

---

## Suggesting Features

We welcome ideas for new capabilities, improved heuristics, or new specialized agents!

To suggest a feature:
1. Go to [New Issue](https://github.com/gabipintea/ha-ai-brain/issues/new/choose) and select **💡 Feature Request / Idea**.
2. Explain the use-case or problem you are trying to solve.
3. Keep the **"Local first, AI last"** principle in mind:
   - HA AI Brain is built to be lightweight on hardware and tokens. Habit mining, normal range detection, backtesting, and watches should cost **zero tokens**.
   - If an idea can be calculated with local math, statistics, or state machines, propose it as a local detector rather than an LLM prompt.
   - LLMs are reserved for synthesis, cross-domain insights, natural language translation, and research homework.

---

## Contributing Code (Pull Requests)

### Branching & Review Workflow

Direct commits to the `main` branch are restricted to repository maintainers. Anyone can fork the repository and open a Pull Request.

1. **Fork** the repository on GitHub: `https://github.com/gabipintea/ha-ai-brain/fork`.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/ha-ai-brain.git
   cd ha-ai-brain
   ```
3. **Create a feature branch**:
   ```bash
   git checkout -b feature/my-feature-name
   ```
4. **Make your changes** following the architectural rules below.
5. **Run the tests** and ensure 100% pass rate.
6. **Push** your branch to your fork and submit a **Pull Request** targeting `main`.
7. All PRs are reviewed and approved by [@gabipintea](https://github.com/gabipintea) before merging. Automated CI tests must pass.

---

### Development Environment

HA AI Brain requires **Python 3.11+** (Docker runtime uses 3.12).

Set up a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e "ha_ai_brain[dev]"
```

Run against the built-in simulated smart home (no physical Home Assistant instance required):
```bash
# Start local API & dashboard
PYTHONPATH=ha_ai_brain/src uvicorn ha_ai_brain.api.app:create_app --factory --host 127.0.0.1 --port 8099
```
Open `http://127.0.0.1:8099` in your browser.

---

### Running the Test Suite

Always run the full test suite before submitting a PR:
```bash
# Using unittest runner:
PYTHONPATH=ha_ai_brain/src python -m unittest discover -s tests

# Or using pytest:
pytest -v
```

If you modify the dashboard (`ha_ai_brain/src/ha_ai_brain/api/dashboard_html.py`), verify that the embedded JavaScript is syntax-clean:
```bash
python3 -c "
import re
from pathlib import Path
content = Path('ha_ai_brain/src/ha_ai_brain/api/dashboard_html.py').read_text()
m = re.search(r'<script>(.*?)</script>', content, re.DOTALL)
Path('/tmp/dash.js').write_text(m.group(1))
"
node --check /tmp/dash.js
```

---

### Architectural Principles

All contributions must respect the project's core design rules:

1. **Hexagonal Architecture (Ports & Adapters):**
   - `domain/` contains pure logic only. No network calls, disk writes, or external framework dependencies. Keep it 100% unit-testable.
   - `application/` orchestrates workflows and imports only `domain/` and `ports/`.
   - `adapters/` implement abstract ports (Home Assistant REST/WS, SQLite, LiteLLM, notifications, sandbox).
   - `api/` handles FastAPI endpoints and the dashboard.
2. **Provider- and Model-Agnostic:**
   - All LLM access goes through LiteLLM. Never introduce vendor-specific logic that locks out other providers (Gemini, OpenAI, Anthropic, OpenRouter, and local Ollama must all work).
3. **Generic for Every Home:**
   - Never hardcode entity IDs, area names, device thresholds, or room layouts specific to one home. Behavior must be driven by data, learning, or user settings.
4. **No Personal Data:**
   - Never commit real person names, phone numbers, email addresses, external URLs, private IP addresses, or tokens. Use standard generic examples (`light.living_room`, `sensor.kitchen_temperature`).
5. **Keep Mirrored Files in Sync:**
   - The repository maintains root copies of certain files (`config.yaml`, `Dockerfile`, `run.sh`, `CHANGELOG.md`, `agents/`, `translations/`) that mirror `ha_ai_brain/`. Whenever you edit one copy, update both. CI enforces this check.
6. **Raspberry Pi Friendly:**
   - Keep memory usage bounded, batch SQLite writes, and avoid CPU-heavy polling loops.

---

## Community & Discussions

Have questions or want to show off your AI Brain automations?
- Join the discussion on the [Home Assistant Community Forum](https://community.home-assistant.io/).
- Open an issue on GitHub for bugs or feature ideas.
