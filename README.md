# GitHub MCP Bridge

This workspace runs the official GitHub MCP server from the attached `github-mcp-server` repository as a local HTTP MCP endpoint on port `9090`.

## How It Works

The runtime model is simple:

1. Docker builds the official Go server from `github-mcp-server/`.
2. The container starts `github-mcp-server http --port 9090`.
3. Your agent connects to `http://127.0.0.1:9090` as an MCP `http` server.
4. The agent sends MCP JSON-RPC requests such as `initialize`, `tools/list`, and `tools/call`.
5. Authentication is provided by the MCP client per request using `Authorization: Bearer <token>`.
6. For GitHub Enterprise, `docker-entrypoint.sh` maps legacy `GITHUB_API_URL=https://host/api/v3` to the upstream server's `GITHUB_HOST=https://host`.

This means the container is only responsible for serving the MCP endpoint. It does not keep a GitHub token internally for all users. Each connecting agent supplies its own token, which is the safer model for shared use.

## Why The Old Python Files Were Removed

The original root Python files implemented a custom stdio bridge based on an outdated assumption that the upstream server only supported stdio. The attached upstream repository already supports streamable HTTP, so those files were redundant and would have created a second, less reliable protocol layer.

## Run The Server

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

## Connect From Agent Mode

The workspace already includes `.vscode/mcp.json` for local agent use.

It points to:

```json
{
  "servers": {
    "github-local-http": {
      "type": "http",
      "url": "http://127.0.0.1:9090",
      "headers": {
        "Authorization": "Bearer ${input:github_token}"
      }
    }
  }
}
```

When the IDE prompts for the token, provide a PAT or enterprise token with repository read access.

## Simple Python Agent Example

See `examples/simple_repo_reader_agent.py`.

It does three things:

1. Sends `initialize` to the local MCP HTTP endpoint.
2. Calls the `get_file_contents` tool.
3. Prints the returned file or directory content.

Example:

```bash
python examples/simple_repo_reader_agent.py --owner github --repo github-mcp-server --path README.md --token YOUR_TOKEN
```

Or with an environment variable:

```bash
export GITHUB_TOKEN=YOUR_TOKEN
python examples/simple_repo_reader_agent.py --owner github --repo github-mcp-server --path README.md
```

## Enterprise Notes

- Preferred GHES setting: `GITHUB_HOST=https://ghe.example.com`
- Legacy compatibility: `GITHUB_API_URL=https://ghe.example.com/api/v3`
- Optional restriction flags:
  - `MCP_READ_ONLY=true`
  - `MCP_SCOPE_CHALLENGE=true`
  - `MCP_TOOLSETS=repos,issues`

## Minimal Request Flow

The example agent uses standard MCP JSON-RPC messages over HTTP:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"simple-repo-reader","version":"1.0"}}}
```

Then:

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_file_contents","arguments":{"owner":"github","repo":"github-mcp-server","path":"README.md"}}}
```

The server responds with MCP tool output that the agent can render as plain text.