from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from typing_extensions import TypedDict

try:
    from langgraph.graph import END, StateGraph
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: langgraph. Install with `pip install -r examples/requirements-langgraph-agent.txt`."
    ) from exc


READ_ONLY_TOOLS: dict[str, str] = {
    "get_file_contents": "Read a file or directory from a repository.",
    "search_code": "Search code using GitHub code search. Prefer repo:owner/repo filters.",
    "search_repositories": "Find repositories by metadata or name.",
    "list_commits": "List commits for a repository or branch.",
    "get_commit": "Get details for a specific commit.",
    "list_branches": "List branches in a repository.",
    "list_tags": "List tags in a repository.",
    "list_releases": "List releases in a repository.",
    "get_latest_release": "Get the latest release.",
    "get_release_by_tag": "Get a release by tag.",
    "list_issues": "List issues in a repository.",
    "issue_read": "Read a single issue, comments, labels, or sub-issues.",
    "search_issues": "Search issues using GitHub search syntax.",
    "list_pull_requests": "List pull requests in a repository.",
    "pull_request_read": "Read a pull request, files, diff, comments, checks, or reviews.",
    "search_pull_requests": "Search pull requests using GitHub search syntax.",
    "list_discussions": "List discussions in a repository.",
    "get_discussion": "Get a single discussion.",
    "get_discussion_comments": "Get discussion comments.",
    "list_discussion_categories": "List discussion categories.",
    "get_repository_tree": "Read the repository tree structure.",
}

REPO_SCOPED_TOOLS = {
    "get_file_contents",
    "list_commits",
    "get_commit",
    "list_branches",
    "list_tags",
    "list_releases",
    "get_latest_release",
    "get_release_by_tag",
    "list_issues",
    "issue_read",
    "list_pull_requests",
    "pull_request_read",
    "list_discussions",
    "get_discussion",
    "get_discussion_comments",
    "list_discussion_categories",
    "get_repository_tree",
}

MCP_PROTOCOL_VERSION = "2025-03-26"
DEFAULT_MCP_URL = "http://127.0.0.1:9090"
DEFAULT_LLM_URL = "http://localhost:8000/complete"
DEFAULT_MODEL = "gpt-4.1"
DEFAULT_GIT_WEB_BASE_URL = os.getenv("GIT_WEB_BASE_URL", os.getenv("GITHUB_HOST", "https://github.com"))
REPORT_FORMATS = ("md", "text", "json")

AGENT_MODES: dict[str, dict[str, str]] = {
    "chat": {
        "label": "Chat",
        "description": "General repository Q&A with balanced planning.",
        "instruction": "Prioritize direct answers with enough evidence to support the conclusion.",
    },
    "deep_report": {
        "label": "Deep Repo Report",
        "description": "Prefer broader repository inspection and a detailed markdown report.",
        "instruction": "Bias toward comprehensive repository analysis and produce a detailed report when useful.",
    },
    "code_search": {
        "label": "Code Search Expert",
        "description": "Prioritize implementation details, symbols, and file-level evidence.",
        "instruction": "Focus on code-level questions, search the repository aggressively, and cite concrete implementation areas.",
    },
    "issues_prs": {
        "label": "Issue and PR Analyst",
        "description": "Focus on issues, pull requests, comments, and review status.",
        "instruction": "Prefer issue and pull request tools when the question could be answered from collaboration history.",
    },
}


class AgentState(TypedDict, total=False):
    user_message: str
    repo_hint: str
    owner: str
    repo: str
    question: str
    agent_mode: str
    mode_instruction: str
    git_web_base_url: str
    report_format: str
    bootstrap_notes: str
    plan_text: str
    plan: dict[str, Any]
    progress_events: list[str]
    progress_callback: Any
    tool_results: list[dict[str, Any]]
    answer: str
    report_markdown: str
    report_path: str
    error: str
    session_repo_hint: str
    verbose: bool


@dataclass
class MCPHTTPClient:
    base_url: str
    token: str
    request_id: int = 0

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/") or DEFAULT_MCP_URL

    def _next_id(self) -> int:
        self.request_id += 1
        return self.request_id

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Failed to connect to MCP server: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Non-JSON MCP response: {raw}") from exc

    def initialize(self) -> dict[str, Any]:
        return self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "langgraph-github-expert-agent",
                        "version": "1.0",
                    },
                },
            }
        )

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": arguments,
                },
            }
        )


@dataclass
class LiteLLMCompleteClient:
    url: str
    model: str
    max_seconds: int

    def complete(self, prompt: str, mode: str = "ask") -> str:
        response = requests.post(
            self.url,
            headers={
                "accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "prompt": prompt,
                "mode": mode,
                "model": self.model,
                "max_seconds": self.max_seconds,
            },
            timeout=self.max_seconds + 10,
        )
        response.raise_for_status()
        payload = response.json()
        return extract_llm_text(payload)


def extract_llm_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        return "\n".join(extract_llm_text(item) for item in payload)
    if not isinstance(payload, dict):
        return json.dumps(payload, ensure_ascii=False)

    for key in ("response", "completion", "answer", "text", "content", "output", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, dict):
            nested = extract_llm_text(value)
            if nested.strip():
                return nested

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
            if isinstance(first.get("text"), str):
                return first["text"]

    return json.dumps(payload, indent=2, ensure_ascii=False)


def extract_text(result: dict[str, Any]) -> str:
    payload = result.get("result", {})
    content = payload.get("content", [])

    text_parts: list[str] = []
    for item in content:
        if item.get("type") == "text":
            text_parts.append(item.get("text", ""))
        else:
            text_parts.append(json.dumps(item, indent=2, ensure_ascii=False))

    if text_parts:
        return "\n".join(part for part in text_parts if part)
    if payload:
        return json.dumps(payload, indent=2, ensure_ascii=False)
    return json.dumps(result, indent=2, ensure_ascii=False)


def extract_json_block(text: str) -> dict[str, Any] | None:
    fenced = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        snippet = text[start : end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            return None
    return None


def sanitize_question(message: str, owner: str | None, repo: str | None, git_web_base_url: str | None = None) -> str:
    base_url = normalize_git_web_base_url(git_web_base_url)
    escaped_base = re.escape(base_url)
    question = re.sub(rf"{escaped_base}/[^\s]+", "", message)
    if owner and repo:
        question = question.replace(f"{owner}/{repo}", "")
    question = re.sub(r"\s+", " ", question).strip(" -:\n\t")
    return question or "Give me a useful summary of this repository."


def parse_repo_reference(text: str, git_web_base_url: str | None = None) -> tuple[str | None, str | None, str | None]:
    base_url = normalize_git_web_base_url(git_web_base_url)
    escaped_base = re.escape(base_url)
    url_match = re.search(rf"{escaped_base}/([^/\s]+)/([^/\s?#]+)", text)
    if url_match:
        owner = url_match.group(1)
        repo = url_match.group(2).removesuffix(".git")
        return owner, repo, url_match.group(0)

    pair_match = re.search(r"\b([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)\b", text)
    if pair_match:
        return pair_match.group(1), pair_match.group(2), f"{base_url}/{pair_match.group(1)}/{pair_match.group(2)}"

    return None, None, None


def should_write_report(question: str) -> bool:
    lowered = question.lower()
    report_terms = (
        "entire repo",
        "whole repo",
        "full repo",
        "comprehensive",
        "deep dive",
        "detailed report",
        "write a report",
        "architecture",
        "explain the repository",
        "explain this repo",
        "analyze this repo",
        "summarize the repository",
    )
    return any(term in lowered for term in report_terms)


def get_agent_mode_settings(agent_mode: str) -> dict[str, str]:
    return AGENT_MODES.get(agent_mode, AGENT_MODES["chat"])


def normalize_report_format(report_format: str | None) -> str:
    if report_format in REPORT_FORMATS:
        return str(report_format)
    return "md"


def normalize_git_web_base_url(git_web_base_url: str | None) -> str:
    candidate = (git_web_base_url or DEFAULT_GIT_WEB_BASE_URL).strip()
    if not candidate:
        return "https://github.com"
    if not re.match(r"^https?://", candidate, re.I):
        candidate = f"https://{candidate}"
    return candidate.rstrip("/")


def emit_progress(state: AgentState, message: str) -> list[str]:
    progress_events = list(state.get("progress_events", []))
    progress_events.append(message)

    callback = state.get("progress_callback")
    if callable(callback):
        callback(message, progress_events[:])

    return progress_events


def truncate_text(text: str, limit: int = 5000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def root_files_from_text(text: str) -> list[str]:
    candidates = [
        "README.md",
        "README",
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "go.mod",
        "Cargo.toml",
        "Dockerfile",
        "docker-compose.yml",
        "src",
        "app",
        "cmd",
        "internal",
        "docs",
    ]
    return [item for item in candidates if item.lower() in text.lower()]


def summarize_results(tool_results: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for item in tool_results:
        tool_name = item.get("tool_name", "unknown")
        arguments = json.dumps(item.get("arguments", {}), ensure_ascii=False)
        output = truncate_text(item.get("text", ""), limit=20000)
        chunks.append(f"Tool: {tool_name}\nArguments: {arguments}\nOutput:\n{output}")
    return "\n\n".join(chunks)


def build_fallback_plan(state: AgentState) -> dict[str, Any]:
    owner = state["owner"]
    repo = state["repo"]
    question = state["question"].lower()
    bootstrap = state.get("bootstrap_notes", "")
    tool_calls: list[dict[str, Any]] = []

    agent_mode = state.get("agent_mode", "chat")

    if agent_mode == "issues_prs":
        tool_calls.extend(
            [
                {"name": "list_issues", "arguments": {"owner": owner, "repo": repo, "perPage": 10}},
                {"name": "list_pull_requests", "arguments": {"owner": owner, "repo": repo, "perPage": 10, "state": "all"}},
            ]
        )
    elif agent_mode == "code_search":
        keywords = re.sub(r"[^a-z0-9 ]", " ", question)
        keywords = " ".join(word for word in keywords.split() if len(word) > 2)
        tool_calls.append(
            {
                "name": "search_code",
                "arguments": {"query": f"repo:{owner}/{repo} {keywords}".strip(), "perPage": 8},
            }
        )

    if should_write_report(state["question"]) or agent_mode == "deep_report":
        for path in root_files_from_text(bootstrap):
            if path not in {"README", "README.md"}:
                tool_calls.append(
                    {
                        "name": "get_file_contents",
                        "arguments": {"owner": owner, "repo": repo, "path": path},
                    }
                )
        tool_calls.extend(
            [
                {"name": "list_branches", "arguments": {"owner": owner, "repo": repo}},
                {"name": "get_latest_release", "arguments": {"owner": owner, "repo": repo}},
                {"name": "list_commits", "arguments": {"owner": owner, "repo": repo, "perPage": 5}},
            ]
        )
    elif "issue #" in question or re.search(r"issue\s+\d+", question):
        match = re.search(r"(\d+)", question)
        if match:
            tool_calls.append(
                {
                    "name": "issue_read",
                    "arguments": {
                        "owner": owner,
                        "repo": repo,
                        "issue_number": int(match.group(1)),
                        "method": "get",
                    },
                }
            )
    elif "pr #" in question or re.search(r"pull request\s+\d+", question):
        match = re.search(r"(\d+)", question)
        if match:
            tool_calls.append(
                {
                    "name": "pull_request_read",
                    "arguments": {
                        "owner": owner,
                        "repo": repo,
                        "pullNumber": int(match.group(1)),
                        "method": "get",
                    },
                }
            )
    else:
        keywords = re.sub(r"[^a-z0-9 ]", " ", question)
        keywords = " ".join(word for word in keywords.split() if len(word) > 2)
        if keywords:
            tool_calls.append(
                {
                    "name": "search_code",
                    "arguments": {"query": f"repo:{owner}/{repo} {keywords}", "perPage": 5},
                }
            )
        tool_calls.append(
            {
                "name": "list_commits",
                "arguments": {"owner": owner, "repo": repo, "perPage": 5},
            }
        )

    return {
        "needs_report": should_write_report(state["question"]) or agent_mode == "deep_report",
        "tool_calls": tool_calls[:6],
        "analysis_focus": "Fallback plan because the LLM planner did not return valid JSON.",
    }


def sanitize_tool_call(tool_call: dict[str, Any], owner: str, repo: str) -> dict[str, Any] | None:
    name = str(tool_call.get("name", "")).strip()
    if name not in READ_ONLY_TOOLS:
        return None

    arguments = tool_call.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}

    if name in REPO_SCOPED_TOOLS:
        arguments.setdefault("owner", owner)
        arguments.setdefault("repo", repo)

    if name == "search_code":
        query = str(arguments.get("query", "")).strip()
        if f"repo:{owner}/{repo}" not in query:
            query = f"repo:{owner}/{repo} {query}".strip()
        arguments["query"] = query
        arguments["perPage"] = min(int(arguments.get("perPage", 5)), 10)

    if "perPage" in arguments:
        try:
            arguments["perPage"] = min(max(int(arguments["perPage"]), 1), 10)
        except (TypeError, ValueError):
            arguments["perPage"] = 5

    return {"name": name, "arguments": arguments}


def build_graph(mcp_client: MCPHTTPClient, llm_client: LiteLLMCompleteClient, report_dir: Path):
    def resolve_repo(state: AgentState) -> AgentState:
        progress_events = emit_progress(state, "Resolving repository reference from the user message.")
        message = state["user_message"]
        agent_mode = state.get("agent_mode", "chat")
        mode_settings = get_agent_mode_settings(agent_mode)
        git_web_base_url = normalize_git_web_base_url(state.get("git_web_base_url"))
        owner, repo, repo_hint = parse_repo_reference(message, git_web_base_url)
        if not owner or not repo:
            prior_hint = state.get("session_repo_hint") or state.get("repo_hint")
            if prior_hint:
                owner, repo, repo_hint = parse_repo_reference(prior_hint, git_web_base_url)

        if not owner or not repo:
            return {
                "error": "Please include a GitHub repository URL like https://github.com/owner/repo or an owner/repo reference.",
                "progress_events": progress_events,
            }

        question = sanitize_question(message, owner, repo, git_web_base_url)
        progress_events = emit_progress(state, f"Repository resolved to {owner}/{repo}.")
        return {
            "owner": owner,
            "repo": repo,
            "repo_hint": repo_hint or f"{git_web_base_url}/{owner}/{repo}",
            "question": question,
            "agent_mode": agent_mode,
            "mode_instruction": mode_settings["instruction"],
            "git_web_base_url": git_web_base_url,
            "report_format": normalize_report_format(state.get("report_format")),
            "progress_events": progress_events,
        }

    def bootstrap_context(state: AgentState) -> AgentState:
        progress_events = emit_progress(state, "Reading repository root and README through MCP.")
        owner = state["owner"]
        repo = state["repo"]
        tool_results = list(state.get("tool_results", []))

        seed_calls = [
            {"name": "get_file_contents", "arguments": {"owner": owner, "repo": repo, "path": "/"}},
            {"name": "get_file_contents", "arguments": {"owner": owner, "repo": repo, "path": "README.md"}},
        ]

        notes: list[str] = []
        for tool_call in seed_calls:
            progress_events = emit_progress(
                state,
                f"Running bootstrap tool `{tool_call['name']}` for path `{tool_call['arguments'].get('path', '/')}`.",
            )
            try:
                raw = mcp_client.call_tool(tool_call["name"], tool_call["arguments"])
                text = extract_text(raw)
            except Exception as exc:  # noqa: BLE001
                text = f"Error: {exc}"
                raw = {"error": str(exc)}

            tool_results.append(
                {
                    "tool_name": tool_call["name"],
                    "arguments": tool_call["arguments"],
                    "text": text,
                    "raw": raw,
                }
            )
            notes.append(f"{tool_call['name']} {tool_call['arguments']}\n{truncate_text(text, 2500)}")

        return {
            "tool_results": tool_results,
            "bootstrap_notes": "\n\n".join(notes),
            "progress_events": progress_events,
        }

    def plan_actions(state: AgentState) -> AgentState:
        progress_events = emit_progress(state, "Planning which read-only tools to use for this question.")
        allowed_lines = "\n".join(f"- {name}: {description}" for name, description in READ_ONLY_TOOLS.items())
        mode_settings = get_agent_mode_settings(state.get("agent_mode", "chat"))
        prompt = textwrap.dedent(
            f"""
            You are a GitHub repository viewer planner.
            The agent is read-only. It must never choose write tools.

            Agent mode: {mode_settings['label']}
            Mode directive: {state.get('mode_instruction', mode_settings['instruction'])}
            Repository: {state['owner']}/{state['repo']}
            User question: {state['question']}
            Existing context from MCP:
            {state.get('bootstrap_notes', 'No bootstrap context available.')}

            Allowed MCP tools:
            {allowed_lines}

            Return JSON only with this exact shape:
            {{
              "needs_report": true or false,
              "analysis_focus": "short reason",
              "tool_calls": [
                {{"name": "tool_name", "arguments": {{...}}}}
              ]
            }}

            Planning rules:
            - Use at most 6 tool calls.
            - Keep everything read-only.
            - Prefer `get_file_contents` for README, manifests, docs, and key source files.
            - Prefer `search_code` for implementation questions. Use a `repo:{state['owner']}/{state['repo']}` filter.
            - In `Issue and PR Analyst` mode, prefer issue and pull request tools when reasonable.
            - In `Code Search Expert` mode, prefer code search and concrete file inspection.
            - In `Deep Repo Report` mode, gather enough structure and history for a comprehensive report.
            - If the user asks for a full explanation or deep analysis, set `needs_report` to true.
            - If bootstrap context already answers the question, you may return no extra tool calls.
            """
        ).strip()

        raw_plan = llm_client.complete(prompt)
        parsed = extract_json_block(raw_plan)
        if not parsed:
            progress_events = emit_progress(state, "Planner output was not valid JSON. Falling back to a deterministic tool plan.")
            parsed = build_fallback_plan(state)
        else:
            planned_count = len(parsed.get("tool_calls", [])) if isinstance(parsed, dict) else 0
            progress_events = emit_progress(state, f"Planner selected {planned_count} additional tool call(s).")

        return {
            "plan_text": raw_plan,
            "plan": parsed,
            "progress_events": progress_events,
        }

    def execute_tools(state: AgentState) -> AgentState:
        progress_events = emit_progress(state, "Executing planned MCP tools.")
        owner = state["owner"]
        repo = state["repo"]
        plan = state.get("plan", {})
        tool_results = list(state.get("tool_results", []))

        for original_call in plan.get("tool_calls", [])[:6]:
            if not isinstance(original_call, dict):
                continue

            tool_call = sanitize_tool_call(original_call, owner, repo)
            if not tool_call:
                continue

            progress_events = emit_progress(
                state,
                f"Calling `{tool_call['name']}` with {json.dumps(tool_call['arguments'], ensure_ascii=False)}.",
            )
            try:
                raw = mcp_client.call_tool(tool_call["name"], tool_call["arguments"])
                text = extract_text(raw)
            except Exception as exc:  # noqa: BLE001
                raw = {"error": str(exc)}
                text = f"Error: {exc}"
                progress_events = emit_progress(state, f"Tool `{tool_call['name']}` failed: {exc}")
            else:
                progress_events = emit_progress(state, f"Tool `{tool_call['name']}` completed.")

            tool_results.append(
                {
                    "tool_name": tool_call["name"],
                    "arguments": tool_call["arguments"],
                    "text": text,
                    "raw": raw,
                }
            )

        return {"tool_results": tool_results, "progress_events": progress_events}

    def write_answer(state: AgentState) -> AgentState:
        progress_events = emit_progress(state, "Synthesizing the final answer from the collected evidence.")
        tool_summary = summarize_results(state.get("tool_results", []))
        mode_settings = get_agent_mode_settings(state.get("agent_mode", "chat"))
        report_format = normalize_report_format(state.get("report_format"))
        needs_report = bool(
            state.get("plan", {}).get("needs_report")
            or should_write_report(state["question"])
            or state.get("agent_mode") == "deep_report"
        )

        if needs_report:
            progress_events = emit_progress(state, f"This request needs a comprehensive {report_format} report.")
            format_requirements = {
                "md": "- Output Markdown only.\n- Use sections with markdown headings.",
                "text": "- Output plain text only.\n- Use simple section titles without markdown syntax.",
                "json": "- Output valid JSON only.\n- Use this exact top-level object shape: {\"executive_summary\": string, \"repository_structure\": [string], \"key_components\": [string], \"relevant_findings\": [string], \"risks_or_unknowns\": [string], \"suggested_next_questions\": [string]}",
            }[report_format]
            prompt = textwrap.dedent(
                f"""
                You are a senior GitHub repository analyst.
                Agent mode: {mode_settings['label']}
                Mode directive: {state.get('mode_instruction', mode_settings['instruction'])}
                Write a comprehensive report for repository {state['owner']}/{state['repo']}.

                User request:
                {state['question']}

                Evidence gathered through MCP:
                {tool_summary}

                Requirements:
                {format_requirements}
                - Include these logical sections: Executive Summary, Repository Structure, Key Components, Relevant Findings, Risks or Unknowns, Suggested Next Questions.
                - Be explicit when evidence is incomplete.
                - Do not invent files or behavior.
                """
            ).strip()
            report_markdown = llm_client.complete(prompt)
            return {"report_markdown": report_markdown, "report_format": report_format, "progress_events": progress_events}

        prompt = textwrap.dedent(
            f"""
            You are a GitHub expert viewer agent.
            Agent mode: {mode_settings['label']}
            Mode directive: {state.get('mode_instruction', mode_settings['instruction'])}
            Answer the user question precisely using the MCP evidence below.

            Repository: {state['owner']}/{state['repo']}
            User question:
            {state['question']}

            MCP evidence:
            {tool_summary}

            Response style:
            - Concise but useful.
            - If evidence is incomplete, say what is missing.
            - Mention the specific files or repository areas you used when possible.
            """
        ).strip()
        answer = llm_client.complete(prompt)
        progress_events = emit_progress(state, "Answer draft completed.")
        return {"answer": answer, "progress_events": progress_events}

    def persist_report(state: AgentState) -> AgentState:
        progress_events = emit_progress(state, "Saving the markdown report to disk.")
        report_markdown = state.get("report_markdown", "").strip()
        report_format = normalize_report_format(state.get("report_format"))
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_repo = f"{state['owner']}-{state['repo']}".replace("/", "-")
        extension = {"md": "md", "text": "txt", "json": "json"}[report_format]
        path = report_dir / f"report-{safe_repo}-{timestamp}.{extension}"
        path.write_text(report_markdown + "\n", encoding="utf-8")

        answer = (
            f"I wrote a detailed {report_format} report for {state['owner']}/{state['repo']} to {path}.\n\n"
            f"Preview:\n\n{truncate_text(report_markdown, 1800)}"
        )
        return {
            "report_path": str(path),
            "report_format": report_format,
            "answer": answer,
            "progress_events": progress_events,
        }

    def route_after_resolve(state: AgentState) -> str:
        return "error" if state.get("error") else "ok"

    def route_after_answer(state: AgentState) -> str:
        if state.get("report_markdown"):
            return "write_report"
        return "done"

    graph = StateGraph(AgentState)
    graph.add_node("resolve_repo", resolve_repo)
    graph.add_node("bootstrap_context", bootstrap_context)
    graph.add_node("plan_actions", plan_actions)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("write_answer", write_answer)
    graph.add_node("persist_report", persist_report)

    graph.set_entry_point("resolve_repo")
    graph.add_conditional_edges(
        "resolve_repo",
        route_after_resolve,
        {"ok": "bootstrap_context", "error": END},
    )
    graph.add_edge("bootstrap_context", "plan_actions")
    graph.add_edge("plan_actions", "execute_tools")
    graph.add_edge("execute_tools", "write_answer")
    graph.add_conditional_edges(
        "write_answer",
        route_after_answer,
        {"write_report": "persist_report", "done": END},
    )
    graph.add_edge("persist_report", END)
    return graph.compile()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LangGraph GitHub expert viewer agent over MCP HTTP")
    parser.add_argument("--message", default="", help="User message containing a repo URL or owner/repo and a question")
    parser.add_argument("--repo-url", default="", help="Optional explicit repository URL or owner/repo")
    parser.add_argument("--interactive", action="store_true", help="Run an interactive chat loop")
    parser.add_argument("--mcp-url", default=os.getenv("MCP_URL", DEFAULT_MCP_URL), help="MCP HTTP base URL")
    parser.add_argument("--git-web-base-url", default=DEFAULT_GIT_WEB_BASE_URL, help="Git web base URL used to parse repository links, for example https://github.com or https://ghe.example.com")
    parser.add_argument("--token", default=os.getenv("MCP_AUTH_TOKEN", os.getenv("GITHUB_TOKEN", "")), help="GitHub bearer token")
    parser.add_argument("--llm-url", default=os.getenv("LITELLM_COMPLETE_URL", DEFAULT_LLM_URL), help="LiteLLM-compatible completion endpoint")
    parser.add_argument("--model", default=os.getenv("LITELLM_MODEL", DEFAULT_MODEL), help="LLM model name")
    parser.add_argument("--max-seconds", type=int, default=int(os.getenv("LITELLM_MAX_SECONDS", "25")), help="LLM timeout budget")
    parser.add_argument("--report-dir", default=str(Path(__file__).with_name("reports")), help="Directory for generated reports")
    parser.add_argument("--report-format", choices=REPORT_FORMATS, default=os.getenv("REPORT_FORMAT", "md"), help="Format for generated deep reports")
    parser.add_argument("--verbose", action="store_true", help="Print planning details and tool activity")
    return parser.parse_args()


def initialize_mcp(client: MCPHTTPClient) -> None:
    response = client.initialize()
    if "error" in response:
        raise RuntimeError(json.dumps(response, indent=2, ensure_ascii=False))


def create_runtime(
    mcp_url: str,
    token: str,
    llm_url: str,
    model: str,
    max_seconds: int,
    report_dir: str | Path,
) -> tuple[Any, MCPHTTPClient, LiteLLMCompleteClient]:
    mcp_client = MCPHTTPClient(mcp_url, token)
    llm_client = LiteLLMCompleteClient(llm_url, model, max_seconds)
    initialize_mcp(mcp_client)
    graph = build_graph(mcp_client, llm_client, Path(report_dir))
    return graph, mcp_client, llm_client


def invoke_turn(graph: Any, session_repo_hint: str, user_message: str, verbose: bool) -> AgentState:
    state: AgentState = {
        "user_message": user_message,
        "session_repo_hint": session_repo_hint,
        "git_web_base_url": DEFAULT_GIT_WEB_BASE_URL,
        "report_format": "md",
        "progress_events": [],
        "tool_results": [],
        "verbose": verbose,
    }
    return graph.invoke(state)


def invoke_turn_with_mode(
    graph: Any,
    session_repo_hint: str,
    user_message: str,
    verbose: bool,
    agent_mode: str,
    git_web_base_url: str = DEFAULT_GIT_WEB_BASE_URL,
    report_format: str = "md",
    progress_callback: Any = None,
) -> AgentState:
    state: AgentState = {
        "user_message": user_message,
        "session_repo_hint": session_repo_hint,
        "git_web_base_url": normalize_git_web_base_url(git_web_base_url),
        "report_format": normalize_report_format(report_format),
        "progress_events": [],
        "progress_callback": progress_callback,
        "tool_results": [],
        "verbose": verbose,
        "agent_mode": agent_mode,
    }
    return graph.invoke(state)


def run_turn(graph: Any, session_repo_hint: str, user_message: str, verbose: bool) -> tuple[str, str]:
    result = invoke_turn(graph, session_repo_hint, user_message, verbose)

    if result.get("error"):
        return result["error"], session_repo_hint

    if verbose:
        print("\n[planner output]")
        print(result.get("plan_text", "<no planner output>"))
        print("\n[tool summary]")
        print(summarize_results(result.get("tool_results", [])))

    return result.get("answer", "No answer generated."), result.get("repo_hint", session_repo_hint)


def interactive_chat(graph: Any, initial_repo_hint: str, verbose: bool) -> int:
    print("LangGraph GitHub expert viewer agent")
    print("Type `exit` to quit.")
    repo_hint = initial_repo_hint

    while True:
        try:
            message = input("\nUser> ").strip()
        except EOFError:
            print()
            return 0

        if not message:
            continue
        if message.lower() in {"exit", "quit"}:
            return 0

        answer, repo_hint = run_turn(graph, repo_hint, message, verbose)
        print(f"\nAgent> {answer}")


def main() -> int:
    args = parse_args()

    if not args.token:
        print("Missing token. Set MCP_AUTH_TOKEN or pass --token.", file=sys.stderr)
        return 1

    try:
        graph, _, _ = create_runtime(
            args.mcp_url,
            args.token,
            args.llm_url,
            args.model,
            args.max_seconds,
            args.report_dir,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to initialize MCP: {exc}", file=sys.stderr)
        return 1

    initial_repo_hint = args.repo_url.strip()

    if args.interactive or not args.message:
        return interactive_chat(graph, initial_repo_hint, args.verbose)

    message = args.message
    if initial_repo_hint and initial_repo_hint not in message:
        message = f"{initial_repo_hint} {message}".strip()

    result = invoke_turn_with_mode(graph, initial_repo_hint, message, args.verbose, "chat", args.git_web_base_url, args.report_format)
    print(result.get("answer", "No answer generated."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
