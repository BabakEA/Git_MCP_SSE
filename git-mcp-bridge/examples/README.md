LangGraph GitHub Expert Viewer Agent
====================================

This example is a real LangGraph-based AI agent that uses your local GitHub MCP HTTP server as a read-only repository viewer and search layer.

What it does

- Accepts a user message containing a GitHub repo URL or `owner/repo` plus a question.
- Uses a LangGraph workflow to resolve the repository, read bootstrap context, plan tool usage, execute read-only MCP tools, and produce an answer.
- Switches into report mode for bigger requests such as full repository explanations, architecture analysis, or comprehensive summaries.
- Writes a report to `examples/reports/` when the user asks for a deep analysis.
- Stays read-only on the client side by allowing only viewer and search tools.
- Supports selectable agent modes in the Streamlit UI: `Chat`, `Deep Repo Report`, `Code Search Expert`, and `Issue and PR Analyst`.
- Collects bearer tokens per tool backend in the sidebar so the same chat UI can grow beyond GitHub MCP later.
- Streams agent progress in the Streamlit chat while the graph resolves the repo, plans tool calls, runs MCP tools, and drafts the answer.
- Lets the user choose report output as `md`, `text`, or `json`.

Author

- `Babak.ea`

Architecture

- `resolve_repo`: extracts the repo URL or falls back to the previous chat turn.
- `bootstrap_context`: reads the root directory and `README.md` through MCP.
- `plan_actions`: asks your LiteLLM endpoint to choose the right read-only MCP tools.
- `execute_tools`: runs the chosen MCP tools with the real MCP JSON-RPC protocol.
- `write_answer`: uses the LLM again to answer briefly or draft a full markdown report.
- `persist_report`: saves the report to disk when needed.

Files

- `examples/langgraph_mcp_agent.py`: the LangGraph agent.
- `examples/streamlit_chat_app.py`: a ChatGPT-style web chat UI over the same agent runtime.
- `examples/requirements-langgraph-agent.txt`: Python dependencies for this example.
- `examples/simple_repo_reader_agent.py`: the smaller non-agent MCP example.

Prerequisites

1. Your local GitHub MCP server is running at `http://127.0.0.1:9090`.
2. Your bearer token has read access to the repositories you want to inspect.
3. Your LiteLLM-compatible endpoint is reachable at `http://localhost:8000/complete`.

Install

```bash
pip install -r git-mcp-bridge/examples/requirements-langgraph-agent.txt
```

Configuration

Use environment variables instead of hardcoding secrets in source files.

```bash
export MCP_URL=http://127.0.0.1:9090
export MCP_AUTH_TOKEN=ghp_replace_me
export LITELLM_COMPLETE_URL=http://localhost:8000/complete
export LITELLM_MODEL=gpt-4.1
export LITELLM_MAX_SECONDS=25
export GIT_WEB_BASE_URL=https://github.com
```

If you are on Windows PowerShell:

```powershell
$env:MCP_URL = "http://127.0.0.1:9090"
$env:MCP_AUTH_TOKEN = "ghp_replace_me"
$env:LITELLM_COMPLETE_URL = "http://localhost:8000/complete"
$env:LITELLM_MODEL = "gpt-4.1"
$env:LITELLM_MAX_SECONDS = "25"
$env:GIT_WEB_BASE_URL = "https://github.com"
```

Enterprise Git host support

The agent no longer assumes `https://github.com`.

- Set `GIT_WEB_BASE_URL` to the web host your users paste repository links from.
- Examples: `https://github.com`, `https://ghe.example.com`, `https://code.rbc.example`
- This affects how the agent parses repository URLs from chat messages.
- MCP tool calls still go through your configured MCP server URL and do not need the Git web URL repeated in every tool call.

Example for an enterprise instance:

```bash
export GIT_WEB_BASE_URL=https://ghe.example.com
export MCP_URL=http://127.0.0.1:9090
./run_ui.sh
```

Quick usage

Single-turn question:

```bash
python git-mcp-bridge/examples/langgraph_mcp_agent.py \
	--message "https://github.com/github/github-mcp-server How does this repo expose MCP tools over HTTP?"
```

Interactive chat:

```bash
python git-mcp-bridge/examples/langgraph_mcp_agent.py --interactive
```

Streamlit web chat:

```bash
streamlit run git-mcp-bridge/examples/streamlit_chat_app.py
```

This gives you a local browser URL similar to a ChatGPT-style chat app, usually something like `http://localhost:8501`.

Smoke test:

```bash
cd git-mcp-bridge
./smoke_test.sh
```

Optional smoke-test controls:

- `PYTHON_BIN` to choose the Python executable
- `RUN_UI_SMOKE=0` to skip starting Streamlit
- `RUN_COMPOSE_SMOKE=0` to skip Docker Compose validation
- `SMOKE_PORT` to change the temporary Streamlit smoke-test port

Hosted login protection:

If both `UI_USERNAME` and `UI_PASSWORD` are set, the Streamlit UI requires an app-level login before the chat becomes available.

```bash
export UI_USERNAME=admin
export UI_PASSWORD=change-me
./run_ui.sh
```

Shell launcher:

```bash
cd git-mcp-bridge
./run_ui.sh
```

Optional environment overrides:

- `PYTHON_BIN` to choose a specific Python executable
- `STREAMLIT_HOST` to change the bind address
- `STREAMLIT_PORT` to change the port

Agent modes in the web UI

- `Chat`: balanced repository Q and A
- `Deep Repo Report`: broader inspection with markdown report output
- `Code Search Expert`: stronger bias toward code search and file-level answers
- `Issue and PR Analyst`: stronger bias toward issues, pull requests, reviews, and comments

Report output formats

- `md`: markdown report with headings
- `text`: plain text report
- `json`: structured JSON report for downstream processing

Tool backend tokens

The sidebar is organized by backend. Right now the active backend is `GitHub MCP`, and it asks for that backend's bearer token.

That means the UI is already structured for future additions like other MCP servers or non-MCP APIs without redesigning the chat screen.

Bearer token behavior

- The GitHub bearer token is attached on every MCP HTTP request made by the agent client.
- That includes `initialize` and every `tools/call` request.
- The agent does not mint or refresh a separate session token for GitHub tools.
- Effective lifetime is the lifetime of the token you provide.
- The optional Streamlit UI login is separate from the GitHub bearer token and only protects the web app itself.

Architecture diagram

- See `examples/agent_architecture.md` for a Mermaid diagram and detailed node-by-node inputs and outputs.

Containerized UI

You can run both the MCP server and the hosted chat UI through Docker Compose:

```bash
docker compose up --build
```

Services:

- MCP server: `http://127.0.0.1:9090`
- Streamlit chat UI: `http://127.0.0.1:8501`

Inside Docker, the UI talks to the MCP server using `UI_MCP_URL=http://git-mcp-bridge:9090` by default.

Interactive examples:

- `https://github.com/github/github-mcp-server explain how the HTTP transport works`
- `https://github.com/github/github-mcp-server give me a comprehensive architecture report`
- `github/github-mcp-server what files define the repository tools?`
- `github/github-mcp-server summarize the latest release and recent commits`

Verbose mode

Use `--verbose` to print the planner output and the MCP evidence collected during the turn.

```bash
python git-mcp-bridge/examples/langgraph_mcp_agent.py \
	--interactive \
	--verbose
```

Read-only guardrails

This agent only permits these MCP tool families:

- repository reading
- code search
- commit, branch, tag, and release inspection
- issue and pull request reading
- discussion reading

It rejects write tools even if the model asks for them. For stronger enforcement, also run the server with read-only mode enabled.

Extending the chat agent later

This layout is set up so you can grow it without replacing the UI:

- add new planner branches in `langgraph_mcp_agent.py`
- add specialized sub-agents for release analysis, issue triage, code walkthroughs, or documentation synthesis
- expose new toggles or agent modes in `streamlit_chat_app.py`
- keep the Streamlit front end as the stable chat URL while the backend graph becomes more capable

Notes

- The planner and summarizer both use your LiteLLM endpoint.
- If the planner returns invalid JSON, the agent falls back to a deterministic read-only plan.
- When the user asks for a large analysis, the markdown report is saved automatically under `examples/reports/`.
- The agent answers only from MCP evidence it collected. If the evidence is incomplete, it should say so.
