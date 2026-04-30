# GitHub MCP Workspace

Written by `Babak EA`

This repository is a working integration workspace around the official GitHub MCP server, plus a modern LangGraph-based chat agent and a Streamlit web UI.

It gives you three main things:

1. A local or containerized GitHub MCP HTTP server on port `9090`
2. A LangGraph repository expert agent that can inspect repositories through MCP
3. A ChatGPT-style Streamlit UI with agent modes, progress streaming, report generation, and optional login protection

## What This Repository Can Do

- Run the official GitHub MCP server over HTTP
- Let agents call GitHub tools through MCP JSON-RPC
- Support GitHub Enterprise through environment configuration
- Parse repository URLs from either `github.com` or an enterprise Git web host
- Use a read-only repository expert agent for repository Q and A
- Generate deep repository reports in `md`, `text`, or `json`
- Expose a browser chat UI for repository analysis
- Support multiple agent modes such as:
  - `Chat`
  - `Deep Repo Report`
  - `Code Search Expert`
  - `Issue and PR Analyst`
- Stream live agent progress in the UI while MCP tools and LLM calls run
- Optionally protect the UI with app-level login using `UI_USERNAME` and `UI_PASSWORD`

## Repository Layout

- `github-mcp-server/`: upstream GitHub MCP server source used for reference and exploration
- `git-mcp-bridge/`: the clean wrapper project intended for publishing or deployment
- `examples/`: agent and UI examples used in the workspace root flow
- `.vscode/mcp.json`: local MCP client configuration for IDE agent usage
- `Dockerfile`, `docker-compose.yml`, `run.sh`: root-level server startup assets

The most polished integration artifacts live under `git-mcp-bridge/`.

## Core Architecture

The runtime model is:

1. Docker builds or runs the official GitHub MCP server
2. The MCP server exposes HTTP on `http://127.0.0.1:9090`
3. The LangGraph agent connects to that MCP endpoint and sends `initialize` and `tools/call`
4. The Streamlit UI sends user requests into the LangGraph runtime
5. The LiteLLM endpoint is used for planning, answers, and report generation
6. Bearer authentication is sent by the agent client on every MCP request

This is intentionally safer than storing one shared Git token inside the server for every user.

## Main Features In The Agent Layer

- Read-only GitHub repository analysis over MCP
- Enterprise-aware repository URL parsing with `GIT_WEB_BASE_URL`
- Tool planning through LiteLLM
- Structured progress events for UI streaming
- Report persistence under `examples/reports/`
- Report output formats:
  - markdown
  - plain text
  - JSON

## Run The MCP Server

### Docker Compose

```bash
docker compose up --build
```

### Docker Run

```bash
docker build -t git-mcp-bridge:latest .
docker run --rm -p 9090:9090 --env-file .env git-mcp-bridge:latest
```

### Health Check

```bash
curl http://127.0.0.1:9090/.well-known/oauth-protected-resource
```

## Run The Chat UI

The preferred launcher is inside `git-mcp-bridge/`:

```bash
cd git-mcp-bridge
./run_ui.sh
```

That starts the Streamlit UI, usually at:

```text
http://127.0.0.1:8501
```

## Smoke Testing

There is a dedicated smoke test script in `git-mcp-bridge/`:

```bash
cd git-mcp-bridge
./smoke_test.sh
```

It checks:

- shell script syntax
- Python syntax
- Python imports
- Docker Compose rendering
- temporary Streamlit startup and health response

## Enterprise Configuration

For GitHub Enterprise or any private Git host, there are two separate concerns:

### MCP Server API Host

Use one of these:

```env
GITHUB_HOST=https://ghe.example.com
```

or legacy:

```env
GITHUB_API_URL=https://ghe.example.com/api/v3
```

### Agent Repository URL Parsing

Use:

```env
GIT_WEB_BASE_URL=https://ghe.example.com
```

This is what lets enterprise users paste internal repository links without changing the code.

## Authentication Model

- The MCP client sends `Authorization: Bearer <token>` on every MCP HTTP request
- That includes `initialize` and each `tools/call`
- The agent does not create a separate Git session token
- Effective token lifetime is the lifetime of the bearer token the user provides
- The optional Streamlit login is separate and only protects the web UI

## IDE Connection

The workspace includes `.vscode/mcp.json` for local agent use.

The MCP server endpoint is:

```text
http://127.0.0.1:9090
```

When prompted, provide a GitHub or enterprise bearer token with the repository access you need.

## Examples

Simple Python MCP client example:

```bash
python examples/simple_repo_reader_agent.py --owner github --repo github-mcp-server --path README.md --token YOUR_TOKEN
```

LangGraph and Streamlit examples live under:

```text
git-mcp-bridge/examples/
```

## Where To Look Next

- `git-mcp-bridge/README.md`: deployment-oriented wrapper documentation
- `git-mcp-bridge/examples/README.md`: LangGraph agent and Streamlit UI details
- `git-mcp-bridge/examples/agent_architecture.md`: Mermaid diagram and detailed agent flow
