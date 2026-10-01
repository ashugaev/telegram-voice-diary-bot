#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --speech ) ]]; then
    echo 'Usage: bash scripts/check-sidecar.sh [--speech]' >&2
    exit 2
fi
: "${SPUR_SESSION_ARTIFACTS_DIR:?Run inside a Spur session}"
check_dir=$(mktemp -d "${SPUR_SESSION_ARTIFACTS_DIR}/check.XXXXXX")
python_bin=${PYTHON:-.venv/bin/python}

# Test credentials only. Disable dotenv loading before importing config.
env -i PATH="$PATH" HOME="$HOME" \
    PYTHON_DOTENV_DISABLED=1 \
    TELEGRAM_TOKEN=test-token OPENAI_API_KEY=test-openai-key \
    NOTION_TOKEN=test-notion-token NOTION_DATABASE_ID=test-notion-db \
    ALLOWED_USER_ID=1 AI_PROVIDER=openai \
    BOT_STATE_PATH="$check_dir/message_state.json" \
    make test PYTHON="$python_bin" 2>&1 | tee "$check_dir/offline.log"

if [[ ${1:-} == --speech ]]; then
    "$python_bin" scripts/speech-smoke.py
fi
printf 'Offline validation passed. Artifacts: %s\n' "$check_dir"
