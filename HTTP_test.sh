#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# HTTP_test.sh — Test the GitHub MCP Server in HTTP (Streamable HTTP) transport
#
# The HTTP transport (port 9051/9053) uses MCP Streamable HTTP spec:
#   • All requests are HTTP POST to /mcp
#   • Responses stream back as SSE (text/event-stream) inside the HTTP body
#   • A session ID in the Mcp-Session-Id header ties requests together
#
# Usage:
#   bash HTTP_test.sh                                  # uses $Github_Token
#   OWNER=myorg REPO=myrepo FILE=src/main.go bash HTTP_test.sh
#   MCP_PORT=9053 bash HTTP_test.sh                    # target private server
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

echo "╔══════════════════════════════════════════════════════════╗"
echo "║       GitHub MCP Server — HTTP Transport Test            ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Transport : Streamable HTTP (MCP spec 2024-11-05)"
echo "  Target    : $BASE_URL"
echo "  Repo      : $OWNER/$REPO"
echo "  File      : $FILE"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — initialize
#   POST /mcp  with method=initialize
#   Server responds: HTTP 200, Content-Type: text/event-stream
#   Body format:
#     event: message
#     data: {"jsonrpc":"2.0","id":1,"result":{...capabilities + serverInfo...}}
#   The Mcp-Session-Id header is returned here — save it for all future requests.
# ─────────────────────────────────────────────────────────────────────────────
echo "┌──────────────────────────────────────────────────────────┐"
echo "│  STEP 1 — initialize                                     │"
echo "└──────────────────────────────────────────────────────────┘"
echo "  POST $BASE_URL"
echo "  Body: method=initialize, protocolVersion=2024-11-05"
echo ""

INIT_RAW=$(curl -si -X POST "$BASE_URL" \
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
      "clientInfo": { "name": "HTTP_test.sh", "version": "1.0" }
    }
  }' 2>/dev/null)

SESSION=$(echo "$INIT_RAW" | grep -i "^Mcp-Session-Id:" | awk '{print $2}' | tr -d '\r')
HTTP_STATUS=$(echo "$INIT_RAW" | head -1 | awk '{print $2}')
CONTENT_TYPE=$(echo "$INIT_RAW" | grep -i "^Content-Type:" | head -1 | awk '{print $2}' | tr -d '\r')
SERVER_NAME=$(echo "$INIT_RAW" | grep '"serverInfo"' | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)
PROTOCOL=$(echo "$INIT_RAW" | grep '"protocolVersion"' | grep -o '"protocolVersion":"[^"]*"' | cut -d'"' -f4)

if [ -z "$SESSION" ]; then
  echo "  ✗ ERROR: No session ID returned. Is the server running on $BASE_URL?"
  exit 1
fi

echo "  ← HTTP $HTTP_STATUS"
echo "  ← Content-Type: $CONTENT_TYPE  ← SSE streaming format"
echo "  ← Mcp-Session-Id: $SESSION"
echo "  ← Server: $SERVER_NAME  (protocol $PROTOCOL)"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — notifications/initialized
#   POST /mcp  with method=notifications/initialized  +  mcp-session-id header
#   This is a JSON-RPC notification (no "id" field) — the client tells the
#   server it has finished processing the initialize result.
#   Server responds: HTTP 202 Accepted, Content-Length: 0  (empty body)
# ─────────────────────────────────────────────────────────────────────────────
echo "┌──────────────────────────────────────────────────────────┐"
echo "│  STEP 2 — notifications/initialized                      │"
echo "└──────────────────────────────────────────────────────────┘"
echo "  POST $BASE_URL"
echo "  Header: mcp-session-id: $SESSION"
echo "  Body: method=notifications/initialized  (no 'id' — it's a notification)"
echo ""

NOTIF_RAW=$(curl -si -X POST "$BASE_URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' 2>/dev/null)

NOTIF_STATUS=$(echo "$NOTIF_RAW" | head -1 | awk '{print $2}')
NOTIF_LEN=$(echo "$NOTIF_RAW" | grep -i "^Content-Length:" | awk '{print $2}' | tr -d '\r')

echo "  ← HTTP $NOTIF_STATUS  ← no body (acknowledged, no response)"
[ -n "$NOTIF_LEN" ] && echo "  ← Content-Length: $NOTIF_LEN"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — tools/call  →  get_file_contents
#   POST /mcp  with method=tools/call  +  mcp-session-id header
#   Server responds: HTTP 200, text/event-stream
#   Body format:
#     event: message
#     data: {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text",...},
#            {"type":"resource","resource":{"uri":...,"text":"<file contents>"}}]}}
# ─────────────────────────────────────────────────────────────────────────────
echo "┌──────────────────────────────────────────────────────────┐"
echo "│  STEP 3 — tools/call  (get_file_contents)                │"
echo "└──────────────────────────────────────────────────────────┘"
echo "  POST $BASE_URL"
echo "  Header: mcp-session-id: $SESSION"
echo "  Body: method=tools/call, name=get_file_contents"
echo "        owner=$OWNER  repo=$REPO  path=$FILE"
echo ""

TOOL_RAW=$(curl -s -X POST "$BASE_URL" \
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

# Strip SSE envelope: "event: message\ndata: " → extract the JSON
JSON=$(echo "$TOOL_RAW" | grep '^data:' | sed 's/^data: //')

# Check for error vs success
if echo "$JSON" | grep -q '"error"'; then
  echo "  ✗ Tool call returned an error:"
  echo "$JSON" | node -e "const d=JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')); const e=d.error||{}; console.log('  Code:',e.code,' Message:',e.message);" 2>/dev/null || echo "$JSON"
  exit 1
fi

# Extract file text from the resource content item (via node — JSON-native)
FILE_TEXT=$(echo "$JSON" | node -e "
const chunks=[];
process.stdin.on('data',c=>chunks.push(c));
process.stdin.on('end',()=>{
  const d=JSON.parse(chunks.join(''));
  const item=d.result.content.find(x=>x.type==='resource');
  if(item) process.stdout.write(item.resource.text);
});
" 2>/dev/null || echo "$TOOL_RAW")

echo "  ← HTTP 200, Content-Type: text/event-stream"
echo "  ← SSE body: event: message"
echo "  ←           data: {\"jsonrpc\":\"2.0\",\"id\":3,\"result\":{\"content\":[...]}}"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  $OWNER/$REPO — $FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "$FILE_TEXT"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  ✓  Done. Session $SESSION used across all 3 requests."
