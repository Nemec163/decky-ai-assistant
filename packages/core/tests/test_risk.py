from __future__ import annotations

import unittest

from deck_assistant_core import (
    RiskLevel,
    classify_command,
    classify_file_edit,
    max_risk,
)


class RiskClassificationTests(unittest.TestCase):
    def test_read_only_commands_stay_read_only(self) -> None:
        self.assertEqual(classify_command(["df", "-h"]), RiskLevel.READ_ONLY)
        self.assertEqual(classify_command(["bash", "--version"]), RiskLevel.READ_ONLY)
        self.assertEqual(classify_command(["codex", "--version"]), RiskLevel.READ_ONLY)
        self.assertEqual(classify_command(["codex", "login", "status"]), RiskLevel.READ_ONLY)

    def test_shell_strings_and_danger_commands_are_danger(self) -> None:
        self.assertEqual(classify_command("rm -rf /tmp/example"), RiskLevel.DANGER)
        self.assertEqual(classify_command(["bash", "-lc", "pwd"]), RiskLevel.DANGER)
        self.assertEqual(classify_command(["sudo", "pacman", "-Syu"]), RiskLevel.DANGER)
        self.assertEqual(classify_command(["find", "/tmp/example", "-delete"]), RiskLevel.DANGER)
        self.assertEqual(
            classify_command(["find", "/tmp/example", "-exec", "rm", "{}", ";"]),
            RiskLevel.DANGER,
        )
        self.assertEqual(classify_command(["python3", "-c", "print('hidden')"]), RiskLevel.DANGER)

    def test_write_commands_are_not_read_only(self) -> None:
        self.assertEqual(
            classify_command(["curl", "-o", "/tmp/page.html", "https://example.com"]),
            RiskLevel.LOW_WRITE,
        )
        self.assertEqual(
            classify_command(["curl", "-o/tmp/page.html", "https://example.com"]),
            RiskLevel.LOW_WRITE,
        )
        self.assertEqual(
            classify_command(["wget", "-O", "/tmp/page.html", "https://example.com"]),
            RiskLevel.LOW_WRITE,
        )
        self.assertEqual(
            classify_command(["wget", "-O/tmp/page.html", "https://example.com"]),
            RiskLevel.LOW_WRITE,
        )
        self.assertEqual(
            classify_command(["wget", "--output-document=/tmp/page.html", "https://example.com"]),
            RiskLevel.LOW_WRITE,
        )
        self.assertEqual(
            classify_command(["flatpak", "override", "--filesystem=/tmp", "com.example.App"]),
            RiskLevel.HIGH_WRITE,
        )
        self.assertEqual(
            classify_command(["sed", "-i", "s/a/b/", "/tmp/file"]),
            RiskLevel.HIGH_WRITE,
        )
        self.assertEqual(classify_command(["env", "sudo", "pacman", "-Syu"]), RiskLevel.DANGER)
        self.assertEqual(classify_command(["unknown-tool", "arg"]), RiskLevel.HIGH_WRITE)

    def test_file_edit_paths_drive_risk(self) -> None:
        self.assertEqual(
            classify_file_edit("/tmp/decky-ai/config.json", "modify"),
            RiskLevel.LOW_WRITE,
        )
        self.assertEqual(
            classify_file_edit("/home/deck/.steam/steam/userdata/config.vdf", "modify"),
            RiskLevel.HIGH_WRITE,
        )
        self.assertEqual(classify_file_edit("/etc/fstab", "modify"), RiskLevel.DANGER)
        self.assertEqual(
            classify_file_edit("/tmp/current-action/output.tmp", "delete", temporary=True),
            RiskLevel.LOW_WRITE,
        )
        self.assertEqual(classify_file_edit("/tmp/user-file.txt", "delete"), RiskLevel.DANGER)

    def test_credential_like_paths_are_classified_as_display_metadata(self) -> None:
        self.assertEqual(
            classify_file_edit("/home/deck/.config/codex/auth.json", "read"),
            RiskLevel.READ_ONLY,
        )
        self.assertEqual(
            classify_command(["cat", "/home/deck/.ssh/id_ed25519"]),
            RiskLevel.READ_ONLY,
        )

    def test_max_risk_returns_highest_level(self) -> None:
        self.assertEqual(
            max_risk(RiskLevel.READ_ONLY, RiskLevel.HIGH_WRITE, RiskLevel.LOW_WRITE),
            RiskLevel.HIGH_WRITE,
        )


if __name__ == "__main__":
    unittest.main()
