#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# MCP_test.sh — Test the GitHub MCP Server via HTTP transport
#
# Usage:
#   bash MCP_test.sh                                   # uses $Github_Token
#   OWNER=myorg REPO=myrepo FILE=README.md bash MCP_test.sh
#   MCP_PORT=9053 bash MCP_test.sh                     # target private server
# ─────────────────────────────────────────────────────────────────────────────
set -e

MCP_HOST="${MCP_HOST:-http://localhost}"
MCP_PORT="${MCP_PORT:-9051}"
BASE_URL="$MCP_HOST:$MCP_PORT/mcp"

OWNER="${OWNER:-BabakEA}"
REPO="${REPO:-WireGuard-VPN-Server}"
FILE="${FILE:-README.md}"

# ── Token resolution ──────────────────────────────────────────────────────────
TOKEN="${Github_Token:-$GITHUB_PERSONAL_ACCESS_TOKEN}"
if [ -z "$TOKEN" ] && [ -f "$(dirname "$0")/.env" ]; then
  export $(grep -E '^(Github_Token|GITHUB_PERSONAL_ACCESS_TOKEN)=' "$(dirname "$0")/.env" | xargs)
  TOKEN="${Github_Token:-$GITHUB_PERSONAL_ACCESS_TOKEN}"
fi
if [ -z "$TOKEN" ]; then
  echo "ERROR: No GitHub token found."
  echo "  Set \$Github_Token or \$GITHUB_PERSONAL_ACCESS_TOKEN, or add it to .env"
  exit 1
fi

echo "=== MCP Test ==="
echo "  Target  : $BASE_URL"
echo "  Repo    : $OWNER/$REPO"
echo "  File    : $FILE"
echo ""

# ── Step 1: Initialize session ────────────────────────────────────────────────
echo "[1/3] Initializing MCP session..."
SESSION=$(curl -si -X POST "$BASE_URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": { "name": "MCP_test.sh", "version": "1.0" }
    }
  }' 2>/dev/null | grep -i "^Mcp-Session-Id:" | awk '{print $2}' | tr -d '\r')

if [ -z "$SESSION" ]; then
  echo "ERROR: Failed to obtain MCP session ID. Is the server running on $BASE_URL?"
  exit 1
fi
echo "  Session : $SESSION"

# ── Step 2: Send initialized notification ────────────────────────────────────
echo "[2/3] Sending initialized notification..."
curl -s -X POST "$BASE_URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' \
  > /dev/null 2>&1

# ── Step 3: Fetch file contents ───────────────────────────────────────────────
echo "[3/3] Fetching $FILE from $OWNER/$REPO..."
echo ""
echo "─────────────────────────────────────────────────────────────────────────"

RESPONSE=$(curl -s -X POST "$BASE_URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "mcp-session-id: $SESSION" \
  -d "{
    \"jsonrpc\": \"2.0\",
    \"id\": 3,
    \"method\": \"tools/call\",
    \"params\": {
      \"name\": \"get_file_contents\",
      \"arguments\": {
        \"owner\": \"$OWNER\",
        \"repo\": \"$REPO\",
        \"path\": \"$FILE\"
      }
    }
  }" 2>/dev/null)

# ── Extract and pretty-print the file text ────────────────────────────────────
JSON=$(echo "$RESPONSE" | grep '^data:' | sed 's/^data: //')
FILE_TEXT=$(echo "$JSON" | node -e "
const chunks=[];
process.stdin.on('data',c=>chunks.push(c));
process.stdin.on('end',()=>{
  const d=JSON.parse(chunks.join(''));
  const item=d.result.content.find(x=>x.type==='resource');
  if(item) process.stdout.write(item.resource.text);
});
" 2>/dev/null || echo "$RESPONSE")

echo "$FILE_TEXT"
echo "─────────────────────────────────────────────────────────────────────────"
echo ""
echo "Done."
