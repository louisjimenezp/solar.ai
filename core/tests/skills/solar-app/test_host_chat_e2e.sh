#!/usr/bin/env bash
# Canonical /app HTTP flow and retirement of disposable scoped chat.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 -m unittest discover -s "$SCRIPT_DIR" -p 'test_voice_http.py' -v
python3 -m unittest discover -s "$SCRIPT_DIR" -p 'test_app_conversations.py' -v
