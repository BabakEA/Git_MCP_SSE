from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

import streamlit as st

from langgraph_mcp_agent import (
    AGENT_MODES,
    DEFAULT_LLM_URL,
    DEFAULT_MCP_URL,
    DEFAULT_MODEL,
    DEFAULT_GIT_WEB_BASE_URL,
    REPORT_FORMATS,
    create_runtime,
    invoke_turn_with_mode,
)


APP_TITLE = "GitHub Expert Chat"
DEFAULT_REPORT_DIR = Path(__file__).with_name("reports")
TOOL_BACKENDS: dict[str, dict[str, str]] = {
    "github_mcp": {
        "label": "GitHub MCP",
        "description": "Read-only GitHub repository tools over MCP HTTP.",
        "token_env": "MCP_AUTH_TOKEN",
        "url_env": "MCP_URL",
        "default_url": DEFAULT_MCP_URL,
    }
}


@st.cache_resource(show_spinner=False)
def get_runtime(
    mcp_url: str,
    token: str,
    llm_url: str,
    model: str,
    max_seconds: int,
    report_dir: str,
):
    return create_runtime(mcp_url, token, llm_url, model, max_seconds, report_dir)


def init_session_state() -> None:
    st.session_state.setdefault("authenticated", False)
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("repo_hint", "")
    st.session_state.setdefault("last_report_path", "")
    st.session_state.setdefault("last_report_format", "md")
    st.session_state.setdefault("active_agent_mode", "chat")


def auth_is_enabled() -> bool:
    return bool(os.getenv("UI_USERNAME") and os.getenv("UI_PASSWORD"))


def render_auth_gate() -> bool:
    if not auth_is_enabled():
        return True

    if st.session_state.authenticated:
        return True

    with st.container(border=True):
        st.subheader("Sign in")
        st.caption("This hosted UI is protected with basic application login before the agent runtime is available.")
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Sign in", type="primary", use_container_width=True):
            expected_username = os.getenv("UI_USERNAME", "")
            expected_password = os.getenv("UI_PASSWORD", "")
            if secrets.compare_digest(username, expected_username) and secrets.compare_digest(password, expected_password):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Invalid username or password.")

    return False


def render_sidebar() -> dict[str, Any]:
    st.sidebar.title("Agent Setup")
    mode_options = list(AGENT_MODES.keys())
    selected_mode = st.sidebar.selectbox(
        "Agent mode",
        options=mode_options,
        index=mode_options.index(st.session_state.active_agent_mode) if st.session_state.active_agent_mode in mode_options else 0,
        format_func=lambda key: AGENT_MODES[key]["label"],
    )
    st.session_state.active_agent_mode = selected_mode
    st.sidebar.caption(AGENT_MODES[selected_mode]["description"])

    st.sidebar.markdown("---")
    st.sidebar.subheader("Tool backends")
    backend_values: dict[str, dict[str, str]] = {}
    for backend_key, backend in TOOL_BACKENDS.items():
        with st.sidebar.expander(backend["label"], expanded=True):
            backend_url = st.text_input(
                f"{backend['label']} URL",
                value=os.getenv(backend["url_env"], backend["default_url"]),
                key=f"{backend_key}_url",
            )
            env_token = os.getenv(backend["token_env"], os.getenv("GITHUB_TOKEN", ""))
            backend_token = st.text_input(
                f"{backend['label']} bearer token",
                value=env_token,
                type="password",
                key=f"{backend_key}_token",
            )
            st.caption(backend["description"])
            backend_values[backend_key] = {"url": backend_url, "token": backend_token}

    st.sidebar.markdown("---")
    st.sidebar.subheader("Model")
    llm_url = st.sidebar.text_input("LiteLLM endpoint", value=os.getenv("LITELLM_COMPLETE_URL", DEFAULT_LLM_URL))
    model = st.sidebar.text_input("Model", value=os.getenv("LITELLM_MODEL", DEFAULT_MODEL))
    git_web_base_url = st.sidebar.text_input("Git web base URL", value=os.getenv("GIT_WEB_BASE_URL", DEFAULT_GIT_WEB_BASE_URL))
    max_seconds = st.sidebar.slider(
        "LLM max seconds",
        min_value=5,
        max_value=120,
        value=int(os.getenv("LITELLM_MAX_SECONDS", "25")),
        step=5,
    )
    verbose = st.sidebar.toggle("Show planning trace", value=False)
    report_dir = st.sidebar.text_input("Report directory", value=str(DEFAULT_REPORT_DIR))
    report_format = st.sidebar.selectbox("Report format", options=list(REPORT_FORMATS), index=list(REPORT_FORMATS).index("md"))

    st.sidebar.markdown("---")
    st.sidebar.caption(
        "The UI collects bearer tokens per backend. Today it uses GitHub MCP, and the same sidebar structure can grow to support more tool providers later."
    )

    return {
        "agent_mode": selected_mode,
        "tool_backends": backend_values,
        "mcp_url": backend_values["github_mcp"]["url"],
        "token": backend_values["github_mcp"]["token"],
        "llm_url": llm_url,
        "model": model,
        "git_web_base_url": git_web_base_url,
        "max_seconds": max_seconds,
        "verbose": verbose,
        "report_dir": report_dir,
        "report_format": report_format,
    }


def render_messages() -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            progress_events = message.get("progress_events") or []
            if progress_events:
                with st.expander("Agent progress"):
                    st.markdown("\n".join(f"- {event}" for event in progress_events))
            if message.get("report_path"):
                st.caption(f"Report saved to {message['report_path']}")
            if message.get("report_format"):
                st.caption(f"Report format: {message['report_format']}")
            trace = message.get("trace")
            if trace:
                with st.expander("Reasoning trace and MCP evidence"):
                    st.code(trace)


def build_trace(result: dict) -> str:
    parts: list[str] = []
    plan_text = result.get("plan_text")
    if plan_text:
        parts.append("[Planner]\n" + plan_text)

    tool_results = result.get("tool_results", [])
    if tool_results:
        tool_chunks: list[str] = []
        for item in tool_results:
            tool_chunks.append(
                "Tool: {name}\nArguments: {arguments}\nOutput:\n{output}".format(
                    name=item.get("tool_name", "unknown"),
                    arguments=item.get("arguments", {}),
                    output=item.get("text", ""),
                )
            )
        parts.append("[MCP Evidence]\n" + "\n\n".join(tool_chunks))

    return "\n\n".join(parts)


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="💬", layout="wide")
    st.title(APP_TITLE)
    st.caption("ChatGPT-style repository chat over LangGraph, LiteLLM, and the local GitHub MCP HTTP server.")

    init_session_state()
    if not render_auth_gate():
        return

    config = render_sidebar()

    if not config["token"]:
        st.warning("Enter the bearer token for the active tool backend in the sidebar to start chatting.")
        render_messages()
        return

    try:
        graph, _, _ = get_runtime(
            str(config["mcp_url"]),
            str(config["token"]),
            str(config["llm_url"]),
            str(config["model"]),
            int(config["max_seconds"]),
            str(config["report_dir"]),
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to initialize runtime: {exc}")
        render_messages()
        return

    col1, col2 = st.columns([3, 1])
    with col1:
        st.info(
            f"Mode: {AGENT_MODES[str(config['agent_mode'])]['label']}. Git web base URL: {config['git_web_base_url']}. Ask about any GitHub repository by URL or owner/repo. Deep analysis requests can produce a {config['report_format']} report automatically."
        )
    with col2:
        if st.button("Clear chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.repo_hint = ""
            st.session_state.last_report_path = ""
            st.rerun()

    if st.session_state.last_report_path:
        report_path = Path(st.session_state.last_report_path)
        if report_path.exists():
            mime_type = {
                "md": "text/markdown",
                "text": "text/plain",
                "json": "application/json",
            }.get(st.session_state.last_report_format, "text/plain")
            st.download_button(
                "Download latest report",
                data=report_path.read_text(encoding="utf-8"),
                file_name=report_path.name,
                mime=mime_type,
            )

    render_messages()

    prompt_examples = {
        "chat": "Ask a repository question, for example: https://github.com/github/github-mcp-server explain the HTTP transport",
        "deep_report": "Ask for a full analysis, for example: github/github-mcp-server write a comprehensive architecture report",
        "code_search": "Ask an implementation question, for example: github/github-mcp-server where are the repository tools defined?",
        "issues_prs": "Ask about collaboration history, for example: github/github-mcp-server summarize recent PR and issue activity",
    }
    prompt = st.chat_input(prompt_examples.get(str(config["agent_mode"]), prompt_examples["chat"]))
    if not prompt:
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        live_status = st.empty()
        live_progress = st.empty()

        def on_progress(_: str, events: list[str]) -> None:
            latest = events[-1] if events else "Starting"
            live_status.info(f"Agent progress: {latest}")
            live_progress.markdown("\n".join(f"- {event}" for event in events))

        with st.spinner("Thinking, reading the repository, and drafting an answer..."):
            result = invoke_turn_with_mode(
                graph,
                st.session_state.repo_hint,
                prompt,
                bool(config["verbose"]),
                str(config["agent_mode"]),
                str(config["git_web_base_url"]),
                str(config["report_format"]),
                on_progress,
            )

        live_status.empty()
        live_progress.empty()

        if result.get("error"):
            answer = result["error"]
        else:
            answer = result.get("answer", "No answer generated.")
            st.session_state.repo_hint = result.get("repo_hint", st.session_state.repo_hint)

        st.markdown(answer)

        trace = build_trace(result) if config["verbose"] else ""
        report_path = result.get("report_path", "")
        report_format = result.get("report_format", str(config["report_format"]))
        progress_events = result.get("progress_events", [])
        if progress_events:
            with st.expander("Agent progress"):
                st.markdown("\n".join(f"- {event}" for event in progress_events))
        if report_path:
            st.session_state.last_report_path = report_path
            st.session_state.last_report_format = report_format
            st.caption(f"Report saved to {report_path}")
            st.caption(f"Report format: {report_format}")
        if trace:
            with st.expander("Reasoning trace and MCP evidence"):
                st.code(trace)

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
            "trace": trace,
            "report_path": report_path,
            "report_format": report_format,
            "progress_events": progress_events,
            "agent_mode": str(config["agent_mode"]),
        }
    )


if __name__ == "__main__":
    main()