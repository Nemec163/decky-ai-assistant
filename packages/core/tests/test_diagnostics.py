from __future__ import annotations

import json
import os
import tempfile
import unittest

from deck_assistant_core import (
    MAX_PROTON_EXCERPT_CHARACTERS,
    MAX_STORAGE_PATH_PLAN_DEPTH,
    MAX_STORAGE_PATH_PLAN_LIBRARY_ROOTS,
    DiagnosticLimit,
    DiagnosticLimitUnit,
    DiagnosticStatus,
    DiagnosticsValidationError,
    ProtonLogExcerpt,
    ProtonLogReference,
    ProtonLogReport,
    StoragePathPlanEntry,
    StorageReport,
    StorageReportItem,
    StorageReportSection,
    StorageSectionName,
    plan_storage_report_paths,
    read_proton_logs,
    read_storage_report,
)


class StorageReportContractTests(unittest.TestCase):
    def test_storage_report_round_trips_with_inferred_statuses(self) -> None:
        item = StorageReportItem(
            path="/home/deck/.local/share/Steam/steamapps/shadercache/12345",
            bytes=2048,
            warnings=("Only the largest entries are shown.",),
        )
        section = StorageReportSection(
            name=StorageSectionName.SHADERCACHE,
            path="/home/deck/.local/share/Steam/steamapps/shadercache",
            bytes=4096,
            items=(item,),
            limits=(
                DiagnosticLimit(
                    name="max_items",
                    unit=DiagnosticLimitUnit.ITEMS,
                    value=20,
                    hit=True,
                ),
            ),
        )
        report = StorageReport(
            sections=(section,),
            warnings=("Only requested sections were included.",),
        )

        restored = StorageReport.from_dict(json.loads(json.dumps(report.to_dict())))

        self.assertEqual(item.status, DiagnosticStatus.WARNING)
        self.assertEqual(section.status, DiagnosticStatus.LIMITED)
        self.assertEqual(report.status, DiagnosticStatus.LIMITED)
        self.assertEqual(restored, report)
        self.assertEqual(restored.sections[0].limits[0].unit, DiagnosticLimitUnit.ITEMS)

    def test_storage_section_rejects_bytes_smaller_than_item_sum(self) -> None:
        with self.assertRaises(DiagnosticsValidationError):
            StorageReportSection(
                name=StorageSectionName.LOGS,
                path="/home/deck/.steam/logs",
                bytes=10,
                items=(
                    StorageReportItem(
                        path="/home/deck/.steam/logs/steam.log",
                        bytes=11,
                    ),
                ),
            )

    def test_declared_status_cannot_understate_item_warnings(self) -> None:
        with self.assertRaises(DiagnosticsValidationError):
            StorageReportItem(
                path="/home/deck/Pictures",
                bytes=1,
                status=DiagnosticStatus.OK,
                warnings=("This entry was normalized from a larger directory listing.",),
            )

    def test_limit_from_dict_rejects_non_boolean_hit_flag(self) -> None:
        with self.assertRaises(DiagnosticsValidationError):
            DiagnosticLimit.from_dict(
                {
                    "name": "max_items",
                    "unit": "items",
                    "value": 20,
                    "hit": "false",
                }
            )

    def test_storage_report_accepts_multi_library_sections_from_path_plan(self) -> None:
        plan = plan_storage_report_paths(
            steam_library_paths=("/run/media/mmcblk0p1/SteamLibrary",),
            sections=(StorageSectionName.SHADERCACHE, StorageSectionName.COMPATDATA),
        )
        sections = tuple(
            StorageReportSection(
                name=entry.section,
                path=entry.path,
                bytes=0,
                limits=(
                    DiagnosticLimit(
                        name="max_depth",
                        unit=DiagnosticLimitUnit.ITEMS,
                        value=entry.max_depth,
                    ),
                ),
            )
            for entry in plan
        )
        report = StorageReport(sections=sections)

        self.assertEqual(len(report.sections), 4)
        self.assertEqual(
            [section.name for section in report.sections],
            [
                StorageSectionName.SHADERCACHE,
                StorageSectionName.SHADERCACHE,
                StorageSectionName.COMPATDATA,
                StorageSectionName.COMPATDATA,
            ],
        )

    def test_storage_report_rejects_duplicate_section_path(self) -> None:
        section = StorageReportSection(
            name=StorageSectionName.LOGS,
            path="/home/deck/.local/share/Steam/logs",
            bytes=0,
        )

        with self.assertRaises(DiagnosticsValidationError):
            StorageReport(sections=(section, section))

    def test_storage_report_paths_must_be_absolute_and_non_sensitive(self) -> None:
        with self.assertRaises(DiagnosticsValidationError):
            StorageReportItem(path="relative/path", bytes=1)

        with self.assertRaises(DiagnosticsValidationError):
            StorageReportSection(
                name=StorageSectionName.LOGS,
                path="/home/deck/.config/codex",
                bytes=0,
            )

        with self.assertRaises(DiagnosticsValidationError):
            ProtonLogReference(path="relative/steam-12345.log")

        with self.assertRaises(DiagnosticsValidationError):
            ProtonLogReference(path="/home/deck/.ssh/id_ed25519")


class StoragePathPlanTests(unittest.TestCase):
    def test_storage_report_path_plan_defaults_are_deterministic_and_bounded(self) -> None:
        plan = plan_storage_report_paths(
            home_path="/home/deck//",
            steam_library_paths=(
                "/run/media/mmcblk0p1/SteamLibrary/steamapps",
                "/run/media/mmcblk0p1/SteamLibrary",
                "/home/deck/.local/share/Steam",
            ),
        )

        self.assertEqual(
            [entry.section for entry in plan],
            [
                StorageSectionName.SHADERCACHE,
                StorageSectionName.SHADERCACHE,
                StorageSectionName.COMPATDATA,
                StorageSectionName.COMPATDATA,
                StorageSectionName.LOGS,
                StorageSectionName.SCREENSHOTS_VIDEOS,
            ],
        )
        self.assertEqual(
            [entry.path for entry in plan],
            [
                "/home/deck/.local/share/Steam/steamapps/shadercache",
                "/run/media/mmcblk0p1/SteamLibrary/steamapps/shadercache",
                "/home/deck/.local/share/Steam/steamapps/compatdata",
                "/run/media/mmcblk0p1/SteamLibrary/steamapps/compatdata",
                "/home/deck/.local/share/Steam/logs",
                "/home/deck/.local/share/Steam/userdata",
            ],
        )
        self.assertTrue(all(entry.follow_symlinks is False for entry in plan))
        self.assertTrue(all(0 < entry.max_depth <= MAX_STORAGE_PATH_PLAN_DEPTH for entry in plan))

    def test_storage_report_path_plan_can_select_one_section(self) -> None:
        plan = plan_storage_report_paths(
            home_path="/home/deck",
            steam_library_paths=("/not/validated/for/logs",),
            sections=(StorageSectionName.LOGS,),
        )

        self.assertEqual(
            plan,
            (
                StoragePathPlanEntry(
                    section=StorageSectionName.LOGS,
                    path="/home/deck/.local/share/Steam/logs",
                    label="Steam logs",
                    max_depth=1,
                ),
            ),
        )

    def test_storage_path_plan_entry_round_trips(self) -> None:
        entry = StoragePathPlanEntry(
            section="logs",
            path="/home/deck/.local/share/Steam/logs",
            label="Steam logs",
            max_depth=1,
        )

        restored = StoragePathPlanEntry.from_dict(json.loads(json.dumps(entry.to_dict())))

        self.assertEqual(restored, entry)
        self.assertEqual(restored.section, StorageSectionName.LOGS)

    def test_storage_report_path_plan_rejects_unbounded_or_sensitive_paths(self) -> None:
        with self.assertRaises(DiagnosticsValidationError):
            plan_storage_report_paths(home_path="home/deck")

        with self.assertRaises(DiagnosticsValidationError):
            plan_storage_report_paths(steam_library_paths=("/home/deck/.config/codex",))

        with self.assertRaises(DiagnosticsValidationError):
            StoragePathPlanEntry(
                section=StorageSectionName.LOGS,
                path="/home/deck/.local/share/Steam/logs",
                label="Steam logs",
                max_depth=MAX_STORAGE_PATH_PLAN_DEPTH + 1,
            )

    def test_storage_report_path_plan_rejects_too_many_library_roots(self) -> None:
        too_many_library_roots = tuple(
            f"/run/media/library-{index}/SteamLibrary"
            for index in range(MAX_STORAGE_PATH_PLAN_LIBRARY_ROOTS)
        )

        with self.assertRaises(DiagnosticsValidationError):
            plan_storage_report_paths(steam_library_paths=too_many_library_roots)

    def test_storage_report_path_plan_rejects_duplicate_sections(self) -> None:
        with self.assertRaises(DiagnosticsValidationError):
            plan_storage_report_paths(
                sections=(StorageSectionName.LOGS, StorageSectionName.LOGS),
            )


class ProtonLogContractTests(unittest.TestCase):
    def test_proton_log_report_round_trips_with_excerpt(self) -> None:
        excerpt = ProtonLogExcerpt(
            text="err:module:import_dll Library vcruntime140.dll not found\n",
            truncated=True,
            line_start=12,
            line_end=12,
        )
        report = ProtonLogReport(
            logs=(
                ProtonLogReference(
                    path="/home/deck/steam-12345.log",
                    app_id=12345,
                    modified_at="2026-06-21T10:00:00+00:00",
                    excerpt=excerpt,
                ),
            ),
        )

        restored = ProtonLogReport.from_dict(json.loads(json.dumps(report.to_dict())))

        self.assertEqual(excerpt.status, DiagnosticStatus.LIMITED)
        self.assertEqual(report.status, DiagnosticStatus.LIMITED)
        self.assertEqual(restored, report)
        self.assertEqual(restored.logs[0].app_id, 12345)

    def test_proton_log_excerpt_enforces_bounded_character_limit(self) -> None:
        with self.assertRaises(DiagnosticsValidationError):
            ProtonLogExcerpt(text="x" * (MAX_PROTON_EXCERPT_CHARACTERS + 1))

        with self.assertRaises(DiagnosticsValidationError):
            ProtonLogExcerpt.from_dict({"text": "line", "truncated": "false"})

    def test_proton_log_reference_validates_app_id_and_line_range(self) -> None:
        with self.assertRaises(DiagnosticsValidationError):
            ProtonLogReference(path="/home/deck/steam-0.log", app_id=0)

        with self.assertRaises(DiagnosticsValidationError):
            ProtonLogExcerpt(
                text="line",
                line_start=8,
                line_end=7,
            )


class FilesystemDiagnosticsReaderTests(unittest.TestCase):
    def _write_bytes(self, path: str, size: int) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"x" * size)

    def _write_text(self, path: str, text: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_read_storage_report_orders_largest_items_and_skips_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            section_root = os.path.join(temp_dir, "shadercache")
            external_root = os.path.join(temp_dir, "external")

            self._write_bytes(os.path.join(section_root, "small", "cache.bin"), 10)
            self._write_bytes(os.path.join(section_root, "mid", "cache.bin"), 20)
            self._write_bytes(os.path.join(section_root, "large", "cache.bin"), 50)
            self._write_bytes(
                os.path.join(section_root, "large", "deeper", "ignored.bin"),
                999,
            )
            self._write_bytes(os.path.join(external_root, "linked.bin"), 2048)
            os.symlink(external_root, os.path.join(section_root, "linked"))

            report = read_storage_report(
                (
                    StoragePathPlanEntry(
                        section=StorageSectionName.SHADERCACHE,
                        path=section_root,
                        label="Shader cache",
                        max_depth=2,
                    ),
                ),
                max_items_per_section=2,
                max_scanned_entries_per_section=64,
            )

            self.assertEqual(report.status, DiagnosticStatus.LIMITED)
            self.assertEqual(len(report.sections), 1)
            section = report.sections[0]

            self.assertEqual(section.bytes, 80)
            self.assertEqual(
                [item.path for item in section.items],
                [
                    os.path.join(section_root, "large"),
                    os.path.join(section_root, "mid"),
                ],
            )
            self.assertEqual([item.bytes for item in section.items], [50, 20])
            self.assertNotIn(os.path.join(section_root, "linked"), [item.path for item in section.items])
            self.assertIn("Only the largest items within the section are shown.", section.warnings)
            self.assertIn(
                "Traversal depth limit reached; deeper descendants were skipped.",
                section.warnings,
            )
            self.assertIn("Symlink entries were skipped.", section.warnings)
            self.assertTrue(any(limit.name == "max_depth" and limit.hit for limit in section.limits))
            self.assertTrue(any(limit.name == "max_items" and limit.hit for limit in section.limits))

    def test_read_storage_report_marks_scan_limit_hits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            section_root = os.path.join(temp_dir, "compatdata")
            for name in ("one", "two", "three"):
                self._write_bytes(os.path.join(section_root, name, "prefix"), 1)

            report = read_storage_report(
                (
                    StoragePathPlanEntry(
                        section=StorageSectionName.COMPATDATA,
                        path=section_root,
                        label="Compatdata",
                        max_depth=2,
                    ),
                ),
                max_scanned_entries_per_section=2,
            )

            section = report.sections[0]
            self.assertEqual(section.status, DiagnosticStatus.LIMITED)
            self.assertIn(
                "Traversal entry limit reached; remaining descendants were skipped.",
                section.warnings,
            )
            self.assertTrue(
                any(limit.name == "max_scanned_entries" and limit.hit for limit in section.limits)
            )
            self.assertLessEqual(len(section.items), 2)

    def test_read_proton_logs_infers_app_id_and_bounds_excerpt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = os.path.join(temp_dir, "steam-12345.log")
            self._write_text(
                log_path,
                "\n".join(f"line {index}" for index in range(40)),
            )
            self._write_text(os.path.join(temp_dir, "notes.log"), "not a proton log")

            report = read_proton_logs(
                paths=(temp_dir,),
                max_excerpt_characters=64,
            )

            self.assertEqual(len(report.logs), 1)
            self.assertEqual(report.status, DiagnosticStatus.LIMITED)
            log = report.logs[0]
            self.assertEqual(log.path, log_path)
            self.assertEqual(log.app_id, 12345)
            self.assertIsNotNone(log.excerpt)
            assert log.excerpt is not None
            self.assertTrue(log.excerpt.truncated)
            self.assertLessEqual(len(log.excerpt.text), 64)
            self.assertTrue(
                any(limit.name == "max_excerpt_characters" and limit.hit for limit in log.limits)
            )

    def test_read_proton_logs_reports_missing_logs_as_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = os.path.join(temp_dir, "steam-99999.log")

            report = read_proton_logs(paths=(missing_path,))

            self.assertEqual(report.status, DiagnosticStatus.UNAVAILABLE)
            self.assertEqual(report.logs, ())
            self.assertIn("Requested path was unavailable.", report.warnings)
            self.assertIn(
                "No Proton log files were found in the requested paths.",
                report.warnings,
            )


if __name__ == "__main__":
    unittest.main()
