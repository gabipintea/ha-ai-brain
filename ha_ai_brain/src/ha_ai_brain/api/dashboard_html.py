"""Self-contained Home Assistant Ingress Web UI Dashboard for HA AI Brain."""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
  <meta name="color-scheme" content="dark" />
  <title>HA AI Brain</title>
  <style>
    :root {
      --bg: #0b1120;
      --panel: #131c2e;
      --panel-2: #0e1626;
      --border: #24324a;
      --text: #e8eefb;
      --muted: #8b9bb8;
      --accent: #4f9cf9;
      --ok: #34d399;
      --warn: #fbbf24;
      --danger: #f87171;
      --radius: 12px;
    }
    * { box-sizing: border-box; }
    html, body { width: 100%; max-width: 100vw; overflow-x: hidden; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.45;
      -webkit-text-size-adjust: 100%;
      padding: 24px max(16px, env(safe-area-inset-right)) 40px max(16px, env(safe-area-inset-left));
    }
    .container { max-width: 1280px; margin: 0 auto; }
    header {
      display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;
      padding-bottom: 16px; margin-bottom: 16px; border-bottom: 1px solid var(--border);
    }
    h1 { margin: 0; font-size: 1.35rem; font-weight: 650; letter-spacing: -0.01em; }
    .sub { color: var(--muted); font-size: 0.85rem; margin-top: 2px; }
    .status { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .pill {
      display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px;
      font-size: 0.74rem; font-weight: 600; letter-spacing: 0.02em; text-transform: uppercase;
      background: rgba(79,156,249,0.14); color: var(--accent); border: 1px solid rgba(79,156,249,0.3);
      white-space: nowrap; flex-shrink: 0;
    }
    .pill.ok { background: rgba(52,211,153,0.12); color: var(--ok); border-color: rgba(52,211,153,0.3); }
    .pill.warn { background: rgba(251,191,36,0.12); color: var(--warn); border-color: rgba(251,191,36,0.3); }
    .pill.danger { background: rgba(248,113,113,0.12); color: var(--danger); border-color: rgba(248,113,113,0.3); }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }

    /* Segmented Top Navigation Tabs */
    .nav-tabs {
      display: flex;
      gap: 8px;
      margin-bottom: 20px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--border);
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      scrollbar-width: none;
    }
    .nav-tabs::-webkit-scrollbar { display: none; }
    .tab-btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 16px;
      border-radius: 999px;
      font-size: 0.88rem;
      font-weight: 600;
      color: var(--muted);
      background: var(--panel-2);
      border: 1px solid var(--border);
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.15s ease;
    }
    .tab-btn:hover {
      color: var(--text);
      border-color: var(--accent);
    }
    .tab-btn.active {
      color: #07101f;
      background: var(--accent);
      border-color: var(--accent);
    }
    .tab-btn .tab-badge {
      padding: 1px 7px;
      border-radius: 999px;
      font-size: 0.72rem;
      font-weight: 700;
      background: rgba(255, 255, 255, 0.16);
      color: var(--text);
    }
    .tab-btn.active .tab-badge {
      background: #07101f;
      color: #fff;
    }
    .tab-pane {
      display: none;
    }
    .tab-pane.active {
      display: block;
      animation: fadeIn 0.15s ease;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(2px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; margin-bottom: 18px; }
    @media (min-width: 900px) { .grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    .card {
      background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
      padding: 18px; min-width: 0; overflow: hidden;
    }
    .card-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 14px; }
    .card h2 { margin: 0; font-size: 0.98rem; font-weight: 600; }
    .hint { color: var(--muted); font-size: 0.82rem; margin: -6px 0 12px; }
    .muted { color: var(--muted); font-size: 0.85rem; }
    .empty { color: var(--muted); font-size: 0.88rem; padding: 6px 0; }
    button {
      font: inherit; font-size: 0.86rem; font-weight: 600; padding: 8px 14px; border-radius: 8px; cursor: pointer;
      border: 1px solid var(--border); background: var(--panel-2); color: var(--text);
      transition: background 0.15s, border-color 0.15s, transform 0.08s;
      white-space: nowrap; flex-shrink: 0;
    }
    button:hover { border-color: var(--accent); }
    button:active { transform: scale(0.98); }
    button.primary { background: var(--accent); border-color: var(--accent); color: #07101f; }
    button.success { background: var(--ok); border-color: var(--ok); color: #05150e; }
    button.danger { background: transparent; border-color: var(--danger); color: var(--danger); }
    button.danger:hover { background: rgba(248,113,113,0.12); }
    button.icon { padding: 5px 12px; font-size: 0.8rem; white-space: nowrap; flex-shrink: 0; min-width: fit-content; text-align: center; }
    .btn-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
    select, input[type="text"], textarea {
      width: 100%; max-width: 100%; font: inherit; font-size: 16px; color: var(--text);
      background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px;
    }
    select:focus, input:focus, textarea:focus { outline: none; border-color: var(--accent); }
    label.field { display: flex; flex-direction: column; gap: 6px; font-size: 0.82rem; color: var(--muted); }
    .fields { display: flex; flex-direction: column; gap: 14px; }
    label.check { display: flex; align-items: center; gap: 10px; font-size: 0.9rem; }
    label.check input { width: 18px; height: 18px; accent-color: var(--accent); }
    .item {
      border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; margin-bottom: 10px;
      background: var(--panel-2); overflow-wrap: anywhere; word-break: break-word;
    }
    .item:last-child { margin-bottom: 0; }
    .row { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
    .row > div:first-child { min-width: 0; flex: 1 1 auto; overflow-wrap: anywhere; word-break: break-word; }
    .row > button { flex-shrink: 0; white-space: nowrap; align-self: flex-start; margin-left: 8px; }
    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.8rem;
      background: rgba(255,255,255,0.05); padding: 1px 6px; border-radius: 5px; overflow-wrap: anywhere; word-break: break-all;
    }
    pre {
      margin: 8px 0 0; padding: 10px; border-radius: 8px; background: #080d18; border: 1px solid var(--border);
      font-size: 0.76rem; color: #c3cee3; white-space: pre-wrap; word-break: break-word; max-width: 100%; overflow-x: auto;
    }
    .inline-form { display: flex; gap: 8px; flex-wrap: wrap; }
    .inline-form input { flex: 1 1 160px; width: auto; }
    .scroll {
      max-height: 520px;
      overflow-y: auto;
      padding-right: 6px;
      scrollbar-width: thin;
      scrollbar-color: rgba(255, 255, 255, 0.18) transparent;
    }
    .scroll::-webkit-scrollbar {
      width: 6px;
    }
    .scroll::-webkit-scrollbar-track {
      background: transparent;
    }
    .scroll::-webkit-scrollbar-thumb {
      background: rgba(255, 255, 255, 0.18);
      border-radius: 4px;
    }
    .scroll::-webkit-scrollbar-thumb:hover {
      background: rgba(255, 255, 255, 0.35);
    }
    .banner {
      display: none; margin-bottom: 18px; padding: 14px 16px; border-radius: var(--radius);
      background: rgba(251,191,36,0.1); border: 1px solid rgba(251,191,36,0.4);
    }
    .banner.info { background: rgba(79,156,249,0.1); border-color: rgba(79,156,249,0.4); }
    .banner strong.t { display: block; margin-bottom: 4px; }
    .sec-title { font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 12px 0 6px; }
    .kv { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; font-size: 0.84rem; }
    .kv span:nth-child(odd) { color: var(--muted); }
    .finding { padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; margin-top: 6px; background: #0a1120; }
    .intent { padding: 8px 10px; border-left: 3px solid var(--ok); border-radius: 6px; margin-top: 6px; background: #0a1120; }
    @keyframes highlightPulse {
      0% {
        box-shadow: 0 0 0 0 rgba(79, 156, 249, 0.95);
        border-color: var(--accent);
        transform: translateY(-2px);
      }
      20% {
        box-shadow: 0 0 0 8px rgba(79, 156, 249, 0.45);
        border-color: var(--accent);
        transform: translateY(-2px);
      }
      45% {
        box-shadow: 0 0 0 14px rgba(79, 156, 249, 0.18);
        border-color: var(--accent);
      }
      70% {
        box-shadow: 0 0 0 6px rgba(79, 156, 249, 0.25);
        border-color: var(--accent);
      }
      100% {
        box-shadow: none;
        border-color: var(--border);
        transform: translateY(0);
      }
    }
    .highlight-pulse {
      animation: highlightPulse 3.5s cubic-bezier(0.25, 1, 0.5, 1) forwards !important;
      border-color: var(--accent) !important;
    }
    .insight-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 8px 12px;
      flex-wrap: wrap;
      margin-bottom: 6px;
    }
    .insight-title-group {
      min-width: 0;
      flex: 1 1 200px;
    }
    .insight-title {
      font-size: 0.96rem;
      font-weight: 650;
      line-height: 1.35;
      color: var(--text);
      display: block;
    }
    .insight-meta {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
      flex-shrink: 0;
    }
    .insight-actions {
      display: flex;
      gap: 6px 8px;
      justify-content: flex-end;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 10px;
    }
    @media (max-width: 600px) {
      body { padding-top: 14px; }
      .card { padding: 14px; }
      .card-head { gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
      .btn-row button { flex: 1 1 100%; }
      header { flex-direction: column; align-items: flex-start; }
      .nav-tabs { gap: 6px; }
      .tab-btn { padding: 7px 12px; font-size: 0.82rem; }
      .inline-form { flex-direction: column; }
      .inline-form input { width: 100%; flex: 1 1 100%; }
      .inline-form button { width: 100%; }
      .row { gap: 10px; }
      .row > button { padding: 6px 12px; font-size: 0.82rem; }
      .hide-mobile { display: none !important; }
      .insight-actions { justify-content: stretch; gap: 6px; }
      .insight-actions button { flex: 1 1 auto; text-align: center; justify-content: center; padding: 6px 8px; font-size: 11px; }
    }
  </style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>HA AI Brain</h1>
      <div class="sub">Autonomous cognitive layer for Home Assistant</div>
    </div>
    <div class="status">
      <span class="pill" id="modeBadge">Loading...</span>
      <span class="pill ok" id="llmBadge"><span class="dot"></span><span id="llmBadgeText">AI ready</span></span>
      <button onclick="triggerBatch()" id="batchBtn">Run analysis now</button>
    </div>
  </header>

  <!-- Top Segmented Tab Navigation Bar -->
  <nav class="nav-tabs" role="tablist">
    <button class="tab-btn active" role="tab" id="tabBtn-approvals" onclick="switchTab('approvals')">
      Approvals
      <span class="tab-badge" id="tabBadge-approvals" style="display:none;">0</span>
    </button>
    <button class="tab-btn" role="tab" id="tabBtn-activity" onclick="switchTab('activity')">
      Activity & Insights
      <span class="tab-badge" id="tabBadge-activity" style="display:none;">0</span>
    </button>
    <button class="tab-btn" role="tab" id="tabBtn-memory" onclick="switchTab('memory')">
      Memory & Rules
    </button>
    <button class="tab-btn" role="tab" id="tabBtn-settings" onclick="switchTab('settings')">
      Settings
    </button>
  </nav>

  <div id="onboardingBanner" class="banner info" style="display:none;">
    <strong class="t">Welcome to HA AI Brain!</strong>
    <div class="muted">To activate autonomous reasoning and continuous optimization for your home, choose your AI provider and enter your API key.</div>
    <div class="btn-row" style="margin-top:10px;">
      <button class="primary" onclick="switchTab('settings'); $('llmApiKeyInput').focus();">Configure AI Provider</button>
    </div>
  </div>

  <div id="quotaBanner" class="banner"></div>

  <!-- TAB 1: Approvals -->
  <div id="pane-approvals" class="tab-pane active">
    <div class="grid">
      <div class="card">
        <div class="card-head">
          <h2>Pending approvals</h2>
          <div style="display:flex; align-items:center; gap:8px;">
            <button id="dismissAllBtn" class="icon" style="display:none; font-size:12px; padding:4px 8px;" onclick="dismissAllApprovals()">Dismiss all</button>
            <span class="pill warn" id="pendingCount" style="display:none;">0</span>
          </div>
        </div>
        <div id="pendingEmpty" class="empty">Nothing is waiting for your approval. All actions are either auto-approved or system is observing.</div>
        <div id="pendingList"></div>
      </div>
    </div>
  </div>

  <!-- TAB 2: Activity & Insights -->
  <div id="pane-activity" class="tab-pane">
    <div class="grid two">
      <div class="card">
        <div class="card-head">
          <h2>Agent activity</h2>
          <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
            <button id="clearLogsBtn" class="icon" style="display:none; font-size:11px; padding:3px 8px;" onclick="clearActivityLogs()">Clear logs</button>
            <span class="pill" id="logsCountBadge">0</span>
          </div>
        </div>
        <div id="logsScrollContainer" class="scroll">
          <div id="logsList"></div>
          <div id="logsEmpty" class="empty">No agent activity yet.</div>
          <div id="logsLoadMoreContainer" style="text-align:center; margin:10px 0 2px; display:none;">
            <button id="loadMoreLogsBtn" onclick="loadMoreLogs()">Load older activity</button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <h2>Insights and recommendations</h2>
          <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
            <button id="dismissAllInsightsBtn" class="icon" style="display:none; font-size:11px; padding:3px 8px;" onclick="dismissAllInsights()">Dismiss all</button>
            <button id="clearAllInsightsBtn" class="icon" style="display:none; font-size:11px; padding:3px 8px;" onclick="clearAllInsights()">Clear all</button>
            <span class="pill info" id="activeInsightsCountBadge" style="display:none;">0</span>
          </div>
        </div>
        <div id="insightsList" class="scroll"></div>
      </div>
    </div>
  </div>

  <!-- TAB 3: Memory & Rules -->
  <div id="pane-memory" class="tab-pane">
    <div class="grid two">
      <div class="card">
        <div class="card-head">
          <h2>Always-allowed actions</h2>
          <span class="pill ok" id="rulesCountBadge" style="display:none;">0</span>
        </div>
        <div class="hint">Approved repeatable actions that run automatically without asking.</div>
        <div id="rulesList" class="scroll"></div>
      </div>
      <div class="card">
        <div class="card-head">
          <h2>Rejected action suggestions</h2>
          <span class="pill warn" id="rejectedCountBadge" style="display:none;">0</span>
        </div>
        <div class="hint">Blocked actions that will not be proposed again. Unblock one to let agents suggest it again.</div>
        <div id="rejectedList" class="scroll"></div>
      </div>
    </div>

    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div class="card-head">
          <h2>Rejected insights &amp; recommendations</h2>
          <span class="pill warn" id="rejectedInsightsCountBadge" style="display:none;">0</span>
        </div>
        <div class="hint">Advisory topics and hardware advice you rejected. Agents are forbidden from proposing these topics again. Unblock to allow agents to suggest them again.</div>
        <div id="rejectedInsightsList" class="scroll"></div>
      </div>
    </div>

    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div class="card-head">
          <h2>Context for the Brain</h2>
          <span class="pill info" id="contextNotesCountBadge" style="display:none;">0</span>
        </div>
        <div class="hint">Tell all agents about hardware quirks or personal rules (e.g. broken humidifier). Applied immediately across all agents.</div>
        <div class="fields">
          <textarea id="contextNoteInput" rows="2" placeholder="e.g. The humidifier on the bedroom air purifier is broken; I only use it to purify air."></textarea>
          <div class="inline-form">
            <input type="text" id="contextEntitiesInput" placeholder="Related entity IDs (optional, comma-separated)" />
            <button class="primary" onclick="addContextNote()">Save note</button>
          </div>
        </div>
        <div id="contextNotesList" class="scroll" style="margin-top:14px;"></div>
      </div>
    </div>
  </div>

  <!-- TAB 4: Settings -->
  <div id="pane-settings" class="tab-pane">
    <div class="grid two">
      <div class="card">
        <div class="card-head"><h2>Operating Settings</h2></div>
        <div class="fields">
          <label class="field">Operating mode
            <select id="modeSelect" autocomplete="off" onchange="updateSetting('operating_mode', this.value)">
              <option value="hybrid">Hybrid (live stream + periodic batch)</option>
              <option value="realtime_stream">Real-time event stream</option>
              <option value="periodic_batch">Periodic batch only (lowest token use)</option>
            </select>
          </label>
          <label class="field">Autonomy
            <select id="autonomySelect" autocomplete="off" onchange="updateSetting('default_autonomy', this.value)">
              <option value="shadow">Shadow - observe and log only</option>
              <option value="copilot">Co-pilot - ask before acting</option>
              <option value="autonomous">Autonomous - act on low/medium risk</option>
            </select>
          </label>
          <label class="field">AI quota fallback
            <select id="fallbackPolicySelect" autocomplete="off" onchange="updateSetting('llm_fallback_policy', this.value)">
              <option value="auto">Auto-switch to fallback and return after cooldown</option>
              <option value="confirm">Ask before switching to a fallback model</option>
              <option value="disabled">Disabled - primary model only</option>
            </select>
          </label>
          <label class="field">Notification target
            <select id="notifyServiceSelect" autocomplete="off" onchange="updateSetting('notification_service', this.value)">
              <option value="notify.notify">Loading HA notify services...</option>
            </select>
          </label>
          <label class="check">
            <input type="checkbox" id="notifyCheck" autocomplete="off" onchange="updateSetting('notifications_enabled', this.checked)" checked />
            Send actionable approval notifications
          </label>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h2>AI provider & Quota</h2><span class="pill" id="quotaPill">-</span></div>
        <div id="quotaBox" class="kv"></div>
        <div id="licenseBox" class="muted" style="margin-top:12px;"></div>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div class="card-head"><h2>AI Provider & Site Context</h2></div>
        <div class="hint">Switch AI models on the fly or update your site layout and family context. Changes take effect immediately.</div>
        <div class="fields" style="margin-top:14px;">
          <label class="field">Quick Provider Presets
            <select id="providerPresetSelect" onchange="onProviderPresetChange(this.value)">
              <option value="">-- Choose a provider preset or customize below --</option>
              <option value="gemini">Google Gemini (Free AI Studio / Vertex Express)</option>
              <option value="openai">OpenAI ChatGPT (gpt-4o / gpt-4o-mini)</option>
              <option value="anthropic">Anthropic Claude (claude-3-5-sonnet / haiku)</option>
              <option value="openrouter">OpenRouter (Multi-Provider Aggregator)</option>
              <option value="ollama">Local Ollama (100% Private, Offline, Zero-Cost)</option>
            </select>
          </label>
          <div class="grid two" style="gap:12px; margin:0;">
            <label class="field">Primary Model (Deep Batch Audits)
              <input type="text" id="llmModelInput" placeholder="e.g. gemini/gemini-3.8-flash or openai/gpt-4o" />
            </label>
            <label class="field">Fast Model (Real-Time Reflexes & Triage)
              <input type="text" id="llmFastModelInput" placeholder="e.g. gemini/gemini-3.5-flash or openai/gpt-4o-mini" />
            </label>
          </div>
          <label class="field">API Key
            <input type="password" id="llmApiKeyInput" autocomplete="new-password" placeholder="Paste API Key (leave blank to keep current)" />
          </label>
          <label class="field">Site & Building Context
            <div class="hint" style="margin-bottom:6px;">Tell the AI about your home, layout, occupants, heating/cooling systems, orientation, and garden.</div>
            <textarea id="siteContextInput" rows="4" style="width:100%; box-sizing:border-box; background:var(--bg); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:8px 10px; font-family:inherit; font-size:13px; line-height:1.4;" placeholder="Describe your home, rooms, HVAC setup, window orientations, occupants..."></textarea>
          </label>
          <div style="margin-top:8px;">
            <button class="primary" id="saveAiBtn" onclick="saveAiConfig()">Save & Apply AI Settings</button>
            <span id="saveAiMsg" class="muted" style="margin-left:12px;"></span>
          </div>
        </div>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div class="card-head"><h2>Ignore list</h2></div>
        <div class="hint">Matching entities are dropped before triage and never reach the AI. Supports <code>*</code> wildcards.</div>
        <div class="inline-form">
          <input type="text" id="ignorePatternInput" placeholder="e.g. sensor.vendor_* or *device_name*" />
          <input type="text" id="ignoreReasonInput" placeholder="Reason (optional)" />
          <button class="primary" onclick="addIgnoredTarget()">Add to ignore list</button>
        </div>
        <div id="ignoredTargetsList" style="margin-top:14px;"></div>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div class="card-head"><h2>Active Specialized Domain Agents</h2><span class="pill" id="agentsCountBadge">0</span></div>
        <div class="hint">Specialized cognitive agents that analyze both real-time stream events and periodic historical batch patterns.</div>
        <div id="agentsList" style="margin-top:14px;"></div>
      </div>
    </div>
  </div>

</div>

<script>
  let settingsMutationSeq = 0;
  let allLoadedLogs = [];
  let loadedLogIds = new Set();
  let totalServerLogs = 0;
  let isLoadingMoreLogs = false;

  function esc(v) {
    return String(v === null || v === undefined ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  const $ = id => document.getElementById(id);

  let pendingHashTarget = null;

  function pulseElement(el) {
    if (!el) return;
    el.classList.remove('highlight-pulse');
    void el.offsetWidth;
    el.classList.add('highlight-pulse');
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setTimeout(() => {
      if (el) el.classList.remove('highlight-pulse');
    }, 3600);
  }

  async function fetchAndInsertLog(runId) {
    if (!runId || loadedLogIds.has(runId)) return;
    try {
      const res = await fetch('./api/logs/' + encodeURIComponent(runId));
      if (!res.ok) return;
      const json = await res.json();
      if (json && json.log && !loadedLogIds.has(json.log.run_id)) {
        allLoadedLogs.unshift(json.log);
        loadedLogIds.add(json.log.run_id);
        const lBox = $('logsList');
        if (lBox) {
          $('logsEmpty').style.display = 'none';
          lBox.insertAdjacentHTML('afterbegin', renderLog(json.log));
        }
      }
    } catch (e) {
      // ignore
    }
  }

  async function jumpToElement(tabName, elementId) {
    switchTab(tabName);
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, null, '#' + elementId);
    }
    let el = document.getElementById(elementId)
      || (elementId.startsWith('approval-') ? document.querySelector(`[data-approval-id="${elementId.replace('approval-', '')}"]`) : null)
      || (elementId.startsWith('log-') ? document.querySelector(`[data-log-id="${elementId.replace('log-', '')}"]`) : null)
      || (elementId.startsWith('ins-') || elementId.startsWith('insight-') ? (document.getElementById(elementId) || document.getElementById('ins-' + elementId.replace(/^ins(ight)?-/, ''))) : null);

    if (el) {
      pulseElement(el);
      return;
    }

    if (elementId.startsWith('log-')) {
      const runId = elementId.replace(/^log-/, '');
      await fetchAndInsertLog(runId);
      el = document.getElementById('log-' + runId) || document.querySelector(`[data-log-id="${runId}"]`);
      if (el) {
        pulseElement(el);
        return;
      }
    }

    pendingHashTarget = elementId;
  }

  function handleHashNav() {
    const rawHash = (window.location.hash || '').replace('#', '').trim();
    if (!rawHash) return;
    if (['approvals', 'activity', 'memory', 'settings'].includes(rawHash)) {
      switchTab(rawHash);
      return;
    }
    if (rawHash.startsWith('approval-')) {
      jumpToElement('approvals', rawHash);
    } else if (rawHash.startsWith('log-')) {
      jumpToElement('activity', rawHash);
    } else if (rawHash.startsWith('ins-') || rawHash.startsWith('insight-')) {
      jumpToElement('activity', rawHash);
    }
  }

  function switchTab(tabName) {
    const tabs = ['approvals', 'activity', 'memory', 'settings'];
    if (!tabs.includes(tabName)) tabName = 'approvals';
    tabs.forEach(t => {
      const btn = $('tabBtn-' + t);
      const pane = $('pane-' + t);
      if (btn) btn.classList.toggle('active', t === tabName);
      if (pane) pane.classList.toggle('active', t === tabName);
    });
    if (window.history && window.history.replaceState) {
      const curHash = (window.location.hash || '').replace('#', '');
      if (['approvals', 'activity', 'memory', 'settings'].includes(curHash)) {
        window.history.replaceState(null, null, '#' + tabName);
      }
    }
  }

  function initTabs() {
    const hash = (window.location.hash || '').replace('#', '').trim();
    if (['approvals', 'activity', 'memory', 'settings'].includes(hash)) {
      switchTab(hash);
    } else if (hash) {
      handleHashNav();
    } else {
      switchTab('approvals');
    }
  }

  function renderLog(l) {
    const research = (l.research_findings || []).map(rf => `
      <div class="finding"><strong>${esc(rf.topic)}</strong>
        <div class="muted">${esc(rf.principle_summary)}</div>
        ${rf.recommended_thresholds_or_physics ? `<div class="muted"><em>Thresholds:</em> ${esc(rf.recommended_thresholds_or_physics)}</div>` : ''}
      </div>`).join('');
    const signals = (l.derived_signals || []).length
      ? `<pre>${esc(JSON.stringify(l.derived_signals.map(s => ({signal: s.signal_name, value: s.value, unit: s.unit, interpretation: s.interpretation})), null, 2))}</pre>`
      : '';
    const intents = (l.proposed_intents || []).map((intent, idx) => {
      const ex = (l.execution_results || [])[idx] || {};
      const approvalId = intent.approval_id || ex.approval_id;
      const extra = intent.native_automation
        ? `<pre>${esc(JSON.stringify(intent.native_automation, null, 2))}</pre>`
        : (Object.keys(intent.service_data || {}).length ? `<pre>${esc(JSON.stringify(intent.service_data, null, 2))}</pre>` : '');
      const jumpToApprovalBtn = approvalId
        ? `<button class="icon primary" style="margin-top:8px; font-size:0.78rem; padding:4px 10px;" onclick="jumpToElement('approvals', 'approval-${esc(approvalId)}')">⚡ View Pending Approval</button>`
        : '';
      return `<div class="intent">
        <div><strong>${esc(intent.domain)}.${esc(intent.service)}</strong>
          ${(intent.target_entity_ids || []).length ? ` &rarr; <code>${esc(intent.target_entity_ids.join(', '))}</code>` : ''}
          <span class="pill" style="margin-left:6px;">${esc(ex.status || 'proposed')}</span></div>
        <div class="muted" style="margin-top:4px;">${esc(intent.rationale)}</div>
        ${extra}
        ${jumpToApprovalBtn}
      </div>`;
    }).join('');
    const t = l.created_at ? new Date(l.created_at).toLocaleString() : '';
    const pendingIntents = (l.proposed_intents || []).filter(i => i.approval_id || ((l.execution_results || [])[l.proposed_intents.indexOf(i)] || {}).approval_id);
    const firstApprovalId = pendingIntents.length ? (pendingIntents[0].approval_id || ((l.execution_results || [])[l.proposed_intents.indexOf(pendingIntents[0])] || {}).approval_id) : '';
    const topApprovalBtn = firstApprovalId
      ? `<button class="icon" style="border-color:var(--warn); color:var(--warn); font-size:0.76rem; padding:2px 8px;" onclick="jumpToElement('approvals', 'approval-${esc(firstApprovalId)}')">⚡ Pending Approval</button>`
      : '';

    return `<div class="item" id="log-${esc(l.run_id)}" data-log-id="${esc(l.run_id)}">
      <div class="row">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
          <strong>${esc(l.agent_id)}</strong>
          ${topApprovalBtn}
        </div>
        <span class="muted">${esc(t)}</span>
      </div>
      <div class="muted" style="margin:2px 0 4px;">${esc(l.mode)} &middot; ${esc(l.trigger_summary)}</div>
      ${research ? `<div class="sec-title">Research</div>${research}` : ''}
      ${signals ? `<div class="sec-title">Computed signals</div>${signals}` : ''}
      ${intents ? `<div class="sec-title">Proposed actions</div>${intents}` : ''}
    </div>`;
  }

  function renderPendingCard(p) {
    const div = document.createElement('div');
    div.className = 'item';
    div.id = 'approval-' + p.approval_id;
    div.setAttribute('data-approval-id', p.approval_id);

    const isAutomation = (p.intent.domain === 'automation') && (p.intent.service === 'upsert_native_automation' || !!p.intent.native_automation);
    const runId = p.run_id || (p.intent && p.intent.run_id);
    const reasoningBtn = runId
      ? `<button class="icon" type="button" style="border-color:rgba(79,156,249,0.5); color:var(--accent); font-size:0.8rem; padding:5px 10px;" onclick="jumpToElement('activity', 'log-${esc(runId)}')">🔍 View agent reasoning &amp; telemetry</button>`
      : '';

    let contentHtml = '';
    if (isAutomation) {
      const auto = p.intent.native_automation || (p.intent.service_data && typeof p.intent.service_data === 'object' ? p.intent.service_data : {});
      const alias = auto.alias || 'Native Automation';
      const autoId = auto.automation_id || ((p.intent.target_entity_ids || [])[0]) || '';
      const triggers = Array.isArray(auto.trigger) ? auto.trigger : (auto.trigger ? [auto.trigger] : []);
      const conditions = Array.isArray(auto.condition) ? auto.condition : (auto.condition ? [auto.condition] : []);
      const actions = Array.isArray(auto.action) ? auto.action : (auto.action ? [auto.action] : []);

      contentHtml = `
        <div style="margin-bottom:8px;">
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
            <span class="pill" style="background:rgba(79,156,249,0.18); color:var(--accent); border-color:rgba(79,156,249,0.4); text-transform:none; font-weight:700; font-size:0.75rem;">⚡ Native Automation</span>
            <span style="font-size:1.02rem; font-weight:650; color:#fff;">Create Native Automation: <strong style="color:var(--accent);">${esc(alias)}</strong></span>
          </div>
          <div class="muted" style="font-size:0.8rem; margin-top:4px;">
            Target Entity ID: <code>${esc(autoId || 'automation.new')}</code> &middot; 
            <span>${triggers.length} trigger${triggers.length === 1 ? '' : 's'}</span> &middot; 
            <span>${conditions.length} condition${conditions.length === 1 ? '' : 's'}</span> &middot; 
            <span>${actions.length} action${actions.length === 1 ? '' : 's'}</span>
          </div>
        </div>
        <div class="muted" style="margin:8px 0; white-space:pre-wrap; line-height:1.45;">${esc(p.intent.rationale || auto.description || '')}</div>
        <details style="margin:8px 0 12px; background:rgba(0,0,0,0.3); border:1px solid var(--border); border-radius:8px; padding:8px 12px;">
          <summary style="cursor:pointer; font-size:0.82rem; font-weight:600; color:var(--accent); user-select:none;">📋 View Automation Triggers, Conditions &amp; Actions</summary>
          <div style="margin-top:8px;">
            ${auto.description ? `<div class="muted" style="font-size:0.82rem; margin-bottom:6px;"><strong>Description:</strong> ${esc(auto.description)}</div>` : ''}
            <div class="sec-title" style="margin-top:4px;">Triggers (${triggers.length})</div>
            <pre>${esc(JSON.stringify(triggers, null, 2))}</pre>
            ${conditions.length ? `<div class="sec-title">Conditions (${conditions.length})</div><pre>${esc(JSON.stringify(conditions, null, 2))}</pre>` : ''}
            <div class="sec-title">Actions (${actions.length})</div>
            <pre>${esc(JSON.stringify(actions, null, 2))}</pre>
          </div>
        </details>`;
    } else {
      const targets = (p.intent.target_entity_ids || []).join(', ');
      const svcData = p.intent.service_data || {};
      const paramsPreview = Object.keys(svcData).length ? `<div class="muted" style="font-size:0.8rem; margin-top:4px;">Parameters: <code>${esc(JSON.stringify(svcData))}</code></div>` : '';
      contentHtml = `
        <div style="margin-bottom:6px;">
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
            <strong>${esc(p.intent.domain)}.${esc(p.intent.service)}</strong>
            ${targets ? `&rarr; <code>${esc(targets)}</code>` : ''}
          </div>
          ${paramsPreview}
        </div>
        <div class="muted" style="margin:6px 0; white-space:pre-wrap; line-height:1.4;">${esc(p.intent.rationale)}</div>`;
    }

    div.innerHTML = `
      ${contentHtml}
      <input type="text" id="note_${esc(p.approval_id)}" autocomplete="off" placeholder="Optional note for the Brain (saved if you reject)" style="margin-top:6px;" />
      <div class="btn-row" style="align-items:center;">
        <button class="primary" onclick="decideApproval('${esc(p.approval_id)}', 'approved_once')">Approve once</button>
        <button class="success" onclick="decideApproval('${esc(p.approval_id)}', 'approved_repeatable')">Always allow</button>
        <button class="icon" title="Dismiss this proposal without executing or permanently blocking" onclick="decideApproval('${esc(p.approval_id)}', 'dismissed')">Dismiss</button>
        <button class="danger" onclick="decideApproval('${esc(p.approval_id)}', 'rejected')">Reject</button>
        ${reasoningBtn}
      </div>`;
    return div;
  }

  function reconcilePending(pending) {
    const list = $('pendingList');
    const ids = new Set(pending.map(p => p.approval_id));
    list.querySelectorAll('[data-approval-id]').forEach(el => {
      if (!ids.has(el.getAttribute('data-approval-id'))) el.remove();
    });
    const have = new Set([...list.querySelectorAll('[data-approval-id]')].map(el => el.getAttribute('data-approval-id')));
    pending.forEach(p => { if (!have.has(p.approval_id)) list.appendChild(renderPendingCard(p)); });
    $('pendingEmpty').style.display = pending.length ? 'none' : 'block';
    const badge = $('pendingCount');
    badge.style.display = pending.length ? 'inline-flex' : 'none';
    badge.textContent = pending.length;
    const dBtn = $('dismissAllBtn');
    if (dBtn) dBtn.style.display = pending.length > 1 ? 'inline-block' : 'none';

    const tabBadge = $('tabBadge-approvals');
    if (tabBadge) {
      tabBadge.style.display = pending.length ? 'inline-block' : 'none';
      tabBadge.textContent = pending.length;
    }

    if (pendingHashTarget && pendingHashTarget.startsWith('approval-')) {
      const aid = pendingHashTarget.replace('approval-', '');
      const el = document.getElementById(pendingHashTarget) || document.querySelector(`[data-approval-id="${aid}"]`);
      if (el) {
        pulseElement(el);
        pendingHashTarget = null;
      }
    }
  }

  function renderQuota(data) {
    const q = data.llm_quota || {};
    const totalTok = (q.prompt_tokens_session || 0) + (q.completion_tokens_session || 0);
    const spend = typeof q.estimated_spend_usd_session === 'number' ? '$' + q.estimated_spend_usd_session.toFixed(4) : '$0.0000';
    const limit = q.quota_limit !== null && q.quota_limit !== undefined ? `${q.quota_limit} (${q.quota_metric || 'provider limit'})` : 'tier default';
    const primUntil = q.primary_cooldown_until ? new Date(q.primary_cooldown_until).toLocaleTimeString() : 'soon';
    const avail = q.available_fallback_models || [];
    const link = q.external_usage_url ? ` <a href="${esc(q.external_usage_url)}" target="_blank" rel="noopener" style="color:var(--accent);">Usage console</a>` : '';
    const banner = $('quotaBanner');
    const pill = $('quotaPill');
    const llmBadge = $('llmBadge');
    const llmText = $('llmBadgeText');

    if (q.awaiting_fallback_confirmation && avail.length) {
      banner.className = 'banner'; banner.style.display = 'block';
      banner.innerHTML = `<strong class="t">Primary model quota reached</strong>
        <div class="muted"><code>${esc(q.primary_model)}</code> is cooling down until <strong>${esc(primUntil)}</strong>. Switch to a fallback model in the meantime?</div>
        <div class="btn-row">${avail.map(m => `<button class="primary" onclick="decideFallback('approve_fallback', '${esc(m)}')">Use ${esc(m)}</button>`).join('')}
        <button onclick="decideFallback('wait_for_primary', null)">Wait for primary</button></div>`;
      pill.className = 'pill warn'; pill.textContent = 'Awaiting confirmation';
      llmBadge.className = 'pill warn'; llmText.textContent = 'Quota reached';
    } else if (q.using_fallback_model) {
      banner.className = 'banner info'; banner.style.display = 'block';
      banner.innerHTML = `<strong class="t">Running on fallback model</strong>
        <div class="muted"><code>${esc(q.active_model)}</code> is active. Returning to <code>${esc(q.primary_model)}</code> automatically at ${esc(primUntil)}.${link}</div>`;
      pill.className = 'pill'; pill.textContent = 'Fallback active';
      llmBadge.className = 'pill'; llmText.textContent = 'Fallback model';
    } else if (q.quota_exhausted && (q.cooldown_seconds_remaining || 0) > 0) {
      const until = q.cooldown_until ? new Date(q.cooldown_until).toLocaleTimeString() : 'soon';
      const mName = q.primary_model || q.model || 'model';
      const fallbacksCount = (q.fallback_models || []).length;
      const allCooling = fallbacksCount > 0 && (!q.available_fallback_models || q.available_fallback_models.length === 0);
      const detailMsg = allCooling 
        ? `Primary <code>${esc(mName)}</code> and all ${fallbacksCount} fallback models in cooldown`
        : `<code>${esc(mName)}</code> in cooldown`;
      banner.className = 'banner'; banner.style.display = 'block';
      banner.innerHTML = `<strong class="t">AI quota reached - cooldown required</strong>
        <div class="muted">${esc(q.provider || 'Provider')} / ${detailMsg} &mdash; resumes at <strong>${esc(until)}</strong> (${esc(q.cooldown_seconds_remaining)}s). Limit: ${esc(limit)}.${link}</div>`;
      pill.className = 'pill danger'; pill.textContent = 'Cooldown';
      llmBadge.className = 'pill danger'; llmText.textContent = 'Quota reached';
    } else {
      banner.style.display = 'none';
      pill.className = 'pill ok'; pill.textContent = 'Healthy';
      llmBadge.className = 'pill ok'; llmText.textContent = 'AI ready';
    }

    const cool = Object.entries(q.model_cooldowns || {}).map(([m, iso]) => `${esc(m)} (until ${esc(new Date(iso).toLocaleTimeString())})`).join(', ');
    $('quotaBox').innerHTML = `
      <span>Primary</span><span><code>${esc(q.primary_model || data.settings.llm_model)}</code></span>
      <span>Active</span><span><code>${esc(q.active_model || q.model || data.settings.llm_model)}</code></span>
      <span>Fallbacks</span><span>${esc(avail.join(', ') || 'none available')}${cool ? ' &middot; cooling: ' + cool : ''}</span>
      <span>Requests</span><span>${esc(q.requests_succeeded_session || 0)} ok / ${esc(q.requests_rate_limited_session || 0)} rate-limited</span>
      <span>Tokens</span><span>${esc(totalTok)} &middot; est. ${esc(spend)}</span>
      <span>Limit</span><span>${esc(limit)}${link}</span>`;
  }

  async function refreshAll() {
    const seqAtStart = settingsMutationSeq;
    let data;
    try {
      const res = await fetch('./api/status', {cache: 'no-store'});
      data = await res.json();
    } catch (e) { return; }

    if (seqAtStart === settingsMutationSeq) {
      $('modeBadge').textContent = data.settings.operating_mode.replace('_', ' ') + ' / ' + data.settings.default_autonomy;
      const setSel = (id, v) => { const el = $(id); if (v && document.activeElement !== el) el.value = v; };
      setSel('modeSelect', data.settings.operating_mode);
      setSel('autonomySelect', data.settings.default_autonomy);
      setSel('fallbackPolicySelect', data.settings.llm_fallback_policy);
      const ns = $('notifyServiceSelect');
      if (document.activeElement !== ns) {
        const avail = [...(data.available_notify_services || [])];
        const cur = data.settings.notification_service || 'notify.notify';
        if (!avail.includes(cur)) avail.unshift(cur);
        ns.innerHTML = avail.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
        ns.value = cur;
      }
      $('notifyCheck').checked = !!data.settings.notifications_enabled;

      const mi = $('llmModelInput');
      if (mi && document.activeElement !== mi) mi.value = data.settings.llm_model || '';
      const fmi = $('llmFastModelInput');
      if (fmi && document.activeElement !== fmi) fmi.value = data.settings.llm_fast_model || '';
      const sci = $('siteContextInput');
      if (sci && document.activeElement !== sci) sci.value = data.settings.site_context || '';
      const aki = $('llmApiKeyInput');
      if (aki && document.activeElement !== aki) {
        if (data.settings.masked_api_key) {
          aki.placeholder = `Key configured: ${data.settings.masked_api_key} (enter new key to replace)`;
        } else {
          aki.placeholder = 'No API key set (enter to configure)';
        }
      }
      const ob = $('onboardingBanner');
      if (ob) {
        const needsOnboard = !data.settings.has_api_key && !(data.settings.llm_model || '').startsWith('ollama');
        ob.style.display = needsOnboard ? 'block' : 'none';
      }
    }
    $('licenseBox').textContent = `Plan: ${data.license.plan_tier} | Tokens used: ${data.license.tokens_used_this_period}`;

    renderQuota(data);
    reconcilePending(data.pending_approvals || []);

    const rules = Object.values(data.endorsed_rules || {});
    const rBadge = $('rulesCountBadge');
    if (rBadge) {
      rBadge.style.display = rules.length ? 'inline-block' : 'none';
      rBadge.textContent = rules.length;
    }
    $('rulesList').innerHTML = rules.length ? rules.map(r => {
      const isAuto = r.domain_service === 'automation.upsert_native_automation' || (r.description && r.description.startsWith('Native Automation'));
      const titleHtml = isAuto
        ? `<div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
            <span class="pill ok" style="font-size:0.72rem; padding:1px 6px;">⚡ Native Automation</span>
            <strong>${esc(r.description || r.domain_service)}</strong>
          </div>`
        : `<strong>${esc(r.domain_service)}</strong>`;
      return `<div class="item"><div class="row"><div>
        ${titleHtml}
        <div class="muted">${esc((r.target_entity_ids || []).join(', '))}</div>
        <div class="muted">${esc(r.execution_count)} auto-runs</div></div>
        <button class="danger icon" data-sig="${esc(r.signature)}" onclick="revokeRule(this.dataset.sig)">Revoke</button></div></div>`;
    }).join('')
      : '<div class="empty">No actions are set to run automatically. Choose "Always allow" on an approval to add one.</div>';

    const rejected = data.rejected_suggestions || [];
    const rejBadge = $('rejectedCountBadge');
    if (rejBadge) {
      rejBadge.style.display = rejected.length ? 'inline-block' : 'none';
      rejBadge.textContent = rejected.length;
    }
    $('rejectedList').innerHTML = rejected.length ? rejected.map(e => {
      const isAuto = e.service_called === 'automation.upsert_native_automation' || (e.service_data && !!e.service_data.alias);
      const autoAlias = (e.service_data && e.service_data.alias) || '';
      const titleHtml = isAuto
        ? `<div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
            <span class="pill danger" style="font-size:0.72rem; padding:1px 6px;">⚡ Native Automation</span>
            <strong>${esc(autoAlias ? `Create Native Automation: ${autoAlias}` : e.service_called)}</strong>
          </div>`
        : `<strong>${esc(e.service_called)}</strong> &rarr; <code>${esc((e.target_entity_ids || []).join(', '))}</code>`;

      const subHtml = isAuto
        ? `<div class="muted" style="font-size:12px; margin-top:2px;">Target: <code>${esc((e.target_entity_ids || []).join(', '))}</code> &middot; ${esc(e.agent_id)} &middot; ${esc(e.cause_category)}${e.created_at ? ' &middot; ' + esc(new Date(e.created_at).toLocaleDateString()) : ''}</div>`
        : `<div class="muted">${esc(e.agent_id)} &middot; ${esc(e.cause_category)}${e.created_at ? ' &middot; ' + esc(new Date(e.created_at).toLocaleDateString()) : ''}</div>`;

      const noteHtml = e.human_note && !e.human_note.startsWith('Rejected by user')
        ? `<div class="muted" style="margin-top:6px; font-size:12px; background:rgba(255,255,255,0.04); padding:6px 8px; border-radius:4px;"><strong>Your rejection note:</strong> ${esc(e.human_note)}</div>`
        : '';

      return `<div class="item">
        <div class="row">
          <div>
            ${titleHtml}
            ${subHtml}
            ${noteHtml}
          </div>
          <button class="icon" data-sig="${esc(e.action_signature)}" onclick="unblockRejected(this.dataset.sig)">Unblock</button>
        </div>
      </div>`;
    }).join('')
      : '<div class="empty">No rejected suggestions.</div>';

    const rejInsBox = $('rejectedInsightsList');
    const rejIns = data.rejected_insights || [];
    const rejInsBadge = $('rejectedInsightsCountBadge');
    if (rejInsBadge) {
      rejInsBadge.style.display = rejIns.length ? 'inline-block' : 'none';
      rejInsBadge.textContent = rejIns.length;
    }
    if (rejInsBox) {
      rejInsBox.innerHTML = rejIns.length ? rejIns.map(ins => `
        <div class="item">
          <div class="row">
            <div>
              <strong>${esc(ins.title)}</strong>
              <div class="muted" style="font-size:11px; margin-top:2px;">Category: ${esc(ins.category || 'advisory')} ${ins.resolved_at ? '&middot; Rejected ' + esc(new Date(ins.resolved_at).toLocaleDateString()) : ''}</div>
            </div>
            <button class="icon" onclick="unblockRejectedInsight('${esc(ins.insight_id)}')">Unblock</button>
          </div>
          ${ins.rejection_reason ? `<div class="muted" style="margin-top:6px; font-size:12px; background:rgba(255,255,255,0.04); padding:6px 8px; border-radius:4px;"><strong>Your rejection note:</strong> ${esc(ins.rejection_reason)}</div>` : ''}
        </div>`).join('') : '<div class="empty">No rejected insights. When you reject an insight, it appears here and agents will not suggest it again.</div>';
    }

    const notes = data.user_context_notes || [];
    const nBadge = $('contextNotesCountBadge');
    if (nBadge) {
      nBadge.style.display = notes.length ? 'inline-block' : 'none';
      nBadge.textContent = notes.length;
    }
    $('contextNotesList').innerHTML = notes.length ? notes.map(n => `
      <div class="item row"><div><div>${esc(n.content)}</div>
        <div class="muted">${esc(n.scope || 'global')}${(n.related_entities || []).length ? ' &middot; ' + esc(n.related_entities.join(', ')) : ''}</div></div>
        <button class="danger icon" title="Remove" onclick="deleteContextNote('${esc(n.note_id)}')">Remove</button></div>`).join('')
      : '<div class="empty">No notes yet.</div>';

    const ignored = data.ignored_targets || [];
    $('ignoredTargetsList').innerHTML = ignored.length ? ignored.map(t => `
      <div class="item row"><div><code>${esc(t.pattern)}</code>${t.reason ? ` <span class="muted">${esc(t.reason)}</span>` : ''}</div>
        <button class="danger icon" title="Remove" onclick="deleteIgnoredTarget('${esc(t.ignore_id)}')">Remove</button></div>`).join('')
      : '<div class="empty">Nothing is ignored.</div>';

    const agents = data.agents || [];
    const aBadge = $('agentsCountBadge');
    if (aBadge) aBadge.textContent = agents.length;
    const aList = $('agentsList');
    if (aList) {
      aList.innerHTML = agents.length ? agents.map(a => `
        <div class="item">
          <div class="row">
            <div>
              <strong>${esc(a.name)}</strong>
              <div class="muted" style="font-size:12px;">${esc(a.specialty)}</div>
            </div>
            <span class="pill ${a.enabled ? 'ok' : ''}">${esc(a.enabled ? 'Active' : 'Disabled')}</span>
          </div>
          <div class="muted" style="font-size:12px; margin:6px 0;">${esc(a.description)}</div>
          <div class="muted" style="font-size:11px;">
            <strong>Monitored domains:</strong> ${esc((a.monitored_domains || []).join(', '))}
            ${(a.monitored_device_classes || []).length ? ` &middot; <strong>Classes:</strong> ${esc(a.monitored_device_classes.join(', '))}` : ''}
          </div>
        </div>`).join('') : '<div class="empty">No agents registered.</div>';
    }

    totalServerLogs = data.total_logs_count || (data.recent_logs || []).length;
    $('logsCountBadge').textContent = totalServerLogs;
    if ($('clearLogsBtn')) $('clearLogsBtn').style.display = totalServerLogs > 0 ? 'inline-block' : 'none';

    const unreadInsights = data.active_insights_count !== undefined ? data.active_insights_count : (data.advisory_insights || []).length;
    const tabActBadge = $('tabBadge-activity');
    if (tabActBadge) {
      tabActBadge.style.display = unreadInsights > 0 ? 'inline-block' : 'none';
      tabActBadge.textContent = unreadInsights;
    }
    const insBadge = $('activeInsightsCountBadge');
    if (insBadge) {
      insBadge.style.display = unreadInsights > 0 ? 'inline-block' : 'none';
      insBadge.textContent = unreadInsights;
    }
    if ($('dismissAllInsightsBtn')) $('dismissAllInsightsBtn').style.display = unreadInsights > 0 ? 'inline-block' : 'none';
    if ($('clearAllInsightsBtn')) $('clearAllInsightsBtn').style.display = (data.advisory_insights || []).length > 0 ? 'inline-block' : 'none';

    const lBox = $('logsList');
    if (data.recent_logs && data.recent_logs.length) {
      $('logsEmpty').style.display = 'none';
      if (allLoadedLogs.length === 0) {
        allLoadedLogs = [...data.recent_logs];
        allLoadedLogs.forEach(l => loadedLogIds.add(l.run_id));
        lBox.innerHTML = allLoadedLogs.map(renderLog).join('');
      } else {
        data.recent_logs.filter(l => !loadedLogIds.has(l.run_id)).reverse().forEach(l => {
          allLoadedLogs.unshift(l); loadedLogIds.add(l.run_id);
          lBox.insertAdjacentHTML('afterbegin', renderLog(l));
        });
      }
    }
    const more = $('logsLoadMoreContainer');
    more.style.display = allLoadedLogs.length < totalServerLogs ? 'block' : 'none';
    $('loadMoreLogsBtn').textContent = `Load older activity (${allLoadedLogs.length} of ${totalServerLogs})`;

    const proposals = [];
    (data.recent_logs || []).forEach(l => (l.proposed_intents || []).forEach(i => {
      if (i.domain === 'automation' || i.native_automation) proposals.push({agent: l.agent_id, intent: i, run_id: l.run_id});
    }));
    let html = (data.advisory_insights || []).map(ins => {
      const viewRunBtn = ins.run_id
        ? `<button class="icon" type="button" style="font-size:11px; padding:3px 8px; color:var(--accent); border-color:rgba(79,156,249,0.4);" onclick="jumpToElement('activity', 'log-${esc(ins.run_id)}')">🔍 View <span class="hide-mobile">agent </span>reasoning</button>`
        : '';
      return `
      <div class="item" id="ins-${esc(ins.insight_id)}" data-insight-id="${esc(ins.insight_id)}">
        <div class="insight-head">
          <div class="insight-title-group">
            <strong class="insight-title">${esc(ins.title)}</strong>
            ${ins.created_at ? `<div class="muted" style="font-size:11px; margin-top:2px;">${esc(new Date(ins.created_at).toLocaleString())}</div>` : ''}
          </div>
          <div class="insight-meta">
            <span class="pill">${esc((ins.category || 'advisory').replace(/_/g, ' '))}</span>
            ${viewRunBtn}
          </div>
        </div>
        <div class="muted" style="margin:8px 0; white-space: pre-wrap; line-height: 1.45; word-break: break-word; overflow-wrap: anywhere;">${esc(ins.finding_details)}</div>
        <div style="margin-top:6px; padding:6px 10px; background:rgba(46, 204, 113, 0.12); border-left:3px solid #2ecc71; border-radius:4px; font-size:13px; line-height:1.4; word-break: break-word; overflow-wrap: anywhere;">
          <strong>Recommended:</strong> ${esc(ins.recommended_human_action)}
        </div>
        ${ins.estimated_impact ? `<div class="muted" style="margin-top:6px; font-size:12px; line-height:1.35; word-break: break-word; overflow-wrap: anywhere;"><strong>Impact:</strong> ${esc(ins.estimated_impact)}</div>` : ''}
        <div class="insight-actions">
          <button class="icon" style="font-size:11px; padding:4px 9px;" onclick="dismissInsight('${esc(ins.insight_id)}')" title="Mark as read / dismiss from active list">
            ✓ Mark read
          </button>
          <button class="icon" style="font-size:11px; padding:4px 9px; color:#e74c3c; border-color:rgba(231,76,60,0.35);" onclick="rejectInsightPrompt('${esc(ins.insight_id)}')" title="Reject this advice so agents never suggest it again">
            ✕ Reject<span class="hide-mobile"> &amp; Never suggest</span>
          </button>
          <button class="icon" style="font-size:11px; padding:4px 8px; color:var(--muted);" onclick="deleteInsight('${esc(ins.insight_id)}')" title="Delete insight permanently">
            🗑<span class="hide-mobile"> Delete</span>
          </button>
        </div>
      </div>`;
    }).join('');
    html += proposals.map(({agent, intent, run_id}) => {
      const approvalId = intent.approval_id;
      const jumpApprovalBtn = approvalId
        ? `<button class="icon primary" type="button" style="font-size:11px; padding:3px 8px;" onclick="jumpToElement('approvals', 'approval-${esc(approvalId)}')">⚡ View Pending Approval</button>`
        : '';
      const viewRunBtn = run_id
        ? `<button class="icon" type="button" style="font-size:11px; padding:3px 8px; color:var(--accent); border-color:rgba(79,156,249,0.4);" onclick="jumpToElement('activity', 'log-${esc(run_id)}')">🔍 View <span class="hide-mobile">agent </span>reasoning</button>`
        : '';
      return `
      <div class="item">
        <div class="insight-head">
          <div class="insight-title-group">
            <strong class="insight-title">⚡ Proposed automation</strong>
            <span class="muted" style="font-size:12px;">${esc(agent)}</span>
          </div>
          <div class="insight-meta">${jumpApprovalBtn}${viewRunBtn}</div>
        </div>
        <div class="muted" style="margin:6px 0; font-size:13px; line-height:1.4; word-break: break-word; overflow-wrap: anywhere;">${esc(intent.rationale)}</div>
        <pre>${esc(JSON.stringify(intent.native_automation || intent.service_data, null, 2))}</pre>
      </div>`;
    }).join('');
    $('insightsList').innerHTML = html || '<div class="empty">No insights yet. Run an analysis to generate some.</div>';

    if (pendingHashTarget) {
      let el = document.getElementById(pendingHashTarget)
        || (pendingHashTarget.startsWith('approval-') ? document.querySelector(`[data-approval-id="${pendingHashTarget.replace('approval-', '')}"]`) : null)
        || (pendingHashTarget.startsWith('log-') ? document.querySelector(`[data-log-id="${pendingHashTarget.replace('log-', '')}"]`) : null)
        || (pendingHashTarget.startsWith('ins-') || pendingHashTarget.startsWith('insight-') ? (document.getElementById(pendingHashTarget) || document.getElementById('ins-' + pendingHashTarget.replace(/^ins(ight)?-/, ''))) : null);
      if (el) {
        pulseElement(el);
        pendingHashTarget = null;
      }
    }
  }

  async function post(url, body) {
    return fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  }

  function onProviderPresetChange(val) {
    const presets = {
      'gemini': {model: 'gemini/gemini-3.8-flash', fast: 'gemini/gemini-3.5-flash', placeholder: 'Paste Google AI Studio (AIza...) or Vertex (AQ...) key'},
      'openai': {model: 'openai/gpt-4o', fast: 'openai/gpt-4o-mini', placeholder: 'Paste OpenAI API key (sk-...)'},
      'anthropic': {model: 'anthropic/claude-3-5-sonnet-20241022', fast: 'anthropic/claude-3-5-haiku-20241022', placeholder: 'Paste Anthropic API key (sk-ant-...)'},
      'openrouter': {model: 'openrouter/anthropic/claude-3.5-sonnet', fast: 'openrouter/google/gemini-2.5-flash', placeholder: 'Paste OpenRouter API key (sk-or-...)'},
      'ollama': {model: 'ollama/llama3.2', fast: 'ollama/llama3.2', placeholder: 'No API key needed for local Ollama'},
    };
    if (presets[val]) {
      $('llmModelInput').value = presets[val].model;
      $('llmFastModelInput').value = presets[val].fast;
      $('llmApiKeyInput').placeholder = presets[val].placeholder;
    }
  }

  async function saveAiConfig() {
    const btn = $('saveAiBtn');
    const msg = $('saveAiMsg');
    btn.disabled = true; btn.textContent = 'Saving...';
    if (msg) msg.textContent = '';
    try {
      const payload = {
        llm_model: $('llmModelInput').value.trim(),
        llm_fast_model: $('llmFastModelInput').value.trim(),
        site_context: $('siteContextInput').value.trim(),
      };
      const keyVal = $('llmApiKeyInput').value.trim();
      if (keyVal) {
        payload.llm_api_key = keyVal;
      }
      await post('./api/settings', payload);
      $('llmApiKeyInput').value = '';
      if (msg) {
        msg.textContent = '✓ Saved and active!';
        msg.style.color = 'var(--ok, #3fb950)';
        setTimeout(() => { if (msg) msg.textContent = ''; }, 4000);
      }
      await refreshAll();
    } catch (e) {
      if (msg) {
        msg.textContent = 'Error saving settings: ' + e;
        msg.style.color = 'var(--danger, #f85149)';
      }
    } finally {
      btn.disabled = false; btn.textContent = 'Save & Apply AI Settings';
    }
  }

  async function updateSetting(field, value) {
    settingsMutationSeq++;
    $('modeBadge').textContent = $('modeSelect').value.replace('_', ' ') + ' / ' + $('autonomySelect').value;
    await post('./api/settings', {[field]: value});
    await refreshAll();
  }

  async function decideFallback(decision, fallbackModel) {
    await post('./api/llm/fallback', {decision, fallback_model: fallbackModel});
    await refreshAll();
  }

  async function triggerBatch() {
    const btn = $('batchBtn');
    btn.disabled = true; btn.textContent = 'Analyzing all agents...';
    try { await post('./api/batch/analyze', {agent_id: 'all'}); }
    finally { btn.disabled = false; btn.textContent = 'Run analysis now'; }
    await refreshAll();
  }

  async function decideApproval(id, decision) {
    const noteEl = document.getElementById('note_' + id);
    const humanNote = noteEl ? noteEl.value.trim() : '';
    await post('./api/approvals/' + id + '/decide', {decision, human_note: humanNote});
    await refreshAll();
  }

  async function dismissAllApprovals() {
    if (!confirm('Dismiss all pending proposals?')) return;
    await post('./api/approvals/dismiss-all', {});
    await refreshAll();
  }

  async function unblockRejected(signature) {
    if (!confirm('Unblock this suggestion? Agents may propose it again.')) return;
    await fetch('./api/rejected?signature=' + encodeURIComponent(signature), {method: 'DELETE'});
    await refreshAll();
  }

  async function revokeRule(signature) {
    if (!confirm('Revoke this rule? The action will ask for your approval again.')) return;
    await fetch('./api/rules?signature=' + encodeURIComponent(signature), {method: 'DELETE'});
    await refreshAll();
  }

  async function clearActivityLogs() {
    if (!confirm('Clear all agent activity logs? This frees database storage.')) return;
    await fetch('./api/logs', {method: 'DELETE'});
    allLoadedLogs = [];
    loadedLogIds.clear();
    $('logsList').innerHTML = '';
    await refreshAll();
  }

  async function dismissInsight(insightId) {
    await post('./api/insights/' + encodeURIComponent(insightId) + '/dismiss', {});
    await refreshAll();
  }

  async function dismissAllInsights() {
    if (!confirm('Mark all active insights as read / dismissed?')) return;
    await post('./api/insights/dismiss_all', {});
    await refreshAll();
  }

  async function rejectInsightPrompt(insightId) {
    const reason = prompt('Why do you want to reject this recommendation? (Optional note so agents never suggest it again):', '');
    if (reason === null) return;
    await post('./api/insights/' + encodeURIComponent(insightId) + '/reject', {reason: reason});
    await refreshAll();
  }

  async function deleteInsight(insightId) {
    if (!confirm('Delete this insight permanently?')) return;
    await fetch('./api/insights/' + encodeURIComponent(insightId), {method: 'DELETE'});
    await refreshAll();
  }

  async function clearAllInsights() {
    if (!confirm('Delete all insights permanently?')) return;
    await fetch('./api/insights', {method: 'DELETE'});
    await refreshAll();
  }

  async function unblockRejectedInsight(insightId) {
    if (!confirm('Unblock this recommendation? Agents will be permitted to analyze and suggest it again.')) return;
    await fetch('./api/insights/rejected/' + encodeURIComponent(insightId), {method: 'DELETE'});
    await refreshAll();
  }

  async function addContextNote() {
    const content = $('contextNoteInput').value.trim();
    if (!content) return;
    const ents = $('contextEntitiesInput').value;
    const related_entities = ents ? ents.split(',').map(s => s.trim()).filter(Boolean) : [];
    await post('./api/context-notes', {content, scope: 'global', related_entities});
    $('contextNoteInput').value = ''; $('contextEntitiesInput').value = '';
    await refreshAll();
  }

  async function deleteContextNote(id) { await fetch('./api/context-notes/' + id, {method: 'DELETE'}); await refreshAll(); }

  async function addIgnoredTarget() {
    const pattern = $('ignorePatternInput').value.trim();
    if (!pattern) return;
    await post('./api/ignore-list', {pattern, reason: $('ignoreReasonInput').value.trim()});
    $('ignorePatternInput').value = ''; $('ignoreReasonInput').value = '';
    await refreshAll();
  }

  async function deleteIgnoredTarget(id) { await fetch('./api/ignore-list/' + id, {method: 'DELETE'}); await refreshAll(); }

  async function loadMoreLogs() {
    if (isLoadingMoreLogs) return;
    isLoadingMoreLogs = true;
    try {
      const res = await fetch('./api/logs?offset=' + allLoadedLogs.length + '&limit=10');
      const json = await res.json();
      totalServerLogs = json.total;
      const fresh = (json.logs || []).filter(l => !loadedLogIds.has(l.run_id));
      fresh.forEach(l => { allLoadedLogs.push(l); loadedLogIds.add(l.run_id); });
      $('logsList').insertAdjacentHTML('beforeend', fresh.map(renderLog).join(''));
      $('logsLoadMoreContainer').style.display = allLoadedLogs.length < totalServerLogs ? 'block' : 'none';
      $('loadMoreLogsBtn').textContent = `Load older activity (${allLoadedLogs.length} of ${totalServerLogs})`;
    } catch (e) { /* keep button available for retry */ }
    finally { isLoadingMoreLogs = false; }
  }

  const logsScroll = $('logsScrollContainer');
  if (logsScroll) {
    logsScroll.addEventListener('scroll', () => {
      if (logsScroll.scrollTop + logsScroll.clientHeight >= logsScroll.scrollHeight - 60
          && allLoadedLogs.length < totalServerLogs && !isLoadingMoreLogs) loadMoreLogs();
    });
  }

  initTabs();
  window.addEventListener('hashchange', handleHashNav);
  refreshAll();
  setInterval(refreshAll, 5000);
</script>
</body>
</html>
"""


def render_dashboard_html(settings: object | None = None, available_notify_services: list[str] | None = None) -> str:
    """Render DASHBOARD_HTML with current server-side settings pre-selected so page refreshes and new devices never flash default values."""
    html = DASHBOARD_HTML
    if settings is None:
        return html

    op_mode = getattr(getattr(settings, "operating_mode", None), "value", getattr(settings, "operating_mode", "hybrid"))
    autonomy = getattr(getattr(settings, "default_autonomy", None), "value", getattr(settings, "default_autonomy", "copilot"))
    fb_policy = getattr(getattr(settings, "llm_fallback_policy", None), "value", getattr(settings, "llm_fallback_policy", "auto"))
    notify_svc = str(getattr(settings, "notification_service", "notify.notify") or "notify.notify")
    notify_enabled = bool(getattr(settings, "notifications_enabled", True))

    html = html.replace(
        '<span class="pill" id="modeBadge">Loading...</span>',
        f'<span class="pill" id="modeBadge">{str(op_mode).replace("_", " ")} / {autonomy}</span>',
    )
    html = html.replace(f'<option value="{op_mode}">', f'<option value="{op_mode}" selected>')
    html = html.replace(f'<option value="{autonomy}">', f'<option value="{autonomy}" selected>')
    html = html.replace(f'<option value="{fb_policy}">', f'<option value="{fb_policy}" selected>')

    svcs = list(available_notify_services or [notify_svc])
    if notify_svc not in svcs:
        svcs.insert(0, notify_svc)
    options_html = "".join(
        f'<option value="{s}"{" selected" if s == notify_svc else ""}>{s}</option>'
        for s in svcs
    )
    html = html.replace(
        '<option value="notify.notify">Loading HA notify services...</option>',
        options_html,
    )
    if not notify_enabled:
        html = html.replace(
            'onchange="updateSetting(\'notifications_enabled\', this.checked)" checked />',
            'onchange="updateSetting(\'notifications_enabled\', this.checked)" />',
        )
    return html
