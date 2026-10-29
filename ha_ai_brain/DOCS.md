# HA AI Brain — User Manual

HA AI Brain is a background "brain" for your Home Assistant. It watches what happens in your home, learns what is normal for **your** house, notices what is unusual, turns your own recurring habits into native Home Assistant automations, and lets a team of specialised AI agents think about the harder questions — always inside safety limits that you control.

**Contents**
1. [In one minute](#1-in-one-minute)
2. [Quick start](#2-quick-start)
3. [How it works](#3-how-it-works)
4. [Complete feature list](#4-complete-feature-list)
5. [The dashboard, tab by tab](#5-the-dashboard-tab-by-tab)
6. [Settings reference](#6-settings-reference)
7. [Recommended rollout](#7-recommended-rollout)
8. [AI providers and models](#8-ai-providers-and-models)
9. [Data, privacy and security](#9-data-privacy-and-security)
10. [Costs and how to control them](#10-costs-and-how-to-control-them)
11. [Custom agents and extra knowledge](#11-custom-agents-and-extra-knowledge)
12. [Troubleshooting](#12-troubleshooting)
13. [Known limitations](#13-known-limitations)
14. [FAQ](#14-faq)

---

## 1. In one minute

* It **discovers** your entities, areas and devices by itself. You configure nothing about your house.
* It **records** every relevant state change and imports your recent Home Assistant history. This costs no AI tokens.
* From that history it **learns locally** (no AI): your habits, what each device normally does at each hour, how long things usually stay on or open, and what every sensor normally reads.
* It **proposes native Home Assistant automations** for your strong habits, after replaying them against your own history ("backtest"). You approve them.
* It **tells you when something is unusual** — a door open while everybody is away, a light on far longer than ever before, a sensor far out of range, a device that went silent, an automation that did not run.
* It lets you **describe your own alerts in plain language** ("watches"); the AI interprets them once, then they run for free.
* Specialised **AI agents** (Climate, Lighting, Security, Energy, Shading, Repair, plus your own) regularly look at the **whole picture of your home** — all current states, their recent trends and the existing automations — and come up with **insights, recommendations and new automation ideas, even when nothing is wrong** (for example "condensation risk on windows" from indoor humidity, indoor temperature and the outdoor temperature). Between those scheduled analyses the AI is only woken for unusual events.
* The agents also do **research homework**: they think like specialists and propose practical knowledge for your equipment. It is only used after you approve it.
* **You decide how much it may do on its own**: shadow, co-pilot or autonomous — per device type — with an Undo button, rate limits, quiet hours, a token budget and a kill switch.

---

## 2. Quick start

1. **Install**: *Settings → Add-ons → Add-on Store → ⋮ → Repositories* → add `https://github.com/gabipintea/ha-ai-brain` → install **HA AI Brain**.
2. **Start** it and switch on **Show in sidebar**. Open **AI Brain** in the sidebar (it runs inside Home Assistant's ingress; there is no separate login and no port to open).
3. **Pick an AI provider** in *Settings → AI Provider & Site Context*: choose a preset (Google Gemini, OpenAI, Anthropic, OpenRouter, Ollama) or type any model name, paste the API key, describe your home in *Site & Building Context* and press **Save & Apply AI Settings**.
4. **Choose your phone** under *Settings → Operating Settings → Notification target* (a `notify.mobile_app_…` service) so approvals reach you as push notifications.

On the very first start with an API key configured, the brain runs one analysis within a few seconds and imports up to 10 days of history from Home Assistant in the background. Leave **Autonomy** on *Co-pilot* (the default) until you have read [Recommended rollout](#7-recommended-rollout).

---

## 3. How it works

### 3.1 The loop

```
 ┌───────────────┐   ┌────────────────┐   ┌───────────────────┐   ┌────────────────┐   ┌──────────────┐
 │  1. OBSERVE   │ → │  2. LEARN      │ → │  3. DECIDE        │ → │  4. THINK      │ → │  5. ACT / ASK │
 │ live events + │   │ locally, free: │   │ is this worth an  │   │ specialised AI │   │ safety checks │
 │ HA history    │   │ habits, normal │   │ AI call? (gating, │   │ agents, once   │   │ approvals,    │
 │               │   │ ranges, routines│  │ exceptions)       │   │ per real need  │   │ undo, verify  │
 └───────────────┘   └────────────────┘   └───────────────────┘   └────────────────┘   └──────────────┘
```

1. **Observe.** A live connection receives every `state_changed` event (plus Companion-App button presses and automation runs). At startup the brain also imports recent history from Home Assistant so it does not start from zero.
2. **Learn (local, free).** Everything relevant is stored in a compact database: every switch/lock/cover/binary state change, and hourly averages for numeric sensors. From it the brain mines habits, builds per-entity profiles ("how long does this usually stay on?", "what does this sensor read at 3 pm on a weekday?") and replays proposals against your history.
3. **Decide.** Most events are boring. The brain filters them in several layers before any AI is involved:
   * **Triage**: tiny sensor wiggles are ignored (deadbands), and changes the brain itself caused are recognised and skipped.
   * **Human-override detection**: if you reverse something the brain did, it backs off that device for 15 minutes and remembers.
   * **Automation attribution**: changes caused by your existing Home Assistant automations are not mistaken for human habits.
   * **Gating** (once ~3 days of history exist): a sensor reading that is normal for this time of day, or a device change that is already routine or already handled by an automation, does **not** wake an AI agent.
4. **Think.** When something does deserve attention, the matching specialised agent gets a compact brief: current states, locally computed statistics, who is home, weather/sun/tariff data, your notes, past feedback, and relevant knowledge. It answers with proposed actions, insights or automations.
5. **Act or ask.** Every proposed action passes deterministic safety checks (section 4.8). Depending on your autonomy setting it is logged only (shadow), sent to you for approval (co-pilot), or executed (autonomous). Autonomous actions come with an Undo button. Expected effects are checked against sensors afterwards.

### 3.2 What is free and what uses AI tokens

| Part | Uses AI tokens? |
|---|---|
| Recording events, importing history | No |
| Habit mining, baselines, profiles, routines | No |
| Automations generated from your habits | **No** |
| Backtesting every proposed automation | No |
| Unusual-situation detection (all detectors) | No |
| Running your watches | No |
| Compiling a watch from plain language | One short call, once per watch |
| Deciding whether an event wakes an agent (gating) | No |
| An agent reacting to an event | Yes (fast model) |
| Periodic batch analysis per agent | Yes (deep model), skipped when nothing changed |
| Research topic planning and research | Yes, a few calls per agent per week |
| Notifications, approvals, undo, dashboard | No |

### 3.3 Operating modes

| Mode | Live events | Scheduled batch analysis | Typical use |
|---|---|---|---|
| **Periodic batch** | Recorded and learned from, **never** sent to agents | Yes (default every 6 h) | Lowest token use; learning phase |
| **Real-time stream** | Significant events can wake agents | No scheduled batches (manual "Run analysis now" still works) | Reflexes only |
| **Hybrid** (default) | Significant events can wake agents | Yes | Everything |

In every mode the brain keeps recording and learning, checks for unusual situations every 5 minutes, and evaluates your watches every minute. In *Periodic batch* mode an unusual situation produces an alert but no agent run.

Habit-based automation proposals and the agents' periodic analyses are produced by the scheduled (or manual) analysis, so use *Hybrid* or *Periodic batch* — or press **Run analysis now** — if you want them while in *Real-time stream* mode.

### 3.4 The specialised agents

| Agent (`agent_id`) | Goal | Watches (domains) | May act on (domains) | Can propose automations | Runs when |
|---|---|---|---|---|---|
| **Climate & Indoor Environment** (`climate_thermal_agent`) | Building-physics view of comfort and risks: condensation, thermal lag, ventilation, heating/cooling; control climate, fans, humidifiers and covers or notify you | sensor, climate, weather, cover, fan, humidifier (temperature, humidity, light level, CO₂, VOC, pressure) | climate, fan, humidifier, cover, notify, automation | Yes | Your home has at least one of the devices it operates |
| **Lighting & Habit Automation** (`lighting_pattern_agent`) | Tell real manual habits from automated ones; act on lighting or propose automations for recurring routines | light, binary_sensor, sensor, sun, person (light level, motion, occupancy, presence) | light, scene, notify, automation | Yes | Your home has lights or scenes |
| **Security & Safety** (`security_safety_agent`) | Combine who is home with doors, windows, leaks, smoke and gas to protect the property; proposes the actual actuator call, which always asks you first | lock, alarm_control_panel, binary_sensor, cover, person (door, window, lock, moisture, smoke, gas) | lock, alarm_control_panel, cover, valve, notify, automation | Yes, for protective routines only (anything that unlocks, disarms or opens always needs your approval) | Your home has locks, alarms, covers or valves |
| **Energy, Power & Solar** (`energy_efficiency_agent`) | Find standby waste, shift flexible loads to cheap or solar-surplus hours, flag energy anomalies | sensor, switch, climate, binary_sensor (power, energy, battery, current, voltage) | switch, climate, notify, automation | Yes | Your home has switches or climate devices |
| **Cover & Solar Shading** (`cover_shading_agent`) | Blinds and shutters follow sun, glare and weather; night closing in winter; automate manual adjustments | cover, sensor, sun, weather, binary_sensor (blind, curtain, shade, shutter, window, light level, temperature) | cover, notify, automation | Yes | Your home has covers |
| **Repair & Diagnostics** (`repair_diagnostics_agent`) | Diagnose unavailable entities and error logs, self-heal or report; may propose an automation for a recurring reliability problem (for example a low battery) that nothing else covers | device_tracker, sensor, switch, climate, light | homeassistant, notify, automation | Yes | Only when some entity is unavailable |

All six are **enabled** by default and appear in the Settings tab. Things that apply to every agent:
* **Permission = "May act on".** An action in any other domain is blocked and shown in the activity log. `automation` means the agent may propose new native automations (they always need your approval); an agent without it is told so and suggests ideas as insights instead. `notify` and `homeassistant` are generic and never count as "owning devices".
* **"Runs when"** is for the scheduled analysis: an agent with nothing to look at in your home is skipped without an AI call. Real-time reactions additionally need a significant, non-routine event in its field.
* **Change one** by saving a file with the same `agent_id` in `/config/ha_ai_brain/agents/` (section 11). **Add your own** the same way. Two disabled examples (solar/energy and brewery) ship as templates.
* Besides the agents, some sources appear in the logs that are not AI agents (see below).

Each agent is a persona with goals, the entity types it watches and the services it is allowed to call. An agent can only act through the device types it is declared to control. You can add your own (section 11). Every agent run follows the same pipeline: gather context → consult its expert notes (generated once per setup and cached; this is separate from the weekly *Research* tab) → compute derived signals (sandboxed Python written by the AI, run in an isolated process) → synthesise actions or insights.

Three more "system" sources appear in logs although they are not AI agents: **pattern_miner** (statistical habit automations), **automation_lifecycle** (health reviews, digests, trust suggestions) and **watch_monitor** / **exception_monitor** (alerts).

### 3.5 When does the AI look at my entities? (and what does it not see)

There are two different ways the AI is used, and it helps to keep them apart:

| | **Scheduled analysis** ("the brain thinking about your home") | **Real-time reaction** |
|---|---|---|
| When | Every `batch_analysis_interval_minutes` (default 6 h), once at first start, and whenever you press **Run analysis now** | Only when a significant event happens |
| What the AI sees | The current states of all entities in that agent's field, locally computed trends over the lookback window (min/max/mean/slope per entity), who is home, weather/sun/tariffs, your existing automations, your notes, past feedback, approved knowledge | The event, the related entities in the same area/outdoors, the same context |
| What it produces | **Insights and recommendations**, **new automation ideas**, optional parameter tweaks | Immediate corrective actions |
| Needs something to be wrong? | **No.** This is the "look at my sensors and suggest something clever" part | Yes — only unusual or non-routine events wake it |

So the brain does **not** only react to outliers. The scheduled analysis is what produces ideas such as "you have indoor humidity, indoor temperature and an outdoor temperature sensor, so condensation risk on the windows can be calculated and an automation can warn you". To do that the agent can write a small calculation (for example a dew-point formula), run it in the sandbox on your real values, and then propose an insight or a native automation based on the result.

Good to know:
* **Scope.** Each agent only looks at the entity types in its field (section 3.4). Sensors with unusual classes that no agent covers (for example soil moisture, particulate matter or noise sensors) are not examined unless you add a [custom agent](#11-custom-agents-and-extra-knowledge) for them.
* **It skips when nothing changed.** If the set of sensors, the states of switches/locks/covers, your automations, notes and ignore list are all the same as at the last analysis, and fewer than 25 events happened, the agent is not called again for up to 24 hours. **Adding a new sensor counts as a change**, so the next scheduled analysis (or **Run analysis now**) looks at it.
* **Size limits.** At most about 250 entities per prompt and 300 entities of history per run (adjustable); the most dynamic entities are summarised first.
* **Where the results appear.** Recommendations in *Activity & Insights* (and as a push notification, unless you are in Shadow mode); proposed automations in *Approvals* with a backtest where possible.
* **Your existing automations.** It avoids proposing something an existing automation already does. It can read automations created in the Home Assistant UI, and YAML automations that have an `id:`; automations without an `id:` are only visible by name.
* **Quality.** The ideas come from the AI model you configured. A stronger deep model produces better and more original ideas; the numbers it uses come from your real data, but you should still read the reasoning on each proposal.

---

## 4. Complete feature list

### 4.1 Understanding your home
* **Zero-configuration discovery** of entities, areas, devices, services and notification targets through the Supervisor connection.
* **Area resolution** from the area/device/entity registries, with a name-based fallback for entities without an area.
* **History import** at startup (switchable entities up to 240 h; numeric sensors up to 96 h as hourly aggregates; up to 300 entities, configurable).
* **Site & Building Context**: free text describing your home that is given to the agents.
* **Context notes** (*Memory & Rules*): permanent instructions such as hardware limits or preferences. Agents must obey them.
* **Ignore list** (*Memory & Rules*): patterns (`sensor.vendor_*`, `*device_name*`, exact IDs) that are removed from triage, learning and agent context entirely.
* **Minimum change per sensor** (*Memory & Rules*): for a noisy numeric sensor you name (exact ID or a wildcard such as `sensor.*_voltage`), moves smaller than the value you set are not treated as significant live events, so they never wake an AI agent. They are still recorded for learning. Nothing is applied automatically: only the sensors you list. Slow drift still counts, because each new value is compared with the last one that mattered.
* **Household context** built locally: who is home, part of day, weekday/weekend, sun, weather and hourly forecast, electricity price and solar-forecast sensors (found by their names/classes).

### 4.2 Learning without AI
* **Telemetry store**: state transitions and hourly sensor averages, kept 90 days by default.
* **Habit mining**:
  * *Time habits* — "this entity goes to state X around 23:00" (weekday/weekend aware, ±20 min clustering).
  * *Sequences* — "B happens within 10 minutes after A" (with a statistical-lift filter so coincidences are ignored).
  * *Shared-trigger filter* — a "B follows A" sequence is dropped when the two only react to the same hidden trigger (for example several separate automations that all start at sunset). Four local checks: **(1)** both changed right after the same third event (such as an automation or a script running; their runs are recorded for this) and the pair no longer holds without it; **(2)** both happen at a fixed or smoothly drifting time of day, so they are two separate time habits; **(3)** one trigger is followed by many different devices (a scene); **(4)** changes made by automations or scripts are not used as triggers (device changes inside a script run are recognised through the script's run context), and bursts of many devices switching within seconds are ignored. Every dropped pair is listed with its reason in the Learned tab under **Habits ignored on purpose**.
  * *Scripts you start by hand* — "this script is run around 21:00" is a time habit like any other (runs started by an automation or the brain are not counted). It can be proposed as an automation calling `script.turn_on`; since the brain cannot see what a script does, this is always **high risk** and needs your approval, even in Autonomous mode. Only scripts you really run by hand qualify. A script already run by one of your UI-made automations counts as automated.
  * *Devices exposed twice* — if one physical device appears through two integrations (for example Matter and HomeKit), the device registry shows the same manufacturer and serial number on two devices. The brain treats such entities as one: it merges their history onto the entity that supports more controls (and is reachable, has an area), ignores the second report of the same change, counts an automation on either entity as covering the habit, and raises one alert instead of two. Entities of one device (a blind and its battery) and entities without a usable serial number are never merged. See **Devices seen twice** in the Learned tab; **Not the same device** undoes a wrong match.
  * Changes caused by your automations or by the brain itself are not counted as habits. History imported at startup cannot tell who caused a change, so imported changes count; live changes are classified.
* **Coverage detection**: the real triggers and actions of your UI-created Home Assistant automations are parsed, so a habit that is already automated is recognised.
* **Automations from habits without AI**: strong, un-automated habits (≥ 75 % reliable over at least 4 days; sequences ≥ 5 times) become native automation proposals — up to 3 per cycle. They fire slightly *before* your usual manual action, add a "someone is home" condition when switching things on, and never automate unlocking or disarming.
* **Backtesting**: every proposed automation (from habits or from an AI agent) is replayed over your recorded history: how often it would have fired, how many times that matches what you did by hand, how often you did the opposite. Proposals that clearly contradict your behaviour are dropped; the rest show a **Backtest** box on the approval card. Supported for time and state triggers; other triggers are labelled "not verifiable".
* **Habits list** (Learned tab): a live view of your *current* habits, recomputed at most every 30 minutes from the last 30 days and limited to the 40 strongest. A habit disappears by itself when your behaviour changes and its reliability drops below the threshold; nothing is stored or needs clearing. Light/switch twins and identically named devices count as one habit. Each habit shows whether an automation already covers it. Noise is filtered out: in-between states such as a blind *opening* or a lock *locking* never start a "when A happens, B follows" habit, two entities that always follow each other (for example the same blind exposed by two integrations, such as Matter and HomeKit) are dropped in both directions, and so are same-named entities of the same type. A habit that is **not automated yet** has a **Propose automation** button: strong habits are proposed automatically (at least 75 % reliable over at least 4 days, up to 3 per scan), but with the button you can send a weaker one to *Approvals* right now. It gets the same backtest, guardrails and approval as any proposal (a proposal whose backtest clearly contradicts your behaviour is still dropped, and one you rejected before stays blocked until you unblock it).
* **Baselines**: for each numeric sensor, its usual value for each hour of weekday/weekend.

### 4.3 Reacting to events in real time
* **Triage**: deadbands per measurement type (temperature, humidity, illuminance, power, CO₂), proportional dead-bands for noisy outdoor light and power, a 10-minute dwell guard, anti-flap guard, causal-loop prevention, human-override lockout (15 min), and attribution of changes caused by native automations.
* **Corroboration**: an event is sent to the agent together with sibling entities of the same area, outdoor/weather/sun entities and existing automations.
* **Gating** (after ~3 days of history): events that are typical for the hour, routine, or already automated do not call the AI. Security-relevant events always do. The Learned tab shows how many AI calls were avoided.
* **Agent reaction**: the agent proposes concrete service calls, which go through the safety pipeline (4.8).
* **Outcome verification**: if an agent predicted an effect ("humidity below 55 %"), the brain checks the sensor later and records success or failure as feedback the agent sees next time.

### 4.4 Periodic batch analysis
Each active agent analyses a longer window (default 24 h, up to 720 h) and returns:
* **Advisory insights** — findings with evidence, a recommended action and an estimated impact.
* **Native automation proposals** — checked against your existing and pending automations (by meaning, not just by name), your rejected proposals, and the backtest.
* **Immediate parameter tweaks** — optional actions through the normal safety pipeline.

An insight that is still in your list is **not offered again** by the same agent (same or very similar title), so you can leave meaningful ones there as a to-do list (for example "replace the battery"). Mark it read once it is fixed, **Reject** it to stop it for good, or delete it (it may then come back at a later analysis).

Cost savers: an agent is **skipped when its inputs are unchanged** since the last run and few new events happened; research results are **cached** per entity set for 72 h; sensor history is summarised locally (min/max/mean/trend per entity over the whole window) instead of being sent raw. Scheduled batches also pause while the AI provider is in a quota cool-down.

### 4.5 Unusual situations (exceptions)
Checked every 5 minutes without AI. There is **no list of devices or situations to maintain**: normal is learned per entity, and only the *severity* depends on whether the entity is safety-relevant (locks, alarms, valves, door/window/garage/leak/smoke/gas sensors) and on whether anyone is home or it is night.

| Detector | Fires when |
|---|---|
| Broken routine | An entity is, for a while, in a state that contradicts what it reliably is at this hour (e.g. ≥ 90 % of comparable days) |
| Abnormally long state | An entity stays in a non-resting state far longer than it ever (or almost ever) did |
| Gone silent | An entity that normally changes several times a day has not changed for much longer than its longest usual pause |
| Flapping | Far more state changes in the last hour than this entity normally produces |
| Out-of-range sensor | A numeric sensor is far outside its usual range for this hour, in two consecutive readings |
| Stale sensor | A sensor that normally reports every few minutes has not reported for hours |
| Stuck unavailable | Entities have been unavailable for over an hour (many at once become one alert) |
| Automation did not run | A time-based automation promised a state that is not there and nobody changed it since |
| Open house while away | Nobody home for 10+ minutes and a lock is unlocked, an alarm disarmed, or a door/garage/window is open |

Alerts appear in *Activity & Insights* and as a push notification (security alerts are time-sensitive and ignore quiet hours). An agent is then asked what to do about it — only for that situation — and, where a device can fix it, proposes the **direct action** (for example *lock the front door now*). In Co-pilot mode that arrives as a second push with **Approve once / Always allow / Dismiss / Reject** (for critical situations it also breaks through quiet hours); in Autonomous mode for that device type it is simply done and you are told. If no device can fix it (for example a window without a motor), you only get the alert. Controls: at most 5 new alerts per check and 20 non-critical per day; calm alerts are held back while the house is empty; cumulative counters (energy totals) are ignored.

**It learns from you:** *Dismiss* an alert and the same alert waits twice as long next time (up to 14 days). *Reject* it and it is muted until you unmute it under *Learned → Muted alerts*.

### 4.6 Watches — your own alerts in plain language
In *Memory & Rules → Watches* describe what you want to be told about: what, for how long, when, and whether someone must be home. The AI turns it into a precise rule **once**; you see how it understood you, which entities it matched, and how often the rule would have fired over your recent history, then you save it. From then on it runs locally every minute at no token cost.

A watch can test a **state** (is / is not a value), a **number** (above and/or below a limit, also on an attribute), or **silence** (nothing reported for N minutes), optionally for a minimum duration, only when someone is home or away, only inside a time window, only on certain weekdays, with a severity (info/warning/critical), a message and a cooldown. Up to 100 watches. You can pause or remove them at any time.

### 4.7 Research — agents doing their homework
Every week (first run one day after start) each agent plays the specialist in its field and proposes practical knowledge for **your** setup: settings worth checking, maintenance, efficiency, safety and cost ideas. Topics come from:
* your **real equipment** — manufacturer and model from the device registry ("known issues and recommended settings for …"), and
* **the agent's own planning**, asking what a specialist would investigate for this home, avoiding anything researched or rejected before.

Findings show the AI's confidence, concrete "apply it" steps in Home Assistant terms, caveats and any standards/documents the model says it relies on (unverified). **Nothing is used until you press Keep** in the *Research* tab; approved findings are given to the matching agent when it reasons. Rejected subjects are never researched again. It works with **any** AI provider.

*Optional deep research (Google Gemini only, off by default):* adds web search with cited, clickable sources and a "% sourced" figure. More informed, but noticeably more tokens. If the search returns nothing, the normal research answers instead.

A small built-in set of generic reference notes (humidity, condensation, ventilation, heating setback, hot-water safety, …) is also given to the agents; it is labelled *unverified seed guidance*. You can add your own (section 11).

### 4.8 Safety and control
**Autonomy levels** (global, with per-device-type overrides):

| Level | What happens to a proposed action |
|---|---|
| **Shadow** | Logged only. Nothing is executed, no approval requests are sent, and routine insight pushes are not sent (unusual-situation and watch alerts still are). |
| **Co-pilot** (default) | Sent to you for approval — unless you previously chose *Always allow* for that kind of action. |
| **Autonomous** | Low- and medium-risk actions run automatically (with an Undo notification). High- and critical-risk actions still need your approval. |

You can override the level for one device type, for example `light → autonomous`, `lock → co-pilot`, `automation → co-pilot` (see the FAQ about automations in Autonomous mode).

**Deterministic guardrails** (applied to every action, whatever the AI says):
* Climate setpoints outside **12–28 °C** are blocked.
* Domains that run arbitrary code or manage the host (`shell_command`, `python_script`, `pyscript`, `command_line`, `rest_command`, `hassio`, `script`, `recorder`) are blocked, also when they appear inside a proposed automation.
* **Critical** (always needs approval): unlocking/opening locks, disarming alarms, opening a garage door or gate. *Garage door or gate* is recognised by Home Assistant's own **device class** (`garage`, `gate`) or by the whole words "garage" / "gate" in the entity id or friendly name (so `investigate` does not match), on covers and also on switch-like openers (`switch`, `button`). Closing, locking, arming, stopping and switching off are never escalated. Anything else (a driveway barrier, a carport door, a barn...) can be added under **Settings → Learning & Safety → "Extra doors, gates or devices that always need approval to open"**: a comma-separated list of exact entity ids (`cover.driveway`), patterns (`*carport*`) or single words (`barn`).
* **High** (never automatic): closing a valve, restarting Home Assistant, moving a cover beyond 30 % (blinds, shades, curtains and shutters are treated as lower risk).
* Creating an automation is at least **medium** risk, **and its risk is the highest of whatever its actions would do later on their own**. The guardrails look inside every automation an agent proposes (including nested conditions, choices and parallel steps): one that would unlock or open a lock, disarm an alarm, open a garage door or gate is **critical** (you must approve it even in Autonomous mode and even if you chose *Always allow* for similar actions); one that would close a valve, restart Home Assistant or call a service chosen by a template is **high**; one that calls a code-running or host-managing service is **blocked**. The approval card names the reason.
* Anything you rejected before (same agent, same service, same device) is blocked.
* Agents may only call device types they are declared to control; targets that do not exist are rejected; actions that would change nothing (already in that state) are suppressed; identical or opposing proposals that are already awaiting your decision are suppressed.

**Conflict arbiter**: devices are leased for 5–10 minutes with priorities (life/security > human override > equipment protection > habit > comfort > energy) so agents never fight each other or you.

**More rails:** hourly action caps (30 total, 3 per device), unanswered approvals expire after about 24 h, **quiet hours** (low-priority pushes are held; security alerts break through), **daily token budget**, **kill switch** ("Pause brain": keeps learning, never acts or calls the AI in real time), **Undo** for 24 h on every autonomous action (undoing also teaches the brain not to repeat it; locks are never auto-reverted), and **ingress-only** access to the dashboard and API.

### 4.9 Approvals and notifications
* An approval request shows what, why, risk, the backtest (for automations) and the agent's reasoning. Push buttons: **Approve once**, **Always allow** (creates an endorsement rule), **Dismiss** (no action, not blocked), **Reject** (blocked next time; a typed note becomes a permanent note for the agents).
* **Always allow** matches the same agent + service + devices, and also extends to other devices of the same agent and service that you already allowed. Revoke it any time in *Memory & Rules*.
* Tapping a notification opens the dashboard on the right item.
* If *Send actionable approval notifications* is switched off, low/medium-risk actions are executed without asking (see the FAQ).

### 4.10 Transparency and lifecycle
* **Activity log**: every agent run (shown under the agent's readable name) with its research, computed signals, proposed actions and what happened to each (executed, awaiting approval, blocked, suppressed, shadow-logged). Last 300 runs.
* **Learned tab**: learning progress, habits found (and whether already automated), AI calls avoided, automations proposed from habits, unusual situations, tokens used, recent autonomous actions with Undo, muted alerts, and the health of automations the brain created.
* **Automation health review (daily)**: for each automation the brain created (approved proposals and automations you wrote with *Create an automation*) — not for your other automations. Statuses: *healthy*, *too new* (deployed under 3 days ago and has not run yet), *never fired*, *overridden* (at least 4 runs and half or more reverted by hand within 15 minutes, counted over its whole life), *disabled* and *missing* (no longer in Home Assistant). Statuses are recomputed from scratch every day, so an automation can return to healthy once clean runs outweigh the reverted ones. Problems become insights (at most one per automation per week); an overridden automation also gets a suggestion to switch it off (needs your approval). Each tracked automation that still exists has **Disable / Enable** and **Delete** buttons (Delete asks for confirmation, removes it from Home Assistant and stops tracking it; automations defined in YAML must be removed there). Unhealthy ones also offer **Stop tracking** (forget it; the brain may propose it again) and **Never propose again** (forget it and block that proposal; undo it under *Memory & Rules → rejected suggestions*). The list is sorted with problems first (missing, overridden, never fired, disabled, then too new and healthy), alphabetically within each status. Names are read live from Home Assistant, so renaming is fine.
* **Re-adopting automations**: automations in Home Assistant whose *id* starts with `ai_brain_` but that the brain does not track (for example after a reinstall) are listed in the Learned tab; tick the ones that are really the brain's and press *Track selected*. Matching is by id, never by name, and nothing is changed in Home Assistant.
* **Trust suggestions**: after five approvals of the same kind of action with no objection, the brain suggests *Always allow* or a more autonomous setting for that device type.
* **Weekly digest**: AI calls avoided, habits automated, exceptions, undone actions, tokens, research waiting for review.
* **Quota and cost monitor**: live status per provider with rate-limit cool-downs, session token counts and an estimated spend.

### 4.11 Your own automations in plain language
In *Memory & Rules → Create an automation* describe what you want ("close the kitchen blind at sunset on weekdays, only when someone is home"). The AI writes a native Home Assistant automation using only entities that exist; you see its interpretation, a history check, any warnings (for example an equivalent automation already exists) and the **YAML** (triggers, conditions, actions), which you can edit freely. If the draft would unlock, disarm, open or otherwise do something sensitive by itself, you get a warning to read the YAML carefully; a draft (or an edit of it) that calls a code-running or host-managing service is refused. **Create automation** adds it to Home Assistant (named `[AI Brain] …`, id `ai_brain_…`); **Cancel** discards the draft. Pressing Create is your approval, so it does not pass through Approvals. Created automations appear in the automation health review like any other.

### 4.12 Backup and restore
*Settings → Backup & restore* exports one JSON file with everything you decided or wrote: dashboard settings, notes, ignore list, minimum-change rules, watches, muted and dismissed alerts, rejected suggestions and insights, always-allow rules, the list of tracked automations, and approved/rejected research with its topics. Recorded history, logs, pending approvals and your API key are never included. **Import** first shows what the file contains (and warns if it holds always-allow rules), then merges it into the current installation; nothing is deleted and importing twice does not duplicate anything. Export before uninstalling the add-on, because uninstalling erases its data.

### 4.13 AI providers
Any model supported by LiteLLM: Google Gemini, OpenAI, Anthropic, OpenRouter, local Ollama, or a managed proxy URL. Two model slots (a **deep** model for batch analysis, research and compilation; a **fast** model for real-time reactions), ordered **fallback models** per provider, and a fallback policy: switch automatically and return to the primary when it recovers, ask you first, or never switch.

---

## 5. The dashboard, tab by tab

| Area | What you find |
|---|---|
| **Header** | Mode/autonomy badge, AI status, **Run analysis now**, **Pause brain**, time of the next scheduled batch |
| **Approvals** | Pending actions and automations with reasoning and backtest; Approve once / Always allow / Dismiss / Reject; *Dismiss all* |
| **Activity & Insights** | Agent run history; active insights and recommendations (dismiss, reject so it is never suggested again, delete); unusual-situation and watch alerts |
| **Memory & Rules** | Always-allow rules (revoke); rejected actions and insights (unblock); **Create an automation**; **Watches**; context notes; ignore list; minimum-change rules |
| **Learned** | Learning progress and statistics; recent autonomous actions (Undo); habits found (with *Propose automation*); muted alerts; automations the brain does not track yet (adopt); automation health with Disable / Enable / Delete |
| **Research** | Research status and controls; findings waiting for your review; approved knowledge; upcoming topics |
| **Settings** | Operating mode, autonomy, quota fallback, notification target; AI provider and quota; site context; Learning & Safety; list of agents; **Backup & restore** |

---

## 6. Settings reference

### Add-on configuration (Settings → Add-ons → HA AI Brain → Configuration)

| Option | Default | Meaning |
|---|---|---|
| `operating_mode` | `hybrid` | `hybrid`, `realtime_stream` or `periodic_batch` |
| `default_autonomy_level` | `copilot` | `shadow`, `copilot` or `autonomous` |
| `llm_provider` | `gemini/gemini-3.8-flash` | Deep model (batch, research, compilation) |
| `llm_fast_model` | `gemini/gemini-3.5-flash` | Fast model (real-time reactions, planning) |
| `llm_api_key` | empty | API key (not needed for Ollama) |
| `site_context` | empty | Description of your home |
| `enable_actionable_notifications` | `true` | Send approval push notifications (see FAQ before disabling) |
| `notification_service` | `notify.notify` | e.g. `notify.mobile_app_<your_phone>` |
| `batch_analysis_interval_minutes` | `360` | 15–10080 |
| `batch_lookback_hours` | `24` | 1–720 |
| `realtime_gating` | `true` | Only wake AI agents for unusual events once routines are learned |
| `exception_detection` | `true` | Unusual-situation alerts |
| `deterministic_automations` | `true` | Habit automations without AI |
| `privacy_scrub` | `true` | Alias people/phones/network identifiers before cloud AI |
| `daily_token_budget` | `0` | Max AI tokens per day (0 = unlimited) |
| `research_enabled` | `true` | Weekly agent research |
| `research_web_search` | `false` | Optional cited web research (Gemini only) |
| `research_interval_days` | `7` | 1–90 |
| `log_level` | `info` | `debug`, `info` or `warning`. `debug` logs every single state change (noisy, more CPU/disk) |
| `quiet_hours_start` / `_end` | empty | `HH:MM` local time |
| `timezone` | empty | IANA name; empty = use Home Assistant's |
| `managed_cloud_proxy_url`, `license_key` | empty | Optional; the license key currently only changes a label |

Settings you change in the dashboard are saved in the brain's database and **take precedence over the add-on options** afterwards.

### Dashboard-only settings
Extra critical openings (`critical_openings`: exact entity ids, `*` patterns or words that always need approval to open) · Real-time coalescing (`realtime_coalesce_seconds`, default 90: a burst of events in one area becomes one AI call) · maximum wake-ups per agent per hour (`max_agent_wakeups_per_hour`, default 6; safety events are exempt) · Per-device-type autonomy · AI quota fallback policy and fallback models · maximum autonomous actions per hour · "tell me when the brain acts on its own" · provider presets · watches · created automations · context notes · ignore list · backup & restore.

### Advanced environment variables (for Docker / development)
`BRAIN_BASELINE_MIN_DAYS` (3), `BRAIN_STORE_RETENTION_DAYS` (90), `BRAIN_STORE_BACKFILL_HOURS` (240), `BRAIN_HISTORY_MAX_ENTITIES` (300), `BRAIN_MAX_NEW_AUTOMATIONS` (3), `BRAIN_MAX_EXCEPTIONS_PER_CYCLE` (5), `BRAIN_MAX_EXCEPTIONS_PER_DAY` (20), `BRAIN_RESEARCH_TOPICS_PER_AGENT` (1), `BRAIN_MAX_ACTIONS_PER_ENTITY_PER_HOUR` (3), `BRAIN_KNOWLEDGE_DIR`, `BRAIN_TRUSTED_PROXIES`. See `.env.example`.

---

## 7. Recommended rollout

1. **Days 1–3 — learn.** Set the mode to *Periodic batch* (or keep *Hybrid*) and autonomy to *Shadow* or *Co-pilot*. Open the **Learned** tab: it shows the history import and the progress towards the first 3 days. Fill in *Site Context*, add *context notes* for anything the AI must know, and put noisy or irrelevant entities on the *ignore list*.
2. **Days 3–7 — review proposals.** Habit automations appear in **Approvals** with their backtest. Approve what you recognise as your habit; reject the rest. Add a few **watches** for the things you personally care about. Dismiss or reject alerts that are not useful.
3. **Week 2 — go real-time in shadow.** Switch to *Hybrid* with autonomy *Shadow* for a few days and compare what the brain says it would do with what you actually did.
4. **Then co-pilot, then selective autonomy.** Use *Always allow* for things you trust, and set individual device types (lights, fans, …) to *Autonomous* in *Settings → Learning & Safety*. Keep locks, alarms and automations on *Co-pilot*.
5. **Keep an eye on the weekly digest** and the **Research** tab.

---

## 8. AI providers and models

* **Two models.** The *deep* model does the heavy thinking (batch analysis, research, compiling watches). The *fast* model handles real-time reactions and topic planning. You may use the same model for both.
* **Which one?** The defaults are Gemini Flash-class models. Any LiteLLM model string works, for example `openai/<model>`, `anthropic/<model>`, `openrouter/<vendor>/<model>`, `gemini/<model>`, `ollama/<model>`. Use the presets in *Settings* to fill in sensible values.
* **Reliability matters more than size.** Agents must return valid JSON. Mid-size hosted "flash/mini"-class models are normally fine; very small local models may produce invalid answers (the brain then simply does nothing for that run).
* **Fallbacks.** If the primary model hits a rate limit, the brain can switch to fallback models and return automatically (or ask you first, or never switch). The *AI provider & Quota* card shows cool-downs and session usage.
* **Local models.** `ollama/<model>` needs no key and sends nothing to the cloud. Local learning, exceptions and watches work with no AI at all; only the AI-written parts need a model.
* **Special features:** *Optional deep research* needs Google Gemini. Everything else is provider-independent.

---

## 9. Data, privacy and security

**What is stored, and where.** Everything is in the add-on's own `/data` folder (included in Home Assistant backups); your custom agents and extra knowledge files are in `/config/ha_ai_brain/` (part of your configuration backups): a SQLite database with feedback, rules, approvals, insights, run logs, learned telemetry (state changes and hourly sensor averages, 90 days), watches, research, undo records and your dashboard settings. Your API key is stored in the add-on options/database in clear text, like other add-on secrets.

**Uninstalling and reinstalling.** Uninstalling the add-on deletes its `/data` (database, history, decisions, watches) and its options (including the API key). Automations it created stay in Home Assistant and keep running, and `/config/ha_ai_brain/` (custom agents, knowledge files) is kept. After a reinstall the brain re-imports about 10 days of recorder history, needs about 3 days before alerts start, recognises your existing automations (so it does not duplicate them) and offers to re-adopt the ones with the `ai_brain_` id prefix. Decisions such as rejections, watches and always-allow rules are lost unless you restore a Home Assistant backup that includes the add-on or import an export file made with *Backup & restore*.

**What is sent to your AI provider.** Prompts contain entity IDs, friendly names, states, units, areas, computed statistics and recent history summaries, your site context, notes and feedback, and — for research — a profile of your home (device types, manufacturers and models; no room names). Nothing is sent when no AI call is made (most of the time). When `privacy_scrub` is on, people, trackers and phone/notify target names are replaced by aliases (and restored in the answer), and e-mail addresses, IP/MAC addresses, coordinates and similar attributes are removed. Free text *you* write (site context, notes, watch requests) is only scrubbed for e-mails and network addresses, so avoid putting names in it if that matters to you. Use a local Ollama model if no data may leave your network.

**Access.** The dashboard and API are only reachable through Home Assistant's ingress (the Supervisor proxy); direct requests from the network are rejected. In Docker/development use bind to localhost.

**What it can do in Home Assistant.** The add-on uses the Supervisor-provided access to read states, history and registries, call services (including notification services), and create/update automations through the configuration API. Automations it creates are named **`[AI Brain] …`** and have an ID starting with `ai_brain_`, so you can always find and delete them. The brain recognises its own automations by that **id**, never by name, and the dashboard's Disable/Delete buttons only work on automations it tracks.

**Sandbox.** Calculation code written by the AI runs in a separate, restricted Python process: no imports besides `math`/`statistics`, no file or network access, no access to your keys, CPU/memory/time limits.

---

## 10. Costs and how to control them

Cost depends on your provider, the models you choose, the size of your home and how busy it is. Most of the brain's work is local and free (see 3.2). Tokens are used by: agent reactions to unusual events, one analysis per agent per batch interval (skipped when nothing changed), watch compilation (once), and research (a few calls per agent per week).

To keep it low:
* Use a small fast model and a mid-size deep model, or a local model.
* Keep **gating**, **exception detection** and **habit automations** on (they replace many AI calls).
* Raise `batch_analysis_interval_minutes`, lower `batch_lookback_hours`, or use *Periodic batch* mode.
* Set a **daily token budget** (real-time reactions and scheduled batches pause when it is reached).
* Put noisy entities on the **ignore list**; leave **deep research** off.
* The brain already avoids waste by itself, whatever the provider: agents are not called when your home has nothing of their kind (for example no shading agent without blinds); a batch is skipped when nothing relevant changed (and backs off to once a day when nothing useful came out of the last runs); a burst of events in one area is one call; the code the AI writes for calculations is cached for 7 days; research is cached per kind of equipment for 14 days; prompts are sent compactly with the fixed part first so providers with prompt caching can reuse it; hidden "thinking" tokens are counted in your budget.
* Watch the *AI provider & Quota* card and the weekly digest for real numbers.

---

## 11. Custom agents and extra knowledge

**Custom agents.** An agent is a YAML file. A complete example (every field):

```yaml
agent_id: pool_agent              # required; letters, digits, _ or -, max 64; also the file name
name: Pool & Garden Agent         # required; shown in the dashboard and logs
specialty: Pool water chemistry and irrigation efficiency   # required; one line
description: >                    # required; what it should look after
  Watches the pool pump, water temperature and the garden irrigation valves and
  suggests how to save energy and water.
monitored_domains: [sensor, switch, valve, weather]   # what it observes
monitored_device_classes: [temperature, power]        # optional filter for sensors
controllable_domains: [switch, valve, notify]         # the ONLY domains it may act on (see below)
goals:                            # plain-language goals
  - Run the pump when it is cheapest and the water actually needs filtering
  - Warn me when the water temperature or pump power looks abnormal
custom_domain_rules_prompt: >     # optional extra rules / knowledge, plain language
  The pump must never run for less than 2 hours per day. Never touch the irrigation valve
  between 22:00 and 06:00.
batch_trigger: auto               # auto (default) | unavailable_only (diagnostic agents) | always
enabled: true                     # false = defined but switched off
```

Only `agent_id`, `name`, `specialty` and `description` are required; everything else has a default.

**What an agent may do is decided by `controllable_domains`.** It is a hard permission enforced in code: any action in another domain is blocked ("blocked_domain_not_permitted" in the activity log), whatever the AI says. The special domain `automation` is the permission to *propose new native automations*; an agent without it is told so in its prompt and returns ideas as insights instead. The text in `goals` and `custom_domain_rules_prompt` only guides the AI; it never grants or removes permissions. The same goes for notes you write on the *Memory & Rules* tab and the note you type when rejecting a proposal (the latter is kept for the agent that made it).

Save it as `/config/ha_ai_brain/agents/pool_agent.yaml` (that is the `ha_ai_brain/agents` folder inside your Home Assistant configuration folder; the **File editor**, **Samba share** or **SSH & Web Terminal** add-ons can reach it) and restart the add-on. A file there with the same `agent_id` as a bundled example overrides it — that is how you **enable** the two bundled examples (a solar/energy agent and a brewery agent ship disabled): copy the example into that folder and set `enabled: true`. Agents registered through `POST /api/agents/custom` are saved in the same folder. Agents cannot be switched on or off from the dashboard yet.

**Changing a built-in agent** (for example stopping the Repair & Diagnostics agent from proposing automations, or giving the Security agent permission to). Built-in agents are defined inside the add-on, but a file in `/config/ha_ai_brain/agents/` with the **same `agent_id`** replaces them. Save the complete definition with your change, then restart the add-on:

```yaml
# /config/ha_ai_brain/agents/repair_diagnostics_agent.yaml
agent_id: repair_diagnostics_agent
name: Repair & Diagnostics Agent
specialty: Smart Home Systems Reliability & Network Diagnostics Engineer
description: >
  Monitors unavailable entities and HA error logs; uses MCP tools to diagnose connectivity,
  DHCP/IP changes, and integration health.
monitored_domains: [device_tracker, sensor, switch, climate, light]
monitored_device_classes: []
controllable_domains: [homeassistant, notify]   # <- "automation" removed (it is on by default)
goals:
  - Detect unavailable entities, inspect HA system logs, and diagnose root causes
  - Use available MCP tools and HA services to self-heal integrations or report actionable diagnostics
batch_trigger: unavailable_only
enabled: true
```

Your file survives add-on updates and uninstalls (it lives in your Home Assistant configuration folder). Two things to know: it replaces the **whole** agent, so improvements to that built-in agent in later add-on versions will not reach you until you compare and update your copy; and to go back to the built-in version, delete your file and restart. The built-in definitions are listed in the add-on's source (`application/agent_registry.py`).

**Extra reference knowledge.** Put YAML files in `/config/ha_ai_brain/knowledge/`:

```yaml
- id: my-note
  title: Short title
  tags: [humidity, climate]      # words that decide when it is relevant
  guidance: What an expert should know here.
  source: Where it comes from
```

Approved research and your own notes are used together with this file-based knowledge.

---

## 12. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Dashboard says "Configure AI Provider" | No API key yet (or no `ollama/` model). Add one in *Settings* |
| The same device is listed twice | Check *Learned* → **Devices seen twice**; if it is not there, the integrations do not share a serial number. Disabling one of the two entities in Home Assistant also works |
| A habit you expected is missing | Open *Learned* → **Habits ignored on purpose**: if it looked like a shared trigger, a fixed clock time or a scene, it is listed there with the reason |
| Nothing is proposed | Needs a few days of history (see the *Learned* tab); habits may already be automated; in *Real-time stream* mode proposals only appear when you press **Run analysis now** |
| No push notifications | Wrong `notification_service`; Companion App not installed; notifications switched off; quiet hours; autonomy is *Shadow* |
| Too many alerts | Dismiss (waits longer) or Reject (mutes); use the ignore list; tighten with a watch instead |
| Alerts for something normal | Dismiss it; it needs to see more days of history; vacations and guests look unusual to it |
| "Quota reached" banner | Provider rate limit; the brain waits or uses fallback models depending on the fallback policy |
| Add-on refuses to start with "invalid options" | Open the add-on Configuration tab and press **Save** so new options get their defaults |
| Dashboard returns 403 | Open it from the Home Assistant sidebar (ingress), not via a direct port |
| Wrong times in habits/alerts | Set `timezone` (the brain normally reads Home Assistant's) |
| Check what it is doing | Add-on **Log** tab; *Activity & Insights* for every run |

---

## 13. Known limitations

* Only automations created in the **Home Assistant UI** can be read in detail. Automations written in YAML are visible as entities but their triggers/actions are not parsed, so the brain may propose a habit you already automate in YAML.
* Twin detection needs a serial number in the device registry; an integration that does not provide one is only caught by the same-name rule. Text sent to AI agents still lists both entities.
* The shared-trigger filter is a heuristic: a genuine habit whose devices both happen at a fixed time every day, or a person's action that is always followed by 4+ devices, can be listed under *Habits ignored on purpose* instead (the time habits themselves are still found). Runs of automations and scripts are recorded from version 0.2.11 on, so older history is only handled by the timing rules; history imported at startup carries no origin and does not contain hand-started script runs. Sun events are not recorded, so a shared sunset/sunrise trigger is recognised through the automations that run on it or through the identical time of day.
* Backtesting replays time and state triggers; numeric-threshold, sun and other triggers are marked "not verifiable". Presence conditions are not replayed.
* Routines need a few days of history; unusual-but-legitimate periods (holidays, guests, repairs) can cause false alerts until the brain has seen more.
* The AI can be wrong. Safety rests on the deterministic guardrails, validation of entities and services, backtests and your approvals — not on the AI's judgement.
* Optional cited web research is Gemini-only. Research without it is the AI's general knowledge and is not verified.
* Automation health and the Disable/Delete buttons cover only automations the brain created (or adopted), not your other automations. An automation whose habit has faded is only noticed when you start reverting it.
* The add-on's data is erased on uninstall; use *Backup & restore* or a Home Assistant backup to keep your decisions.
* The `license_key` option is informational in this version; nothing is locked behind it.
* Habit/exception learning covers switchable, binary and presence entities and numeric sensors. Text, enum and media states are not learned.

---

## 14. FAQ

**Does the AI come up with ideas for my home, or does it only react to abnormal behaviour?**
Both. The scheduled analysis looks at the current states and recent trends of everything in each agent's field and proposes insights, recommendations and automations even when nothing is wrong — for example a condensation-risk warning built from your indoor humidity, indoor temperature and outdoor temperature sensors. In between, the AI is only woken for unusual or non-routine events, and the local unusual-situation detectors and your watches run without any AI. See [3.5](#35-when-does-the-ai-look-at-my-entities-and-what-does-it-not-see).

**Can I describe an automation and have the brain create it?**
Yes: *Memory & Rules → Create an automation*. You review and can edit the generated YAML before anything is created.

**What happens to my settings and rules if I uninstall the add-on?**
They are erased with the add-on's data, but the automations it created stay in Home Assistant. Use *Settings → Backup & restore* to export first, or restore a Home Assistant backup. See section 9.

**An automation is "overridden" or "missing" in the health list. What should I do?**
Overridden: edit it in Home Assistant, switch it off (the brain offers this) or delete it; the Disable and Delete buttons are in the same list. Missing: you deleted it; *Stop tracking* removes it from the list (the brain may propose it again), *Never propose again* also blocks it.

**I just added new sensors. When will it notice?**
At the next scheduled analysis (adding a sensor counts as a change), or immediately when you press **Run analysis now**.

**Does it work without a cloud AI?**
Partly, and well: with a local `ollama/` model everything works with no data leaving your network. Without any model, the local features — recording, habit detection, backtests, unusual-situation alerts and running existing watches — still run, but agents, insights, research and watch compilation need a model.

**Will it change my devices without asking?**
Not in the default *Co-pilot* mode: it asks first. In *Autonomous* mode it executes low- and medium-risk actions by itself (with an Undo notification). Unlocking, disarming, opening garage doors/gates, closing valves and restarting Home Assistant always need your approval.

**Important: what happens if I switch off approval notifications?**
With *Send actionable approval notifications* off, low- and medium-risk actions are executed **without asking, even in Co-pilot mode**, because there is no way to ask you. Keep it on unless you want that. High and critical actions still require approval (visible on the dashboard).

**Can it create automations by itself?**
Creating an automation counts as medium risk, unless what it would do later is more sensitive (unlocking, disarming, opening a garage door or gate is critical; closing a valve, restarting or template-chosen services is high; code-running services are blocked), in which case it needs your approval even in Autonomous mode. In Co-pilot you approve each one. In *Autonomous* mode it is created automatically — to keep approvals for automations while everything else is autonomous, set the device type `automation` to *Co-pilot* in *Settings → Learning & Safety*. Everything it creates is named `[AI Brain] …`.

**How do I remove an automation it created?**
Delete it in *Settings → Automations* (search for "AI Brain"). The brain will notice it is gone during its daily check. Because the habit behind it still exists, it may propose the same automation again later — if you never want it, **Reject** the proposal in *Approvals* (a plain Dismiss does not block it), or put the device on the ignore list.

**How long until it is useful?**
Habit proposals, gating and routine-based alerts start once about 3 days of history exist. Because it imports your recent Home Assistant history at startup, this can be almost immediately; a full week gives better weekday/weekend detail.

**What is the difference between Dismiss and Reject?**
On an approval, *Dismiss* just closes it; *Reject* blocks that exact kind of action in the future and stores your optional note. On an alert, *Dismiss* makes the same alert wait twice as long next time; *Reject* mutes it until you unmute it.

**What does "Always allow" do exactly?**
It runs the action now and remembers that this agent may do this service on these devices without asking again (and on other devices of the same agent and service that you already allowed). Revoke it in *Memory & Rules*. It never overrides the hard guardrails.

**Why was an AI agent not called for an event?**
Because local learning decided it was not needed: the value is normal for the hour, the change is a routine of yours, or an existing automation already handles it. The *Learned* tab counts these. Security-relevant events always call the agent.

**How is this different from Home Assistant's own automations or Assist?**
They do what you configure or ask. The Brain works in the background: it learns your routines, writes standard Home Assistant automations for you, watches for the unexpected, and runs AI analyses. The automations it creates are normal Home Assistant automations that keep working without the add-on.

**Can I use only a cheap or local model?**
Yes. Use the same model for both slots. Smaller models may return malformed answers more often; the brain then skips that run. Local learning does not depend on the model at all.

**What is the "kill switch"?**
*Pause brain* in the header: it keeps recording and learning and still alerts, but does not act, and does not call the AI for live events. Manual approvals still work.

**What can I do if an alert is wrong?**
Dismiss it (quieter next time) or reject it (muted). If it is a recurring false alarm for a whole device, add the device to the ignore list.

**Can I tell it things the AI cannot know?**
Yes — *Context notes* ("the second fan is only for noise, never run it at night"), the *Site Context* text, and rejection notes. Agents must obey them.

**Does research do anything on its own?**
No. Research only produces proposals. A finding influences agents only after you press Keep, and you can remove it at any time.

**Do I need the optional deep research?**
No. It adds cited web sources for those who want more informed (and costlier) findings. The normal research uses the general knowledge of your AI model.

**Why does the Research tab say "Needs an AI provider"?**
No model is configured. Any provider works; add an API key (or an `ollama/` model) in *Settings*.

**How do watches work without spending tokens?**
The AI is used once to translate your sentence into a structured rule (entities, condition, duration, schedule, severity). After that the rule is checked by plain code every minute.

**How do I enable one of the bundled example agents?**
Create a file with the same `agent_id` in `/config/ha_ai_brain/agents/` and set `enabled: true`, then restart the add-on (see section 11). The two examples are a solar/energy agent (`solar_energy_agent`) and a brewery agent (`beer_brewery_agent`).

**Does it support several phones or people?**
Pick a notification service that reaches everyone you want (a Home Assistant `notify` group works). Presence-aware features use all `person` entities.

**How do I reset what it has learned?**
Uninstalling the add-on with *Delete data* removes everything. To keep the add-on but forget learning, stop it and delete `/data/ha_ai_brain.db` (and its `-wal`/`-shm` files); you will lose rules, approvals, notes and settings too.

**Is my data included in backups?**
Yes: the add-on's `/data` folder is part of normal Home Assistant add-on backups.

**Can I upgrade or downgrade safely?**
Upgrades migrate the database in place. Take a backup first. Going back to an older version keeps working, but newer data (telemetry, watches, research) is simply ignored by it.

**Does the license key do anything?**
Not in this version: it only changes the plan label shown in Settings. Nothing is locked.

**Where do I see why it did something?**
*Activity & Insights*: each run lists the research, the calculated signals, the proposed actions, and the outcome of each. Approval cards link to the reasoning, and the add-on log shows details.

### Performance and storage (Raspberry Pi friendly)
* **Database size**: telemetry uses a compact layout (about 5× smaller than 0.1.x: a busy home at 90 days is roughly 25 MB instead of 136 MB). Upgrading converts old data automatically on first start (a few seconds, one time) and shrinks the file. Auto-vacuum keeps the file from growing after clean-ups.
* **Retention**: run logs 30 days / 300 entries; resolved approvals 60 days; dismissed insights 90 days; verified outcome feedback 180 days; caches and counters are cleaned daily. Rules, rejected suggestions, notes and settings are never deleted.
* **SD-card friendly**: sensor readings and state changes are written in batches (about every 30 s) instead of one write per event.
* **AI-provider neutral**: everything above works with any provider. Only Google Gemini additionally receives a "less thinking" hint for simple planning calls; other providers ignore it.
