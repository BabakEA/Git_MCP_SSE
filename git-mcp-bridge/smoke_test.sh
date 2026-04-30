#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXAMPLES_DIR="$SCRIPT_DIR/examples"
PYTHON_BIN="${PYTHON_BIN:-python}"
SMOKE_PORT="${SMOKE_PORT:-8512}"
SMOKE_HOST="${SMOKE_HOST:-127.0.0.1}"
RUN_UI_SMOKE="${RUN_UI_SMOKE:-1}"
RUN_COMPOSE_SMOKE="${RUN_COMPOSE_SMOKE:-1}"

cleanup() {
  if [[ -n "${STREAMLIT_PID:-}" ]]; then
    kill "$STREAMLIT_PID" >/dev/null 2>&1 || true
    wait "$STREAMLIT_PID" 2>/dev/null || true
  fi
  rm -f "$SCRIPT_DIR/.env"
}
trap cleanup EXIT

echo "[1/5] Checking shell scripts"
bash -n "$SCRIPT_DIR/run_ui.sh"

echo "[2/5] Checking Python syntax"
"$PYTHON_BIN" -m py_compile \
  "$EXAMPLES_DIR/langgraph_mcp_agent.py" \
  "$EXAMPLES_DIR/streamlit_chat_app.py"

echo "[3/5] Checking Python imports"
PYTHONPATH="$EXAMPLES_DIR${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON_BIN" -c "import langgraph_mcp_agent, streamlit_chat_app; print('imports-ok')"

if [[ "$RUN_COMPOSE_SMOKE" == "1" ]]; then
  echo "[4/5] Checking docker compose config"
  cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
  (cd "$SCRIPT_DIR" && docker compose config >/dev/null)
  rm -f "$SCRIPT_DIR/.env"
fi

if [[ "$RUN_UI_SMOKE" == "1" ]]; then
  echo "[5/5] Starting Streamlit smoke server"
  PYTHONPATH="$EXAMPLES_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    STREAMLIT_GLOBAL_DEVELOPMENT_MODE=false \
    UI_USERNAME=smoke \
    UI_PASSWORD=smoke \
    "$PYTHON_BIN" -m streamlit run "$EXAMPLES_DIR/streamlit_chat_app.py" \
      --server.headless true \
      --server.address "$SMOKE_HOST" \
      --server.port "$SMOKE_PORT" >/tmp/git-mcp-bridge-streamlit-smoke.log 2>&1 &
  STREAMLIT_PID=$!

  "$PYTHON_BIN" -c "import time, urllib.request; url='http://$SMOKE_HOST:$SMOKE_PORT/_stcore/health'; deadline=time.time()+40; last=None
while time.time()<deadline:
    try:
        print(urllib.request.urlopen(url, timeout=3).read().decode('utf-8', 'replace'))
        raise SystemExit(0)
    except Exception as exc:
        last=exc
        time.sleep(1)
print(f'healthcheck failed: {last}')
raise SystemExit(1)"
fi

echo "Smoke tests passed."