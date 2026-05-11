# GitHub MCP Server — HTTP & SSE Mode

This fork of the [GitHub MCP Server](https://github.com/github/github-mcp-server) extends the original STDIO-only server with **HTTP** and **SSE** transports, running on four dedicated ports so that both public GitHub and a private GitHub Enterprise instance can be served simultaneously.

---

## Architecture Overview

| Mode | GitHub Target | Port | Transport Spec |
|------|--------------|------|----------------|
| `http` | Public (`github.com`) | **9051** | MCP Streamable HTTP (recommended) |
| `sse`  | Public (`github.com`) | **9050** | MCP Legacy SSE |
| `http` | Private (your GHE URL) | **9053** | MCP Streamable HTTP (recommended) |
| `sse`  | Private (your GHE URL) | **9052** | MCP Legacy SSE |

### HTTP vs SSE — What's the Difference?

Both transports carry the same JSON-RPC messages, but they differ in connection model:

| | HTTP mode (Streamable HTTP) | SSE mode (Legacy SSE) |
|-|----------------------------|-----------------------|
| **Port** | 9051 / 9053 | 9050 / 9052 |
| **How it works** | Every request is a `POST /mcp`. Responses stream back as SSE events *inside* the HTTP response body. | Client opens a persistent `GET /events` connection to receive server pushes; client POSTs requests separately. |
| **Connection** | Stateless HTTP requests, tied by session ID header | Long-lived SSE connection + separate POST channel |
| **`notifications/initialized` response** | `HTTP 202 Accepted` — empty body | `HTTP 202 Accepted` |
| **Tool call response** | `HTTP 200`, `Content-Type: text/event-stream`, body = SSE events | SSE event pushed on the open GET connection |
| **Recommended?** | ✅ Yes — MCP spec 2024-11-05 standard | ⚠️ Legacy — kept for older clients |

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Go 1.22+ | `go version` to verify |
| GitHub Personal Access Token | Needs `repo`, `read:org` scopes |
| Built binary | Run `go build ./cmd/github-mcp-server` |

---

## Build

```bash
cd f:/2026/github-mcp-server
go build -o github-mcp-server ./cmd/github-mcp-server
```

---

## Token Configuration

The server resolves your GitHub token in this priority order:

1. `$Github_Token` environment variable
2. `$GITHUB_PERSONAL_ACCESS_TOKEN` environment variable
3. `.env` file in the project root

`.env` format:
```env
Github_Token=ghp_your_token_here
```

---

## Start All Four Servers

```bash
bash run_all_mcp_servers.sh
```

To override the private GitHub Enterprise URL:

```bash
PRIVATE_GITHUB_HOST=https://github.mycompany.com bash run_all_mcp_servers.sh
```

Expected startup output:
```
=== Starting GitHub MCP Servers ===
  Public  HTTP  → port 9051 (https://github.com)
  Public  SSE   → port 9050 (https://github.com)
  Private HTTP  → port 9053 (https://github.mycompany.com)
  Private SSE   → port 9052 (https://github.mycompany.com)

All servers started. Press Ctrl+C to stop all.
```

Verify with:
```bash
netstat -ano | grep -E '905[0-3]'
```

---

## MCP Handshake — Step by Step

Both transports share the same 3-step handshake. Here is what actually flows over the wire on the **HTTP transport** (port 9051):

### Step 1 — `initialize`

```
POST /mcp  HTTP/1.1
Authorization: Bearer <token>
Content-Type: application/json
Accept: application/json, text/event-stream

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": { "name": "my-client", "version": "1.0" }
  }
}
```

Server responds — `HTTP 200`, `Content-Type: text/event-stream`:

```
Mcp-Session-Id: FGJK6NEZAHKEZEQXTVZUAIY4AS   ← save this!

event: message
data: {"jsonrpc":"2.0","id":1,"result":{
  "protocolVersion": "2024-11-05",
  "capabilities": { "tools": {}, "resources": {}, "prompts": {} },
  "serverInfo": { "name": "github-mcp-server", "version": "..." }
}}
```

> The response body is **SSE format** even on the HTTP transport port.
> The `Mcp-Session-Id` header must be sent on every subsequent request.

---

### Step 2 — `notifications/initialized`

This is a JSON-RPC **notification** (no `"id"` field). It tells the server the client has processed the capabilities and is ready to send tool calls.

```
POST /mcp  HTTP/1.1
Authorization: Bearer <token>
Content-Type: application/json
mcp-session-id: FGJK6NEZAHKEZEQXTVZUAIY4AS

{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}
```

Server responds — `HTTP 202 Accepted`, empty body:

```
HTTP/1.1 202 Accepted
Content-Length: 0
                        ← no body, just acknowledgement
```

---

### Step 3 — `tools/call`

```
POST /mcp  HTTP/1.1
Authorization: Bearer <token>
Content-Type: application/json
mcp-session-id: FGJK6NEZAHKEZEQXTVZUAIY4AS

{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "get_file_contents",
    "arguments": { "owner": "BabakEA", "repo": "WireGuard-VPN-Server", "path": "README.md" }
  }
}
```

Server responds — `HTTP 200`, `Content-Type: text/event-stream`:

```
event: message
data: {"jsonrpc":"2.0","id":3,"result":{
  "content": [
    {"type":"text",     "text":"successfully downloaded text file (SHA: …)"},
    {"type":"resource", "resource": {
      "uri":      "repo://BabakEA/WireGuard-VPN-Server/sha/…/contents/README.md",
      "mimeType": "text/plain; charset=utf-8",
      "text":     "# 🔒 WireGuard VPN Server…"   ← actual file content
    }}
  ]
}}
```

---

### Full Handshake Diagram

```
Client                                    Server (port 9051)
  │                                           │
  │── POST /mcp  (initialize) ───────────────▶│
  │◀── HTTP 200 + Mcp-Session-Id header ──────│
  │    body: event: message / data: {...}      │
  │                                           │
  │── POST /mcp  (notifications/initialized) ▶│
  │◀── HTTP 202 Accepted  (empty body) ───────│
  │                                           │
  │── POST /mcp  (tools/call) ───────────────▶│
  │◀── HTTP 200 + SSE body ───────────────────│
  │    event: message                         │
  │    data: {"result":{"content":[...]}}      │
  │                                           │
  │  (repeat Step 3 for more tool calls)      │
```

Key header required on every request after Step 1:
```
mcp-session-id: <value-from-Mcp-Session-Id-response-header>
```

---

## Manual curl Commands

### Step 1 — Initialize session

```bash
SESSION=$(curl -si -X POST http://localhost:9051/mcp \
  -H "Authorization: Bearer $Github_Token" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": { "name": "curl", "version": "1.0" }
    }
  }' 2>/dev/null | grep -i "^Mcp-Session-Id:" | awk '{print $2}' | tr -d '\r')

echo "Session: $SESSION"
```

### Step 2 — Send initialized notification

```bash
curl -s -X POST http://localhost:9051/mcp \
  -H "Authorization: Bearer $Github_Token" \
  -H "Content-Type: application/json" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
```

### Step 3 — Call a tool (e.g. fetch a file)

```bash
curl -s -X POST http://localhost:9051/mcp \
  -H "Authorization: Bearer $Github_Token" \
  -H "Content-Type: application/json" \
  -H "mcp-session-id: $SESSION" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "get_file_contents",
      "arguments": {
        "owner": "BabakEA",
        "repo": "WireGuard-VPN-Server",
        "path": "README.md"
      }
    }
  }'
```

---

## MCP_test.sh — SSE/HTTP Quick Test Script

[MCP_test.sh](MCP_test.sh) automates the full 3-step handshake and prints the file contents.

### Usage

```bash
# Default: fetch README.md from BabakEA/WireGuard-VPN-Server via port 9051
bash MCP_test.sh

# Custom repo and file
OWNER=myorg REPO=myrepo FILE=src/main.go bash MCP_test.sh

# Target the private GitHub Enterprise server (port 9053)
MCP_PORT=9053 OWNER=myorg REPO=private-repo bash MCP_test.sh
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_HOST` | `http://localhost` | Server base URL |
| `MCP_PORT` | `9051` | Server port |
| `OWNER` | `BabakEA` | GitHub repo owner |
| `REPO` | `WireGuard-VPN-Server` | GitHub repo name |
| `FILE` | `README.md` | Path to fetch |
| `Github_Token` | _(from env / .env)_ | GitHub PAT |

### Example Output

```
=== MCP Test ===
  Target  : http://localhost:9051/mcp
  Repo    : BabakEA/WireGuard-VPN-Server
  File    : README.md

[1/3] Initializing MCP session...
  Session : NY6VZ5OYM5RJ33TVDPC54FYULJ
[2/3] Sending initialized notification...
[3/3] Fetching README.md from BabakEA/WireGuard-VPN-Server...

─────────────────────────────────────────────────────────────────────────
# 🔒 WireGuard VPN Server for Windows
...
─────────────────────────────────────────────────────────────────────────

Done.
```

---

## HTTP_test.sh — Verbose HTTP Transport Test Script

[HTTP_test.sh](HTTP_test.sh) does the same thing as `MCP_test.sh` but prints every HTTP status code, header, and response shape at each step — so you can see exactly what the Streamable HTTP transport is doing.

### Usage

```bash
# Default: port 9051, README.md from BabakEA/WireGuard-VPN-Server
bash HTTP_test.sh

# Custom repo / file
OWNER=myorg REPO=myrepo FILE=src/main.go bash HTTP_test.sh

# Private server (port 9053)
MCP_PORT=9053 bash HTTP_test.sh
```

### What It Prints at Each Step

**Step 1 — initialize:**
```
← HTTP 200
← Content-Type: text/event-stream  ← SSE streaming format
← Mcp-Session-Id: FGJK6NEZAHKEZEQXTVZUAIY4AS
← Server: github-mcp-server  (protocol 2024-11-05)
```

**Step 2 — notifications/initialized:**
```
← HTTP 202  ← no body (acknowledged, no response)
← Content-Length: 0
```

**Step 3 — tools/call:**
```
← HTTP 200, Content-Type: text/event-stream
← SSE body: event: message
←           data: {"jsonrpc":"2.0","id":3,"result":{"content":[...]}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  BabakEA/WireGuard-VPN-Server — README.md
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🔒 WireGuard VPN Server for Windows
...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓  Done. Session FGJK6NEZAHKEZEQXTVZUAIY4AS used across all 3 requests.
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Failed to obtain MCP session ID` | Server not running — run `bash run_all_mcp_servers.sh` first |
| `400 Bad Request` after initialize | `notifications/initialized` was not sent before the tool call |
| `host must have a scheme` | Use full URL with `https://` (e.g. `https://github.com`, not `github.com`) |
| Empty response / grep returns nothing | Response is SSE format — do not pipe through `python -m json.tool` |
| Port collision (SSE uses HTTP port) | Each command reads its port via `cmd.Flags().GetInt("port")` — rebuild if needed |

---

## File Reference

| File | Purpose |
|------|---------|
| `cmd/github-mcp-server/main.go` | Cobra CLI — defines `stdio`, `http`, `sse` subcommands |
| `pkg/http/server.go` | `RunHTTPServer` + `RunSSEServer` implementations |
| `internal/ghmcp/server.go` | `NewStdioMCPServer`, GitHub client creation |
| `run_all_mcp_servers.sh` | Launches all 4 server instances |
| `MCP_test.sh` | Quick end-to-end test (clean output) |
| `HTTP_test.sh` | Verbose HTTP transport test (shows every header + status) |

## Docker

[Dockerfile.multi](Dockerfile.multi) builds a single image that starts **all four MCP server instances** automatically when the container starts.

### Architecture of the Docker Image

| Stage | Base Image | Purpose |
|-------|-----------|---------|
| `ui-build` | `node:20-alpine` | Compile the React/Vite UI assets |
| `build` | `golang:1.24-alpine` | Compile the Go server binary |
| runtime | `alpine:3.20` | Run all 4 server processes via shell entrypoint |

> **Why Alpine and not distroless?**
> The original Dockerfile used `gcr.io/distroless/base-debian12` which has no shell.
> Our startup needs `/bin/sh` to launch 4 background processes and handle signals, so we use Alpine instead (~15 MB image).

### Port Mapping

| Container Port | Transport | GitHub Target | Description |
|---------------|---------|--------|-------------|
| **9051** | HTTP | Public `github.com` | MCP Streamable HTTP ← recommended |
| **9050** | SSE  | Public `github.com` | MCP Legacy SSE |
| **9053** | HTTP | Private GHE URL | MCP Streamable HTTP |
| **9052** | SSE  | Private GHE URL | MCP Legacy SSE |

### Build

```bash
# Standard build
docker build -f Dockerfile.multi -t github-mcp-server:latest .

# With a version tag
docker build -f Dockerfile.multi --build-arg VERSION=1.0.0 -t github-mcp-server:1.0.0 .
```

### Run — Public GitHub only (ports 9050 + 9051)

```bash
docker run -d \
  --name github-mcp \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=ghp_your_token_here \
  -p 9050:9050 \
  -p 9051:9051 \
  github-mcp-server:latest
```

### Run — Public + Private GitHub (all 4 ports)

```bash
docker run -d \
  --name github-mcp \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=ghp_your_token_here \
  -e PRIVATE_GITHUB_HOST=https://github.mycompany.com \
  -p 9050:9050 \
  -p 9051:9051 \
  -p 9052:9052 \
  -p 9053:9053 \
  github-mcp-server:latest
```

### Run — Using a `.env` file

```bash
# .env contents:
# GITHUB_PERSONAL_ACCESS_TOKEN=ghp_your_token_here
# PRIVATE_GITHUB_HOST=https://github.mycompany.com

docker run -d \
  --name github-mcp \
  --env-file .env \
  -p 9050:9050 \
  -p 9051:9051 \
  -p 9052:9052 \
  -p 9053:9053 \
  github-mcp-server:latest
```

### Docker Compose

```yaml
services:
  github-mcp:
    build:
      context: .
      dockerfile: Dockerfile.multi
    env_file: .env
    ports:
      - "9050:9050"   # Public  SSE
      - "9051:9051"   # Public  HTTP  ← use this for MCP clients
      - "9052:9052"   # Private SSE
      - "9053:9053"   # Private HTTP
    restart: unless-stopped
```

```bash
docker compose up -d
```

### Startup Output

```
╔══════════════════════════════════════════════════════════╗
║          GitHub MCP Server — Docker Container            ║
╚══════════════════════════════════════════════════════════╝

  Public  HTTP  → port 9051  (https://github.com)
  Public  SSE   → port 9050  (https://github.com)
  Private HTTP  → port 9053  (https://github.mycompany.com)
  Private SSE   → port 9052  (https://github.mycompany.com)

[INFO] All servers started. Container is ready.
[PUB-HTTP] time=... level=INFO msg="server listening" addr=:9051
[PUB-SSE ] time=... level=INFO msg="server listening" addr=:9050
[PVT-HTTP] time=... level=INFO msg="server listening" addr=:9053
[PVT-SSE ] time=... level=INFO msg="server listening" addr=:9052
```

### Test the Running Container

```bash
# Once running, use HTTP_test.sh (it targets localhost:9051 by default)
bash HTTP_test.sh

# Or manually:
SESSION=$(curl -si -X POST http://localhost:9051/mcp \
  -H "Authorization: Bearer $GITHUB_PERSONAL_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
  | grep -i "^Mcp-Session-Id:" | awk '{print $2}' | tr -d '\r')

curl -s -X POST http://localhost:9051/mcp \
  -H "Authorization: Bearer $GITHUB_PERSONAL_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'

curl -s -X POST http://localhost:9051/mcp \
  -H "Authorization: Bearer $GITHUB_PERSONAL_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_file_contents","arguments":{"owner":"BabakEA","repo":"WireGuard-VPN-Server","path":"README.md"}}}'
```

### Graceful Shutdown

```bash
docker stop github-mcp     # sends SIGTERM → entrypoint cleanly stops all 4 servers
docker rm github-mcp
```

### Troubleshooting Docker

| Symptom | Fix |
|---------|-----|
| `No GitHub token provided` | Add `-e GITHUB_PERSONAL_ACCESS_TOKEN=...` or `--env-file .env` |
| Private ports not reachable | Must pass `-p 9052:9052 -p 9053:9053` AND set `PRIVATE_GITHUB_HOST` |
| Container exits immediately | Run `docker logs github-mcp` — usually a missing token |
| `host must have a scheme` | `PRIVATE_GITHUB_HOST` must start with `https://` |

---

## Docker

[Dockerfile.multi](Dockerfile.multi) builds a single image that starts **all four MCP server instances** automatically when the container starts.

### Architecture of the Docker Image

| Stage | Base Image | Purpose |
|-------|-----------|---------|
| `ui-build` | `node:20-alpine` | Compile the React/Vite UI assets |
| `build` | `golang:1.24-alpine` | Compile the Go server binary |
| runtime | `alpine:3.20` | Run all 4 server processes via shell entrypoint |

> **Why Alpine and not distroless?**
> The original Dockerfile used `gcr.io/distroless/base-debian12` which has no shell.
> Our startup needs `/bin/sh` to launch 4 background processes and handle signals gracefully, so we use Alpine instead (~15 MB image).

### Port Mapping

| Container Port | Transport | GitHub Target | Description |
|---------------|-----------|---------------|-------------|
| **9051** | HTTP | Public `github.com` | MCP Streamable HTTP ← recommended |
| **9050** | SSE  | Public `github.com` | MCP Legacy SSE |
| **9053** | HTTP | Private GHE URL | MCP Streamable HTTP |
| **9052** | SSE  | Private GHE URL | MCP Legacy SSE |

### Build

```bash
# Standard build
docker build -f Dockerfile.multi -t github-mcp-server:latest .

# With a version tag
docker build -f Dockerfile.multi --build-arg VERSION=1.0.0 -t github-mcp-server:1.0.0 .
```

### Run — Public GitHub only (ports 9050 + 9051)

```bash
docker run -d \
  --name github-mcp \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=ghp_your_token_here \
  -p 9050:9050 \
  -p 9051:9051 \
  github-mcp-server:latest
```

### Run — Public + Private GitHub (all 4 ports)

```bash
docker run -d \
  --name github-mcp \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=ghp_your_token_here \
  -e PRIVATE_GITHUB_HOST=https://github.mycompany.com \
  -p 9050:9050 \
  -p 9051:9051 \
  -p 9052:9052 \
  -p 9053:9053 \
  github-mcp-server:latest
```

### Run — Using a `.env` File

```bash
# .env contents:
# GITHUB_PERSONAL_ACCESS_TOKEN=ghp_your_token_here
# PRIVATE_GITHUB_HOST=https://github.mycompany.com

docker run -d \
  --name github-mcp \
  --env-file .env \
  -p 9050:9050 \
  -p 9051:9051 \
  -p 9052:9052 \
  -p 9053:9053 \
  github-mcp-server:latest
```

### Docker Compose

```yaml
services:
  github-mcp:
    build:
      context: .
      dockerfile: Dockerfile.multi
    env_file: .env
    ports:
      - "9050:9050"   # Public  SSE
      - "9051:9051"   # Public  HTTP  <- use this for MCP clients
      - "9052:9052"   # Private SSE
      - "9053:9053"   # Private HTTP
    restart: unless-stopped
```

```bash
docker compose up -d
```

### Startup Output

When the container starts, all four servers launch simultaneously:

```
╔══════════════════════════════════════════════════════════╗
║          GitHub MCP Server — Docker Container            ║
╚══════════════════════════════════════════════════════════╝

  Public  HTTP  -> port 9051  (https://github.com)
  Public  SSE   -> port 9050  (https://github.com)
  Private HTTP  -> port 9053  (https://github.mycompany.com)
  Private SSE   -> port 9052  (https://github.mycompany.com)

[INFO] All servers started. Container is ready.
[PUB-HTTP] time=... level=INFO msg="server listening" addr=:9051
[PUB-SSE ] time=... level=INFO msg="server listening" addr=:9050
[PVT-HTTP] time=... level=INFO msg="server listening" addr=:9053
[PVT-SSE ] time=... level=INFO msg="server listening" addr=:9052
```

### Test the Running Container

```bash
# Use the verbose HTTP test script (targets localhost:9051 by default)
bash HTTP_test.sh

# Or run the quick test:
bash MCP_test.sh
```

### Graceful Shutdown

```bash
docker stop github-mcp     # sends SIGTERM -> entrypoint cleanly stops all 4 servers
docker rm github-mcp
```

### Troubleshooting Docker

| Symptom | Fix |
|---------|-----|
| `No GitHub token provided` | Add `-e GITHUB_PERSONAL_ACCESS_TOKEN=...` or `--env-file .env` |
| Private ports not reachable | Pass `-p 9052:9052 -p 9053:9053` AND set `PRIVATE_GITHUB_HOST` |
| Container exits immediately | Run `docker logs github-mcp` — usually a missing token |
| `host must have a scheme` | `PRIVATE_GITHUB_HOST` must start with `https://` |

---

## File Reference

| File | Purpose |
|------|---------|
| `cmd/github-mcp-server/main.go` | Cobra CLI — `stdio`, `http`, `sse` subcommands |
| `pkg/http/server.go` | `RunHTTPServer` + `RunSSEServer` implementations |
| `internal/ghmcp/server.go` | `NewStdioMCPServer`, GitHub client creation |
| `run_all_mcp_servers.sh` | Start all 4 servers locally (no Docker) |
| `docker-entrypoint.sh` | Container startup — launches all 4 servers with signal handling |
| `Dockerfile.multi` | Multi-stage Docker build (UI + Go binary + Alpine runtime) |
| `MCP_test.sh` | Quick end-to-end test (clean output) |
| `HTTP_test.sh` | Verbose HTTP transport test (shows every header + status code) |


## Production — Docker Hub

The pre-built image is published at **[hub.docker.com/r/647326/github-mcp-server](https://hub.docker.com/r/647326/github-mcp-server)**.

### Pull

```bash
docker pull 647326/github-mcp-server:latest
```

### Run — Public GitHub only (ports 9050 + 9051)

```bash
docker run -d \
  --name github-mcp \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=ghp_your_token \
  -p 9050:9050 \
  -p 9051:9051 \
  647326/github-mcp-server:latest
```

### Run — Public + Private GitHub Enterprise (all 4 ports)

Use `PRIVATE_GITHUB_TOKEN` when your enterprise instance uses a different PAT than your public GitHub token. If omitted, the public token is reused for the private servers.

```bash
docker run -d \
  --name github-mcp \
  -e GITHUB_PERSONAL_ACCESS_TOKEN=ghp_your_public_github_token \
  -e PRIVATE_GITHUB_HOST=https://github.mycompany.com \
  -e PRIVATE_GITHUB_TOKEN=ghp_your_enterprise_token \
  -p 9050:9050 -p 9051:9051 \
  -p 9052:9052 -p 9053:9053 \
  647326/github-mcp-server:latest
```

### Environment Variable Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `GITHUB_PERSONAL_ACCESS_TOKEN` | ✅ Yes | PAT for public `github.com` |
| `PRIVATE_GITHUB_HOST` | Optional | Full URL of your GHE instance, e.g. `https://github.mycompany.com` |
| `PRIVATE_GITHUB_TOKEN` | Optional | PAT for the private GHE instance — falls back to `GITHUB_PERSONAL_ACCESS_TOKEN` if not set |
