#!/usr/bin/env bash
# Voice core unit tests — parse_intent + parse_sse_line (no network).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SCRIPTS="$CORE_ROOT/skills/solar-app/scripts"
PASS=0
FAIL=0

assert_ok() {
  local label="$1"
  shift
  if "$@"; then
    echo "PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $label" >&2
    FAIL=$((FAIL + 1))
  fi
}

export SOLAR_VOICE_MOCK_STREAM=1
export SOLAR_VOICE_MOCK_STREAM_FIXTURE="$SCRIPT_DIR/fixtures/voice_mock_stream.sse"

python3 - <<'PY' "$SCRIPTS" || exit 1
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
import voice_core as vc

cases = [
    ("status del host", "status"),
    ("estado", "status"),
    ("aprobar", "approve"),
    ("reject pending", "reject"),
    ("switch uhorizon", "switch_ws"),
    ("abrir dashboard", "open_dashboard"),
    ("open host please", "open_dashboard"),
    ("cuántos leads hay", "ask"),
]
for text, want in cases:
    got = vc.parse_intent(text)
    assert got == want, f"parse_intent({text!r}) = {got!r}, want {want!r}"

sse_cases = [
    ('data: {"type": "chunk", "text": "hi"}', "chunk"),
    ('data: {"type": "done", "status": "succeeded"}', "done"),
    ("not sse", None),
    ("data: {broken", None),
]
for line, want_type in sse_cases:
    evt = vc.parse_sse_line(line)
    if want_type is None:
        assert evt is None, line
    else:
        assert evt and evt.get("type") == want_type, line

chunks = list(vc.stream_ask("mock", "thread_x"))
assert any(c.get("type") == "chunk" for c in chunks), chunks
assert any(c.get("type") == "done" for c in chunks), chunks

assert vc.detect_text_language("Prepara un resumen de los gastos") == "es"
assert vc.detect_text_language("Please prepare a summary of the expenses") == "en"
assert vc.detect_text_language("Prépare un résumé des dépenses") == "fr"
vc._say_voices = [("Mónica", "es_ES"), ("Daniel", "en_GB"), ("Thomas", "fr_FR")]
assert vc.tts_voice_for_text("¿Puedes leer este resultado?") == "Mónica"
assert vc.tts_voice_for_text("Please read this result") == "Daniel"
with patch.object(vc.shutil, "which", return_value="/usr/bin/say"), \
     patch.object(vc.subprocess, "Popen") as popen:
    process = popen.return_value
    process.poll.return_value = 0
    vc.speak_brief("Please read this result")
    popen.assert_called_once_with(["say", "-v", "Daniel", "Please read this result"])
    process.wait.assert_called_once()
print("OK: voice_core unit")
PY
assert_ok "voice_core unit inline" test $? -eq 0

python3 -m py_compile "$SCRIPTS/voice_core.py" "$SCRIPTS/voice_cli.py"
assert_ok "py_compile voice modules" test $? -eq 0

echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
