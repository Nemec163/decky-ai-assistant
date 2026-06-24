from __future__ import annotations

import unittest

from deck_assistant_core import (
    is_bypass_enabled,
    normalize_profile_name,
    parse_profile_permissions,
    serialize_profile_permissions,
)


class NormalizeProfileNameTests(unittest.TestCase):
    def test_lowercases_and_strips_surrounding_whitespace(self) -> None:
        self.assertEqual(normalize_profile_name("  Codex  "), "codex")

    def test_collapses_disallowed_runs_into_single_dash(self) -> None:
        self.assertEqual(normalize_profile_name("My Custom CLI!!"), "my-custom-cli")
        self.assertEqual(normalize_profile_name("a   b"), "a-b")

    def test_preserves_allowed_punctuation(self) -> None:
        self.assertEqual(normalize_profile_name("setup-codex.auth_v2"), "setup-codex.auth_v2")

    def test_strips_leading_and_trailing_separators(self) -> None:
        self.assertEqual(normalize_profile_name("--codex--"), "codex")
        self.assertEqual(normalize_profile_name("._-claude-_."), "claude")

    def test_empty_or_separator_only_names_raise(self) -> None:
        for value in ("", "   ", "!!!", "._-", "---"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_profile_name(value)


class ParseProfilePermissionsTests(unittest.TestCase):
    def test_non_dict_inputs_are_default_off(self) -> None:
        for raw in (None, [], "codex", 0, 1, object()):
            with self.subTest(raw=raw):
                self.assertEqual(parse_profile_permissions(raw), {})

    def test_empty_dict_is_default_off(self) -> None:
        self.assertEqual(parse_profile_permissions({}), {})

    def test_only_truthy_bypass_entries_are_kept(self) -> None:
        raw = {
            "codex": {"bypass_permissions": True},
            "claude": {"bypass_permissions": False},
            "bash": {"other": True},
        }
        self.assertEqual(
            parse_profile_permissions(raw),
            {"codex": {"bypass_permissions": True}},
        )

    def test_malformed_entries_are_ignored(self) -> None:
        raw = {
            "good": {"bypass_permissions": True},
            "bad-value": "not-a-dict",
            "bad-list": ["bypass_permissions"],
            "!!!": {"bypass_permissions": True},  # name normalizes to empty -> skipped
        }
        self.assertEqual(
            parse_profile_permissions(raw),
            {"good": {"bypass_permissions": True}},
        )

    def test_names_are_normalized_as_keys(self) -> None:
        raw = {"  My CLI  ": {"bypass_permissions": True}}
        self.assertEqual(
            parse_profile_permissions(raw),
            {"my-cli": {"bypass_permissions": True}},
        )


class SerializeProfilePermissionsTests(unittest.TestCase):
    def test_only_enabled_entries_are_emitted(self) -> None:
        permissions = {
            "codex": {"bypass_permissions": True},
            "claude": {"bypass_permissions": False},
        }
        self.assertEqual(
            serialize_profile_permissions(permissions),
            {"codex": {"bypass_permissions": True}},
        )

    def test_output_is_sorted_by_key(self) -> None:
        permissions = {
            "zeta": {"bypass_permissions": True},
            "alpha": {"bypass_permissions": True},
            "Mike": {"bypass_permissions": True},
        }
        self.assertEqual(
            list(serialize_profile_permissions(permissions)),
            ["alpha", "mike", "zeta"],
        )

    def test_round_trip_parse_serialize_is_stable(self) -> None:
        raw = {
            "Codex": {"bypass_permissions": True},
            "claude": {"bypass_permissions": False},
            "broken": "x",
        }
        parsed = parse_profile_permissions(raw)
        serialized = serialize_profile_permissions(parsed)
        self.assertEqual(serialized, parsed)
        self.assertEqual(parse_profile_permissions(serialized), parsed)


class IsBypassEnabledTests(unittest.TestCase):
    def test_true_for_normalized_enabled_profile(self) -> None:
        permissions = parse_profile_permissions({"codex": {"bypass_permissions": True}})
        self.assertTrue(is_bypass_enabled(permissions, "codex"))
        self.assertTrue(is_bypass_enabled(permissions, "  Codex  "))

    def test_false_when_absent_or_disabled(self) -> None:
        permissions = parse_profile_permissions({"codex": {"bypass_permissions": True}})
        self.assertFalse(is_bypass_enabled(permissions, "claude"))
        self.assertFalse(is_bypass_enabled({}, "codex"))

    def test_false_for_unnormalizable_name(self) -> None:
        permissions = {"codex": {"bypass_permissions": True}}
        self.assertFalse(is_bypass_enabled(permissions, "!!!"))

    def test_false_when_stored_entry_is_malformed(self) -> None:
        self.assertFalse(is_bypass_enabled({"codex": "x"}, "codex"))
        self.assertFalse(is_bypass_enabled({"codex": {"bypass_permissions": False}}, "codex"))


if __name__ == "__main__":
    unittest.main()
