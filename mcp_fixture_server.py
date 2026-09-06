"""
Minimal MCP server fixture for tests (stdio transport, JSON-RPC 2.0).
Implements: initialize, notifications/initialized, tools/list, tools/call.
Tools: echo, add, fail (always returns an error result).
"""
import json
import sys


def send(payload):
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = message.get("method", "")
        request_id = message.get("id")

        if method == "initialize":
            send({
                "jsonrpc": "2.0", "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fixture", "version": "0.0.1"},
                },
            })
        elif method == "tools/list":
            send({
                "jsonrpc": "2.0", "id": request_id,
                "result": {"tools": [
                    {
                        "name": "echo",
                        "description": "Echo the given text",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    },
                    {
                        "name": "add",
                        "description": "Add two integers",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                            "required": ["a", "b"],
                        },
                    },
                    {
                        "name": "fail",
                        "description": "Always returns a tool error",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                ]},
            })
        elif method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "echo":
                result = {"content": [{"type": "text", "text": f"echo: {args.get('text', '')}"}]}
            elif name == "add":
                total = int(args.get("a", 0)) + int(args.get("b", 0))
                result = {"content": [{"type": "text", "text": f"sum: {total}"}]}
            else:
                result = {"isError": True, "content": [{"type": "text", "text": "intentional failure"}]}
            send({"jsonrpc": "2.0", "id": request_id, "result": result})
        elif request_id is not None and method.startswith("notifications/") is False:
            send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "not found"}})


if __name__ == "__main__":
    main()
