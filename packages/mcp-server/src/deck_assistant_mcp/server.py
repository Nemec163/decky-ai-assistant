"""Stdio MCP server for the Decky AI Assistant tool catalog.

This module adds a minimal, dependency-free Model Context Protocol transport on
top of the in-process tool dispatcher. It speaks newline-delimited JSON-RPC 2.0
over stdin/stdout, exposes the static tool catalog through ``tools/list``, and
routes ``tools/call`` through the same validated dispatcher used by the tests.

The server is read-only by default: it wires real bounded diagnostics readers
and an in-memory staged-action store. It never executes staged actions, never
reads provider credential stores, and refuses approval-gated execution because
no Decky approval token path is available to a CLI-launched server.
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from collections.abc import Mapping, Sequence
from typing import Any, TextIO

from deck_assistant_core.actions import StagedActionStore
from deck_assistant_core.cli import managed_cli_user_home
from deck_assistant_core.diagnostics import (
    MAX_PROTON_EXCERPT_CHARACTERS,
    plan_storage_report_paths,
    read_proton_logs,
    read_storage_report,
)

from deck_assistant_mcp.contracts import TOOL_CONTRACTS
from deck_assistant_mcp.dispatcher import (
    InProcessToolDispatcher,
    create_in_process_tool_dispatcher,
)


SERVER_NAME = "deck-assistant-mcp"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
# Protocol revisions this server understands. ``initialize`` negotiates the
# requested version against this set and falls back to the default otherwise.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

JSONRPC_VERSION = "2.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class _RpcError(Exception):
    """Internal error mapped to a JSON-RPC error response."""

    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def build_default_dispatcher(*, home_path: str | None = None) -> InProcessToolDispatcher:
    """Build a dispatcher wired with real read-only diagnostics readers.

    Knowledge search has no injected index in the default server, so it returns
    an empty result set until a local index is wired. Storage and Proton-log
    tools read bounded local filesystem metadata only.
    """

    home = home_path or managed_cli_user_home()

    def storage_path_planner(*, sections: Any = None) -> Sequence[Any]:
        if sections is None:
            return plan_storage_report_paths(home_path=home)
        return plan_storage_report_paths(home_path=home, sections=sections)

    def storage_report_reader(plan: Sequence[Any]) -> Any:
        return read_storage_report(plan)

    def proton_log_reader(
        *,
        max_excerpt_characters: int = MAX_PROTON_EXCERPT_CHARACTERS,
    ) -> Any:
        return read_proton_logs(
            home_path=home,
            max_excerpt_characters=max_excerpt_characters,
        )

    return create_in_process_tool_dispatcher(
        TOOL_CONTRACTS,
        storage_path_planner=storage_path_planner,
        storage_report_reader=storage_report_reader,
        proton_log_reader=proton_log_reader,
        staged_action_store=StagedActionStore(),
    )


class McpStdioServer:
    """Newline-delimited JSON-RPC 2.0 MCP server over text streams."""

    def __init__(
        self,
        dispatcher: InProcessToolDispatcher,
        *,
        name: str = SERVER_NAME,
        version: str = SERVER_VERSION,
    ) -> None:
        self._dispatcher = dispatcher
        self._name = name
        self._version = version
        # Build the method dispatch table once; it never changes per message.
        self._method_handlers: dict[str, Any] = {
            "initialize": self._handle_initialize,
            "ping": self._handle_ping,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
        }

    def serve(self, stream_in: TextIO, stream_out: TextIO) -> None:
        """Process messages until the input stream reaches EOF."""

        for raw_line in stream_in:
            line = raw_line.strip()
            if not line:
                continue
            response = self._handle_line(line)
            if response is not None:
                stream_out.write(json.dumps(response, ensure_ascii=False))
                stream_out.write("\n")
                stream_out.flush()

    def _handle_line(self, line: str) -> dict[str, Any] | list[Any] | None:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return _error_response(None, PARSE_ERROR, "Parse error")

        if isinstance(message, list):
            return self._handle_batch(message)

        return self._handle_single(message)

    def _handle_batch(self, batch: list[Any]) -> list[Any] | dict[str, Any] | None:
        # JSON-RPC 2.0 batch: an empty array is itself an invalid request.
        if not batch:
            return _error_response(None, INVALID_REQUEST, "Invalid Request")

        responses: list[Any] = []
        for element in batch:
            response = self._handle_single(element)
            if response is not None:
                responses.append(response)

        # Emit nothing when every element was a notification (no responses).
        return responses or None

    def _handle_single(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, Mapping):
            return _error_response(None, INVALID_REQUEST, "Invalid Request")
        if message.get("jsonrpc") != JSONRPC_VERSION:
            return _error_response(message.get("id"), INVALID_REQUEST, "Invalid Request")

        return self._handle_message(message)

    def _handle_message(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        is_notification = "id" not in message
        message_id = message.get("id")
        method = message.get("method")

        if not isinstance(method, str) or not method:
            if is_notification:
                return None
            return _error_response(message_id, INVALID_REQUEST, "Invalid Request")

        if method.startswith("notifications/"):
            return None

        params = message.get("params")
        if params is None:
            params = {}

        handler = self._method_handlers.get(method)
        if handler is None:
            if is_notification:
                return None
            return _error_response(message_id, METHOD_NOT_FOUND, f"Method not found: {method}")

        try:
            result = handler(params)
        except _RpcError as error:
            if is_notification:
                return None
            return _error_response(message_id, error.code, error.message, error.data)
        except Exception as error:  # defensive: never break the serve loop
            if is_notification:
                return None
            return _error_response(message_id, INTERNAL_ERROR, f"Internal error: {error}")

        if is_notification:
            return None
        return {"jsonrpc": JSONRPC_VERSION, "id": message_id, "result": result}

    def _handle_initialize(self, params: Mapping[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion") if isinstance(params, Mapping) else None
        # Negotiate: honor a recognized requested version, otherwise fall back to
        # the server default instead of echoing an unknown/empty value.
        if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
            protocol_version = requested
        else:
            protocol_version = DEFAULT_PROTOCOL_VERSION
        return {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self._name, "version": self._version},
        }

    def _handle_ping(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        return {}

    def _handle_tools_list(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        tools = [
            {
                "name": contract.name,
                "description": contract.purpose,
                "inputSchema": deepcopy(contract.input_schema),
            }
            for contract in self._dispatcher.list_tool_contracts()
        ]
        return {"tools": tools}

    def _handle_tools_call(self, params: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(params, Mapping):
            raise _RpcError(INVALID_PARAMS, "tools/call params must be an object")

        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise _RpcError(INVALID_PARAMS, "tools/call requires a string tool name")

        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, Mapping):
            raise _RpcError(INVALID_PARAMS, "tools/call arguments must be an object")

        payload = self._dispatcher.dispatch_tool_call(name, arguments)
        if payload.get("ok"):
            result = payload.get("result", {})
            content_text = json.dumps(result, ensure_ascii=False)
            response: dict[str, Any] = {
                "content": [{"type": "text", "text": content_text}],
                "isError": False,
            }
            if isinstance(result, Mapping):
                response["structuredContent"] = deepcopy(dict(result))
            return response

        # The dispatcher always attaches a structured ``error`` when ``ok`` is
        # false; a missing one is a contract violation, not something to mask.
        error = payload["error"]
        return {
            "content": [{"type": "text", "text": json.dumps(error, ensure_ascii=False)}],
            "isError": True,
        }


def _error_response(
    message_id: Any,
    code: int,
    message: str,
    data: Any | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": message_id, "error": error}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the stdio MCP server. Only the ``serve`` subcommand is supported."""

    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "serve"
    if command != "serve":
        sys.stderr.write(f"unknown command: {command}\n")
        return 2

    server = McpStdioServer(build_default_dispatcher())
    server.serve(sys.stdin, sys.stdout)
    return 0


__all__ = [
    "DEFAULT_PROTOCOL_VERSION",
    "McpStdioServer",
    "SERVER_NAME",
    "SERVER_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "build_default_dispatcher",
    "main",
]
