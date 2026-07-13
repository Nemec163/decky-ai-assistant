from __future__ import annotations

import io
import json
import tempfile
import unittest

from deck_assistant_mcp import (
    DEFAULT_PROTOCOL_VERSION,
    SERVER_NAME,
    SUPPORTED_PROTOCOL_VERSIONS,
    TOOL_CONTRACTS,
    McpStdioServer,
    build_default_dispatcher,
)


def _run_messages(messages, *, home_path=None):
    dispatcher = build_default_dispatcher(home_path=home_path)
    server = McpStdioServer(dispatcher)
    stream_in = io.StringIO("".join(json.dumps(message) + "\n" for message in messages))
    stream_out = io.StringIO()
    server.serve(stream_in, stream_out)
    responses = []
    for line in stream_out.getvalue().splitlines():
        if line.strip():
            responses.append(json.loads(line))
    return responses


def _run_raw_lines(lines, *, home_path=None):
    """Feed already-serialized JSON lines and return parsed output lines."""

    dispatcher = build_default_dispatcher(home_path=home_path)
    server = McpStdioServer(dispatcher)
    stream_in = io.StringIO("".join(line + "\n" for line in lines))
    stream_out = io.StringIO()
    server.serve(stream_in, stream_out)
    return [
        json.loads(line)
        for line in stream_out.getvalue().splitlines()
        if line.strip()
    ]


class McpStdioServerTests(unittest.TestCase):
    def test_initialize_reports_server_info_and_tool_capability(self) -> None:
        responses = _run_messages(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"},
                }
            ]
        )

        self.assertEqual(len(responses), 1)
        result = responses[0]["result"]
        self.assertEqual(result["serverInfo"]["name"], SERVER_NAME)
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertIn("tools", result["capabilities"])

    def test_tools_list_matches_catalog(self) -> None:
        responses = _run_messages(
            [{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        )

        tools = responses[0]["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertEqual(len(tools), len(TOOL_CONTRACTS))
        self.assertIn("get_storage_report", names)
        self.assertIn("inspect_current_game", names)
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertTrue(tool["description"])

    def test_initialized_notification_has_no_response(self) -> None:
        responses = _run_messages(
            [{"jsonrpc": "2.0", "method": "notifications/initialized"}]
        )

        self.assertEqual(responses, [])

    def test_tools_call_read_only_tool_succeeds(self) -> None:
        responses = _run_messages(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "inspect_current_game", "arguments": {}},
                }
            ]
        )

        result = responses[0]["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["content"][0]["type"], "text")
        self.assertIsNone(result["structuredContent"]["game"])

    def test_tools_call_storage_report_reads_bounded_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as home_dir:
            responses = _run_messages(
                [
                    {
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {"name": "get_storage_report", "arguments": {}},
                    }
                ],
                home_path=home_dir,
            )

        result = responses[0]["result"]
        self.assertFalse(result["isError"])
        self.assertIn("sections", result["structuredContent"])

    def test_tools_call_unknown_tool_returns_structured_error(self) -> None:
        responses = _run_messages(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {
                        "name": "missing_tool",
                        "arguments": {},
                    },
                }
            ]
        )

        result = responses[0]["result"]
        self.assertTrue(result["isError"])
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["code"], "unknown_tool")

    def test_unknown_method_returns_method_not_found(self) -> None:
        responses = _run_messages(
            [{"jsonrpc": "2.0", "id": 6, "method": "does/not/exist"}]
        )

        self.assertEqual(responses[0]["error"]["code"], -32601)

    def test_parse_error_is_reported(self) -> None:
        dispatcher = build_default_dispatcher()
        server = McpStdioServer(dispatcher)
        stream_out = io.StringIO()
        server.serve(io.StringIO("{not json}\n"), stream_out)
        response = json.loads(stream_out.getvalue().splitlines()[0])
        self.assertEqual(response["error"]["code"], -32700)

    def test_initialize_falls_back_for_unknown_protocol_version(self) -> None:
        for requested in ("1999-01-01", "", 5, None):
            with self.subTest(requested=requested):
                responses = _run_messages(
                    [
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {"protocolVersion": requested},
                        }
                    ]
                )
                self.assertEqual(
                    responses[0]["result"]["protocolVersion"],
                    DEFAULT_PROTOCOL_VERSION,
                )

    def test_initialize_honors_each_supported_protocol_version(self) -> None:
        for requested in SUPPORTED_PROTOCOL_VERSIONS:
            with self.subTest(requested=requested):
                responses = _run_messages(
                    [
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {"protocolVersion": requested},
                        }
                    ]
                )
                self.assertEqual(
                    responses[0]["result"]["protocolVersion"],
                    requested,
                )

    def test_batch_of_two_calls_returns_single_json_array(self) -> None:
        batch = json.dumps(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"},
                },
            ]
        )

        output_lines = _run_raw_lines([batch])

        # A batch yields exactly one output line containing a JSON array.
        self.assertEqual(len(output_lines), 1)
        responses = output_lines[0]
        self.assertIsInstance(responses, list)
        self.assertEqual(len(responses), 2)
        by_id = {response["id"]: response for response in responses}
        self.assertIn("tools", by_id[1]["result"])
        self.assertEqual(by_id[2]["result"]["protocolVersion"], "2025-06-18")

    def test_batch_mixing_call_and_notification_returns_only_call_response(self) -> None:
        batch = json.dumps(
            [
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 7, "method": "ping"},
            ]
        )

        output_lines = _run_raw_lines([batch])

        self.assertEqual(len(output_lines), 1)
        responses = output_lines[0]
        self.assertIsInstance(responses, list)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], 7)
        self.assertEqual(responses[0]["result"], {})

    def test_batch_of_only_notifications_emits_nothing(self) -> None:
        batch = json.dumps(
            [
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "method": "notifications/cancelled"},
            ]
        )

        output_lines = _run_raw_lines([batch])

        self.assertEqual(output_lines, [])

    def test_empty_batch_is_rejected_as_invalid_request(self) -> None:
        output_lines = _run_raw_lines(["[]"])

        self.assertEqual(len(output_lines), 1)
        response = output_lines[0]
        self.assertIsInstance(response, dict)
        self.assertIsNone(response["id"])
        self.assertEqual(response["error"]["code"], -32600)

    def test_batch_reports_unknown_tool_while_serving_other_calls(self) -> None:
        batch = json.dumps(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "missing_tool",
                        "arguments": {},
                    },
                },
            ]
        )

        responses = _run_raw_lines([batch])[0]
        by_id = {response["id"]: response for response in responses}
        self.assertIn("tools", by_id[1]["result"])
        failed = by_id[2]["result"]
        self.assertTrue(failed["isError"])
        payload = json.loads(failed["content"][0]["text"])
        self.assertEqual(payload["code"], "unknown_tool")


if __name__ == "__main__":
    unittest.main()
