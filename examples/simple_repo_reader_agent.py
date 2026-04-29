import argparse
import json
import os
import sys
import urllib.error
import urllib.request


class MCPHTTPClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/") or "http://127.0.0.1:9090"
        self.token = token
        self.request_id = 0

    def _next_id(self) -> int:
        self.request_id += 1
        return self.request_id

    def _post(self, payload: dict) -> dict:
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
            with urllib.request.urlopen(request, timeout=30) as response:
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

    def initialize(self) -> dict:
        return self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "simple-repo-reader",
                        "version": "1.0",
                    },
                },
            }
        )

    def call_tool(self, name: str, arguments: dict) -> dict:
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


def extract_text(result: dict) -> str:
    payload = result.get("result", {})
    content = payload.get("content", [])

    text_parts = []
    for item in content:
        if item.get("type") == "text":
            text_parts.append(item.get("text", ""))
        else:
            text_parts.append(json.dumps(item, indent=2))

    if text_parts:
        return "\n".join(part for part in text_parts if part)

    if payload:
        return json.dumps(payload, indent=2)

    return json.dumps(result, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple MCP HTTP agent that reads repository files")
    parser.add_argument("--base-url", default="http://127.0.0.1:9090", help="MCP HTTP base URL")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN", ""), help="GitHub bearer token")
    parser.add_argument("--owner", required=True, help="Repository owner")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--path", default="/", help="Repository path to read")
    parser.add_argument("--ref", default="", help="Optional ref, branch, or tag")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.token:
        print("Missing token. Pass --token or set GITHUB_TOKEN.", file=sys.stderr)
        return 1

    client = MCPHTTPClient(args.base_url, args.token)

    init_response = client.initialize()
    if "error" in init_response:
        print(json.dumps(init_response, indent=2), file=sys.stderr)
        return 1

    tool_args = {
        "owner": args.owner,
        "repo": args.repo,
        "path": args.path,
    }
    if args.ref:
        tool_args["ref"] = args.ref

    result = client.call_tool("get_file_contents", tool_args)
    if "error" in result:
        print(json.dumps(result, indent=2), file=sys.stderr)
        return 1

    print(extract_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())