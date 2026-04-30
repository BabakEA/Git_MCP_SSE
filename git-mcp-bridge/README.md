# git-mcp-bridge

This folder is the clean version you can push to your own GitHub repository.

It contains only your integration layer and does not vendor the original `github-mcp-server` source tree. Instead, Docker fetches the upstream repository during the build.

That means you do not need to commit the original MCP server files into this wrapper repository unless you explicitly want a vendored copy or a git submodule.

## Included Files

- `Dockerfile`: builds the official GitHub MCP server from upstream and runs it on port `9090`
- `Dockerfile.ui`: builds the Streamlit chat UI image on port `8501`
- `docker-entrypoint.sh`: maps your local env vars to the upstream server flags
- `docker-compose.yml`: local development runner
- `.env.example`: example configuration
- `.gitignore`: prevents `.env` and local cache files from being committed
- `.vscode/mcp.json`: local MCP client configuration for agent mode
- `examples/simple_repo_reader_agent.py`: minimal Python client that reads repository contents through MCP

## Run It

1. Copy `.env.example` to `.env`
2. Start the server:

```bash
docker compose up --build
```

3. Connect your MCP client or IDE to:

```text
http://127.0.0.1:9090
```

4. Send a bearer token from the client side.

If you also want the hosted chat UI, start the full stack and open:

```text
http://127.0.0.1:8501
```

## How This Model Works

The server process is the official GitHub MCP server in HTTP mode.

Source of the MCP server in this clean folder:

1. `Dockerfile` clones `https://github.com/github/github-mcp-server.git`
2. It builds the `github-mcp-server` binary inside the image
3. The final container runs that binary with `http --port 9090`

So the MCP server is not missing. It is fetched and built as part of the Docker image build.

Request flow:

1. Your agent sends `initialize` to `http://127.0.0.1:9090/`
2. The agent then sends `tools/call`
3. The GitHub MCP server executes the selected tool
4. The result is returned as an MCP JSON-RPC response

The sample agent uses `get_file_contents` with arguments like:

```json
{
  "owner": "github",
  "repo": "github-mcp-server",
  "path": "README.md"
}
```

## GitHub Enterprise

Preferred setting:

```env
GITHUB_HOST=https://ghe.example.com
```

Legacy compatibility also works:

```env
GITHUB_API_URL=https://ghe.example.com/api/v3
```

If the chat agent needs to parse repository links from an enterprise web UI, also set:

```env
GIT_WEB_BASE_URL=https://ghe.example.com
```

The MCP server host configuration and the agent's Git web base URL should usually point at the same Git installation, but they serve different purposes:

- `GITHUB_HOST` or `GITHUB_API_URL`: used by the MCP server to talk to the Git API
- `GIT_WEB_BASE_URL`: used by the LangGraph agent and Streamlit UI to parse user-pasted repository URLs

## What The `MCP_*` Environment Variables Do

These variables do not add tools by themselves.

- `MCP_TOOLSETS`: enables a subset of the upstream toolsets
- `MCP_TOOLS`: enables specific upstream tools by exact name
- `MCP_EXCLUDE_TOOLS`: removes specific tools
- `MCP_READ_ONLY=true`: disables write operations
- `MCP_SCOPE_CHALLENGE=true`: enables scope-based auth challenges

Tool availability still comes from the upstream `github-mcp-server` binary. If you leave these values empty, the server uses its default built-in tool selection.

## How To Link Your Repo To The Original GitHub MCP Project

You have three reasonable options.

### Option 1: Build From Upstream At Docker Build Time

This folder already does that.

```env
GITHUB_MCP_REPO=https://github.com/github/github-mcp-server.git
GITHUB_MCP_REF=main
```

If you want to pin a version, set `GITHUB_MCP_REF` to a tag or commit-like branch reference.

### Option 2: Add The Original Repo As A Git Submodule

Use this if you want your repo to track upstream source explicitly:

```bash
git submodule add https://github.com/github/github-mcp-server.git vendor/github-mcp-server
git commit -m "Add github-mcp-server submodule"
```

Then change the Dockerfile to copy `vendor/github-mcp-server/` instead of cloning during build.

### Option 3: Fork The Original Repo And Add An Upstream Remote

Use this only if you plan to modify the original MCP server code itself, not just wrap it.

```bash
git remote add upstream https://github.com/github/github-mcp-server.git
git fetch upstream
```

That pattern is best when your repository is actually a fork of the original project.

## Push To Your GitHub

Inside `git-mcp-bridge/`:

```bash
git init
git add .
git commit -m "Initial git-mcp-bridge wrapper"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

## Example Agent

Run the simple client like this:

```bash
python examples/simple_repo_reader_agent.py --owner github --repo github-mcp-server --path README.md --token YOUR_TOKEN
```