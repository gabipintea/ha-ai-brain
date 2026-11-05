#!/usr/bin/env bash
set -euo pipefail

# setup_github_repo.sh
# Configures GitHub repository settings, metadata, discussions, topics,
# and branch protection rulesets using the official GitHub CLI ('gh').

REPO="gabipintea/ha-ai-brain"

echo "=== HA AI Brain GitHub Configuration Tool ==="

# Check gh CLI availability
if ! command -v gh >/dev/null 2>&1; then
  if [ -x "/opt/homebrew/bin/gh" ]; then
    export PATH="/opt/homebrew/bin:$PATH"
  else
    echo "Error: GitHub CLI ('gh') is not installed. Run 'brew install gh' first."
    exit 1
  fi
fi

# Verify gh authentication
if ! gh auth status >/dev/null 2>&1; then
  echo ""
  echo "GitHub CLI is not authenticated yet."
  echo "Launching browser login..."
  gh auth login --hostname github.com -p https --web
fi

echo ""
echo " Authenticated as: $(gh api user --jq .login)"
echo " Configuring repository: $REPO..."

# 1. Update Repository Metadata, Homepage, and Features
echo " Setting description, homepage, issues, discussions, squash-merge..."
gh repo edit "$REPO" \
  --description "Autonomous Multi-Agent Cognitive Brain for Home Assistant: local habit learning, zero-token statistics, backtested native automations, anomaly watches, and multi-provider LLM agents." \
  --homepage "https://github.com/gabipintea/ha-ai-brain" \
  --enable-issues \
  --enable-discussions \
  --enable-squash-merge \
  --delete-branch-on-merge

# 2. Add Topics (Tags)
echo " Adding repository topics for community discoverability..."
TOPICS=(
  "home-assistant"
  "home-assistant-addon"
  "smart-home"
  "automations"
  "llm"
  "ai-agent"
  "local-first"
  "gemini"
  "openai"
  "anthropic"
  "ollama"
  "privacy-first"
)

for topic in "${TOPICS[@]}"; do
  gh repo edit "$REPO" --add-topic "$topic"
done

# 3. Configure Branch Ruleset for 'main'
echo " Configuring branch ruleset: 'Protect main branch'..."

# Check if ruleset already exists
EXISTING_RULESET_ID=$(gh api "repos/$REPO/rulesets" --jq '.[] | select(.name=="Protect main branch") | .id' 2>/dev/null || true)

PAYLOAD='{
  "name": "Protect main branch",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [
    {
      "actor_id": 5,
      "actor_type": "RepositoryRole",
      "bypass_mode": "always"
    }
  ],
  "conditions": {
    "ref_name": {
      "include": ["~DEFAULT_BRANCH"],
      "exclude": []
    }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": true,
        "require_last_push_approval": true,
        "required_review_thread_resolution": true
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          { "context": "Test Suite (Python 3.11)" },
          { "context": "Test Suite (Python 3.12)" },
          { "context": "Verify Mirrored Files & JS Syntax" }
        ]
      }
    }
  ]
}'

if [ -n "$EXISTING_RULESET_ID" ]; then
  echo "Updating existing ruleset ID: $EXISTING_RULESET_ID..."
  echo "$PAYLOAD" | gh api --method PUT "repos/$REPO/rulesets/$EXISTING_RULESET_ID" --input - >/dev/null
  echo " Ruleset updated successfully."
else
  echo "Creating new branch ruleset..."
  echo "$PAYLOAD" | gh api --method POST "repos/$REPO/rulesets" --input - >/dev/null
  echo " Ruleset created successfully."
fi

echo ""
echo "🎉 Repository configuration complete!"
echo "View your updated repository at: https://github.com/$REPO"
echo "View branch rulesets at: https://github.com/$REPO/settings/rules"
