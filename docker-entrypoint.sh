#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# docker-entrypoint.sh — Start all GitHub MCP Server instances
#
# Environment variables:
#   GITHUB_PERSONAL_ACCESS_TOKEN  (required) GitHub PAT for public github.com
#   Github_Token                  (alternative token var, same priority)
#   PRIVATE_GITHUB_HOST           (optional)  full URL of private GHE instance
#                                             e.g. https://github.mycompany.com
#                                             default: disabled (skip private servers)
#   PRIVATE_GITHUB_TOKEN          (optional)  PAT for the private GHE instance
#                                             if not set, falls back to GITHUB_PERSONAL_ACCESS_TOKEN
# ─────────────────────────────────────────────────────────────────────────────
set -e

PUBLIC_GITHUB_HOST="https://github.com"
PRIVATE_GITHUB_HOST="${PRIVATE_GITHUB_HOST:-}"

# Resolve public token
TOKEN="${Github_Token:-${GITHUB_PERSONAL_ACCESS_TOKEN:-}}"
if [ -z "$TOKEN" ]; then
  echo "[ERROR] No GitHub token provided."
  echo "  Set GITHUB_PERSONAL_ACCESS_TOKEN or Github_Token environment variable."
  exit 1
fi

# Resolve private token (falls back to the public token if not set)
PRIVATE_TOKEN="${PRIVATE_GITHUB_TOKEN:-$TOKEN}"

# Export public token under the canonical name the server binary reads
export GITHUB_PERSONAL_ACCESS_TOKEN="$TOKEN"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║          GitHub MCP Server — Docker Container            ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Public  HTTP  → port 9051  ($PUBLIC_GITHUB_HOST)"
echo "  Public  SSE   → port 9050  ($PUBLIC_GITHUB_HOST)"
if [ -n "$PRIVATE_GITHUB_HOST" ]; then
  echo "  Private HTTP  → port 9053  ($PRIVATE_GITHUB_HOST)"
  echo "  Private SSE   → port 9052  ($PRIVATE_GITHUB_HOST)"
  if [ -n "$PRIVATE_GITHUB_TOKEN" ]; then
    echo "  Private token → PRIVATE_GITHUB_TOKEN (separate from public token)"
  else
    echo "  Private token → same as GITHUB_PERSONAL_ACCESS_TOKEN"
  fi
else
  echo "  Private servers → DISABLED  (set PRIVATE_GITHUB_HOST to enable)"
fi
echo ""

# ── Graceful shutdown ─────────────────────────────────────────────────────────
# Collect all child PIDs and kill them on SIGTERM/SIGINT
PIDS=""

cleanup() {
  echo ""
  echo "[INFO] Shutting down all MCP servers..."
  for pid in $PIDS; do
    kill "$pid" 2>/dev/null || true
  done
  wait
  echo "[INFO] All servers stopped."
  exit 0
}
trap cleanup INT TERM

# ── Start Public GitHub servers ───────────────────────────────────────────────
/server/github-mcp-server http \
  --port 9051 \
  --gh-host "$PUBLIC_GITHUB_HOST" \
  2>&1 | sed 's/^/[PUB-HTTP] /' &
PIDS="$PIDS $!"

/server/github-mcp-server sse \
  --port 9050 \
  --gh-host "$PUBLIC_GITHUB_HOST" \
  2>&1 | sed 's/^/[PUB-SSE ] /' &
PIDS="$PIDS $!"

# ── Start Private/Enterprise GitHub servers (if configured) ───────────────────
if [ -n "$PRIVATE_GITHUB_HOST" ]; then
  GITHUB_PERSONAL_ACCESS_TOKEN="$PRIVATE_TOKEN" /server/github-mcp-server http \
    --port 9053 \
    --gh-host "$PRIVATE_GITHUB_HOST" \
    2>&1 | sed 's/^/[PVT-HTTP] /' &
  PIDS="$PIDS $!"

  GITHUB_PERSONAL_ACCESS_TOKEN="$PRIVATE_TOKEN" /server/github-mcp-server sse \
    --port 9052 \
    --gh-host "$PRIVATE_GITHUB_HOST" \
    2>&1 | sed 's/^/[PVT-SSE ] /' &
  PIDS="$PIDS $!"
fi

echo "[INFO] All servers started. Container is ready."
echo "[INFO] Send SIGTERM or docker stop to shut down gracefully."
echo ""

# Wait for all background processes
wait
