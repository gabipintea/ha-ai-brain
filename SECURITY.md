# Security Policy

## Supported Versions

Security updates and bug fixes are provided for the latest minor release line.

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| < 0.2.0 | :x:                |

---

## Reporting a Vulnerability

We take the security and privacy of smart homes very seriously. If you discover a security vulnerability in HA AI Brain, please report it responsibly so we can fix it before public disclosure.

### How to Report

1. **GitHub Private Vulnerability Reporting (Preferred):**
   Go to the [Security Advisories](https://github.com/gabipintea/ha-ai-brain/security/advisories/new) page of the repository and click **"Report a vulnerability"**. This opens a private conversation visible only to repository maintainers.

2. **Direct Contact:**
   If you are unable to use GitHub Security Advisories, contact [@gabipintea](https://github.com/gabipintea) via GitHub or open a minimal issue requesting private security contact.

### What to Include

Please provide:
- A description of the vulnerability and its potential impact.
- Clear reproduction steps or a minimal proof of concept (PoC).
- The version(s) of HA AI Brain, Home Assistant Core, and OS tested.
- Any suggested mitigations or patches.

### Our Commitment

- We will acknowledge receipt of your report within 48 hours.
- We will provide an estimated timeframe for a fix and keep you updated on progress.
- Once fixed, a security patch release will be published with credit given to the reporter (unless you prefer anonymity).

---

## Privacy & Security by Design in HA AI Brain

HA AI Brain incorporates several architectural security boundaries:
- **Zero Cloud by Default for Learning:** Habit detection, statistical baselines, anomaly watches, and backtesting run entirely locally in SQLite without transmitting data to any cloud service.
- **Privacy Scrubber:** When cloud LLM providers are configured, an automated privacy scrubber removes person names, phone numbers, and network identifiers prior to prompt generation.
- **Strict Guardrails:** Destructive operations (door unlocking, security system disarming, garage doors, water/gas valves, and system restarts) are locked behind hard deterministic guardrails and cannot be executed autonomously by LLMs.
- **Local Python Sandbox:** Dynamic Python execution for calculations runs inside a locked down, restricted subprocess sandbox.
