#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_FILE="$SCRIPT_DIR/examples/streamlit_chat_app.py"
REQ_FILE="$SCRIPT_DIR/examples/requirements-langgraph-agent.txt"

PYTHON_BIN="${PYTHON_BIN:-python}"
STREAMLIT_HOST="${STREAMLIT_HOST:-127.0.0.1}"
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"

if [[ -n "${GIT_WEB_BASE_URL:-}" ]]; then
  export GIT_WEB_BASE_URL
fi

if [[ -n "${REPORT_FORMAT:-}" ]]; then
  export REPORT_FORMAT
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python executable not found: $PYTHON_BIN" >&2
  exit 1
fi

if [ ! -f "$APP_FILE" ]; then
  echo "Streamlit app not found: $APP_FILE" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c "import streamlit" >/dev/null 2>&1; then
  cat >&2 <<EOF
Missing Python dependency: streamlit

Install the example dependencies first:
  $PYTHON_BIN -m pip install -r "$REQ_FILE"
EOF
  exit 1
fi

if [ -z "${MCP_AUTH_TOKEN:-${GITHUB_TOKEN:-}}" ]; then
  cat <<EOF
Warning: MCP_AUTH_TOKEN is not set.
The UI will start, but you still need to enter a bearer token in the sidebar before the agent can use GitHub MCP tools.
EOF
fi

if [ -n "${UI_USERNAME:-}" ] && [ -z "${UI_PASSWORD:-}" ]; then
  echo "Warning: UI_USERNAME is set but UI_PASSWORD is empty. Hosted login will stay disabled." >&2
fi

export PYTHONPATH="$SCRIPT_DIR/examples${PYTHONPATH:+:$PYTHONPATH}"

echo "Starting Streamlit UI on http://$STREAMLIT_HOST:$STREAMLIT_PORT"
exec "$PYTHON_BIN" -m streamlit run "$APP_FILE" \
  --server.address "$STREAMLIT_HOST" \
  --server.port "$STREAMLIT_PORT" \
  "$@"