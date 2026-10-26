#!/bin/bash
# Full gate: syntax + frontend workflows + monitor simulations + contracts.
# PYTHON=/path/to/python NODE=/path/to/node scripts/test.sh [src/webui]
set -eu
cd "$(dirname "$0")/.."
TARGET="${1:-src/webui}"
export VRCX_PI_SRC="$PWD/$TARGET"
export VRCX_PI_HOME="$PWD/$TARGET"
export PYTHONDONTWRITEBYTECODE=1
PY="${PYTHON:-python3}"
if [ -z "${PYTHON:-}" ] && [ -x .venv/bin/python ]; then PY=.venv/bin/python; fi
JS="${NODE:-node}"
if ! "$PY" -c 'import requests, websocket, pytest' 2>/dev/null; then
  echo 'Missing test dependencies. Create .venv and install requirements.txt + requirements-dev.txt, or set PYTHON.'
  exit 2
fi
command -v "$JS" >/dev/null || { echo 'Node.js is required for frontend regression tests; set NODE.'; exit 2; }
"$PY" - <<'PY'
import os
from pathlib import Path
if Path('run.py').exists(): compile(Path('run.py').read_text(), 'run.py', 'exec')
for root in (Path(os.environ['VRCX_PI_SRC']), Path('src/application'), Path('backend'), Path('scripts')):
    for p in root.rglob('*.py'):
        compile(p.read_text(),str(p),'exec')
print('PASS Python syntax')
PY
while IFS= read -r js; do "$JS" --check "$js"; done < <(rg --files "$TARGET/static" -g '*.js')
"$JS" --test tests/frontend/*.test.cjs
RC=0
for simulation in tests/test_*.py; do "$PY" "$simulation" || RC=1; done
# Explicit reduced mode for sandboxes that cannot bind loopback sockets. Default
# always executes the full HTTP cookie transport integration tests.
if [ "${VRCX_TEST_SKIP_HTTP:-0}" = 1 ]; then
  echo 'PARTIAL GATE: 3 loopback HTTP tests deselected; full HTTP/Pi validation is still required.'
  "$PY" -m pytest tests/contract -p no:cacheprovider -q --tb=short -k 'not test_challenge_starts_with_clean_cookie_jar and not test_verify_step_keeps_challenge_session_cookies and not test_resend_challenge_clears_previous_challenge_cookies' || RC=1
else
  "$PY" -m pytest tests/contract -p no:cacheprovider -q --tb=short || RC=1
fi
exit "$RC"
