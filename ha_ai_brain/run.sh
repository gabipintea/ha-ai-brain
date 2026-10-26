#!/usr/bin/env bash
set -euo pipefail

OPTIONS_FILE="/data/options.json"

# Read an add-on option, falling back to a default only when the key is missing/null.
# (`jq '.x // default'` is wrong for booleans: `false // true` evaluates to `true`.)
opt() {
    jq -r --arg key "$1" --arg def "$2" \
        'if has($key) and .[$key] != null then .[$key] else $def end | tostring' "$OPTIONS_FILE"
}

if [ -f "$OPTIONS_FILE" ]; then
    export BRAIN_OPERATING_MODE="$(opt operating_mode hybrid)"
    export BRAIN_DEFAULT_AUTONOMY="$(opt default_autonomy_level copilot)"
    export BRAIN_LLM_MODEL="$(opt llm_provider gemini/gemini-3.8-flash)"
    export BRAIN_LLM_FAST_MODEL="$(opt llm_fast_model gemini/gemini-3.5-flash)"
    export BRAIN_LLM_API_KEY="$(opt llm_api_key '')"
    export BRAIN_MANAGED_PROXY_URL="$(opt managed_cloud_proxy_url '')"
    export BRAIN_LICENSE_KEY="$(opt license_key DEV-TRIAL-KEY)"
    export BRAIN_SITE_CONTEXT="$(opt site_context '')"
    export BRAIN_NOTIFICATIONS_ENABLED="$(opt enable_actionable_notifications true)"
    export BRAIN_NOTIFICATION_SERVICE="$(opt notification_service notify.notify)"
    export BRAIN_BATCH_INTERVAL_MINUTES="$(opt batch_analysis_interval_minutes 360)"
    export BRAIN_BATCH_LOOKBACK_HOURS="$(opt batch_lookback_hours 24)"
    export BRAIN_REALTIME_GATING="$(opt realtime_gating true)"
    export BRAIN_EXCEPTION_DETECTION="$(opt exception_detection true)"
    export BRAIN_DETERMINISTIC_AUTOMATIONS="$(opt deterministic_automations true)"
    export BRAIN_PRIVACY_SCRUB="$(opt privacy_scrub true)"
    export BRAIN_DAILY_TOKEN_BUDGET="$(opt daily_token_budget 0)"
    export BRAIN_QUIET_HOURS_START="$(opt quiet_hours_start '')"
    export BRAIN_QUIET_HOURS_END="$(opt quiet_hours_end '')"
    export BRAIN_RESEARCH_ENABLED="$(opt research_enabled true)"
    export BRAIN_RESEARCH_WEB_SEARCH="$(opt research_web_search false)"
    export BRAIN_RESEARCH_INTERVAL_DAYS="$(opt research_interval_days 7)"
    export BRAIN_LOG_LEVEL="$(opt log_level info)"
    export BRAIN_TIMEZONE="$(opt timezone '')"
    export BRAIN_KNOWLEDGE_DIR="/config/ha_ai_brain/knowledge"
    export BRAIN_DB_PATH="/data/ha_ai_brain.db"
    export BRAIN_CUSTOM_AGENTS_DIR="/config/ha_ai_brain/agents"
    export BRAIN_BUNDLED_AGENTS_DIR="/app/agents"
fi

# User-editable files (custom agents, extra reference knowledge) live in the Home Assistant config folder,
# where the File editor / Samba / SSH add-ons can reach them.
mkdir -p /config/ha_ai_brain/agents /config/ha_ai_brain/knowledge 2>/dev/null || true

# An empty site context option must not override the built-in default description.
if [ -z "${BRAIN_SITE_CONTEXT:-}" ]; then
    unset BRAIN_SITE_CONTEXT
fi

if [ -n "${SUPERVISOR_TOKEN:-}" ]; then
    export BRAIN_HA_URL="http://supervisor/core"
    export BRAIN_HA_WS_URL="ws://supervisor/core/websocket"
    export BRAIN_HA_TOKEN="${SUPERVISOR_TOKEN}"
    export BRAIN_USE_SIMULATOR="false"
fi

echo "Starting HA AI Brain on port 8099 (Simulator=${BRAIN_USE_SIMULATOR:-auto})..."
exec python3 -m uvicorn ha_ai_brain.api.app:create_app --factory --host 0.0.0.0 --port 8099
