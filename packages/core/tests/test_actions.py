from __future__ import annotations

import unittest

from deck_assistant_core import (
    ActionValidationError,
    ApprovalRiskMismatch,
    BackupSpec,
    CommandSpec,
    FileEditSpec,
    RiskLevel,
    RollbackStep,
    StagedAction,
    StagedActionNotFound,
    StagedActionStore,
)


class StagedActionTests(unittest.TestCase):
    def test_create_computes_risk_from_parts(self) -> None:
        action = StagedAction.create(
            title="Update Flatpak permission",
            commands=(
                CommandSpec.from_sequence(
                    ["flatpak", "override", "--filesystem=/tmp", "com.example.App"]
                ),
            ),
        )

        self.assertEqual(action.risk, RiskLevel.HIGH_WRITE)

    def test_declared_risk_cannot_be_lower_than_computed_risk(self) -> None:
        with self.assertRaises(ActionValidationError):
            StagedAction.create(
                title="Underclassified action",
                commands=(CommandSpec.from_sequence(["sudo", "pacman", "-Syu"]),),
                risk=RiskLevel.LOW_WRITE,
            )

    def test_command_spec_rejects_shell_string(self) -> None:
        with self.assertRaises(ActionValidationError):
            CommandSpec.from_sequence("rm -rf /tmp/example")

    def test_high_write_requires_backup_or_note_and_file_diff(self) -> None:
        action = StagedAction.create(
            title="Edit Steam config",
            file_edits=(
                FileEditSpec(
                    path="/home/deck/.steam/steam/config/config.vdf",
                    operation="modify",
                ),
            ),
        )

        with self.assertRaises(ActionValidationError):
            action.validate_for_approval()

        approval_ready = StagedAction.create(
            title="Edit Steam config",
            file_edits=(
                FileEditSpec(
                    path="/home/deck/.steam/steam/config/config.vdf",
                    operation="modify",
                    diff="--- before\n+++ after\n@@\n-old\n+new\n",
                ),
            ),
            backups=(
                BackupSpec(
                    source_path="/home/deck/.steam/steam/config/config.vdf",
                    backup_path="/home/deck/.steam/steam/config/config.vdf.bak",
                    reason="Restore previous Steam config if the edit fails.",
                ),
            ),
        )

        approval_ready.validate_for_approval()

    def test_high_write_create_requires_exact_diff(self) -> None:
        action = StagedAction.create(
            title="Create Steam config",
            file_edits=(
                FileEditSpec(
                    path="/home/deck/.steam/steam/config/new-config.vdf",
                    operation="create",
                ),
            ),
            backup_note="New file; no previous content exists.",
        )

        with self.assertRaises(ActionValidationError):
            action.validate_for_approval()

        approval_ready = StagedAction.create(
            title="Create Steam config",
            file_edits=(
                FileEditSpec(
                    path="/home/deck/.steam/steam/config/new-config.vdf",
                    operation="create",
                    diff="--- /dev/null\n+++ new-config.vdf\n@@\n+setting=value\n",
                ),
            ),
            backup_note="New file; no previous content exists.",
        )

        approval_ready.validate_for_approval()

    def test_danger_requires_rollback_note_or_steps(self) -> None:
        action = StagedAction.create(
            title="System package operation",
            commands=(CommandSpec.from_sequence(["sudo", "pacman", "-Syu"]),),
            backup_note="System package manager operations do not have a single file backup.",
        )

        with self.assertRaises(ActionValidationError):
            action.validate_for_approval()

        approval_ready = StagedAction.create(
            title="System package operation",
            commands=(CommandSpec.from_sequence(["sudo", "pacman", "-Syu"]),),
            backup_note="System package manager operations do not have a single file backup.",
            rollback=(
                RollbackStep(
                    description="Use the package manager log to identify changed packages."
                ),
            ),
        )

        approval_ready.validate_for_approval()

    def test_round_trip_dict_preserves_contract(self) -> None:
        action = StagedAction.create(
            title="Create plugin config",
            file_edits=(
                FileEditSpec(
                    path="/home/deck/homebrew/settings/decky-ai.json",
                    operation="create",
                ),
            ),
            backup_note="New file; no previous content exists.",
        )

        restored = StagedAction.from_dict(action.to_dict())

        self.assertEqual(restored.id, action.id)
        self.assertEqual(restored.title, action.title)
        self.assertEqual(restored.risk, RiskLevel.LOW_WRITE)
        self.assertEqual(restored.file_edits[0].path, "/home/deck/homebrew/settings/decky-ai.json")

    def test_render_approval_plan_for_read_only_action(self) -> None:
        action = StagedAction.create(
            title="Inspect storage usage",
            commands=(CommandSpec.from_sequence(["ls", "/home/deck"]),),
        )

        plan = action.render_approval_plan()

        self.assertEqual(plan["risk"], RiskLevel.READ_ONLY.value)
        self.assertEqual(plan["approval_gate"]["type"], "user_request")
        self.assertFalse(plan["approval_gate"]["requires_plan"])
        self.assertEqual(
            plan["commands"],
            [
                {
                    "argv": ["ls", "/home/deck"],
                    "risk": RiskLevel.READ_ONLY.value,
                    "has_redactions": False,
                }
            ],
        )
        self.assertEqual(plan["summary"]["command_count"], 1)
        self.assertEqual(plan["summary"]["file_edit_count"], 0)

    def test_render_approval_plan_for_low_write_action(self) -> None:
        action = StagedAction.create(
            title="Create local marker",
            commands=(CommandSpec.from_sequence(["touch", "/tmp/decky-ai-assistant-marker"]),),
        )

        plan = action.render_approval_plan()

        self.assertEqual(plan["risk"], RiskLevel.LOW_WRITE.value)
        self.assertEqual(plan["approval_gate"]["type"], "approval_required")
        self.assertTrue(plan["approval_gate"]["requires_plan"])
        self.assertFalse(plan["approval_gate"]["requires_exact_commands_or_diffs"])
        self.assertEqual(
            plan["commands"][0]["argv"],
            ["touch", "/tmp/decky-ai-assistant-marker"],
        )

    def test_render_approval_plan_for_high_write_action(self) -> None:
        action = StagedAction.create(
            title="Edit Steam config",
            file_edits=(
                FileEditSpec(
                    path="/home/deck/.steam/steam/config/config.vdf",
                    operation="modify",
                    diff="--- before\n+++ after\n@@\n-old\n+new\n",
                ),
            ),
            backups=(
                BackupSpec(
                    source_path="/home/deck/.steam/steam/config/config.vdf",
                    backup_path="/home/deck/.steam/steam/config/config.vdf.bak",
                    reason="Restore previous config if token=abc replacement is wrong.",
                ),
            ),
        )

        plan = action.render_approval_plan()

        self.assertEqual(plan["risk"], RiskLevel.HIGH_WRITE.value)
        self.assertEqual(plan["approval_gate"]["type"], "approval_required")
        self.assertTrue(plan["approval_gate"]["requires_exact_commands_or_diffs"])
        self.assertTrue(plan["approval_gate"]["requires_backup_or_note"])
        self.assertEqual(
            plan["file_edits"][0],
            {
                "path": "/home/deck/.steam/steam/config/config.vdf",
                "operation": "modify",
                "temporary": False,
                "risk": RiskLevel.HIGH_WRITE.value,
                "has_diff": True,
                "diff_line_count": 5,
            },
        )
        self.assertNotIn("diff", plan["file_edits"][0])
        self.assertEqual(
            plan["backups"][0]["reason"],
            "Restore previous config if token= [REDACTED] replacement is wrong.",
        )

    def test_render_approval_plan_for_danger_action(self) -> None:
        action = StagedAction.create(
            title="System package operation",
            commands=(CommandSpec.from_sequence(["sudo", "pacman", "-Syu"]),),
            backup_note="Reference package log token=super-secret before system changes.",
            rollback=(
                RollbackStep(
                    description="Review password=hidden package history before retrying.",
                    command=CommandSpec.from_sequence(["sudo", "pacman", "-Q"]),
                ),
            ),
            rollback_note="Use recovery media if rollback is not enough.",
        )

        plan = action.render_approval_plan()

        self.assertEqual(plan["risk"], RiskLevel.DANGER.value)
        self.assertEqual(
            plan["approval_gate"]["type"],
            "separate_confirmation_required",
        )
        self.assertTrue(plan["approval_gate"]["requires_exact_commands_or_diffs"])
        self.assertTrue(plan["approval_gate"]["requires_backup_or_note"])
        self.assertTrue(plan["approval_gate"]["requires_separate_confirmation"])
        self.assertEqual(plan["backup_note"], "Reference package log token= [REDACTED] before system changes.")
        self.assertEqual(
            plan["rollback"][0]["description"],
            "Review password= [REDACTED] package history before retrying.",
        )
        self.assertEqual(
            plan["rollback"][0]["command"]["argv"],
            ["sudo", "pacman", "-Q"],
        )

    def test_render_approval_plan_redacts_sensitive_values_and_paths(self) -> None:
        action = StagedAction.create(
            title="Inspect remote headers",
            commands=(
                CommandSpec.from_sequence(
                    [
                        "curl",
                        "--header",
                        "Authorization: Bearer secret-value",
                        "--user",
                        "deck:super-secret",
                        "https://deck:pw@example.com/api",
                    ]
                ),
                CommandSpec.from_sequence(
                    ["env", "OPENAI_API_KEY=super-secret", "printf", "hello"],
                    cwd="/home/deck/.config/codex/session",
                ),
            ),
        )

        plan = action.render_approval_plan()

        self.assertEqual(
            plan["commands"][0]["argv"],
            [
                "curl",
                "--header",
                "[REDACTED]",
                "--user",
                "[REDACTED]",
                "https://[REDACTED]@example.com/api",
            ],
        )
        self.assertTrue(plan["commands"][0]["has_redactions"])
        self.assertEqual(
            plan["commands"][1]["argv"],
            ["env", "OPENAI_API_KEY=[REDACTED]", "printf", "hello"],
        )
        self.assertEqual(plan["commands"][1]["cwd"], "[REDACTED_PATH]")
        self.assertTrue(plan["commands"][1]["has_redactions"])

    def test_url_credentials_are_redacted_exactly_once(self) -> None:
        # M3: URL redaction must run a single time per argv element. A doubly-applied
        # redaction would corrupt the already-substituted "[REDACTED]@" marker.
        action = StagedAction.create(
            title="Fetch with embedded URL credentials",
            commands=(
                CommandSpec.from_sequence(
                    ["curl", "https://deck:super-secret@example.com/api"]
                ),
            ),
        )

        plan = action.render_approval_plan()

        self.assertEqual(
            plan["commands"][0]["argv"],
            ["curl", "https://[REDACTED]@example.com/api"],
        )
        self.assertTrue(plan["commands"][0]["has_redactions"])

    def test_consolidated_keyword_vocabulary_keeps_known_redactions(self) -> None:
        # L4/L5: the canonical keyword set must still redact every previously
        # redacted form (assignment keys, sensitive flags, and inline secrets).
        command = CommandSpec.from_sequence(
            [
                "tool",
                "--token",
                "abc123",
                "OPENAI_API_KEY=sk-secret",
                "PASSWORD=hunter2",
                "REFRESH_TOKEN=rt-value",
                "CLIENT_SECRET=cs-value",
                "token=plainsecret",
            ]
        )

        argv = command.to_approval_dict()["argv"]

        self.assertEqual(
            argv,
            [
                "tool",
                "--token",
                "[REDACTED]",
                "OPENAI_API_KEY=[REDACTED]",
                "PASSWORD=[REDACTED]",
                "REFRESH_TOKEN=[REDACTED]",
                "CLIENT_SECRET=[REDACTED]",
                "token=[REDACTED]",
            ],
        )

    def test_header_short_flag_is_case_sensitive(self) -> None:
        sensitive = CommandSpec.from_sequence(["curl", "-H", "Authorization: Bearer raw"])
        help_flag = CommandSpec.from_sequence(["tool", "-h", "topic"])

        self.assertEqual(
            sensitive.to_approval_dict()["argv"],
            ["curl", "-H", "[REDACTED]"],
        )
        self.assertEqual(
            help_flag.to_approval_dict()["argv"],
            ["tool", "-h", "topic"],
        )

    def test_consolidated_keyword_vocabulary_is_not_weaker(self) -> None:
        # L5: tightening is allowed but never leaking more. Cookie/auth assignments,
        # which the canonical set now covers, must be redacted, not passed through.
        command = CommandSpec.from_sequence(
            [
                "tool",
                "MY_COOKIE=session-raw",
                "AUTH=raw-value",
                "harmless",
            ]
        )

        argv = command.to_approval_dict()["argv"]

        self.assertEqual(argv[0], "tool")
        self.assertEqual(argv[1], "MY_COOKIE=[REDACTED]")
        self.assertEqual(argv[2], "AUTH=[REDACTED]")
        self.assertEqual(argv[3], "harmless")


class StagedActionStoreTests(unittest.TestCase):
    def test_approval_token_is_released_only_after_approval(self) -> None:
        timestamps = iter(
            (
                "2026-06-21T10:00:00+00:00",
                "2026-06-21T10:05:00+00:00",
            )
        )
        store = StagedActionStore(
            token_factory=lambda: "opaque-token-1",
            timestamp_factory=lambda: next(timestamps),
        )
        action = StagedAction.create(
            title="Create plugin config",
            file_edits=(
                FileEditSpec(
                    path="/tmp/decky-ai-assistant/config.json",
                    operation="create",
                ),
            ),
        )

        staged = store.stage_action(action)

        self.assertEqual(staged.action_id, action.id)
        self.assertEqual(staged.risk, RiskLevel.LOW_WRITE)
        self.assertEqual(staged.staged_at, "2026-06-21T10:00:00+00:00")
        self.assertIsNone(staged.approved_at)
        with self.assertRaises(StagedActionNotFound):
            store.get_token_metadata("opaque-token-1")

        retrieved = store.get_staged_action(
            action.id,
            expected_risk=RiskLevel.LOW_WRITE,
        )
        self.assertEqual(retrieved.id, action.id)
        self.assertEqual(retrieved.file_edits[0].path, "/tmp/decky-ai-assistant/config.json")

        token_metadata = store.mark_approved(
            action.id,
            expected_risk=RiskLevel.LOW_WRITE,
        )

        self.assertEqual(token_metadata.token, "opaque-token-1")
        self.assertEqual(token_metadata.action_id, action.id)
        self.assertEqual(token_metadata.risk, RiskLevel.LOW_WRITE)
        self.assertEqual(token_metadata.issued_at, "2026-06-21T10:05:00+00:00")
        self.assertEqual(token_metadata.approved_at, "2026-06-21T10:05:00+00:00")
        self.assertEqual(
            store.get_staged_metadata(action.id).approved_at,
            "2026-06-21T10:05:00+00:00",
        )
        self.assertEqual(
            store.get_approved_action(
                action.id,
                "opaque-token-1",
                expected_risk=RiskLevel.LOW_WRITE,
            ).approved_by_user_at,
            "2026-06-21T10:05:00+00:00",
        )
        self.assertEqual(
            store.get_token_metadata("opaque-token-1").approved_at,
            "2026-06-21T10:05:00+00:00",
        )

    def test_risk_mismatch_rejects_retrieval_and_approval(self) -> None:
        store = StagedActionStore(
            token_factory=lambda: "opaque-token-2",
            timestamp_factory=lambda: "2026-06-21T11:00:00+00:00",
        )
        action = StagedAction.create(
            title="Create local marker",
            commands=(CommandSpec.from_sequence(["touch", "/tmp/decky-ai-assistant-marker"]),),
        )
        metadata = store.stage_action(action)

        self.assertEqual(metadata.risk, RiskLevel.LOW_WRITE)

        with self.assertRaises(ApprovalRiskMismatch):
            store.get_staged_action(
                action.id,
                expected_risk=RiskLevel.HIGH_WRITE,
            )

        with self.assertRaises(ApprovalRiskMismatch):
            store.mark_approved(
                action.id,
                expected_risk=RiskLevel.HIGH_WRITE,
            )

    def test_approved_action_requires_matching_id_token_and_risk(self) -> None:
        store = StagedActionStore(
            token_factory=lambda: "opaque-token-3",
            timestamp_factory=lambda: "2026-06-21T11:30:00+00:00",
        )
        action = StagedAction.create(
            title="Create local marker",
            commands=(CommandSpec.from_sequence(["touch", "/tmp/decky-ai-assistant-marker"]),),
        )
        store.stage_action(action)
        token = store.mark_approved(action.id, expected_risk=RiskLevel.LOW_WRITE)

        with self.assertRaises(StagedActionNotFound):
            store.get_approved_action(
                "different-action-id",
                token.token,
                expected_risk=RiskLevel.LOW_WRITE,
            )

        with self.assertRaises(StagedActionNotFound):
            store.get_approved_action(
                action.id,
                "wrong-token",
                expected_risk=RiskLevel.LOW_WRITE,
            )

        with self.assertRaises(ApprovalRiskMismatch):
            store.get_approved_action(
                action.id,
                token.token,
                expected_risk=RiskLevel.HIGH_WRITE,
            )

    def test_missing_or_unstaged_token_is_rejected(self) -> None:
        store = StagedActionStore()

        with self.assertRaises(StagedActionNotFound):
            store.get_staged_action(
                "missing-action-id",
                expected_risk=RiskLevel.LOW_WRITE,
            )

        with self.assertRaises(StagedActionNotFound):
            store.mark_approved(
                "missing-action-id",
                expected_risk=RiskLevel.LOW_WRITE,
            )

        with self.assertRaises(StagedActionNotFound):
            store.get_token_metadata("missing-token")

    def test_stage_action_requires_approval_ready_action(self) -> None:
        store = StagedActionStore(
            token_factory=lambda: "unused-token",
            timestamp_factory=lambda: "2026-06-21T12:00:00+00:00",
        )
        action = StagedAction.create(
            title="Edit Steam config",
            file_edits=(
                FileEditSpec(
                    path="/home/deck/.steam/steam/config/config.vdf",
                    operation="modify",
                ),
            ),
        )

        with self.assertRaises(ActionValidationError):
            store.stage_action(action)

        with self.assertRaises(StagedActionNotFound):
            store.get_token_metadata("unused-token")

    def test_duplicate_approval_is_rejected(self) -> None:
        tokens = iter(("opaque-token-4", "opaque-token-5"))
        store = StagedActionStore(
            token_factory=lambda: next(tokens),
            timestamp_factory=lambda: "2026-06-21T12:30:00+00:00",
        )
        action = StagedAction.create(
            title="Create local marker",
            commands=(CommandSpec.from_sequence(["touch", "/tmp/decky-ai-assistant-marker"]),),
        )

        store.stage_action(action)
        store.mark_approved(action.id, expected_risk=RiskLevel.LOW_WRITE)

        with self.assertRaises(ActionValidationError):
            store.mark_approved(action.id, expected_risk=RiskLevel.LOW_WRITE)


if __name__ == "__main__":
    unittest.main()
