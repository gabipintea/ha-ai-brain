#!/usr/bin/env bash
set -e

OPTIONS_FILE="/data/options.json"

if [ -f "$OPTIONS_FILE" ]; then
    export BRAIN_OPERATING_MODE=$(jq -r '.operating_mode // "hybrid"' "$OPTIONS_FILE")
    export BRAIN_DEFAULT_AUTONOMY=$(jq -r '.default_autonomy_level // "shadow"' "$OPTIONS_FILE")
    export BRAIN_LLM_MODEL=$(jq -r '.llm_provider // "openai/gpt-4o"' "$OPTIONS_FILE")
    export BRAIN_LLM_FAST_MODEL=$(jq -r '.llm_fast_model // "openai/gpt-4o-mini"' "$OPTIONS_FILE")
    export BRAIN_LLM_API_KEY=$(jq -r '.llm_api_key // ""' "$OPTIONS_FILE")
    export BRAIN_MANAGED_PROXY_URL=$(jq -r '.managed_cloud_proxy_url // ""' "$OPTIONS_FILE")
    export BRAIN_LICENSE_KEY=$(jq -r '.license_key // ""' "$OPTIONS_FILE")
    export BRAIN_SITE_CONTEXT=$(jq -r '.site_context // ""' "$OPTIONS_FILE")
    export BRAIN_NOTIFICATIONS_ENABLED=$(jq -r '.enable_actionable_notifications // true' "$OPTIONS_FILE")
    export BRAIN_NOTIFICATION_SERVICE=$(jq -r '.notification_service // "notify.notify"' "$OPTIONS_FILE")
    export BRAIN_BATCH_INTERVAL_MINUTES=$(jq -r '.batch_analysis_interval_minutes // 360' "$OPTIONS_FILE")
    export BRAIN_DB_PATH="/data/ha_ai_brain.db"
fi

if [ -n "${SUPERVISOR_TOKEN:-}" ]; then
    export BRAIN_HA_URL="http://supervisor/core"
    export BRAIN_HA_WS_URL="ws://supervisor/core/websocket"
    export BRAIN_HA_TOKEN="${SUPERVISOR_TOKEN}"
    export BRAIN_USE_SIMULATOR="false"
fi

echo "Starting HA AI Brain on port 8099 (Simulator=${BRAIN_USE_SIMULATOR:-auto})..."
exec python3 -m uvicorn ha_ai_brain.api.app:create_app --factory --host 0.0.0.0 --port 8099
