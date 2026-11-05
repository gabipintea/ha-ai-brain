## 📝 Description

Please include a summary of the change, motivation, and relevant context. If this PR fixes an open issue, link it below.

Fixes # (issue reference, if applicable)

---

### 🏷️ Type of Change

- [ ] 🐛 Bug fix (non-breaking change fixing an issue)
- [ ] ✨ New feature / enhancement (non-breaking change adding new capability)
- [ ] 📖 Documentation update
- [ ] ⚡ Performance optimization / refactoring
- [ ] 🧪 Tests / CI improvements

---

### 🏛️ Architectural & Contribution Checklist

Before submitting, please verify that your PR adheres to the project guidelines:

- [ ] **Hexagonal Architecture**: `domain/` contains pure logic only (no network, disk, or framework imports). Concrete adapters stay in `adapters/`.
- [ ] **Local First, AI Last**: Features avoid unnecessary LLM calls where local statistics or deterministic logic suffice.
- [ ] **Generic for Every Home**: No hardcoded entity IDs, area names, brands, or thresholds specific to one physical house.
- [ ] **Provider-Agnostic**: Works across Gemini, OpenAI, Claude, OpenRouter, and local Ollama (uses `LLMProviderPort`).
- [ ] **No Personal Data**: Examples and tests use generic/invented names (`light.living_room`, `sensor.kitchen_temperature`).
- [ ] **Synchronized Root Copies**: If editing `config.yaml`, `Dockerfile`, `run.sh`, `CHANGELOG.md`, `agents/`, `translations/`, or `pyproject.toml`, the mirrored copy in `ha_ai_brain/` (or root) was updated identically.
- [ ] **Tests Pass**: Ran the full test suite (`python -m unittest discover -s tests` or pytest) and verified all tests pass.
- [ ] **New Tests Added**: Added unit tests for any new domain logic or adapter behavior.
