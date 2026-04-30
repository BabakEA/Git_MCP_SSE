#!/bin/sh
set -eu

sanitize_env_value() {
	value="$1"
	case "$value" in
		\"*\")
			value="${value#\"}"
			value="${value%\"}"
			;;
	esac
	printf '%s' "$value"
}

normalize_host() {
	value="$(sanitize_env_value "$1")"
	value="${value%/}"

	case "$value" in
		*/api/v3)
			value="${value%/api/v3}"
			;;
	esac

	printf '%s' "$value"
}

host="$(normalize_host "${GITHUB_HOST:-${GITHUB_API_URL:-}}")"
port="$(sanitize_env_value "${PORT:-9090}")"

if [ -n "$host" ]; then
	export GITHUB_HOST="$host"
fi

set -- github-mcp-server http --port "$port"

base_url="$(sanitize_env_value "${MCP_BASE_URL:-}")"
base_path="$(sanitize_env_value "${MCP_BASE_PATH:-}")"
read_only="$(sanitize_env_value "${MCP_READ_ONLY:-false}")"
scope_challenge="$(sanitize_env_value "${MCP_SCOPE_CHALLENGE:-false}")"
toolsets="$(sanitize_env_value "${MCP_TOOLSETS:-}")"
tools="$(sanitize_env_value "${MCP_TOOLS:-}")"
exclude_tools="$(sanitize_env_value "${MCP_EXCLUDE_TOOLS:-}")"

if [ -n "$base_url" ]; then
	set -- "$@" --base-url "$base_url"
fi

if [ -n "$base_path" ]; then
	set -- "$@" --base-path "$base_path"
fi

if [ "$read_only" = "true" ]; then
	set -- "$@" --read-only
fi

if [ "$scope_challenge" = "true" ]; then
	set -- "$@" --scope-challenge
fi

if [ -n "$toolsets" ]; then
	set -- "$@" --toolsets "$toolsets"
fi

if [ -n "$tools" ]; then
	set -- "$@" --tools "$tools"
fi

if [ -n "$exclude_tools" ]; then
	set -- "$@" --exclude-tools "$exclude_tools"
fi

exec "$@"