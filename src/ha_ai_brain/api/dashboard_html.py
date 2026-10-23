"""Self-contained Home Assistant Ingress Web UI Dashboard for HA AI Brain."""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>HA AI Brain — Autonomous Multi-Agent Control Plane</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --emerald: #10b981;
      --amber: #f59e0b;
      --rose: #f43f5e;
    }
    * { box-sizing: border-box; }
    html, body {
      width: 100%;
      max-width: 100vw;
      overflow-x: hidden;
    }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 20px;
      -webkit-text-size-adjust: 100%;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
      padding-bottom: 16px;
      margin-bottom: 24px;
      flex-wrap: wrap;
      gap: 12px;
      width: 100%;
    }
    h1 { margin: 0; font-size: 1.5rem; display: flex; align-items: center; gap: 10px; }
    .badge {
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 600;
      background: #0284c7;
      color: white;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 18px;
      margin-bottom: 24px;
      width: 100%;
    }
    @media (min-width: 860px) {
      .grid {
        grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      }
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      min-width: 0;
      max-width: 100%;
      overflow: hidden;
      box-sizing: border-box;
    }
    .card h2 {
      margin-top: 0;
      font-size: 1.05rem;
      color: var(--accent);
      border-bottom: 1px solid var(--border);
      padding-bottom: 10px;
    }
    button {
      background: var(--accent);
      color: #0f172a;
      border: none;
      border-radius: 8px;
      padding: 8px 14px;
      font-weight: 600;
      cursor: pointer;
      transition: opacity 0.15s, transform 0.1s;
      font-size: 0.9rem;
    }
    button:active { transform: scale(0.98); }
    button:hover { opacity: 0.9; }
    button.emerald { background: var(--emerald); color: #fff; }
    button.amber { background: var(--amber); color: #0f172a; }
    button.rose { background: var(--rose); color: #fff; }
    .btn-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; width: 100%; }
    code {
      overflow-wrap: anywhere;
      word-break: break-all;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }
    pre {
      background: #090d16;
      padding: 12px;
      border-radius: 8px;
      overflow-x: auto;
      max-width: 100%;
      font-size: 0.8rem;
      color: #cbd5e1;
      border: 1px solid var(--border);
      white-space: pre-wrap;
      word-break: break-word;
    }
    .item {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 10px;
      background: rgba(15, 23, 42, 0.5);
      min-width: 0;
      max-width: 100%;
      overflow-wrap: anywhere;
      word-break: break-word;
      box-sizing: border-box;
    }
    .muted { color: var(--muted); font-size: 0.85rem; }
    select, input[type="text"], textarea {
      background: #090d16;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 8px 12px;
      border-radius: 6px;
      font-family: inherit;
      font-size: 16px; /* 16px prevents iOS Safari from auto-zooming and distorting layout on input focus */
      width: 100%;
      max-width: 100%;
      box-sizing: border-box;
    }
    @media (max-width: 600px) {
      body {
        padding: 12px;
      }
      header {
        flex-direction: column;
        align-items: stretch;
      }
      .btn-row {
        flex-direction: column;
      }
      .btn-row button {
        width: 100%;
      }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>🧠 HA AI Brain <span class="badge" id="modeBadge">Loading...</span></h1>
      <div class="muted" id="siteContextText">Autonomous Multi-Agent Cognitive Layer for Home Assistant (LangGraph + Hexagonal Architecture)</div>
    </div>
    <div class="btn-row">
      <button onclick="triggerScenario('condensation_risk')">💧 Simulate Window Condensation Event</button>
      <button onclick="triggerScenario('solar_ufh_gain')">☀️ Simulate Solar + UFH Inertia Event</button>
      <button class="emerald" onclick="triggerBatch()">📊 Run Periodic Batch Analysis (Low-Token Mode)</button>
    </div>
  </header>

  <div id="quotaBanner" style="display:none; background:rgba(245, 158, 11, 0.14); border:1px solid var(--amber); border-left:5px solid var(--amber); border-radius:10px; padding:14px 18px; margin-bottom:20px;"></div>

  <div class="grid">
    <div class="card">
      <h2>⚙️ Operating Mode, Autonomy & Guardrails</h2>
      <div style="display:flex; flex-direction:column; gap:10px;">
        <label>Operating Mode:
          <select id="modeSelect" autocomplete="off" onchange="updateSetting('operating_mode', this.value)">
            <option value="hybrid">Hybrid (Live Stream + Periodic Batch)</option>
            <option value="realtime_stream">Real-Time Event Stream (24/7 Reactive)</option>
            <option value="periodic_batch">Periodic Batch Only (Low Token Spend)</option>
          </select>
        </label>
        <label>Autonomy Level:
          <select id="autonomySelect" autocomplete="off" onchange="updateSetting('default_autonomy', this.value)">
            <option value="shadow">Shadow Mode (Observe & Log Only)</option>
            <option value="copilot">Co-Pilot Mode (Confirm Unapproved Actions)</option>
            <option value="autonomous">Autonomous Mode (Auto-Execute Low/Med Risk)</option>
          </select>
        </label>
        <label>AI Quota Fallback Policy:
          <select id="fallbackPolicySelect" autocomplete="off" onchange="updateSetting('llm_fallback_policy', this.value)">
            <option value="auto">Auto-Fallback & Auto-Return to Primary After Cooldown</option>
            <option value="confirm">Ask Confirmation Before Switching to Fallback</option>
            <option value="disabled">Disabled (Strict Primary Model Only)</option>
          </select>
        </label>
        <label>HA Notification Target (Only this device receives alerts):
          <select id="notifyServiceSelect" autocomplete="off" onchange="updateSetting('notification_service', this.value)">
            <option value="notify.notify">Loading HA notify services...</option>
          </select>
        </label>
        <label>
          <input type="checkbox" id="notifyCheck" autocomplete="off" onchange="updateSetting('notifications_enabled', this.checked)" checked />
          Enable Actionable Approval Notifications
        </label>
      </div>
      <div id="licenseBox" class="muted" style="margin-top:14px;"></div>
      <div id="quotaBox" class="item" style="margin-top:12px; margin-bottom:0;"></div>
    </div>

    <div class="card">
      <h2>🛡️ Pending Guardrail Approvals</h2>
      <div id="pendingList" class="muted">No pending approvals.</div>
    </div>

    <div class="card">
      <h2>✅ Endorsed Repeatable Rules (Never Ask Again)</h2>
      <div id="rulesList" class="muted">No repeatable rules endorsed yet.</div>
    </div>

    <div class="card">
      <h2>💬 Tell the Brain (User Context & Hardware Directives)</h2>
      <div class="muted" style="margin-bottom:8px;">
        Tell the AI Brain anytime about hardware quirks, broken sub-features, or personal rules so all agents adapt immediately.
      </div>
      <div style="display:flex; flex-direction:column; gap:8px;">
        <textarea id="contextNoteInput" rows="2" placeholder="e.g., The humidifier on the Philips Air Purifier is mechanically broken; I only use it to purify air."></textarea>
        <div style="display:flex; gap:8px; flex-wrap:wrap;">
          <input type="text" id="contextEntitiesInput" style="flex:1; min-width:180px;" placeholder="Optional entity IDs (comma-separated)" />
          <button class="emerald" onclick="addContextNote()">➕ Save Context Directive</button>
        </div>
      </div>
      <div id="contextNotesList" class="muted" style="margin-top:12px;">No custom user context directives added yet.</div>
    </div>

    <div class="card">
      <h2>🚫 Ignored Entities & Devices (Zero Context & Zero Alerts)</h2>
      <div class="muted" style="margin-bottom:8px;">
        Add exact entity IDs, device prefixes, or wildcards (e.g. <code>sensor.myengie_*</code>, <code>*daikinap98340*</code>, <code>humidifier.bedroom_none</code>). Ignored entities are filtered out before Triage and LLM calls so they never trigger diagnostics or consume tokens.
      </div>
      <div style="display:flex; flex-direction:column; gap:8px;">
        <div style="display:flex; gap:8px; flex-wrap:wrap;">
          <input type="text" id="ignorePatternInput" style="flex:1; min-width:160px;" placeholder="e.g., sensor.myengie_* or *daikinap98340*" />
          <input type="text" id="ignoreReasonInput" style="flex:1; min-width:140px;" placeholder="Optional reason (e.g. Known offline)" />
          <button class="amber" onclick="addIgnoredTarget()">🚫 Add to Ignore List</button>
        </div>
      </div>
      <div id="ignoredTargetsList" class="muted" style="margin-top:12px;">No ignored entities or patterns configured.</div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); padding-bottom:10px; margin-bottom:12px;">
        <h2 style="margin:0; border:none; padding:0;">🔬 Live Agent Reasoning & Sub-Agent Computations</h2>
        <span class="badge" id="logsCountBadge">0 traces</span>
      </div>
      <div id="logsScrollContainer" style="max-height: 520px; overflow-y: auto; padding-right: 4px; display: flex; flex-direction: column; gap: 10px;">
        <div id="logsList" class="muted">No reasoning traces yet.</div>
        <div id="logsLoadMoreContainer" style="text-align: center; margin: 8px 0; display: none;">
          <button id="loadMoreLogsBtn" class="amber" style="width: auto; padding: 6px 16px; font-size: 0.82rem;" onclick="loadMoreLogs()">📜 Load More Older Logs</button>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>🏗️ Batch Insights & Synthesized Native HA Automations</h2>
      <div id="insightsList" class="muted">Run Periodic Batch Analysis to diagnose building insulation & generate native HA automations.</div>
    </div>
  </div>

  <script>
    let settingsMutationSeq = 0;
    let allLoadedLogs = [];
    let loadedLogIds = new Set();
    let totalServerLogs = 0;
    let isLoadingMoreLogs = false;

    function renderSingleLogHtml(l) {
      const researchHtml = (l.research_findings || []).map(rf => `
        <div style="margin-bottom:6px; padding:6px 8px; background:#090d16; border-radius:6px; border:1px solid var(--border);">
          <strong style="color:var(--accent);">🔬 ${rf.topic}</strong>
          <div class="muted" style="margin-top:2px;">${rf.principle_summary}</div>
          ${rf.recommended_thresholds_or_physics ? `<div class="muted" style="font-size:0.78rem; margin-top:2px;"><em>Physics/Thresholds:</em> ${rf.recommended_thresholds_or_physics}</div>` : ''}
        </div>
      `).join('');

      const signalsHtml = (l.derived_signals || []).length
        ? `<pre>${JSON.stringify(l.derived_signals.map(s => ({signal: s.signal_name, value: s.value, unit: s.unit, formula: s.formula_or_method, interpretation: s.interpretation})), null, 2)}</pre>`
        : '<div class="muted">No numeric signals computed in this pass.</div>';

      const intentsHtml = (l.proposed_intents || []).length
        ? (l.proposed_intents || []).map((intent, idx) => {
            const execRes = (l.execution_results || [])[idx] || {};
            const autoBlock = intent.native_automation
              ? `<pre>${JSON.stringify(intent.native_automation, null, 2)}</pre>`
              : (Object.keys(intent.service_data || {}).length ? `<pre>${JSON.stringify(intent.service_data, null, 2)}</pre>` : '');
            return `
              <div style="margin-bottom:8px; padding:8px 10px; background:#090d16; border-radius:6px; border-left:3px solid var(--emerald);">
                <div><strong>⚡ ${intent.domain}.${intent.service}</strong> ${intent.target_entity_ids && intent.target_entity_ids.length ? `→ <code>${intent.target_entity_ids.join(', ')}</code>` : ''} <span class="badge" style="font-size:0.7rem;">${execRes.status || 'proposed'}</span></div>
                <div style="margin-top:4px; font-size:0.88rem;"><strong>Why:</strong> ${intent.rationale}</div>
                ${autoBlock}
                <div class="muted" style="font-size:0.75rem;">Signature: <code>${execRes.signature || ''}</code></div>
              </div>
            `;
          }).join('')
        : '<div class="muted">No actions proposed in this pass.</div>';

      const timeStr = l.created_at ? new Date(l.created_at).toLocaleTimeString() : '';

      return `
        <div class="item" data-log-id="${l.run_id}">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; gap:8px;">
            <strong>[${l.mode}] ${l.agent_id}</strong>
            <span class="muted" style="font-size:0.78rem;">${timeStr}</span>
          </div>
          <div class="muted" style="margin-bottom:8px;">${l.trigger_summary}</div>
          <div class="muted" style="margin-bottom:4px;"><strong>1. Expert Domain & Scientific Research Findings (${(l.research_findings || []).length}):</strong></div>
          ${researchHtml || '<div class="muted">None</div>'}
          <div class="muted" style="margin-top:8px; margin-bottom:4px;"><strong>2. Derived Signals (Computation Sub-Agent Python Sandbox):</strong></div>
          ${signalsHtml}
          <div class="muted" style="margin-top:8px; margin-bottom:4px;"><strong>3. Proposed Reactions & Automation Suggestions (${(l.proposed_intents || []).length}):</strong></div>
          ${intentsHtml}
        </div>
      `;
    }

    async function refreshAll() {
      const seqAtStart = settingsMutationSeq;
      const res = await fetch('./api/status', {cache: 'no-store'});
      const data = await res.json();
      if (seqAtStart === settingsMutationSeq) {
        document.getElementById('modeBadge').textContent =
          data.settings.operating_mode.toUpperCase() + ' | ' + data.settings.default_autonomy.toUpperCase();
        const modeEl = document.getElementById('modeSelect');
        if (document.activeElement !== modeEl) modeEl.value = data.settings.operating_mode;
        const autoEl = document.getElementById('autonomySelect');
        if (document.activeElement !== autoEl) autoEl.value = data.settings.default_autonomy;
        const fbEl = document.getElementById('fallbackPolicySelect');
        if (data.settings.llm_fallback_policy && document.activeElement !== fbEl) {
          fbEl.value = data.settings.llm_fallback_policy;
        }
        const notifySelect = document.getElementById('notifyServiceSelect');
        if (document.activeElement !== notifySelect) {
          const availNotify = [...(data.available_notify_services || ['notify.notify'])];
          const currentNotify = data.settings.notification_service || 'notify.notify';
          if (!availNotify.includes(currentNotify)) {
            availNotify.unshift(currentNotify);
          }
          notifySelect.innerHTML = availNotify.map(svc =>
            `<option value="${svc}" ${svc === currentNotify ? 'selected' : ''}>${svc}</option>`
          ).join('');
          notifySelect.value = currentNotify;
        }
        document.getElementById('notifyCheck').checked = data.settings.notifications_enabled;
      }
      document.getElementById('licenseBox').textContent =
        `Plan: ${data.license.plan_tier} | Tokens used: ${data.license.tokens_used_this_period}`;

      // AI Model Quota, Rate-Limit Cooldown, Fallback Routing & Spend Telemetry
      const q = data.llm_quota || {};
      const qBanner = document.getElementById('quotaBanner');
      const qBox = document.getElementById('quotaBox');
      const totalTok = (q.prompt_tokens_session || 0) + (q.completion_tokens_session || 0);
      const spendStr = typeof q.estimated_spend_usd_session === 'number'
        ? `$${q.estimated_spend_usd_session.toFixed(4)} USD`
        : '$0.0000 USD';
      const limitStr = q.quota_limit !== null && q.quota_limit !== undefined
        ? `${q.quota_limit} (${q.quota_metric || 'provider limit'})`
        : 'Tier default';
      const extLink = q.external_usage_url
        ? ` — <a href="${q.external_usage_url}" target="_blank" style="color:var(--accent);">Open Provider Usage & Quota Console ↗</a>`
        : '';
      const primUntilLocal = q.primary_cooldown_until ? new Date(q.primary_cooldown_until).toLocaleTimeString() : 'soon';
      const availFallbacks = q.available_fallback_models || [];

      if (q.awaiting_fallback_confirmation && availFallbacks.length) {
        const fbButtons = availFallbacks.map(m =>
          `<button class="emerald" onclick="decideFallback('approve_fallback', '${m}')">✅ Switch to ${m} (Auto-Return to ${q.primary_model} at ${primUntilLocal})</button>`
        ).join('');
        qBanner.style.display = 'block';
        qBanner.innerHTML = `
          <div style="font-weight:700; color:var(--amber); font-size:0.98rem;">
            ⚠️ Primary Model Quota Topped (<code>${q.primary_model}</code>) — Confirm Fallback Model?
          </div>
          <div style="margin-top:4px; font-size:0.88rem;">
            Primary model <code>${q.primary_model}</code> is in cooldown for <code>${q.primary_cooldown_seconds_remaining || q.cooldown_seconds_remaining}s</code> (until <strong>${primUntilLocal}</strong>).
            Available fallback models with remaining quota: <code>${availFallbacks.join(', ')}</code>.
          </div>
          <div class="btn-row" style="margin-top:10px;">
            ${fbButtons}
            <button class="amber" onclick="decideFallback('wait_for_primary', null)">⏸️ Wait for Primary Model Cooldown</button>
          </div>
        `;
      } else if (q.using_fallback_model) {
        qBanner.style.display = 'block';
        qBanner.innerHTML = `
          <div style="font-weight:700; color:var(--emerald); font-size:0.98rem;">
            🔄 Running on Fallback Model <code>${q.active_model}</code> (Primary <code>${q.primary_model}</code> Cooling Down)
          </div>
          <div style="margin-top:4px; font-size:0.88rem;">
            Will <strong>automatically switch back</strong> to primary model <code>${q.primary_model}</code> in <code>${q.primary_cooldown_seconds_remaining || 0}s</code> (at <strong>${primUntilLocal}</strong>)
            | <strong>Session Spend:</strong> <code>${spendStr}</code> (${totalTok} tokens)
            ${extLink}
          </div>
        `;
      } else if (q.quota_exhausted && (q.cooldown_seconds_remaining || 0) > 0) {
        const untilLocal = q.cooldown_until ? new Date(q.cooldown_until).toLocaleTimeString() : 'soon';
        qBanner.style.display = 'block';
        qBanner.innerHTML = `
          <div style="font-weight:700; color:var(--amber); font-size:0.98rem;">
            ⏳ AI Model Quota Reached (${q.provider || 'LLM'} — <code>${q.model || ''}</code>) — Cooldown Required
          </div>
          <div style="margin-top:4px; font-size:0.88rem;">
            <strong>Cooldown Remaining:</strong> <code>${q.cooldown_seconds_remaining}s</code> (resumes at <strong>${untilLocal}</strong>)
            | <strong>Enforced Limit:</strong> <code>${limitStr}</code>
            | <strong>Session Spend:</strong> <code>${spendStr}</code> (${totalTok} tokens)
            ${extLink}
          </div>
          ${q.last_error_message ? `<div class="muted" style="margin-top:4px; font-size:0.8rem;">Provider response: ${q.last_error_message}</div>` : ''}
        `;
      } else {
        qBanner.style.display = 'none';
      }

      const cooldownModelsList = Object.entries(q.model_cooldowns || {}).map(([m, iso]) =>
        `<code>${m}</code> (until ${new Date(iso).toLocaleTimeString()})`
      ).join(', ');

      qBox.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <strong>🤖 AI Provider Quota, Fallback & Spend (${q.provider || 'llm'})</strong>
          <span class="badge" style="background:${q.quota_exhausted ? 'var(--amber)' : (q.using_fallback_model ? '#0284c7' : 'var(--emerald)')}; color:${q.quota_exhausted ? '#0f172a' : '#fff'};">
            ${q.awaiting_fallback_confirmation ? 'AWAITING FALLBACK CONFIRMATION' : (q.quota_exhausted ? `COOLDOWN (${q.cooldown_seconds_remaining}s)` : (q.using_fallback_model ? `FALLBACK: ${q.active_model}` : 'PRIMARY HEALTHY'))}
          </span>
        </div>
        <div class="muted" style="margin-top:6px; line-height:1.45;">
          <div>Primary Model: <code>${q.primary_model || data.settings.llm_model}</code> | Active Model: <code>${q.active_model || q.model || data.settings.llm_model}</code> ${q.using_fallback_model ? `(auto-returns to primary in <strong>${q.primary_cooldown_seconds_remaining || 0}s</strong>)` : ''}</div>
          <div>Available Fallbacks with Quota: <code>${(q.available_fallback_models || []).join(', ') || 'none'}</code> ${cooldownModelsList ? `| Cooling Down: ${cooldownModelsList}` : ''}</div>
          <div>Session Calls: <strong>${q.requests_succeeded_session || 0}</strong> ok / <strong>${q.requests_rate_limited_session || 0}</strong> rate-limited | Tokens: <strong>${totalTok}</strong> | Est. Spend: <strong>${spendStr}</strong></div>
          <div>Detected Quota Limit: <code>${limitStr}</code>${extLink}</div>
        </div>
      `;

      // Pending approvals with element & focus preservation
      const pBox = document.getElementById('pendingList');
      const curPending = data.pending_approvals || [];
      if (!curPending.length) {
        pBox.innerHTML = '<div class="muted">No actions awaiting approval.</div>';
      } else {
        // Collect existing draft notes currently typed by user
        const draftNotes = {};
        pBox.querySelectorAll('input[id^="note_"]').forEach(inp => {
          if (inp.value) {
            draftNotes[inp.id] = inp.value;
          }
        });

        // Find existing cards in DOM
        const existingCardIds = new Set();
        pBox.querySelectorAll('[data-approval-id]').forEach(card => {
          existingCardIds.add(card.getAttribute('data-approval-id'));
        });

        const newIds = new Set(curPending.map(p => p.approval_id));

        // Check if the set of approval IDs changed
        const unchanged = existingCardIds.size === newIds.size && [...existingCardIds].every(id => newIds.has(id));

        if (!unchanged) {
          // If the list actually changed, remove resolved cards
          pBox.querySelectorAll('[data-approval-id]').forEach(card => {
            const id = card.getAttribute('data-approval-id');
            if (!newIds.has(id)) {
              card.remove();
            }
          });

          // Add any new cards that don't have a card yet
          curPending.forEach(p => {
            if (!existingCardIds.has(p.approval_id)) {
              const div = document.createElement('div');
              div.className = 'item';
              div.setAttribute('data-approval-id', p.approval_id);
              div.innerHTML = `
                <strong>${p.intent.domain}.${p.intent.service}</strong> → <code>${p.intent.target_entity_ids.join(', ')}</code>
                <div class="muted" style="margin:6px 0;">${p.intent.rationale}</div>
                <div class="muted">Signature: <code>${p.signature}</code></div>
                <div style="margin-top:8px;">
                  <input type="text" id="note_${p.approval_id}" autocomplete="off" placeholder="Optional feedback / context note (e.g. 'Humidifier on Philips is broken, only use purifier')" />
                </div>
                <div class="btn-row">
                  <button onclick="decideApproval('${p.approval_id}', 'approved_once')">Approve Once</button>
                  <button class="emerald" onclick="decideApproval('${p.approval_id}', 'approved_repeatable')">Approve & Always Allow (Repeatable)</button>
                  <button class="rose" onclick="decideApproval('${p.approval_id}', 'rejected')">Reject (+ Save Note if provided)</button>
                </div>
              `;
              const placeholder = pBox.querySelector('.muted');
              if (placeholder && !placeholder.closest('[data-approval-id]')) {
                placeholder.remove();
              }
              pBox.appendChild(div);
            }
          });

          // Restore draft notes if any
          Object.entries(draftNotes).forEach(([id, val]) => {
            const el = document.getElementById(id);
            if (el && !el.value) {
              el.value = val;
            }
          });
        }
      }

      // Endorsed repeatable rules
      const rBox = document.getElementById('rulesList');
      const rules = Object.values(data.endorsed_rules || {});
      if (!rules.length) {
        rBox.innerHTML = '<div class="muted">Approve an action with "Always Allow" to store its repeatable signature here.</div>';
      } else {
        rBox.innerHTML = rules.map(r => `
          <div class="item">
            <strong>${r.domain_service}</strong> (${r.cause_category})
            <div class="muted">Targets: ${r.target_entity_ids.join(', ')} | Auto-executions: <strong>${r.execution_count}</strong></div>
            <div class="muted"><code>${r.signature}</code></div>
          </div>
        `).join('');
      }

      // User Context & Hardware Directives
      const cBox = document.getElementById('contextNotesList');
      const notes = data.user_context_notes || [];
      if (!notes.length) {
        cBox.innerHTML = '<div class="muted">No custom user context directives added yet.</div>';
      } else {
        cBox.innerHTML = notes.map(n => `
          <div class="item" style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px;">
            <div>
              <div><strong>📌 ${n.content}</strong></div>
              <div class="muted" style="font-size:0.78rem; margin-top:3px;">
                Scope: <code>${n.scope || 'global'}</code>
                ${n.related_entities && n.related_entities.length ? ` | Entities: <code>${n.related_entities.join(', ')}</code>` : ''}
              </div>
            </div>
            <button class="rose" style="padding:4px 10px; font-size:0.75rem;" onclick="deleteContextNote('${n.note_id}')">✕</button>
          </div>
        `).join('');
      }

      // Ignored Entities & Devices
      const igBox = document.getElementById('ignoredTargetsList');
      const ignored = data.ignored_targets || [];
      if (!ignored.length) {
        igBox.innerHTML = '<div class="muted">No ignored entities or patterns configured.</div>';
      } else {
        igBox.innerHTML = ignored.map(t => `
          <div class="item" style="display:flex; justify-content:space-between; align-items:center; gap:10px; padding:8px 12px;">
            <div>
              <code>${t.pattern}</code>
              ${t.reason ? `<span class="muted"> — ${t.reason}</span>` : ''}
            </div>
            <button class="rose" style="padding:4px 10px; font-size:0.75rem;" onclick="deleteIgnoredTarget('${t.ignore_id}')">✕</button>
          </div>
        `).join('');
      }

      // Logs (Live Reasoning traces with infinite scroll / lazy loading)
      totalServerLogs = data.total_logs_count || (data.recent_logs ? data.recent_logs.length : 0);
      const logsCountBadge = document.getElementById('logsCountBadge');
      if (logsCountBadge) logsCountBadge.textContent = totalServerLogs + ' traces';

      const lBox = document.getElementById('logsList');
      const loadMoreContainer = document.getElementById('logsLoadMoreContainer');
      const loadMoreBtn = document.getElementById('loadMoreLogsBtn');

      if (data.recent_logs && data.recent_logs.length) {
        if (allLoadedLogs.length === 0) {
          allLoadedLogs = [...data.recent_logs];
          allLoadedLogs.forEach(l => loadedLogIds.add(l.run_id));
          lBox.innerHTML = allLoadedLogs.map(renderSingleLogHtml).join('');
        } else {
          const newLiveLogs = (data.recent_logs || []).filter(l => !loadedLogIds.has(l.run_id));
          if (newLiveLogs.length > 0) {
            newLiveLogs.reverse().forEach(l => {
              allLoadedLogs.unshift(l);
              loadedLogIds.add(l.run_id);
              lBox.insertAdjacentHTML('afterbegin', renderSingleLogHtml(l));
            });
          }
        }
      }

      if (loadMoreContainer && loadMoreBtn) {
        if (allLoadedLogs.length < totalServerLogs) {
          loadMoreContainer.style.display = 'block';
          loadMoreBtn.textContent = `📜 Load More (${allLoadedLogs.length} of ${totalServerLogs})`;
        } else {
          loadMoreContainer.style.display = 'none';
        }
      }

      // Insights
      const iBox = document.getElementById('insightsList');
      const allAutoProposals = [];
      (data.recent_logs || []).forEach(l => {
        (l.proposed_intents || []).forEach(intent => {
          if (intent.domain === 'automation' || intent.native_automation) {
            allAutoProposals.push({agent_id: l.agent_id, intent});
          }
        });
      });

      let insightsContent = '';
      if (data.advisory_insights && data.advisory_insights.length) {
        insightsContent += data.advisory_insights.map(ins => `
          <div class="item">
            <strong>💡 ${ins.title}</strong> <span class="badge" style="font-size:0.7rem;">${ins.category}</span>
            <div class="muted" style="margin:6px 0;">${ins.finding_details}</div>
            <div><strong>Recommended Action:</strong> ${ins.recommended_human_action}</div>
          </div>
        `).join('');
      }
      if (allAutoProposals.length) {
        insightsContent += allAutoProposals.map(({agent_id, intent}) => `
          <div class="item">
            <strong>🤖 Proposed Native HA Automation (${agent_id})</strong>
            <div class="muted" style="margin:6px 0;">${intent.rationale}</div>
            <pre>${JSON.stringify(intent.native_automation || intent.service_data, null, 2)}</pre>
          </div>
        `).join('');
      }
      if (insightsContent) {
        iBox.innerHTML = insightsContent;
      }
    }

    async function updateSetting(field, value) {
      settingsMutationSeq++;
      const modeVal = document.getElementById('modeSelect').value;
      const autoVal = document.getElementById('autonomySelect').value;
      document.getElementById('modeBadge').textContent =
        modeVal.toUpperCase() + ' | ' + autoVal.toUpperCase();
      await fetch('./api/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({[field]: value})
      });
      await refreshAll();
    }

    async function updateSettings() {
      settingsMutationSeq++;
      await fetch('./api/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          operating_mode: document.getElementById('modeSelect').value,
          default_autonomy: document.getElementById('autonomySelect').value,
          llm_fallback_policy: document.getElementById('fallbackPolicySelect').value,
          notification_service: document.getElementById('notifyServiceSelect').value,
          notifications_enabled: document.getElementById('notifyCheck').checked
        })
      });
      await refreshAll();
    }

    async function decideFallback(decision, fallbackModel) {
      await fetch('./api/llm/fallback', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          decision: decision,
          fallback_model: fallbackModel
        })
      });
      await refreshAll();
    }

    async function triggerScenario(scenario) {
      await fetch('./api/events/simulate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({scenario})
      });
      await refreshAll();
    }

    async function triggerBatch() {
      await fetch('./api/batch/analyze', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({agent_id: 'climate_thermal_agent'})
      });
      await refreshAll();
    }

    async function decideApproval(id, decision) {
      const noteEl = document.getElementById(`note_${id}`);
      const humanNote = noteEl ? noteEl.value.trim() : '';
      await fetch(`./api/approvals/${id}/decide`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({decision, human_note: humanNote})
      });
      await refreshAll();
    }

    async function addContextNote() {
      const contentEl = document.getElementById('contextNoteInput');
      const entitiesEl = document.getElementById('contextEntitiesInput');
      const content = contentEl.value.trim();
      if (!content) return;
      const related_entities = entitiesEl.value
        ? entitiesEl.value.split(',').map(s => s.trim()).filter(Boolean)
        : [];
      await fetch('./api/context-notes', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({content, scope: 'global', related_entities})
      });
      contentEl.value = '';
      entitiesEl.value = '';
      await refreshAll();
    }

    async function deleteContextNote(noteId) {
      await fetch(`./api/context-notes/${noteId}`, {method: 'DELETE'});
      await refreshAll();
    }

    async function addIgnoredTarget() {
      const patEl = document.getElementById('ignorePatternInput');
      const reasonEl = document.getElementById('ignoreReasonInput');
      const pattern = patEl.value.trim();
      if (!pattern) return;
      await fetch('./api/ignore-list', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({pattern, reason: reasonEl.value.trim()})
      });
      patEl.value = '';
      reasonEl.value = '';
      await refreshAll();
    }

    async function deleteIgnoredTarget(ignoreId) {
      await fetch(`./api/ignore-list/${ignoreId}`, {method: 'DELETE'});
      await refreshAll();
    }

    async function loadMoreLogs() {
      if (isLoadingMoreLogs) return;
      isLoadingMoreLogs = true;
      const btn = document.getElementById('loadMoreLogsBtn');
      if (btn) btn.textContent = '⏳ Loading older traces...';
      try {
        const res = await fetch(`./api/logs?offset=${allLoadedLogs.length}&limit=10`);
        const json = await res.json();
        totalServerLogs = json.total;
        const countBadge = document.getElementById('logsCountBadge');
        if (countBadge) countBadge.textContent = totalServerLogs + ' traces';

        const newItems = (json.logs || []).filter(l => !loadedLogIds.has(l.run_id));
        if (newItems.length > 0) {
          newItems.forEach(l => {
            allLoadedLogs.push(l);
            loadedLogIds.add(l.run_id);
          });
          const lBox = document.getElementById('logsList');
          lBox.insertAdjacentHTML('beforeend', newItems.map(renderSingleLogHtml).join(''));
        }
        const loadMoreContainer = document.getElementById('logsLoadMoreContainer');
        if (loadMoreContainer && btn) {
          if (allLoadedLogs.length < totalServerLogs) {
            loadMoreContainer.style.display = 'block';
            btn.textContent = `📜 Load More (${allLoadedLogs.length} of ${totalServerLogs})`;
          } else {
            loadMoreContainer.style.display = 'none';
          }
        }
      } catch (err) {
        console.error('Failed to load more logs:', err);
        if (btn) btn.textContent = '⚠️ Error loading logs';
      } finally {
        isLoadingMoreLogs = false;
      }
    }

    const logsScroll = document.getElementById('logsScrollContainer');
    if (logsScroll) {
      logsScroll.addEventListener('scroll', () => {
        if (logsScroll.scrollTop + logsScroll.clientHeight >= logsScroll.scrollHeight - 60) {
          if (allLoadedLogs.length < totalServerLogs && !isLoadingMoreLogs) {
            loadMoreLogs();
          }
        }
      });
    }

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
        '<span class="badge" id="modeBadge">Loading...</span>',
        f'<span class="badge" id="modeBadge">{str(op_mode).upper()} | {str(autonomy).upper()}</span>',
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
            'id="notifyCheck" autocomplete="off" onchange="updateSetting(\'notifications_enabled\', this.checked)" checked />',
            'id="notifyCheck" autocomplete="off" onchange="updateSetting(\'notifications_enabled\', this.checked)" />',
        )
    return html

