#!/bin/bash
set -e

# ─── Configuration ────────────────────────────────────────────────────────────
MCP_SERVER="$(dirname "$0")/github-mcp-server"

# Private/custom GitHub Enterprise full URL (edit this, must include https://)
PRIVATE_GITHUB_HOST="${PRIVATE_GITHUB_HOST:-https://github.mycompany.com}"
PUBLIC_GITHUB_HOST="https://github.com"

# Token: prefer $Github_Token, fallback to GITHUB_PERSONAL_ACCESS_TOKEN
if [ -z "$Github_Token" ] && [ -z "$GITHUB_PERSONAL_ACCESS_TOKEN" ]; then
  if [ -f "$(dirname "$0")/.env" ]; then
    export $(grep -E '^(Github_Token|GITHUB_PERSONAL_ACCESS_TOKEN)=' "$(dirname "$0")/.env" | xargs)
  fi
fi

echo "=== Starting GitHub MCP Servers ==="
echo "  Public  HTTP  → port 9051 ($PUBLIC_GITHUB_HOST)"
echo "  Public  SSE   → port 9050 ($PUBLIC_GITHUB_HOST)"
echo "  Private HTTP  → port 9053 ($PRIVATE_GITHUB_HOST)"
echo "  Private SSE   → port 9052 ($PRIVATE_GITHUB_HOST)"
echo ""

# Public GitHub — HTTP (port 9051)
"$MCP_SERVER" http --port 9051 --gh-host "$PUBLIC_GITHUB_HOST" \
  2>&1 | sed 's/^/[PUB-HTTP] /' &

# Public GitHub — SSE (port 9050)
"$MCP_SERVER" sse --port 9050 --gh-host "$PUBLIC_GITHUB_HOST" \
  2>&1 | sed 's/^/[PUB-SSE ] /' &

# Private/Custom GitHub — HTTP (port 9053)
"$MCP_SERVER" http --port 9053 --gh-host "$PRIVATE_GITHUB_HOST" \
  2>&1 | sed 's/^/[PVT-HTTP] /' &

# Private/Custom GitHub — SSE (port 9052)
"$MCP_SERVER" sse --port 9052 --gh-host "$PRIVATE_GITHUB_HOST" \
  2>&1 | sed 's/^/[PVT-SSE ] /' &

echo "All servers started. Press Ctrl+C to stop all."
wait
