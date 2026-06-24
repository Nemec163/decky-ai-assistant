from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest import mock


sys.modules.setdefault(
    "decky",
    types.SimpleNamespace(
        logger=types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
        )
    ),
)

from main import Plugin, _clipboard_process_text, _extract_terminal_links, _read_system_clipboard_text


class TerminalLinkExtractionTests(unittest.TestCase):
    def test_rejects_partial_oauth_query_parameter(self) -> None:
        output = (
            "Open: https://claude.com/cai/oauth/authorize?code=true"
            "&client_id=client-id&response_typ\n"
        )

        self.assertEqual(_extract_terminal_links(output), [])

    def test_unwraps_wrapped_claude_oauth_url(self) -> None:
        expected = (
            "https://claude.com/cai/oauth/authorize?code=true"
            "&client_id=client-id&response_type=code"
            "&redirect_uri=http%3A%2F%2F127.0.0.1%3A43829%2Fcallback"
            "&state=state-value&code_challenge=challenge-value"
            "&code_challenge_method=S256"
        )
        output = (
            "Open this link:\n"
            "https://claude.com/cai/oauth/authorize?code=true&client_id=client-id&response_typ\n"
            "e=code&redirect_uri=http%3A%2F%2F127.0.0.1%3A43829%2Fcallback&state=state-\n"
            "value&code_challenge=challenge-value&code_challenge_method=S256\n"
        )

        self.assertEqual(_extract_terminal_links(output), [expected])

    def test_does_not_append_next_prompt_after_wrapped_oauth_url(self) -> None:
        expected = (
            "https://claude.com/cai/oauth/authorize?code=true"
            "&client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e"
            "&response_type=code"
            "&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback"
            "&scope=org%3Acreate_api_key+user%3Aprofile+user%3Ainference"
            "+user%3Asessions%3Aclaude_code+user%3Amcp_servers+user%3Afile_upload"
            "&code_challenge=challenge-value"
            "&code_challenge_method=S256"
            "&state=_Ns8MT-tS9IQ9mz0otvuCCBvcZm6C-VswN_6xEV5mlU"
        )
        output = (
            "Browser didn't open? Use the url below to sign in (c to copy)\n"
            "https://claude.com/cai/oauth/authorize?code=true&client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e&respon\n"
            "se_type=code&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback&scope=org%3Acrea\n"
            "te_api_key+user%3Aprofile+user%3Ainference+user%3Asessions%3Aclaude_code+user%3Amcp_servers+user%3Afil\n"
            "e_upload&code_challenge=challenge-value&code_challenge_method=S256&state=_Ns8MT-tS9IQ9mz0otvuCCBvcZm6C-VswN_6xEV5mlU\n"
            "Paste code here if prompted >"
        )

        self.assertEqual(_extract_terminal_links(output), [expected])

    def test_unwraps_ansi_colored_crcrlf_claude_oauth_url(self) -> None:
        expected = (
            "https://claude.com/cai/oauth/authorize?code=true"
            "&client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e"
            "&response_type=code"
            "&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback"
            "&scope=org%3Acreate_api_key+user%3Aprofile+user%3Ainference"
            "+user%3Asessions%3Aclaude_code+user%3Amcp_servers+user%3Afile_upload"
            "&code_challenge=86lXaXDS4AytHWZ1zb8r3tOU6d9uzP_1zXQUDJGXJik"
            "&code_challenge_method=S256"
            "&state=WwglWxrFwnLVRfAPVLiBApQWYksOXhWhrF81n-sIrGs"
        )
        output = (
            "\x1b[38;2;153;153;153mBrowser didn't open? Use the url below to sign in (c to copy)\x1b[39m\r\r\n"
            "\r\r\n"
            "\x1b[38;2;153;153;153mhttps://claude.com/cai/oauth/authorize?code=true&client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e&respon\x1b[39m\n\n"
            "\x1b[38;2;153;153;153mse_type=code&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback&scope=org%3Acrea\x1b[39m\n\n"
            "\x1b[38;2;153;153;153mte_api_key+user%3Aprofile+user%3Ainference+user%3Asessions%3Aclaude_code+user%3Amcp_servers+user%3Afil\x1b[39m\n\n"
            "\x1b[38;2;153;153;153me_upload&code_challenge=86lXaXDS4AytHWZ1zb8r3tOU6d9uzP_1zXQUDJGXJik&code_challenge_method=S256&state=W\x1b[39m\n\n"
            "\x1b[38;2;153;153;153mwglWxrFwnLVRfAPVLiBApQWYksOXhWhrF81n-sIrGs\x1b[39m\r\r\n"
            "\r\r\n"
            "Pastecodehereifprompted>"
        )

        self.assertEqual(_extract_terminal_links(output), [expected])

    def test_ignores_plain_non_auth_url(self) -> None:
        output = "See the docs at https://example.com/guide/getting-started for details.\n"

        self.assertEqual(_extract_terminal_links(output), [])

    def test_ignores_bare_repo_url(self) -> None:
        output = "Cloning https://github.com/owner/repo into the workspace...\n"

        self.assertEqual(_extract_terminal_links(output), [])

    def test_detects_auth_link_by_surrounding_login_context(self) -> None:
        link = "https://example.com/start?session=abc123def456"
        output = f"To sign in, open this link in your browser:\n{link}\n"

        self.assertEqual(_extract_terminal_links(output), [link])

    def test_detects_auth_link_by_url_shape_without_context(self) -> None:
        link = "https://id.example.com/connect/begin?session=abc123def456"
        output = f"{link}\n"

        self.assertEqual(_extract_terminal_links(output), [link])

    def test_extracts_url_from_osc8_hyperlink_escape(self) -> None:
        output = "\x1b]8;;https://example.com/oauth/authorize?state=ready\x07Open link\x1b]8;;\x07"

        self.assertEqual(
            _extract_terminal_links(output),
            ["https://example.com/oauth/authorize?state=ready"],
        )

    def test_ignores_codex_local_login_server_url(self) -> None:
        expected = (
            "https://auth.openai.com/oauth/authorize?response_type=code"
            "&client_id=app_EMoamEEZ73f0CkXaXp7hrann"
            "&redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback"
            "&scope=openid%20profile%20email%20offline_access"
            "&code_challenge=xpjb2UZ7aYfqOmLreUfdSvWxN9RdncFQn4oPmbEZmkE"
            "&code_challenge_method=S256"
            "&state=7aJ3GEGVcu1B774vdbdj42WuCrpAkgE3aRn06tHO6Wk"
            "&originator=codex_cli_rs"
        )
        output = (
            "Starting local login server on http://localhost:1455.\n"
            "If your browser did not open, navigate to this URL to authenticate:\n\n"
            f"{expected}\n\n"
            "On a remote or headless machine? Use `codex login --device-auth` instead.\n"
        )

        self.assertEqual(_extract_terminal_links(output), [expected])

    def test_get_terminal_links_rescans_output_tail(self) -> None:
        expected = (
            "https://claude.com/cai/oauth/authorize?code=true"
            "&client_id=client-id&response_type=code"
            "&redirect_uri=http%3A%2F%2F127.0.0.1%3A43829%2Fcallback"
            "&state=state-value&code_challenge=challenge-value"
            "&code_challenge_method=S256"
        )
        output = (
            "Browser didn't open? Use the url below to sign in (c to copy)\n"
            "https://claude.com/cai/oauth/authorize?code=true&client_id=client-id&response_typ\n"
            "e=code&redirect_uri=http%3A%2F%2F127.0.0.1%3A43829%2Fcallback&state=state-\n"
            "value&code_challenge=challenge-value&code_challenge_method=S256\n"
            "Paste code here if prompted >"
        )
        plugin = Plugin()
        plugin.terminal_links = {}
        plugin.terminal_link_buffers = {}
        plugin.terminal_output_tails = {}

        plugin._record_terminal_output("session-1", output)

        self.assertEqual(plugin._terminal_session_links("session-1"), [])
        result = asyncio.run(plugin.get_terminal_session_links({"session_id": "session-1"}))
        self.assertEqual(result["links"], [expected])
        self.assertEqual(result["output_tail"], output)

    def test_auth_completion_suppresses_stale_tail_link(self) -> None:
        output = (
            "Open this link:\n"
            "https://example.com/oauth/authorize?state=ready\n"
            "Login successful\n"
        )
        plugin = Plugin()
        plugin.terminal_links = {}
        plugin.terminal_link_buffers = {}
        plugin.terminal_output_tails = {}
        plugin.terminal_link_suppressed = set()

        plugin._record_terminal_output("session-1", output)
        result = asyncio.run(plugin.get_terminal_session_links({"session_id": "session-1"}))

        self.assertEqual(result["links"], [])
        self.assertEqual(result["output_tail"], output)

    def test_clear_terminal_links_suppresses_tail_rescan_until_new_link_output(self) -> None:
        first_link = "https://example.com/oauth/authorize?state=first"
        second_link = "https://example.com/oauth/authorize?state=second"
        plugin = Plugin()
        plugin.terminal_links = {}
        plugin.terminal_link_buffers = {}
        plugin.terminal_output_tails = {}
        plugin.terminal_link_suppressed = set()

        plugin._record_terminal_output("session-1", f"{first_link}\n")
        self.assertEqual(
            asyncio.run(plugin.get_terminal_session_links({"session_id": "session-1"}))["links"],
            [first_link],
        )

        self.assertEqual(
            asyncio.run(plugin.clear_terminal_session_links({"session_id": "session-1"}))["links"],
            [],
        )
        self.assertEqual(
            asyncio.run(plugin.get_terminal_session_links({"session_id": "session-1"}))["links"],
            [],
        )

        self.assertEqual(plugin._record_terminal_links("session-1", f"{second_link}\n"), [second_link])


class SystemClipboardTests(unittest.TestCase):
    def test_clipboard_process_text_removes_one_trailing_newline(self) -> None:
        self.assertEqual(_clipboard_process_text("code-value\n"), "code-value")

    def test_returns_x11_clipboard_result_when_available(self) -> None:
        with mock.patch(
            "main._read_x11_clipboard_text",
            return_value={"text": "browser-code", "source": "x11::0:CLIPBOARD", "error": None},
        ):
            result = _read_system_clipboard_text()

        self.assertEqual(result["text"], "browser-code")
        self.assertEqual(result["source"], "x11::0:CLIPBOARD")
        self.assertIsNone(result["error"])

    def test_reports_when_x11_reader_is_unavailable(self) -> None:
        with mock.patch("main._read_x11_clipboard_text", return_value=None):
            result = _read_system_clipboard_text()

        self.assertEqual(result["text"], "")
        self.assertIsNone(result["source"])
        self.assertEqual(result["error"], "no X11 clipboard reader available")


if __name__ == "__main__":
    unittest.main()
