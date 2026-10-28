"""Self-contained Home Assistant Ingress Web UI Dashboard for HA AI Brain."""

from __future__ import annotations

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
    .pill.wrap { white-space: normal; flex-shrink: 1; max-width: 100%; min-width: 0; text-transform: none; overflow-wrap: anywhere; line-height: 1.3; }
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
      overflow-x: hidden;
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
    <div class="status" style="display:flex; flex-direction:column; align-items:flex-end; gap:4px;">
      <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; justify-content:flex-end;">
        <span class="pill" id="modeBadge">Loading...</span>
        <span class="pill ok" id="llmBadge"><span class="dot"></span><span id="llmBadgeText">AI ready</span></span>
        <button onclick="triggerBatch()" id="batchBtn">Run analysis now</button>
        <button class="icon" onclick="togglePause()" id="pauseBtn" title="Kill switch: keep learning but never act or call the AI in real time">Pause brain</button>
      </div>
      <div id="nextBatchHeader" class="muted" style="font-size:11px; white-space:nowrap; display:none;"></div>
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
    <button class="tab-btn" role="tab" id="tabBtn-learned" onclick="switchTab('learned')">
      Learned
    </button>
    <button class="tab-btn" role="tab" id="tabBtn-research" onclick="switchTab('research')">
      Research
      <span class="tab-badge" id="tabBadge-research" style="display:none;">0</span>
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
  <div id="pausedBanner" class="banner">
    <strong class="t">Brain paused</strong>
    <div class="muted">It keeps learning from events but will not act on devices or call the AI in real time. Manual approvals still work.</div>
  </div>

  <!-- TAB 1: Approvals -->
  <div id="pane-approvals" class="tab-pane active">
    <div class="grid" style="margin-bottom:16px;">
      <div class="card">
        <div class="card-head"><h2>Create an automation</h2></div>
        <div class="hint">Describe it in your own words. The AI writes a native Home Assistant automation; you review and edit the YAML, then create or cancel. Nothing is created until you press Create.</div>
        <textarea id="autoText" rows="2" maxlength="1500" style="width:100%; box-sizing:border-box; margin-top:8px; background:var(--bg); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:8px 10px; font-family:inherit; font-size:13px;" placeholder="e.g. Close the kitchen blind at sunset on weekdays, but only when someone is home"></textarea>
        <div class="btn-row" style="align-items:center;">
          <button class="primary" id="autoDraftBtn" onclick="draftAutomation()">Write automation</button>
          <span id="autoMsg" class="muted"></span>
        </div>
        <div id="autoDraft"></div>
      </div>
    </div>
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
          <div>
            <h2>Agent activity</h2>
            <div id="nextBatchActivity" class="muted" style="font-size:11px; margin-top:2px; font-weight:normal;"></div>
          </div>
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
        <div class="card-head"><h2>Watches</h2><span class="pill" id="watchCount">0</span></div>
        <div class="hint">Describe in your own words what you want to be told about. The AI interprets it once; from then on it is checked every minute without using any AI tokens.</div>
        <textarea id="watchText" rows="2" maxlength="1000" style="width:100%; box-sizing:border-box; margin-top:8px; background:var(--bg); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:8px 10px; font-family:inherit; font-size:13px;" placeholder="What should trigger an alert, for how long, and when does it apply?"></textarea>
        <div class="btn-row" style="align-items:center;">
          <button class="primary" id="watchCompileBtn" onclick="compileWatch()">Interpret</button>
          <span id="watchMsg" class="muted"></span>
        </div>
        <div id="watchDraft"></div>
        <div id="watchList" class="scroll" style="margin-top:12px;"></div>
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

    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div class="card-head">
          <h2>Ignored entities &amp; devices</h2>
          <span class="pill" id="ignoredCountBadge" style="display:none;">0</span>
        </div>
        <div class="hint">Matching entities are dropped before triage and never reach the AI. Supports <code>*</code> wildcards.</div>
        <div class="inline-form">
          <input type="text" id="ignorePatternInput" placeholder="e.g. sensor.vendor_* or *device_name*" />
          <input type="text" id="ignoreReasonInput" placeholder="Reason (optional)" />
          <button class="primary" onclick="addIgnoredTarget()">Add to ignore list</button>
        </div>
        <div id="ignoredTargetsList" class="scroll" style="margin-top:14px;"></div>
      </div>
    </div>

    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div class="card-head">
          <h2>Minimum change per sensor</h2>
          <span class="pill" id="minChangeCountBadge" style="display:none;">0</span>
        </div>
        <div class="hint">For noisy numeric sensors only: moves smaller than this are not treated as significant live events (they are still recorded). Applies only to what you list here; supports <code>*</code> wildcards, e.g. <code>sensor.*_voltage</code>. Use the sensor's own unit.</div>
        <div class="inline-form">
          <input type="text" id="minChangePatternInput" placeholder="e.g. sensor.mains_voltage" />
          <input type="number" id="minChangeValueInput" min="0" step="any" placeholder="Minimum change, e.g. 5" />
          <input type="text" id="minChangeReasonInput" placeholder="Reason (optional)" />
          <button class="primary" onclick="addMinChange()">Add</button>
        </div>
        <div id="minChangeList" class="scroll" style="margin-top:14px;"></div>
      </div>
    </div>
  </div>

  <!-- TAB: Learned -->
  <div id="pane-learned" class="tab-pane">
    <div class="grid two">
      <div class="card">
        <div class="card-head"><h2>Learning progress</h2><span class="pill" id="learnedStatePill">-</span></div>
        <div style="height:8px; background:rgba(255,255,255,0.08); border-radius:6px; overflow:hidden; margin:8px 0 12px;">
          <div id="learnedBar" style="height:100%; width:0%; background:var(--accent);"></div>
        </div>
        <div id="learnedKv" class="kv"></div>
      </div>
      <div class="card">
        <div class="card-head"><h2>Last 7 days</h2></div>
        <div class="hint">What local learning did for you without spending AI tokens.</div>
        <div id="learnedStats" class="kv" style="margin-top:8px;"></div>
      </div>
    </div>
    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div class="card-head"><h2>Recent autonomous actions</h2></div>
        <div class="hint">Anything the brain did on its own in the last 24 hours can be reverted here.</div>
        <div id="undoList" class="scroll" style="margin-top:8px;"></div>
      </div>
    </div>
    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div class="card-head"><h2>Habits found in your history</h2><span class="pill" id="patternsCount">0</span></div>
        <div class="hint">Recurring behaviour measured from your own usage. Strong habits that no automation covers yet are proposed as native automations (see Approvals).</div>
        <div id="patternsList" class="scroll" style="margin-top:8px;"></div>
      </div>
    </div>
    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div class="card-head"><h2>Muted alerts</h2></div>
        <div class="hint">Unusual-situation alerts you rejected. Dismissing an alert makes the brain wait longer before repeating it; rejecting mutes it until you unmute it here.</div>
        <div id="mutedList" style="margin-top:8px;"></div>
      </div>
    </div>
    <div class="grid" style="margin-top:16px; display:none;" id="adoptCard">
      <div class="card">
        <div class="card-head"><h2>Automations found that the brain does not track</h2></div>
        <div class="hint">These automations have the brain's id prefix (ai_brain_) in Home Assistant, but the brain has no record of them, for example after a reinstall. Tick the ones that are really the brain's and start tracking them so their health is reviewed. Nothing is changed in Home Assistant.</div>
        <div id="adoptList" style="margin-top:8px;"></div>
        <div class="btn-row"><button class="primary" onclick="adoptSelected()">Track selected</button></div>
      </div>
    </div>
    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div class="card-head"><h2>Deployed automation health</h2></div>
        <div class="hint">Checked daily. This lists only automations created through the brain (approved proposals and ones you wrote above), not all your Home Assistant automations. Renaming one in Home Assistant is fine. If you deleted one, "Stop tracking" lets the brain propose it again later, "Never propose again" does not.</div>
        <div id="reviewsList" class="scroll" style="margin-top:8px;"></div>
      </div>
    </div>
  </div>

  <!-- TAB: Research -->
  <div id="pane-research" class="tab-pane">
    <div class="grid">
      <div class="card">
        <div class="card-head"><h2>Research agenda</h2><span class="pill" id="researchStatePill">-</span></div>
        <div class="hint">Each specialised agent thinks like an expert in its field and proposes practical knowledge about your equipment and setup. Works with any AI provider. Nothing influences the agents until you approve it.</div>
        <div id="researchKv" class="kv" style="margin-top:8px;"></div>
        <div id="researchNote" class="muted" style="font-size:0.82rem; margin-top:8px;"></div>
        <div class="btn-row" style="align-items:center; margin-top:10px;">
          <label class="check"><input type="checkbox" id="researchCheck" onchange="setRuntime('research_enabled', this.checked)" /> Research automatically</label>
          <label class="field" style="flex-direction:row; align-items:center; gap:6px;">every
            <input type="number" min="1" max="90" id="researchIntervalInput" style="width:70px;" onchange="setRuntime('research_interval_days', parseInt(this.value || '7', 10))" /> days
          </label>
          <button class="primary" id="researchRunBtn" onclick="runResearchNow()">Research now</button>
        </div>
        <label class="check" style="margin-top:8px;"><input type="checkbox" id="researchWebCheck" onchange="setRuntime('research_web_search', this.checked)" /> Optional deep research with web search and cited sources (Google Gemini only, uses noticeably more tokens)</label>
      </div>
    </div>
    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div class="card-head"><h2>Waiting for your review</h2><span class="pill warn" id="researchProposedCount">0</span></div>
        <div class="hint">Keep what looks useful and reject the rest. Rejected topics are never researched again. Items based on general AI knowledge are not checked against sources; judge them like advice from a knowledgeable friend.</div>
        <div id="researchProposed" style="margin-top:8px;"></div>
      </div>
    </div>
    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div class="card-head"><h2>Approved knowledge</h2><span class="pill ok" id="researchApprovedCount">0</span></div>
        <div class="hint">Used by the matching agent in its reasoning.</div>
        <div id="researchApproved" style="margin-top:8px;"></div>
      </div>
    </div>
    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div class="card-head"><h2>Upcoming topics</h2></div>
        <div id="researchBacklog" style="margin-top:8px;"></div>
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
          <div id="batchScheduleBox" style="margin-top:12px; padding:10px 12px; background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:6px; font-size:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; gap:8px;">
              <span class="muted">Next scheduled batch:</span>
              <strong id="nextBatchSettings">-</strong>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
              <span class="muted">Last batch executed:</span>
              <span id="lastBatchSettings" class="muted">-</span>
            </div>
          </div>
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
        <div class="card-head"><h2>Learning &amp; Safety</h2></div>
        <div class="hint">Local learning runs without AI tokens. Safety limits apply to everything the brain does on its own.</div>
        <div class="fields" style="margin-top:12px;">
          <label class="check"><input type="checkbox" id="gatingCheck" onchange="setRuntime('realtime_gating', this.checked)" /> Only wake the AI for unusual events once routines are learned</label>
          <label class="check"><input type="checkbox" id="exceptionCheck" onchange="setRuntime('exception_detection', this.checked)" /> Detect unusual situations (unlocked while away, broken routine, automation did not run)</label>
          <label class="check"><input type="checkbox" id="habitCheck" onchange="setRuntime('deterministic_automations', this.checked)" /> Propose automations for strong habits straight from statistics (no AI tokens)</label>
          <label class="check"><input type="checkbox" id="announceCheck" onchange="setRuntime('notify_autonomous_actions', this.checked)" /> Tell me, with an Undo button, when the brain acts on its own</label>
          <label class="check"><input type="checkbox" id="privacyCheck" onchange="setRuntime('privacy_scrub', this.checked)" /> Hide people, phones and network identifiers from cloud AI providers</label>
          <div class="grid two" style="gap:12px; margin:0;">
            <label class="field">Daily AI token budget (0 = unlimited)
              <input type="number" min="0" step="1000" id="tokenBudgetInput" onchange="setRuntime('daily_token_budget', parseInt(this.value || '0', 10))" />
            </label>
            <label class="field">Max autonomous actions per hour
              <input type="number" min="1" max="1000" id="maxActionsInput" onchange="setRuntime('max_actions_per_hour', parseInt(this.value || '30', 10))" />
            </label>
          </div>
          <div class="grid two" style="gap:12px; margin:0;">
            <label class="field">Merge events in the same area for (seconds, 0 = off)
              <input type="number" min="0" max="3600" id="coalesceInput" onchange="setRuntime('realtime_coalesce_seconds', parseInt(this.value || '0', 10))" />
            </label>
            <label class="field">Max real-time AI wake-ups per agent per hour (0 = unlimited)
              <input type="number" min="0" max="1000" id="wakeCapInput" onchange="setRuntime('max_agent_wakeups_per_hour', parseInt(this.value || '0', 10))" />
            </label>
          </div>
          <div class="grid two" style="gap:12px; margin:0;">
            <label class="field">Quiet hours start (low-priority pushes are held)
              <input type="time" id="quietStartInput" onchange="saveQuietHours()" />
            </label>
            <label class="field">Quiet hours end
              <input type="time" id="quietEndInput" onchange="saveQuietHours()" />
            </label>
          </div>
          <div class="hint" style="margin:4px 0 10px; display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
            <span id="quietHint">Quiet hours are off.</span>
            <button class="icon" type="button" onclick="clearQuietHours()">Clear quiet hours</button>
          </div>
          <div class="field">Autonomy per device type
            <div class="hint" style="margin:4px 0 6px;">Override the global autonomy for one domain, for example lights autonomous while locks stay co-pilot. Critical security actions always need approval.</div>
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
              <input type="text" id="domainAutoName" placeholder="domain, e.g. light" style="flex:1 1 140px;" />
              <select id="domainAutoLevel">
                <option value="shadow">Shadow</option>
                <option value="copilot">Co-pilot</option>
                <option value="autonomous">Autonomous</option>
              </select>
              <button class="primary" onclick="addDomainAutonomy()">Set</button>
            </div>
            <div id="domainAutonomyList" style="margin-top:8px;"></div>
          </div>
        </div>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div class="card-head"><h2>Active Specialized Domain Agents</h2><span class="pill" id="agentsCountBadge">0</span></div>
        <div class="hint">Specialized cognitive agents that analyze both real-time stream events and periodic historical batch patterns.</div>
        <div id="agentsList" style="margin-top:14px;"></div>
      </div>
    </div>
    <div class="grid" style="margin-top:16px;">
      <div class="card">
        <div class="card-head"><h2>Backup &amp; restore</h2></div>
        <div class="hint">Saves what you decided or wrote: settings, notes, ignore list, minimum-change rules, Watches, muted alerts, rejected suggestions and insights, always-allow rules, tracked automations and approved research. It does not include recorded history, logs or your API key. Importing merges into what is already here and never deletes anything. Uninstalling the add-on erases all of this, so export first.</div>
        <div class="btn-row" style="align-items:center;">
          <a href="./api/export" download><button class="primary" type="button">Export to file</button></a>
          <button class="icon" type="button" onclick="$('importFile').click()">Import from file...</button>
          <input type="file" id="importFile" accept="application/json,.json" style="display:none;" onchange="previewImport(this)" />
        </div>
        <div id="importPreview"></div>
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
  let latestApprovalStatuses = {};
  let activePendingApprovalIds = new Set();

  function esc(v) {
    return String(v === null || v === undefined ? '' : v)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  const $ = id => document.getElementById(id);

  function formatRelativeSchedule(isoString) {
    if (!isoString) return null;
    const target = new Date(isoString);
    if (isNaN(target.getTime())) return null;
    const now = new Date();
    const diffMs = target.getTime() - now.getTime();
    const isPast = diffMs < -60000;
    const absDiffSec = Math.floor(Math.abs(diffMs) / 1000);
    const hours = Math.floor(absDiffSec / 3600);
    const mins = Math.floor((absDiffSec % 3600) / 60);

    let relText = '';
    if (hours >= 24) {
      const days = Math.floor(hours / 24);
      relText = `${days}d ${hours % 24}h`;
    } else if (hours > 0) {
      relText = `${hours}h ${mins}m`;
    } else if (mins > 0) {
      relText = `${mins}m`;
    } else {
      relText = '<1m';
    }

    const timeStr = target.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const isToday = target.toDateString() === now.toDateString();
    const tomorrow = new Date(now);
    tomorrow.setDate(tomorrow.getDate() + 1);
    const isTomorrow = target.toDateString() === tomorrow.toDateString();

    let datePrefix = '';
    if (isToday) {
      datePrefix = 'Today';
    } else if (isTomorrow) {
      datePrefix = 'Tomorrow';
    } else {
      datePrefix = target.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }

    if (isPast) {
      return `${datePrefix} at ${timeStr} (${relText} ago)`;
    }
    return `${datePrefix} at ${timeStr} (in ${relText})`;
  }

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

  function getActiveHash() {
    let rawHash = (window.location.hash || '').replace('#', '').trim();
    if (!rawHash) {
      try {
        if (window.parent && window.parent !== window && window.parent.location && window.parent.location.hash) {
          rawHash = (window.parent.location.hash || '').replace('#', '').trim();
        }
      } catch (e) {
        // Cross-origin iframe fallback
      }
    }
    return rawHash;
  }

  function handleHashNav() {
    const rawHash = getActiveHash();
    if (!rawHash) return;
    if (['approvals', 'activity', 'memory', 'learned', 'research', 'settings'].includes(rawHash)) {
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
    const tabs = ['approvals', 'activity', 'memory', 'learned', 'research', 'settings'];
    if (!tabs.includes(tabName)) tabName = 'approvals';
    tabs.forEach(t => {
      const btn = $('tabBtn-' + t);
      const pane = $('pane-' + t);
      if (btn) btn.classList.toggle('active', t === tabName);
      if (pane) pane.classList.toggle('active', t === tabName);
    });
    if (tabName === 'learned') refreshLearned();
    if (tabName === 'memory') refreshWatches();
    if (tabName === 'research') refreshResearch();
    if (window.history && window.history.replaceState) {
      const curHash = getActiveHash();
      if (['approvals', 'activity', 'memory', 'learned', 'research', 'settings'].includes(curHash)) {
        window.history.replaceState(null, null, '#' + tabName);
        try {
          if (window.parent && window.parent !== window && window.parent.history && window.parent.history.replaceState) {
            window.parent.history.replaceState(null, null, '#' + tabName);
          }
        } catch (e) {}
      }
    }
  }

  function initTabs() {
    const hash = getActiveHash();
    if (['approvals', 'activity', 'memory', 'learned', 'research', 'settings'].includes(hash)) {
      switchTab(hash);
    } else if (hash) {
      handleHashNav();
    } else {
      switchTab('approvals');
    }
  }

  function renderApprovalStatusBadge(approvalId, isInline) {
    if (!approvalId) return '';
    const st = latestApprovalStatuses[approvalId] || (activePendingApprovalIds.has(approvalId) ? 'pending' : '');
    const inlinePad = isInline ? 'font-size:11px; padding:3px 8px;' : 'margin-top:8px; font-size:0.78rem; padding:4px 10px;';
    if (!st || st === 'pending') {
      return `<button class="icon primary" style="${inlinePad}" onclick="jumpToElement('approvals', 'approval-${esc(approvalId)}')">⚡ View Pending Approval</button>`;
    }
    if (st === 'approved_once') {
      return `<span class="pill ok" style="${inlinePad} display:inline-block; font-weight:600;" title="Action was approved and executed">✓ Approved once</span>`;
    }
    if (st === 'approved_repeatable') {
      return `<button class="icon" style="${inlinePad} color:var(--ok); border-color:rgba(46,204,113,0.4); font-weight:600;" onclick="switchTab('memory')" title="Always allowed rule created - click to view in Memory & Rules">✓ Always allowed rule</button>`;
    }
    if (st === 'rejected') {
      return `<button class="icon" style="${inlinePad} color:#e74c3c; border-color:rgba(231,76,60,0.4); font-weight:600;" onclick="switchTab('memory')" title="Rejected by user - click to view in Memory & Rules">✕ Rejected</button>`;
    }
    if (st === 'dismissed') {
      return `<span class="pill" style="${inlinePad} display:inline-block; color:var(--muted);" title="Dismissed without execution">Dismissed</span>`;
    }
    return '';
  }

  function renderTopApprovalBadge(approvalId) {
    if (!approvalId) return '';
    const st = latestApprovalStatuses[approvalId] || (activePendingApprovalIds.has(approvalId) ? 'pending' : '');
    if (!st || st === 'pending') {
      return `<button class="icon" style="border-color:var(--warn); color:var(--warn); font-size:0.76rem; padding:2px 8px;" onclick="jumpToElement('approvals', 'approval-${esc(approvalId)}')">⚡ Pending Approval</button>`;
    }
    if (st === 'approved_once') {
      return `<span class="pill ok" style="font-size:0.76rem; padding:2px 8px; font-weight:600;" title="Action was approved and executed">✓ Approved</span>`;
    }
    if (st === 'approved_repeatable') {
      return `<button class="icon" style="font-size:0.76rem; padding:2px 8px; color:var(--ok); border-color:rgba(46,204,113,0.4); font-weight:600;" onclick="switchTab('memory')" title="Always allowed rule created">✓ Always allowed</button>`;
    }
    if (st === 'rejected') {
      return `<button class="icon" style="font-size:0.76rem; padding:2px 8px; color:#e74c3c; border-color:rgba(231,76,60,0.4); font-weight:600;" onclick="switchTab('memory')" title="Rejected by user">✕ Rejected</button>`;
    }
    if (st === 'dismissed') {
      return `<span class="pill" style="font-size:0.76rem; padding:2px 8px; color:var(--muted);" title="Dismissed without execution">Dismissed</span>`;
    }
    return '';
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
      const jumpToApprovalBtn = approvalId ? renderApprovalStatusBadge(approvalId, false) : '';
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
    const topApprovalBtn = firstApprovalId ? renderTopApprovalBadge(firstApprovalId) : '';

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
        ${renderBacktest(p.intent.backtest)}
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
        <div class="btn-row">${avail.map(m => `<button class="primary" data-model="${esc(m)}" onclick="decideFallback('approve_fallback', this.dataset.model)">Use ${esc(m)}</button>`).join('')}
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
      <span>Requests</span><span>${esc(q.requests_succeeded_session || 0)} ok / ${esc(q.requests_rate_limited_session || 0)} rate-limited <small class="muted">(current run)</small></span>
      <span>Tokens</span><span>${esc(totalTok)} &middot; est. ${esc(spend)} <small class="muted">(current run)</small></span>
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
      syncSafetyControls(data.settings);

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
    $('licenseBox').textContent = `Plan: ${data.license.plan_tier} | Tokens used: ${data.license.tokens_used_this_period} (current container session)`;

    pausedState = !!(data.settings && data.settings.paused);
    $('pausedBanner').style.display = pausedState ? 'block' : 'none';
    $('pauseBtn').textContent = pausedState ? 'Resume brain' : 'Pause brain';
    const rb = $('tabBadge-research');
    if (rb) { const n = data.research_pending_review || 0; rb.textContent = n; rb.style.display = n > 0 ? 'inline-block' : 'none'; }
    latestUndo = data.undo_records || [];
    renderUndo();

    latestApprovalStatuses = data.approval_statuses || {};
    activePendingApprovalIds = new Set((data.pending_approvals || []).map(p => p.approval_id));

    renderQuota(data);
    reconcilePending(data.pending_approvals || []);

    const opMode = (data.settings && data.settings.operating_mode) || 'hybrid';
    const nextBatchStr = formatRelativeSchedule(data.next_batch_run_at);
    const lastBatchStr = formatRelativeSchedule(data.last_batch_run_at);
    const intervalMins = data.batch_interval_minutes || 360;
    const intervalHours = (intervalMins / 60).toFixed(intervalMins % 60 === 0 ? 0 : 1);

    const nbHeader = $('nextBatchHeader');
    if (nbHeader) {
      if (opMode === 'realtime_stream') {
        nbHeader.textContent = 'Next batch: Paused in Real-time mode';
        nbHeader.style.display = 'block';
      } else if (nextBatchStr) {
        nbHeader.textContent = 'Next batch: ' + nextBatchStr;
        nbHeader.style.display = 'block';
      } else {
        nbHeader.style.display = 'none';
      }
    }

    const nbActivity = $('nextBatchActivity');
    if (nbActivity) {
      if (opMode === 'realtime_stream') {
        nbActivity.textContent = 'Periodic batch paused (Real-time event mode)';
      } else if (nextBatchStr) {
        nbActivity.textContent = 'Next scheduled batch: ' + nextBatchStr;
      } else {
        nbActivity.textContent = '';
      }
    }

    const nbSettings = $('nextBatchSettings');
    const lbSettings = $('lastBatchSettings');
    if (nbSettings) {
      if (opMode === 'realtime_stream') {
        nbSettings.textContent = 'Paused in Real-time mode';
      } else {
        nbSettings.textContent = (nextBatchStr || '-') + (intervalHours ? ` (every ${intervalHours}h)` : '');
      }
    }
    if (lbSettings) {
      lbSettings.textContent = lastBatchStr || (data.last_batch_run_at ? new Date(data.last_batch_run_at).toLocaleString() : 'None yet');
    }

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
    const ignBadge = $('ignoredCountBadge');
    if (ignBadge) {
      ignBadge.style.display = ignored.length ? 'inline-block' : 'none';
      ignBadge.textContent = ignored.length;
    }
    $('ignoredTargetsList').innerHTML = ignored.length ? ignored.map(t => `
      <div class="item row"><div><code>${esc(t.pattern)}</code>${t.reason ? ` <span class="muted">${esc(t.reason)}</span>` : ''}</div>
        <button class="danger icon" title="Remove" onclick="deleteIgnoredTarget('${esc(t.ignore_id)}')">Remove</button></div>`).join('')
      : '<div class="empty">Nothing is ignored.</div>';

    const minRules = data.min_change_rules || [];
    const mcBadge = $('minChangeCountBadge');
    if (mcBadge) { mcBadge.style.display = minRules.length ? 'inline-block' : 'none'; mcBadge.textContent = minRules.length; }
    $('minChangeList').innerHTML = minRules.length ? minRules.map(r => `
      <div class="item row"><div><code>${esc(r.pattern)}</code> <span class="muted">ignore moves smaller than ${esc(String(r.min_change))}${r.reason ? ' &middot; ' + esc(r.reason) : ''}</span></div>
        <button class="danger icon" title="Remove" onclick="deleteMinChange('${esc(r.rule_id)}')">Remove</button></div>`).join('')
      : '<div class="empty">No minimum changes set.</div>';

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

    const proposals = [];
    (data.recent_logs || []).forEach(l => (l.proposed_intents || []).forEach((i, idx) => {
      if (i.domain === 'automation' || i.native_automation) {
        const ex = (l.execution_results || [])[idx] || {};
        const approvalId = i.approval_id || ex.approval_id;
        const st = (latestApprovalStatuses && latestApprovalStatuses[approvalId]) || (activePendingApprovalIds.has(approvalId) ? 'pending' : '');
        // An automation proposal belongs in "Insights & recommendations" ONLY if it is still awaiting user action!
        // Once approved, rejected, or dismissed, it is resolved and lives in Agent Activity and Memory & Rules.
        if (approvalId && (activePendingApprovalIds.has(approvalId) || (!st || st === 'pending'))) {
          proposals.push({agent: l.agent_id, intent: i, run_id: l.run_id, approvalId});
        }
      }
    }));

    const unreadInsights = data.active_insights_count !== undefined ? data.active_insights_count : (data.advisory_insights || []).length;
    const totalActiveItems = unreadInsights + proposals.length;
    const tabActBadge = $('tabBadge-activity');
    if (tabActBadge) {
      tabActBadge.style.display = totalActiveItems > 0 ? 'inline-block' : 'none';
      tabActBadge.textContent = totalActiveItems;
    }
    const insBadge = $('activeInsightsCountBadge');
    if (insBadge) {
      insBadge.style.display = totalActiveItems > 0 ? 'inline-block' : 'none';
      insBadge.textContent = totalActiveItems;
    }
    if ($('dismissAllInsightsBtn')) $('dismissAllInsightsBtn').style.display = unreadInsights > 0 ? 'inline-block' : 'none';
    if ($('clearAllInsightsBtn')) $('clearAllInsightsBtn').style.display = (data.advisory_insights || []).length > 0 ? 'inline-block' : 'none';

    const lBox = $('logsList');
    if (data.recent_logs && data.recent_logs.length) {
      $('logsEmpty').style.display = 'none';
      if (allLoadedLogs.length === 0) {
        allLoadedLogs = [...data.recent_logs];
        allLoadedLogs.forEach(l => loadedLogIds.add(l.run_id));
      } else {
        data.recent_logs.filter(l => !loadedLogIds.has(l.run_id)).reverse().forEach(l => {
          allLoadedLogs.unshift(l); loadedLogIds.add(l.run_id);
        });
      }
      const scrollPos = $('logsScrollContainer') ? $('logsScrollContainer').scrollTop : 0;
      lBox.innerHTML = allLoadedLogs.map(renderLog).join('');
      if ($('logsScrollContainer')) $('logsScrollContainer').scrollTop = scrollPos;
    }
    const more = $('logsLoadMoreContainer');
    more.style.display = allLoadedLogs.length < totalServerLogs ? 'block' : 'none';
    $('loadMoreLogsBtn').textContent = `Load older activity (${allLoadedLogs.length} of ${totalServerLogs})`;

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
    html += proposals.map(({agent, intent, run_id, approvalId}) => {
      const viewRunBtn = run_id
        ? `<button class="icon" type="button" style="font-size:11px; padding:3px 8px; color:var(--accent); border-color:rgba(79,156,249,0.4);" onclick="jumpToElement('activity', 'log-${esc(run_id)}')">🔍 View <span class="hide-mobile">agent </span>reasoning</button>`
        : '';
      const actions = approvalId ? `
        <div class="insight-actions">
          <button class="icon primary" style="font-size:11px; padding:4px 9px;" onclick="jumpToElement('approvals', 'approval-${esc(approvalId)}')">
            ⚡ Review in Approvals
          </button>
          <button class="icon" style="font-size:11px; padding:4px 9px; color:#e74c3c; border-color:rgba(231,76,60,0.35);" onclick="decideApproval('${esc(approvalId)}', 'rejected')" title="Reject this proposed automation">
            ✕ Reject
          </button>
          <button class="icon" style="font-size:11px; padding:4px 8px; color:var(--muted);" onclick="decideApproval('${esc(approvalId)}', 'dismissed')" title="Dismiss without action">
            Dismiss
          </button>
        </div>` : '';
      return `
      <div class="item" id="prop-${esc(approvalId || run_id)}">
        <div class="insight-head">
          <div class="insight-title-group">
            <strong class="insight-title">⚡ Proposed automation</strong>
            <span class="muted" style="font-size:12px;">${esc(agent)}</span>
          </div>
          <div class="insight-meta">${viewRunBtn}</div>
        </div>
        <div class="muted" style="margin:6px 0; font-size:13px; line-height:1.4; word-break: break-word; overflow-wrap: anywhere;">${esc(intent.rationale)}</div>
        <pre>${esc(JSON.stringify(intent.native_automation || intent.service_data, null, 2))}</pre>
        ${actions}
      </div>`;
    }).join('');
    $('insightsList').innerHTML = html || '<div class="empty">No active insights or recommendations. Run an analysis to generate some.</div>';

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

  let pausedState = false;
  let latestUndo = [];

  function renderBacktest(bt) {
    if (!bt || !bt.summary) return '';
    const colors = {supported: 'var(--ok)', partial: 'var(--warn)', weak: '#e74c3c', unverifiable: 'var(--muted)'};
    const labels = {supported: 'Matches your history', partial: 'Partly matches your history', weak: 'Does not match your history', unverifiable: 'Not verifiable from history'};
    const color = colors[bt.verdict] || 'var(--muted)';
    const quality = (bt.quality !== null && bt.quality !== undefined) ? ' (' + Math.round(bt.quality * 100) + '% aligned)' : '';
    return `<div style="margin:8px 0; padding:8px 12px; border:1px solid var(--border); border-left:3px solid ${color}; border-radius:8px; background:rgba(0,0,0,0.25);">
      <div style="font-size:0.78rem; font-weight:700; color:${color};">🧪 Backtest: ${esc(labels[bt.verdict] || bt.verdict)}${esc(quality)}</div>
      <div class="muted" style="font-size:0.8rem; margin-top:3px;">${esc(bt.summary)}</div></div>`;
  }

  function renderUndo() {
    const box = $('undoList');
    if (!box) return;
    box.innerHTML = latestUndo.length ? latestUndo.map(u => `<div class="item"><div style="display:flex; justify-content:space-between; gap:8px; align-items:center;">
        <span>${esc(u.summary)} <span class="muted">${esc(new Date(u.created_at).toLocaleString())}</span></span>
        <button class="icon" data-id="${esc(u.undo_id)}" onclick="undoAction(this.dataset.id)">Undo</button></div></div>`).join('')
      : '<div class="empty">Nothing to undo. Autonomous actions appear here for 24 hours.</div>';
  }

  async function undoAction(id) {
    const res = await fetch('./api/undo/' + encodeURIComponent(id), {method: 'POST'});
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || 'Undo failed');
    }
    await refreshAll();
  }

  async function setRuntime(field, value) {
    settingsMutationSeq++;
    const res = await post('./api/settings', {[field]: value});
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(typeof err.detail === 'string' ? err.detail : 'Could not save this setting');
    }
    await refreshAll();
  }

  async function togglePause() { await setRuntime('paused', !pausedState); }

  async function saveQuietHours() {
    settingsMutationSeq++;
    await post('./api/settings', {quiet_hours_start: $('quietStartInput').value || '', quiet_hours_end: $('quietEndInput').value || ''});
    await refreshAll();
  }

  async function clearQuietHours() {
    $('quietStartInput').value = '';
    $('quietEndInput').value = '';
    await saveQuietHours();
  }

  let currentDomainAutonomy = {};
  function renderDomainAutonomy() {
    const entries = Object.entries(currentDomainAutonomy);
    $('domainAutonomyList').innerHTML = entries.length ? entries.map(([d, lvl]) => `<div class="item" style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
        <span><code>${esc(d)}</code> &rarr; ${esc(lvl)}</span>
        <button class="icon" data-d="${esc(d)}" onclick="removeDomainAutonomy(this.dataset.d)">Remove</button></div>`).join('')
      : '<div class="muted" style="font-size:0.8rem;">No overrides: the global autonomy applies to every device type.</div>';
  }
  async function addDomainAutonomy() {
    const name = ($('domainAutoName').value || '').trim().toLowerCase();
    if (!name) return;
    currentDomainAutonomy = Object.assign({}, currentDomainAutonomy, {[name]: $('domainAutoLevel').value});
    $('domainAutoName').value = '';
    await setRuntime('domain_autonomy', currentDomainAutonomy);
  }
  async function removeDomainAutonomy(domain) {
    const next = Object.assign({}, currentDomainAutonomy);
    delete next[domain];
    currentDomainAutonomy = next;
    await setRuntime('domain_autonomy', next);
  }

  function syncSafetyControls(st) {
    const setChk = (id, v) => { const el = $(id); if (el && document.activeElement !== el) el.checked = !!v; };
    const setVal = (id, v) => { const el = $(id); if (el && document.activeElement !== el) el.value = v === null || v === undefined ? '' : v; };
    setChk('gatingCheck', st.realtime_gating);
    setChk('exceptionCheck', st.exception_detection);
    setChk('habitCheck', st.deterministic_automations);
    setChk('announceCheck', st.notify_autonomous_actions);
    setChk('privacyCheck', st.privacy_scrub);
    setVal('tokenBudgetInput', st.daily_token_budget);
    setVal('maxActionsInput', st.max_actions_per_hour);
    setVal('coalesceInput', st.realtime_coalesce_seconds);
    setVal('wakeCapInput', st.max_agent_wakeups_per_hour);
    setVal('quietStartInput', st.quiet_hours_start);
    setVal('quietEndInput', st.quiet_hours_end);
    const quietHint = $('quietHint');
    if (quietHint) {
      quietHint.textContent = (st.quiet_hours_start && st.quiet_hours_end && st.quiet_hours_start !== st.quiet_hours_end)
        ? `Quiet hours are on: ${st.quiet_hours_start} to ${st.quiet_hours_end}. Low-priority pushes are held.`
        : 'Quiet hours are off (both fields empty, or start equals end). Browsers may show an empty time field as 12:30 PM.';
    }
    currentDomainAutonomy = st.domain_autonomy || {};
    renderDomainAutonomy();
  }

  const STAT_LABELS = {
    llm_calls_avoided: 'AI calls avoided (routine / typical events)',
    batch_skipped_unchanged: 'Batch analyses skipped (nothing changed)',
    habit_automations_proposed: 'Automations proposed from your habits',
    exceptions_detected: 'Unusual situations detected',
    undone: 'Actions you undid',
    outcomes_success: 'Predictions confirmed by sensors',
    outcomes_failure: 'Predictions that did not work',
    rate_limited: 'Actions held back by safety limits',
    budget_skipped: 'Runs skipped by the token budget',
    batch_skipped_no_scope: 'Analyses skipped (no matching devices)',
    events_coalesced: 'Events merged into one AI run',
    wakeups_skipped_no_actuator: 'AI wake-ups skipped (nothing to operate)',
    wakeups_capped: 'AI wake-ups held back by the hourly cap',
  };
  const VERDICT_PILL = {healthy: 'ok', too_new: '', never_fired: 'warn', overridden: 'warn', disabled: 'warn', missing: 'danger'};

  function renderResearchItem(it, names, reviewable) {
    const confClass = {high: 'ok', medium: 'warn', low: 'danger'}[it.confidence] || '';
    const web = it.basis === 'web_sources';
    const src = (it.sources || []).map(s => `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title || s.url)}</a>${s.trust === 'low' ? ' <span class="muted">(user-generated)</span>' : ''}`).join('<br>');
    const points = (it.key_points || []).map(p => `<li>${esc(p)}</li>`).join('');
    const refs = (it.references || []).length ? `<div class="muted" style="margin-top:4px; font-size:0.8rem;">The AI says it draws on: ${esc(it.references.join('; '))} (not verified)</div>` : '';
    return `<div class="item">
      <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
        <strong>${esc(it.title)}</strong>
        <span class="pill">${esc(names[it.agent_id] || it.agent_id)}</span>
        <span class="pill ${confClass}">${esc(it.confidence)} confidence</span>
        <span class="pill ${web ? 'ok' : ''}">${web ? 'web sources' : 'AI knowledge'}</span>
        ${web ? `<span class="pill" title="Share of the answer backed by the cited sources">${Math.round((it.grounding_coverage || 0) * 100)}% sourced</span>` : ''}
      </div>
      <div style="margin-top:6px; line-height:1.45;">${esc(it.summary)}</div>
      ${points ? `<ul style="margin:6px 0 0 18px; padding:0; font-size:0.86rem;">${points}</ul>` : ''}
      ${it.how_to_apply ? `<div style="margin-top:6px; font-size:0.86rem;"><strong>Apply it:</strong> ${esc([].concat(it.how_to_apply).join(' '))}</div>` : ''}
      ${it.caveats ? `<div class="muted" style="margin-top:4px; font-size:0.82rem;">Caveats: ${esc([].concat(it.caveats).join(' '))}</div>` : ''}
      ${refs}
      ${src ? `<div style="margin-top:6px; font-size:0.82rem;">${src}</div>` : ''}
      <div class="btn-row">
        ${reviewable
          ? `<button class="success" data-id="${esc(it.item_id)}" onclick="decideResearch(this.dataset.id, 'approve')">Keep</button>
             <button class="danger" data-id="${esc(it.item_id)}" onclick="decideResearch(this.dataset.id, 'reject')">Reject</button>`
          : `<button class="danger icon" data-id="${esc(it.item_id)}" onclick="removeResearch(this.dataset.id)">Remove</button>`}
      </div></div>`;
  }

  async function refreshResearch() {
    let d;
    try { d = await (await fetch('./api/research', {cache: 'no-store'})).json(); } catch (e) { return; }
    const names = d.agent_names || {};
    const pill = $('researchStatePill');
    pill.textContent = d.running ? 'Researching...' : (!d.can_research ? 'Needs an AI provider' : (d.enabled ? 'Active' : 'Off'));
    pill.className = 'pill ' + (d.running ? 'warn' : (d.can_research && d.enabled ? 'ok' : ''));
    const fmt = v => v ? new Date(v).toLocaleString() : '-';
    const sum = d.last_summary;
    $('researchKv').innerHTML = [
      ['Last run', fmt(d.last_run)],
      ['Next run', d.enabled ? fmt(d.next_run) : 'automatic research is off'],
      ['Topics per agent per run', d.topics_per_agent],
      ['Topics researched so far', d.researched_topics],
      ['Last run result', sum ? (sum.findings + ' finding(s) from ' + sum.topics_researched + ' topic(s)') : '-'],
    ].map(([k, v]) => `<span>${esc(k)}</span><span>${esc(v)}</span>`).join('');
    let note = '';
    if (!d.can_research) note = 'Research needs an AI provider. Add an API key in Settings; any provider works.';
    else if (d.web_search_enabled && !d.supports_web_search) note = 'Web search is only available with Google Gemini; research uses the general knowledge of the AI model instead.';
    $('researchNote').textContent = note;
    $('researchRunBtn').disabled = !!d.running || !d.can_research;
    const chk = $('researchCheck'); if (document.activeElement !== chk) chk.checked = !!d.enabled;
    const web = $('researchWebCheck'); if (document.activeElement !== web) { web.checked = !!d.web_search_enabled; web.disabled = !d.supports_web_search; }
    const iv = $('researchIntervalInput'); if (document.activeElement !== iv) iv.value = d.interval_days;

    $('researchProposedCount').textContent = (d.proposed || []).length;
    $('researchProposed').innerHTML = (d.proposed || []).length ? d.proposed.map(i => renderResearchItem(i, names, true)).join('') : '<div class="empty">Nothing waiting for review.</div>';
    $('researchApprovedCount').textContent = (d.approved || []).length;
    $('researchApproved').innerHTML = (d.approved || []).length ? d.approved.map(i => renderResearchItem(i, names, false)).join('') : '<div class="empty">No approved knowledge yet.</div>';
    $('researchBacklog').innerHTML = (d.backlog || []).length ? d.backlog.map(t => `<div class="item"><strong>${esc(t.title)}</strong> <span class="pill">${esc(names[t.agent_id] || t.agent_id)}</span> <span class="muted" style="font-size:0.78rem;">${t.origin === 'device_seed' ? 'from your equipment' : 'planned by the agent'}</span></div>`).join('') : '<div class="empty">No topics queued. The agents plan new ones before each run.</div>';
  }

  async function runResearchNow() {
    $('researchRunBtn').disabled = true;
    const res = await post('./api/research/run', {});
    const r = await res.json().catch(() => ({}));
    if (r.status === 'unavailable') alert(r.message);
    await refreshResearch();
  }
  async function decideResearch(id, decision) {
    await post('./api/research/items/' + encodeURIComponent(id) + '/decision', {decision});
    await refreshResearch(); await refreshAll();
  }
  async function removeResearch(id) {
    await fetch('./api/research/items/' + encodeURIComponent(id), {method: 'DELETE'});
    await refreshResearch();
  }

  let watchDraft = null;

  function describeWatch(w) {
    const c = w.condition;
    let t;
    if (c.kind === 'numeric') {
      const parts = [];
      if (c.above !== null && c.above !== undefined) parts.push('above ' + c.above);
      if (c.below !== null && c.below !== undefined) parts.push('below ' + c.below);
      t = parts.join(' or ');
    } else if (c.kind === 'silence') {
      t = 'no update for ' + c.for_minutes + ' min';
    } else {
      t = (c.negate ? 'is not ' : 'is ') + "'" + c.state + "'";
    }
    if (c.kind !== 'silence' && c.for_minutes) t += ' for ' + c.for_minutes + ' min';
    const extra = [];
    if (w.presence && w.presence !== 'any') extra.push(w.presence === 'home' ? 'only when someone is home' : 'only when nobody is home');
    if (w.window_start) extra.push(w.window_start + '-' + w.window_end);
    if ((w.weekdays || []).length) extra.push(w.weekdays.join(', '));
    return (w.entity_ids || []).join(', ') + ' ' + t + (extra.length ? ' (' + extra.join('; ') + ')' : '');
  }

  async function compileWatch() {
    const text = ($('watchText').value || '').trim();
    if (!text) return;
    $('watchMsg').textContent = 'Interpreting...';
    $('watchCompileBtn').disabled = true;
    let r;
    try {
      const res = await post('./api/watches/compile', {text});
      r = await res.json();
    } catch (e) { r = {errors: ['Request failed']}; }
    $('watchCompileBtn').disabled = false;
    $('watchMsg').textContent = '';
    renderWatchDraft(r);
  }

  function renderWatchDraft(r) {
    const errors = r.errors || [];
    watchDraft = (r.draft && !errors.length) ? r.draft : null;
    const bt = r.backtest;
    let html = '';
    if (errors.length) html += `<div class="banner" style="display:block; margin:10px 0;">${errors.map(e => esc(e)).join('<br>')}</div>`;
    if (r.draft) {
      html += `<div class="item" style="margin-top:10px;"><strong>${esc(r.draft.name)}</strong> <span class="pill ${r.draft.severity === 'critical' ? 'danger' : (r.draft.severity === 'warning' ? 'warn' : '')}">${esc(r.draft.severity)}</span>
        <div class="muted" style="font-size:0.84rem; margin-top:4px;">${esc(describeWatch(r.draft))}</div>
        ${r.explanation ? `<div style="font-size:0.84rem; margin-top:6px;">${esc(r.explanation)}</div>` : ''}
        ${bt && bt.episodes !== null && bt.episodes !== undefined ? `<div class="muted" style="font-size:0.8rem; margin-top:6px;">🧪 On your last ${esc(bt.days)} days it would have alerted ${esc(bt.episodes)} time(s)${bt.approximate ? ' (approximate)' : ''}. ${esc(bt.note || '')}</div>` : (bt && bt.note ? `<div class="muted" style="font-size:0.8rem; margin-top:6px;">${esc(bt.note)}</div>` : '')}
        ${(r.warnings || []).map(w => `<div class="muted" style="font-size:0.8rem; margin-top:4px;">⚠ ${esc(w)}</div>`).join('')}
        ${watchDraft ? '<div class="btn-row"><button class="primary" onclick="saveWatchDraft()">Save watch</button><button class="icon" onclick="discardWatchDraft()">Discard</button></div>' : '<div class="btn-row"><button class="icon" onclick="discardWatchDraft()">Discard</button></div>'}
      </div>`;
    }
    $('watchDraft').innerHTML = html;
  }

  function discardWatchDraft() { watchDraft = null; $('watchDraft').innerHTML = ''; }

  async function saveWatchDraft() {
    if (!watchDraft) return;
    const res = await post('./api/watches', watchDraft);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(typeof err.detail === 'string' ? err.detail : 'Could not save this watch');
      return;
    }
    $('watchText').value = '';
    discardWatchDraft();
    await refreshWatches();
  }

  async function refreshWatches() {
    let d;
    try { d = await (await fetch('./api/watches', {cache: 'no-store'})).json(); } catch (e) { return; }
    const list = d.watches || [];
    $('watchCount').textContent = list.length;
    $('watchList').innerHTML = list.length ? list.map(w => `<div class="item">
        <div style="display:flex; justify-content:space-between; gap:8px; align-items:center; flex-wrap:wrap;">
          <span><strong>${esc(w.name)}</strong> <span class="pill ${w.enabled ? 'ok' : ''}">${w.enabled ? 'active' : 'paused'}</span></span>
          <span>
            <button class="icon" data-id="${esc(w.watch_id)}" onclick="toggleWatch(this.dataset.id)">${w.enabled ? 'Pause' : 'Resume'}</button>
            <button class="danger icon" data-id="${esc(w.watch_id)}" onclick="deleteWatch(this.dataset.id)">Remove</button>
          </span>
        </div>
        <div class="muted" style="font-size:0.82rem; margin-top:3px;">${esc(describeWatch(w))}</div>
        <div class="muted" style="font-size:0.78rem;">Alerted ${esc(w.fire_count)} time(s)${w.last_fired ? ', last ' + esc(new Date(w.last_fired).toLocaleString()) : ''}</div></div>`).join('')
      : '<div class="empty">No watches yet.</div>';
  }

  async function toggleWatch(id) { await fetch('./api/watches/' + encodeURIComponent(id) + '/toggle', {method: 'POST'}); await refreshWatches(); }
  async function deleteWatch(id) { await fetch('./api/watches/' + encodeURIComponent(id), {method: 'DELETE'}); await refreshWatches(); }

  async function unmuteException(key) {
    await post('./api/exceptions/unmute', {key});
    await refreshLearned();
  }

  let autoDraftId = '';
  let autoDraftText = '';

  async function draftAutomation() {
    const text = ($('autoText').value || '').trim();
    if (!text) return;
    $('autoMsg').textContent = 'Writing...';
    $('autoDraftBtn').disabled = true;
    let r;
    try { r = await (await post('./api/automations/draft', {text})).json(); } catch (e) { r = {errors: ['Request failed']}; }
    $('autoDraftBtn').disabled = false;
    $('autoMsg').textContent = '';
    autoDraftText = text;
    renderAutomationDraft(r);
  }

  function renderAutomationDraft(r) {
    const errors = r.errors || [];
    let html = '';
    if (errors.length) html += `<div class="banner" style="display:block; margin:10px 0;">${errors.map(e => esc(e)).join('<br>')}</div>`;
    if (r.draft) {
      autoDraftId = r.draft.automation_id;
      const bt = r.backtest;
      html += `<div class="item" style="margin-top:10px;">
        ${r.explanation ? `<div style="font-size:0.84rem;">${esc(r.explanation)}</div>` : ''}
        ${bt && bt.summary ? `<div class="muted" style="font-size:0.8rem; margin-top:6px;">🧪 ${esc(bt.summary)}</div>` : ''}
        ${(r.warnings || []).map(w => `<div class="muted" style="font-size:0.8rem; margin-top:4px;">⚠ ${esc(w)}</div>`).join('')}
        <div class="muted" style="font-size:0.78rem; margin-top:8px;">Triggers, conditions and actions (YAML). You can edit it before creating.</div>
        <textarea id="autoYaml" rows="14" spellcheck="false" style="width:100%; box-sizing:border-box; margin-top:4px; background:#080d18; color:#c3cee3; border:1px solid var(--border); border-radius:6px; padding:8px 10px; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:12px;">${esc(r.draft.yaml)}</textarea>
        <div class="btn-row"><button class="primary" id="autoCreateBtn" onclick="createAutomation()">Create automation</button><button class="icon" onclick="discardAutomationDraft()">Cancel</button></div>
        <div id="autoCreateMsg" class="muted" style="font-size:0.82rem; margin-top:4px;"></div>
      </div>`;
    } else if (errors.length) {
      html += '<div class="btn-row"><button class="icon" onclick="discardAutomationDraft()">Dismiss</button></div>';
    }
    $('autoDraft').innerHTML = html;
  }

  function discardAutomationDraft() { autoDraftId = ''; $('autoDraft').innerHTML = ''; }

  async function createAutomation() {
    const yamlText = $('autoYaml').value;
    $('autoCreateBtn').disabled = true;
    $('autoCreateMsg').textContent = 'Creating...';
    const res = await post('./api/automations/create', {yaml: yamlText, automation_id: autoDraftId, request_text: autoDraftText});
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      $('autoCreateBtn').disabled = false;
      $('autoCreateMsg').textContent = typeof body.detail === 'string' ? body.detail : 'Could not create this automation.';
      return;
    }
    $('autoText').value = '';
    $('autoDraft').innerHTML = `<div class="item" style="margin-top:10px;">✅ Created "${esc(body.alias)}" in Home Assistant. It is tracked under Deployed automation health.</div>`;
    autoDraftId = '';
    await refreshAll();
  }

  let importData = null;

  async function previewImport(input) {
    const file = input.files && input.files[0];
    input.value = '';
    if (!file) return;
    let data;
    try { data = JSON.parse(await file.text()); } catch (e) { $('importPreview').innerHTML = '<div class="banner" style="display:block; margin:10px 0;">This file is not valid JSON.</div>'; return; }
    const res = await post('./api/import', {data, apply: false});
    const body = await res.json().catch(() => ({}));
    if (!res.ok) { importData = null; $('importPreview').innerHTML = `<div class="banner" style="display:block; margin:10px 0;">${esc(typeof body.detail === 'string' ? body.detail : 'Could not read this file.')}</div>`; return; }
    importData = data;
    const rows = (body.sections || []).map(x => `<div>${esc(x.label)}: <strong>${esc(x.count)}</strong>${x.skipped ? ` <span class="muted">(${esc(x.skipped)} skipped as invalid)</span>` : ''}</div>`).join('');
    $('importPreview').innerHTML = `<div class="item" style="margin-top:10px;"><div class="muted" style="font-size:0.8rem; margin-bottom:6px;">The file contains:</div>${rows || '<div class="muted">Nothing to import.</div>'}
      ${(body.warnings || []).map(w => `<div class="muted" style="font-size:0.8rem; margin-top:6px;">⚠ ${esc(w)}</div>`).join('')}
      <div class="btn-row">${rows ? '<button class="primary" onclick="applyImport()">Import</button>' : ''}<button class="icon" onclick="cancelImport()">Cancel</button></div></div>`;
  }

  function cancelImport() { importData = null; $('importPreview').innerHTML = ''; }

  async function applyImport() {
    if (!importData) return;
    const res = await post('./api/import', {data: importData, apply: true});
    const body = await res.json().catch(() => ({}));
    importData = null;
    $('importPreview').innerHTML = res.ok ? '<div class="item" style="margin-top:10px;">✅ Imported. Everything was merged into the current settings and rules.</div>'
      : `<div class="banner" style="display:block; margin:10px 0;">${esc(typeof body.detail === 'string' ? body.detail : 'Import failed.')}</div>`;
    await refreshAll();
    await refreshLearned();
    await refreshWatches();
  }

  async function refreshAdoptable() {
    let d;
    try { d = await (await fetch('./api/automations/adoptable', {cache: 'no-store'})).json(); } catch (e) { return; }
    const list = d.automations || [];
    $('adoptCard').style.display = list.length ? 'block' : 'none';
    if (!list.length) { $('adoptList').innerHTML = ''; return; }
    $('adoptList').innerHTML = list.map(a => `<label class="check" style="margin:6px 0;"><input type="checkbox" class="adoptBox" value="${esc(a.automation_id)}" checked />
      <span>${esc(a.alias)} <code>${esc(a.automation_id)}</code></span></label>`).join('');
  }

  async function adoptSelected() {
    const ids = Array.from(document.querySelectorAll('.adoptBox:checked')).map(b => b.value);
    if (!ids.length) return;
    await post('./api/automations/adopt', {automation_ids: ids});
    await refreshAdoptable();
    await refreshLearned();
  }

  async function setAutomationEnabled(id, enabled) {
    const res = await post('./api/automations/' + encodeURIComponent(id) + '/enabled', {enabled});
    if (!res.ok) { const b = await res.json().catch(() => ({})); alert(typeof b.detail === 'string' ? b.detail : 'Could not change the automation.'); }
    await refreshLearned();
  }

  async function deleteAutomation(id, alias) {
    if (!confirm('Delete "' + alias + '" from Home Assistant? This cannot be undone. (Use "Never propose again" first if you do not want the brain to suggest it again.)')) return;
    const res = await fetch('./api/automations/' + encodeURIComponent(id), {method: 'DELETE'});
    if (!res.ok) { const b = await res.json().catch(() => ({})); alert(typeof b.detail === 'string' ? b.detail : 'Could not delete the automation.'); }
    await refreshLearned();
  }

  async function forgetAutomation(id, block) {
    if (block && !confirm('Remove it from this list and never propose this automation again?')) return;
    await post('./api/automations/' + encodeURIComponent(id) + '/forget', {block});
    await refreshLearned();
  }

  async function refreshLearned() {
    let d;
    try {
      const res = await fetch('./api/learned', {cache: 'no-store'});
      d = await res.json();
    } catch (e) { return; }
    const pct = Math.min(100, Math.round(100 * d.days_of_data / Math.max(1, d.baseline_min_days)));
    $('learnedBar').style.width = pct + '%';
    const pill = $('learnedStatePill');
    pill.textContent = d.baseline_ready ? 'Routines learned' : 'Learning...';
    pill.className = 'pill ' + (d.baseline_ready ? 'ok' : 'warn');
    const store = d.store || {};
    $('learnedKv').innerHTML = [
      ['History recorded', d.days_of_data + ' days (needs ' + d.baseline_min_days + ')'],
      ['State changes stored', store.transitions || 0],
      ['Devices tracked', (store.entities_with_transitions || 0) + ' switchable, ' + (store.entities_with_numeric || 0) + ' sensors'],
      ['Existing HA automations known', d.existing_automations],
      ['Smart AI wake-ups', d.gating_active ? 'Only for unusual events' : 'Every significant event (still learning)'],
      ['AI tokens today', d.tokens_today + (d.daily_token_budget ? ' / ' + d.daily_token_budget : ' (no budget)')],
      ['Timezone', d.timezone],
    ].map(([k, v]) => `<span>${esc(k)}</span><span>${esc(v)}</span>`).join('');
    const stats = d.stats_7d || {};
    const keys = Object.keys(STAT_LABELS).filter(k => stats[k]);
    $('learnedStats').innerHTML = keys.length ? keys.map(k => `<span>${esc(STAT_LABELS[k])}</span><span>${esc(stats[k])}</span>`).join('')
      : '<span class="muted">Nothing yet</span><span></span>';

    const patterns = d.patterns || [];
    $('patternsCount').textContent = patterns.length;
    $('patternsList').innerHTML = patterns.length ? patterns.map(p => `<div class="item">
        <div>${esc(p.description)}</div>
        <div style="margin-top:4px; display:flex; gap:6px; flex-wrap:wrap;">
          <span class="pill">${Math.round(p.confidence * 100)}% confidence</span>
          ${p.covered_by ? `<span class="pill ok wrap">already automated: ${esc(p.covered_by)}</span>` : '<span class="pill warn">not automated yet</span>'}
        </div></div>`).join('')
      : '<div class="empty">No recurring habits found yet. They appear after a few days of recorded history.</div>';

    const muted = d.muted_exceptions || [];
    $('mutedList').innerHTML = muted.length ? muted.map(k => `<div class="item" style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
        <code>${esc(k)}</code><button class="icon" data-k="${esc(k)}" onclick="unmuteException(this.dataset.k)">Unmute</button></div>`).join('')
      : '<div class="muted" style="font-size:0.8rem;">Nothing muted.</div>';

    const reviews = d.automation_reviews || [];
    $('reviewsList').innerHTML = reviews.length ? reviews.map(r => `<div class="item">
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;"><strong>${esc(r.alias)}</strong>
          <span class="pill ${VERDICT_PILL[r.verdict] || ''}">${esc(String(r.verdict).replace('_', ' '))}</span></div>
        <div class="muted" style="font-size:0.82rem; margin-top:3px;">${esc(r.details)}</div>
        ${r.verdict !== 'missing' && r.entity_id ? `<div class="btn-row" style="margin-top:6px;">
          <button class="icon" data-id="${esc(r.automation_id)}" onclick="setAutomationEnabled(this.dataset.id, ${r.verdict === 'disabled'})">${r.verdict === 'disabled' ? 'Enable' : 'Disable'}</button>
          <button class="danger icon" data-id="${esc(r.automation_id)}" data-alias="${esc(r.alias)}" onclick="deleteAutomation(this.dataset.id, this.dataset.alias)">Delete</button></div>` : ''}
        ${r.verdict !== 'healthy' && r.verdict !== 'too_new' ? `<div class="btn-row" style="margin-top:6px;">
          <button class="icon" data-id="${esc(r.automation_id)}" onclick="forgetAutomation(this.dataset.id, false)">Stop tracking</button>
          <button class="icon" data-id="${esc(r.automation_id)}" onclick="forgetAutomation(this.dataset.id, true)">Never propose again</button></div>` : ''}</div>`).join('')
      : '<div class="empty">No automations deployed by the brain yet.</div>';
    refreshAdoptable();
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
    latestApprovalStatuses[id] = decision;
    activePendingApprovalIds.delete(id);
    await post('./api/approvals/' + id + '/decide', {decision, human_note: humanNote});
    await refreshAll();
  }

  async function dismissAllApprovals() {
    if (!confirm('Dismiss all pending proposals?')) return;
    activePendingApprovalIds.forEach(id => {
      latestApprovalStatuses[id] = 'dismissed';
    });
    activePendingApprovalIds.clear();
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

  async function addMinChange() {
    const pattern = $('minChangePatternInput').value.trim();
    const min_change = parseFloat($('minChangeValueInput').value);
    if (!pattern || !(min_change > 0)) return;
    await post('./api/min-change', {pattern, min_change, reason: $('minChangeReasonInput').value.trim()});
    $('minChangePatternInput').value = ''; $('minChangeValueInput').value = ''; $('minChangeReasonInput').value = '';
    await refreshAll();
  }

  async function deleteMinChange(id) { await fetch('./api/min-change/' + id, {method: 'DELETE'}); await refreshAll(); }

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
  try {
    if (window.parent && window.parent !== window) {
      window.parent.addEventListener('hashchange', handleHashNav);
    }
  } catch (e) {}
  refreshAll();
  setInterval(refreshAll, 5000);
  setInterval(() => { const pane = $('pane-learned'); if (pane && pane.classList.contains('active')) refreshLearned(); }, 15000);
  setInterval(() => { const pane = $('pane-research'); if (pane && pane.classList.contains('active')) refreshResearch(); }, 10000);
  setInterval(() => { const pane = $('pane-memory'); if (pane && pane.classList.contains('active')) refreshWatches(); }, 30000);
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
