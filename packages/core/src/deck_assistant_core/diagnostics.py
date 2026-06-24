"""Read-only diagnostics contracts for future Steam Deck MCP tools.

This module models storage reports and Proton log summaries without touching the
filesystem, executing commands, or reading credential stores.
"""

from __future__ import annotations

import os
import posixpath
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from deck_assistant_core import _validation


MAX_DIAGNOSTIC_WARNINGS = 16
MAX_DIAGNOSTIC_LIMITS = 8
MAX_STORAGE_REPORT_SECTIONS = 32
MAX_STORAGE_SECTION_ITEMS = 64
MAX_STORAGE_PATH_PLAN_ENTRIES = 32
MAX_STORAGE_PATH_PLAN_LIBRARY_ROOTS = 8
MAX_STORAGE_PATH_PLAN_DEPTH = 8
MAX_PROTON_LOG_REFERENCES = 32
MAX_PROTON_EXCERPT_CHARACTERS = 8192


class DiagnosticsValidationError(ValueError):
    """Raised when a diagnostics contract is incomplete or inconsistent."""


class DiagnosticStatus(str, Enum):
    """Structured status for bounded read-only diagnostics output."""

    OK = "ok"
    WARNING = "warning"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"


class DiagnosticLimitUnit(str, Enum):
    """Units used to describe report and excerpt limits."""

    BYTES = "bytes"
    ITEMS = "items"
    LINES = "lines"
    CHARACTERS = "characters"


class StorageSectionName(str, Enum):
    """Known storage sections for `get_storage_report`."""

    SHADERCACHE = "shadercache"
    COMPATDATA = "compatdata"
    LOGS = "logs"
    SCREENSHOTS_VIDEOS = "screenshots_videos"


_STATUS_ORDER = {
    DiagnosticStatus.OK: 0,
    DiagnosticStatus.WARNING: 1,
    DiagnosticStatus.LIMITED: 2,
    DiagnosticStatus.UNAVAILABLE: 3,
}

_DEFAULT_STORAGE_PLAN_SECTIONS = (
    StorageSectionName.SHADERCACHE,
    StorageSectionName.COMPATDATA,
    StorageSectionName.LOGS,
    StorageSectionName.SCREENSHOTS_VIDEOS,
)

_AI_CLI_CREDENTIAL_PATH_MARKERS = (
    "/.aws",
    "/.codex",
    "/.config/codex",
    "/.claude",
    "/.config/claude",
    "/.gemini",
    "/.config/gemini",
    "/.gnupg",
    "/.netrc",
    "/.ssh",
    "/credentials",
    "/secrets",
    "/tokens",
)

_STORAGE_SECTION_LABELS = {
    StorageSectionName.SHADERCACHE: "Steam shader cache",
    StorageSectionName.COMPATDATA: "Steam compatibility data",
    StorageSectionName.LOGS: "Steam logs",
    StorageSectionName.SCREENSHOTS_VIDEOS: "Steam screenshots and videos",
}

_DEFAULT_STORAGE_SECTION_MAX_SCANNED_ENTRIES = 512
_DEFAULT_PROTON_LOG_DIRECTORY_MAX_ENTRIES = 128

_PROTON_LOG_APP_ID_PATTERN = re.compile(r"steam-(?P<app_id>\d+)\.log$", re.IGNORECASE)

_DEPTH_LIMIT_WARNING = "Traversal depth limit reached; deeper descendants were skipped."
_ENTRY_LIMIT_WARNING = "Traversal entry limit reached; remaining descendants were skipped."
_SYMLINK_SKIPPED_WARNING = "Symlink entries were skipped."
_SENSITIVE_PATH_WARNING = "Sensitive paths were skipped."
_UNREADABLE_PATH_WARNING = "Some paths could not be read."
_UNAVAILABLE_PATH_WARNING = "Requested path was unavailable."
_PROTON_LOG_NOT_FOUND_WARNING = "No Proton log files were found in the requested paths."
_DIRECTORY_SCAN_LIMIT_WARNING = (
    "Directory scan limit reached; additional Proton log files were skipped."
)
_EMPTY_LOG_WARNING = "Log file was empty."


def _status_rank(status: DiagnosticStatus) -> int:
    return _STATUS_ORDER[status]


def _require_text(value: Any, field_name: str) -> str:
    # Diagnostics returns the stripped value and uses a "non-empty string" message.
    if not isinstance(value, str) or not value.strip():
        raise DiagnosticsValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name)


def _require_non_negative_int(value: Any, field_name: str) -> int:
    return _validation.require_non_negative_int(
        value, field_name, error=DiagnosticsValidationError
    )


def _require_positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise DiagnosticsValidationError(f"{field_name} must be an integer")
    if value < 0:
        raise DiagnosticsValidationError(f"{field_name} must not be negative")
    if value <= 0:
        raise DiagnosticsValidationError(f"{field_name} must be greater than zero")
    return value


def _require_bool(value: Any, field_name: str) -> bool:
    return _validation.require_bool(value, field_name, error=DiagnosticsValidationError)


def _require_mapping(data: Mapping[str, Any] | Any, field_name: str) -> Mapping[str, Any]:
    return _validation.require_mapping(data, field_name, error=DiagnosticsValidationError)


def _validate_timestamp(value: str, field_name: str) -> str:
    # Diagnostics timestamps do NOT accept a trailing ``Z`` (unlike knowledge).
    return _validation.validate_timestamp(
        value, field_name, error=DiagnosticsValidationError, allow_zulu=False
    )


def _coerce_status(value: DiagnosticStatus | str | None) -> DiagnosticStatus | None:
    if value is None:
        return None
    return _validation.coerce_enum(
        value,
        DiagnosticStatus,
        error=DiagnosticsValidationError,
        message="unsupported diagnostic status",
    )


def _coerce_limit_unit(value: DiagnosticLimitUnit | str) -> DiagnosticLimitUnit:
    return _validation.coerce_enum(
        value,
        DiagnosticLimitUnit,
        error=DiagnosticsValidationError,
        message="unsupported diagnostic limit unit",
    )


def _coerce_section_name(value: StorageSectionName | str) -> StorageSectionName:
    return _validation.coerce_enum(
        value,
        StorageSectionName,
        error=DiagnosticsValidationError,
        message="unsupported storage section name",
    )


def _reject_ai_cli_credential_path(path: str, field_name: str) -> None:
    normalized = path.rstrip("/").lower()
    for marker in _AI_CLI_CREDENTIAL_PATH_MARKERS:
        if normalized.endswith(marker) or f"{marker}/" in normalized:
            raise DiagnosticsValidationError(
                f"{field_name} must not target an AI CLI credential directory"
            )


def _normalize_absolute_path(value: Any, field_name: str) -> str:
    text = _require_text(value, field_name).replace("\\", "/")
    if "\x00" in text:
        raise DiagnosticsValidationError(f"{field_name} must not contain NUL bytes")
    if not text.startswith("/"):
        raise DiagnosticsValidationError(f"{field_name} must be an absolute path")

    normalized = posixpath.normpath(text)
    if normalized.startswith("//"):
        normalized = "/" + normalized.lstrip("/")
    if normalized == "/":
        raise DiagnosticsValidationError(f"{field_name} must not be the filesystem root")
    _reject_ai_cli_credential_path(normalized, field_name)
    return normalized


def _join_storage_path(base_path: str, relative_path: str) -> str:
    return _normalize_absolute_path(posixpath.join(base_path, relative_path), "storage path")


def _steamapps_child_path(library_root: str, child_name: str) -> str:
    if posixpath.basename(library_root.rstrip("/")) == "steamapps":
        return _join_storage_path(library_root, child_name)
    return _join_storage_path(library_root, posixpath.join("steamapps", child_name))


def _coerce_warnings(value: Sequence[str] | None, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise DiagnosticsValidationError(f"{field_name} must be a sequence of strings")

    warnings = tuple(_require_text(item, field_name) for item in value)
    if len(warnings) > MAX_DIAGNOSTIC_WARNINGS:
        raise DiagnosticsValidationError(
            f"{field_name} must include at most {MAX_DIAGNOSTIC_WARNINGS} warnings"
        )
    return warnings


def _coerce_limits(
    value: Sequence["DiagnosticLimit"] | None,
    field_name: str,
) -> tuple["DiagnosticLimit", ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        raise DiagnosticsValidationError(f"{field_name} must be a sequence of limits")

    limits = tuple(value)
    if len(limits) > MAX_DIAGNOSTIC_LIMITS:
        raise DiagnosticsValidationError(
            f"{field_name} must include at most {MAX_DIAGNOSTIC_LIMITS} limits"
        )
    for limit in limits:
        if not isinstance(limit, DiagnosticLimit):
            raise DiagnosticsValidationError(f"{field_name} entries must be DiagnosticLimit")
    return limits


def _coerce_storage_plan_sections(
    sections: Sequence[StorageSectionName | str] | None,
) -> tuple[StorageSectionName, ...]:
    if sections is None:
        return _DEFAULT_STORAGE_PLAN_SECTIONS
    if isinstance(sections, (str, bytes)):
        raise DiagnosticsValidationError("storage plan sections must be a sequence")

    normalized = tuple(_coerce_section_name(section) for section in sections)
    if not normalized:
        raise DiagnosticsValidationError("storage plan sections must not be empty")
    if len(normalized) > MAX_STORAGE_REPORT_SECTIONS:
        raise DiagnosticsValidationError(
            f"storage plan sections must include at most {MAX_STORAGE_REPORT_SECTIONS} entries"
        )

    seen_sections: set[StorageSectionName] = set()
    for section in normalized:
        if section in seen_sections:
            raise DiagnosticsValidationError(f"duplicate storage plan section: {section.value}")
        seen_sections.add(section)
    return normalized


def _coerce_steam_library_roots(
    *,
    home_path: str,
    steam_library_paths: Sequence[str] | None,
) -> tuple[str, ...]:
    primary_root = _join_storage_path(home_path, ".local/share/Steam")
    if steam_library_paths is None:
        additional_roots: tuple[str, ...] = ()
    else:
        if isinstance(steam_library_paths, (str, bytes)):
            raise DiagnosticsValidationError("steam_library_paths must be a sequence of paths")
        additional_roots = tuple(
            sorted(
                {
                    _normalize_absolute_path(path, "steam library path")
                    for path in steam_library_paths
                }
            )
        )

    roots = (primary_root,) + tuple(path for path in additional_roots if path != primary_root)
    if len(roots) > MAX_STORAGE_PATH_PLAN_LIBRARY_ROOTS:
        raise DiagnosticsValidationError(
            "storage path planning supports at most "
            f"{MAX_STORAGE_PATH_PLAN_LIBRARY_ROOTS} Steam library roots"
        )
    return roots


def _infer_status(
    *,
    warnings: Sequence[str],
    limits: Sequence["DiagnosticLimit"],
    child_statuses: Sequence[DiagnosticStatus] = (),
    limited: bool = False,
) -> DiagnosticStatus:
    inferred = DiagnosticStatus.OK
    for child_status in child_statuses:
        if _status_rank(child_status) > _status_rank(inferred):
            inferred = child_status
    if warnings and _status_rank(DiagnosticStatus.WARNING) > _status_rank(inferred):
        inferred = DiagnosticStatus.WARNING
    if (limited or any(limit.hit for limit in limits)) and _status_rank(
        DiagnosticStatus.LIMITED
    ) > _status_rank(inferred):
        inferred = DiagnosticStatus.LIMITED
    return inferred


@dataclass
class _TraversalFlags:
    depth_limit_hit: bool = False
    entry_limit_hit: bool = False
    symlink_skipped: bool = False
    sensitive_skipped: bool = False
    unreadable_paths: bool = False


@dataclass
class _StorageSectionTraversalState:
    scanned_entries: int = 0
    flags: _TraversalFlags = field(default_factory=_TraversalFlags)


def _merge_flags(target: _TraversalFlags, source: _TraversalFlags) -> None:
    target.depth_limit_hit = target.depth_limit_hit or source.depth_limit_hit
    target.entry_limit_hit = target.entry_limit_hit or source.entry_limit_hit
    target.symlink_skipped = target.symlink_skipped or source.symlink_skipped
    target.sensitive_skipped = target.sensitive_skipped or source.sensitive_skipped
    target.unreadable_paths = target.unreadable_paths or source.unreadable_paths


def _warnings_from_flags(flags: _TraversalFlags) -> tuple[str, ...]:
    warnings: list[str] = []
    if flags.depth_limit_hit:
        warnings.append(_DEPTH_LIMIT_WARNING)
    if flags.entry_limit_hit:
        warnings.append(_ENTRY_LIMIT_WARNING)
    if flags.symlink_skipped:
        warnings.append(_SYMLINK_SKIPPED_WARNING)
    if flags.sensitive_skipped:
        warnings.append(_SENSITIVE_PATH_WARNING)
    if flags.unreadable_paths:
        warnings.append(_UNREADABLE_PATH_WARNING)
    return tuple(warnings)


def _mark_sensitive_path(flags: _TraversalFlags) -> None:
    flags.sensitive_skipped = True


def _safe_lstat(path: str, *, flags: _TraversalFlags) -> os.stat_result | None:
    try:
        _reject_ai_cli_credential_path(path, "diagnostics path")
    except DiagnosticsValidationError:
        _mark_sensitive_path(flags)
        return None

    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        flags.unreadable_paths = True
        return None


def _resolve_status(
    value: DiagnosticStatus | str | None,
    *,
    warnings: Sequence[str],
    limits: Sequence["DiagnosticLimit"],
    child_statuses: Sequence[DiagnosticStatus] = (),
    limited: bool = False,
) -> DiagnosticStatus:
    declared = _coerce_status(value)
    inferred = _infer_status(
        warnings=warnings,
        limits=limits,
        child_statuses=child_statuses,
        limited=limited,
    )
    if declared is None:
        return inferred
    if _status_rank(declared) < _status_rank(inferred):
        raise DiagnosticsValidationError(
            f"declared status {declared.value} is lower than inferred status {inferred.value}"
        )
    return declared


@dataclass(frozen=True)
class DiagnosticLimit:
    """A bounded output limit applied by a diagnostics tool."""

    name: str
    unit: DiagnosticLimitUnit
    value: int
    hit: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_text(self.name, "limit name"))
        object.__setattr__(self, "unit", _coerce_limit_unit(self.unit))
        object.__setattr__(self, "value", _require_non_negative_int(self.value, "limit value"))
        object.__setattr__(self, "hit", _require_bool(self.hit, "limit hit"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit.value,
            "value": self.value,
            "hit": self.hit,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DiagnosticLimit":
        data = _require_mapping(data, "limit")
        return cls(
            name=data["name"],
            unit=data["unit"],
            value=data["value"],
            hit=data.get("hit", False),
        )


@dataclass(frozen=True)
class StoragePathPlanEntry:
    """One bounded absolute path future storage diagnostics may inspect."""

    section: StorageSectionName
    path: str
    label: str
    max_depth: int
    follow_symlinks: bool = False

    def __post_init__(self) -> None:
        max_depth = _require_positive_int(self.max_depth, "storage path plan max_depth")
        if max_depth > MAX_STORAGE_PATH_PLAN_DEPTH:
            raise DiagnosticsValidationError(
                f"storage path plan max_depth must be at most {MAX_STORAGE_PATH_PLAN_DEPTH}"
            )

        object.__setattr__(self, "section", _coerce_section_name(self.section))
        object.__setattr__(
            self,
            "path",
            _normalize_absolute_path(self.path, "storage path plan path"),
        )
        object.__setattr__(self, "label", _require_text(self.label, "storage path plan label"))
        object.__setattr__(self, "max_depth", max_depth)
        object.__setattr__(
            self,
            "follow_symlinks",
            _require_bool(self.follow_symlinks, "storage path plan follow_symlinks"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section.value,
            "path": self.path,
            "label": self.label,
            "max_depth": self.max_depth,
            "follow_symlinks": self.follow_symlinks,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StoragePathPlanEntry":
        data = _require_mapping(data, "storage path plan entry")
        return cls(
            section=data["section"],
            path=data["path"],
            label=data["label"],
            max_depth=data["max_depth"],
            follow_symlinks=data.get("follow_symlinks", False),
        )


def plan_storage_report_paths(
    *,
    home_path: str = "/home/deck",
    steam_library_paths: Sequence[str] | None = None,
    sections: Sequence[StorageSectionName | str] | None = None,
) -> tuple[StoragePathPlanEntry, ...]:
    """Build a deterministic read-only path plan for future `get_storage_report`.

    The helper only normalizes and bounds paths. It does not stat, list, open, or
    execute anything, and it rejects AI CLI credential-like directories.
    """

    normalized_home = _normalize_absolute_path(home_path, "home_path")
    selected_sections = _coerce_storage_plan_sections(sections)
    needs_steam_library_roots = any(
        section in {StorageSectionName.SHADERCACHE, StorageSectionName.COMPATDATA}
        for section in selected_sections
    )
    steam_library_roots = (
        _coerce_steam_library_roots(
            home_path=normalized_home,
            steam_library_paths=steam_library_paths,
        )
        if needs_steam_library_roots
        else ()
    )

    entries: list[StoragePathPlanEntry] = []
    for section in selected_sections:
        label = _STORAGE_SECTION_LABELS[section]
        if section is StorageSectionName.SHADERCACHE:
            for library_root in steam_library_roots:
                entries.append(
                    StoragePathPlanEntry(
                        section=section,
                        path=_steamapps_child_path(library_root, "shadercache"),
                        label=f"{label}: {library_root}",
                        max_depth=2,
                    )
                )
        elif section is StorageSectionName.COMPATDATA:
            for library_root in steam_library_roots:
                entries.append(
                    StoragePathPlanEntry(
                        section=section,
                        path=_steamapps_child_path(library_root, "compatdata"),
                        label=f"{label}: {library_root}",
                        max_depth=2,
                    )
                )
        elif section is StorageSectionName.LOGS:
            entries.append(
                StoragePathPlanEntry(
                    section=section,
                    path=_join_storage_path(normalized_home, ".local/share/Steam/logs"),
                    label=label,
                    max_depth=1,
                )
            )
        elif section is StorageSectionName.SCREENSHOTS_VIDEOS:
            entries.append(
                StoragePathPlanEntry(
                    section=section,
                    path=_join_storage_path(normalized_home, ".local/share/Steam/userdata"),
                    label=label,
                    max_depth=6,
                )
            )
        else:
            raise DiagnosticsValidationError(f"unsupported storage plan section: {section.value}")

    deduped_entries: list[StoragePathPlanEntry] = []
    seen_entries: set[tuple[StorageSectionName, str]] = set()
    for entry in entries:
        entry_key = (entry.section, entry.path)
        if entry_key in seen_entries:
            continue
        seen_entries.add(entry_key)
        deduped_entries.append(entry)

    if len(deduped_entries) > MAX_STORAGE_PATH_PLAN_ENTRIES:
        raise DiagnosticsValidationError(
            f"storage path plan must include at most {MAX_STORAGE_PATH_PLAN_ENTRIES} entries"
        )
    return tuple(deduped_entries)


@dataclass(frozen=True)
class StorageReportItem:
    """One path-sized entry within a bounded storage section."""

    path: str
    bytes: int
    label: str | None = None
    status: DiagnosticStatus | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        warnings = _coerce_warnings(self.warnings, "storage report item warnings")
        object.__setattr__(
            self,
            "path",
            _normalize_absolute_path(self.path, "storage report item path"),
        )
        object.__setattr__(self, "bytes", _require_non_negative_int(self.bytes, "item bytes"))
        object.__setattr__(self, "label", _optional_text(self.label, "storage report item label"))
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(
            self,
            "status",
            _resolve_status(self.status, warnings=warnings, limits=()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "bytes": self.bytes,
            "label": self.label,
            "status": self.status.value,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StorageReportItem":
        data = _require_mapping(data, "storage report item")
        return cls(
            path=data["path"],
            bytes=data["bytes"],
            label=data.get("label"),
            status=data.get("status"),
            warnings=tuple(data.get("warnings", ())),
        )


@dataclass(frozen=True)
class StorageReportSection:
    """One bounded storage category for future Deck diagnostics."""

    name: StorageSectionName
    path: str
    bytes: int
    items: tuple[StorageReportItem, ...] = ()
    status: DiagnosticStatus | None = None
    warnings: tuple[str, ...] = ()
    limits: tuple[DiagnosticLimit, ...] = ()

    def __post_init__(self) -> None:
        items = tuple(self.items)
        warnings = _coerce_warnings(self.warnings, "storage report section warnings")
        limits = _coerce_limits(self.limits, "storage report section limits")

        if len(items) > MAX_STORAGE_SECTION_ITEMS:
            raise DiagnosticsValidationError(
                f"storage report section items must include at most {MAX_STORAGE_SECTION_ITEMS} entries"
            )
        for item in items:
            if not isinstance(item, StorageReportItem):
                raise DiagnosticsValidationError("storage report section items must be StorageReportItem")

        total_item_bytes = sum(item.bytes for item in items)
        section_bytes = _require_non_negative_int(self.bytes, "section bytes")
        if total_item_bytes > section_bytes:
            raise DiagnosticsValidationError("section bytes must be at least the sum of item bytes")

        object.__setattr__(self, "name", _coerce_section_name(self.name))
        object.__setattr__(
            self,
            "path",
            _normalize_absolute_path(self.path, "storage report section path"),
        )
        object.__setattr__(self, "bytes", section_bytes)
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "limits", limits)
        object.__setattr__(
            self,
            "status",
            _resolve_status(
                self.status,
                warnings=warnings,
                limits=limits,
                child_statuses=tuple(item.status for item in items),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name.value,
            "path": self.path,
            "bytes": self.bytes,
            "status": self.status.value,
            "warnings": list(self.warnings),
            "limits": [limit.to_dict() for limit in self.limits],
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StorageReportSection":
        data = _require_mapping(data, "storage report section")
        return cls(
            name=data["name"],
            path=data["path"],
            bytes=data["bytes"],
            status=data.get("status"),
            warnings=tuple(data.get("warnings", ())),
            limits=tuple(
                DiagnosticLimit.from_dict(limit_data) for limit_data in data.get("limits", ())
            ),
            items=tuple(
                StorageReportItem.from_dict(item_data) for item_data in data.get("items", ())
            ),
        )


@dataclass(frozen=True)
class StorageReport:
    """Top-level future output contract for `get_storage_report`."""

    sections: tuple[StorageReportSection, ...]
    status: DiagnosticStatus | None = None
    warnings: tuple[str, ...] = ()
    limits: tuple[DiagnosticLimit, ...] = ()

    def __post_init__(self) -> None:
        sections = tuple(self.sections)
        warnings = _coerce_warnings(self.warnings, "storage report warnings")
        limits = _coerce_limits(self.limits, "storage report limits")

        if len(sections) > MAX_STORAGE_REPORT_SECTIONS:
            raise DiagnosticsValidationError(
                f"storage report sections must include at most {MAX_STORAGE_REPORT_SECTIONS} entries"
            )
        seen_sections: set[tuple[StorageSectionName, str]] = set()
        for section in sections:
            if not isinstance(section, StorageReportSection):
                raise DiagnosticsValidationError("storage report sections must be StorageReportSection")
            section_key = (section.name, section.path)
            if section_key in seen_sections:
                raise DiagnosticsValidationError(
                    f"duplicate storage report section path: {section.name.value} {section.path}"
                )
            seen_sections.add(section_key)

        object.__setattr__(self, "sections", sections)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "limits", limits)
        object.__setattr__(
            self,
            "status",
            _resolve_status(
                self.status,
                warnings=warnings,
                limits=limits,
                child_statuses=tuple(section.status for section in sections),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "warnings": list(self.warnings),
            "limits": [limit.to_dict() for limit in self.limits],
            "sections": [section.to_dict() for section in self.sections],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StorageReport":
        data = _require_mapping(data, "storage report")
        return cls(
            status=data.get("status"),
            warnings=tuple(data.get("warnings", ())),
            limits=tuple(
                DiagnosticLimit.from_dict(limit_data) for limit_data in data.get("limits", ())
            ),
            sections=tuple(
                StorageReportSection.from_dict(section_data)
                for section_data in data.get("sections", ())
            ),
        )


@dataclass(frozen=True)
class ProtonLogExcerpt:
    """A bounded excerpt captured from a Proton log."""

    text: str
    truncated: bool = False
    line_start: int | None = None
    line_end: int | None = None
    status: DiagnosticStatus | None = None
    warnings: tuple[str, ...] = ()
    limits: tuple[DiagnosticLimit, ...] = ()

    def __post_init__(self) -> None:
        text = _require_text(self.text, "proton log excerpt text")
        warnings = _coerce_warnings(self.warnings, "proton log excerpt warnings")
        limits = _coerce_limits(self.limits, "proton log excerpt limits")

        if "\x00" in text:
            raise DiagnosticsValidationError("proton log excerpt text must not contain NUL bytes")
        if len(text) > MAX_PROTON_EXCERPT_CHARACTERS:
            raise DiagnosticsValidationError(
                "proton log excerpt text exceeds the bounded excerpt character limit"
            )
        truncated = _require_bool(self.truncated, "proton log excerpt truncated")

        line_start = self.line_start
        line_end = self.line_end
        if line_start is not None:
            line_start = _require_positive_int(line_start, "proton log excerpt line_start")
        if line_end is not None:
            line_end = _require_positive_int(line_end, "proton log excerpt line_end")
        if line_start is not None and line_end is not None and line_end < line_start:
            raise DiagnosticsValidationError(
                "proton log excerpt line_end must be greater than or equal to line_start"
            )

        object.__setattr__(self, "text", text)
        object.__setattr__(self, "truncated", truncated)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "limits", limits)
        object.__setattr__(self, "line_start", line_start)
        object.__setattr__(self, "line_end", line_end)
        object.__setattr__(
            self,
            "status",
            _resolve_status(
                self.status,
                warnings=warnings,
                limits=limits,
                limited=truncated,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "truncated": self.truncated,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "status": self.status.value,
            "warnings": list(self.warnings),
            "limits": [limit.to_dict() for limit in self.limits],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProtonLogExcerpt":
        data = _require_mapping(data, "proton log excerpt")
        return cls(
            text=data["text"],
            truncated=data.get("truncated", False),
            line_start=data.get("line_start"),
            line_end=data.get("line_end"),
            status=data.get("status"),
            warnings=tuple(data.get("warnings", ())),
            limits=tuple(
                DiagnosticLimit.from_dict(limit_data) for limit_data in data.get("limits", ())
            ),
        )


@dataclass(frozen=True)
class ProtonLogReference:
    """One Proton log path plus an optional bounded excerpt."""

    path: str
    app_id: int | None = None
    modified_at: str | None = None
    excerpt: ProtonLogExcerpt | None = None
    status: DiagnosticStatus | None = None
    warnings: tuple[str, ...] = ()
    limits: tuple[DiagnosticLimit, ...] = ()

    def __post_init__(self) -> None:
        warnings = _coerce_warnings(self.warnings, "proton log reference warnings")
        limits = _coerce_limits(self.limits, "proton log reference limits")

        app_id = self.app_id
        if app_id is not None:
            app_id = _require_positive_int(app_id, "proton log reference app_id")
        modified_at = self.modified_at
        if modified_at is not None:
            modified_at = _validate_timestamp(modified_at, "proton log reference modified_at")
        if self.excerpt is not None and not isinstance(self.excerpt, ProtonLogExcerpt):
            raise DiagnosticsValidationError("proton log reference excerpt must be ProtonLogExcerpt")

        object.__setattr__(
            self,
            "path",
            _normalize_absolute_path(self.path, "proton log reference path"),
        )
        object.__setattr__(self, "app_id", app_id)
        object.__setattr__(self, "modified_at", modified_at)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "limits", limits)
        object.__setattr__(
            self,
            "status",
            _resolve_status(
                self.status,
                warnings=warnings,
                limits=limits,
                child_statuses=((self.excerpt.status,) if self.excerpt is not None else ()),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "app_id": self.app_id,
            "modified_at": self.modified_at,
            "status": self.status.value,
            "warnings": list(self.warnings),
            "limits": [limit.to_dict() for limit in self.limits],
            "excerpt": self.excerpt.to_dict() if self.excerpt is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProtonLogReference":
        data = _require_mapping(data, "proton log reference")
        excerpt_data = data.get("excerpt")
        return cls(
            path=data["path"],
            app_id=data.get("app_id"),
            modified_at=data.get("modified_at"),
            excerpt=ProtonLogExcerpt.from_dict(excerpt_data) if excerpt_data else None,
            status=data.get("status"),
            warnings=tuple(data.get("warnings", ())),
            limits=tuple(
                DiagnosticLimit.from_dict(limit_data) for limit_data in data.get("limits", ())
            ),
        )


@dataclass(frozen=True)
class ProtonLogReport:
    """Top-level future output contract for `read_proton_logs`."""

    logs: tuple[ProtonLogReference, ...]
    status: DiagnosticStatus | None = None
    warnings: tuple[str, ...] = ()
    limits: tuple[DiagnosticLimit, ...] = ()

    def __post_init__(self) -> None:
        logs = tuple(self.logs)
        warnings = _coerce_warnings(self.warnings, "proton log report warnings")
        limits = _coerce_limits(self.limits, "proton log report limits")

        if len(logs) > MAX_PROTON_LOG_REFERENCES:
            raise DiagnosticsValidationError(
                f"proton log report logs must include at most {MAX_PROTON_LOG_REFERENCES} entries"
            )
        seen_paths: set[str] = set()
        for log in logs:
            if not isinstance(log, ProtonLogReference):
                raise DiagnosticsValidationError("proton log report logs must be ProtonLogReference")
            if log.path in seen_paths:
                raise DiagnosticsValidationError(f"duplicate proton log path: {log.path}")
            seen_paths.add(log.path)

        object.__setattr__(self, "logs", logs)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "limits", limits)
        object.__setattr__(
            self,
            "status",
            _resolve_status(
                self.status,
                warnings=warnings,
                limits=limits,
                child_statuses=tuple(log.status for log in logs),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "warnings": list(self.warnings),
            "limits": [limit.to_dict() for limit in self.limits],
            "logs": [log.to_dict() for log in self.logs],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProtonLogReport":
        data = _require_mapping(data, "proton log report")
        return cls(
            status=data.get("status"),
            warnings=tuple(data.get("warnings", ())),
            limits=tuple(
                DiagnosticLimit.from_dict(limit_data) for limit_data in data.get("limits", ())
            ),
            logs=tuple(
                ProtonLogReference.from_dict(log_data) for log_data in data.get("logs", ())
            ),
        )


def _branch_size_from_path(
    path: str,
    *,
    depth_remaining: int,
    follow_symlinks: bool,
    max_scanned_entries: int,
    state: _StorageSectionTraversalState,
) -> tuple[int, _TraversalFlags]:
    # Single source of truth: this branch records every traversal flag only on the
    # local ``flags`` it returns. ``state`` keeps the shared scanned-entry counter;
    # callers merge the returned flags into ``state.flags`` once.
    flags = _TraversalFlags()
    if state.scanned_entries >= max_scanned_entries:
        flags.entry_limit_hit = True
        return 0, flags

    stats = _safe_lstat(path, flags=flags)
    if stats is None:
        return 0, flags
    state.scanned_entries += 1

    mode = stats.st_mode
    if stat.S_ISLNK(mode):
        if not follow_symlinks:
            flags.symlink_skipped = True
            return 0, flags
        try:
            stats = os.stat(path)
        except FileNotFoundError:
            return 0, flags
        except OSError:
            flags.unreadable_paths = True
            return 0, flags
        mode = stats.st_mode

    if stat.S_ISREG(mode):
        return max(stats.st_size, 0), flags

    if not stat.S_ISDIR(mode):
        return max(stats.st_size, 0), flags

    if depth_remaining <= 0:
        try:
            with os.scandir(path) as iterator:
                has_children = next(iterator, None) is not None
        except OSError:
            flags.unreadable_paths = True
            return 0, flags
        if has_children:
            flags.depth_limit_hit = True
        return 0, flags

    try:
        with os.scandir(path) as iterator:
            child_paths = tuple(sorted(entry.path for entry in iterator))
    except OSError:
        flags.unreadable_paths = True
        return 0, flags

    total_bytes = 0
    for child_path in child_paths:
        child_bytes, child_flags = _branch_size_from_path(
            child_path,
            depth_remaining=depth_remaining - 1,
            follow_symlinks=follow_symlinks,
            max_scanned_entries=max_scanned_entries,
            state=state,
        )
        total_bytes += child_bytes
        _merge_flags(flags, child_flags)
        if flags.entry_limit_hit:
            break
    return total_bytes, flags


def read_storage_report(
    plan: Sequence[StoragePathPlanEntry],
    *,
    max_items_per_section: int = MAX_STORAGE_SECTION_ITEMS,
    max_scanned_entries_per_section: int = _DEFAULT_STORAGE_SECTION_MAX_SCANNED_ENTRIES,
) -> StorageReport:
    """Read bounded storage metadata from planned filesystem roots.

    The reader is strictly local and read-only: it only stats filesystem paths,
    skips symlinks by default according to the path plan, avoids credential-like
    paths, and returns deterministic top items ordered by size then path.
    """

    if isinstance(plan, (str, bytes)):
        raise DiagnosticsValidationError("storage report plan must be a sequence")

    entries = tuple(plan)
    if not entries:
        raise DiagnosticsValidationError("storage report plan must not be empty")
    if len(entries) > MAX_STORAGE_PATH_PLAN_ENTRIES:
        raise DiagnosticsValidationError(
            f"storage report plan must include at most {MAX_STORAGE_PATH_PLAN_ENTRIES} entries"
        )

    max_items = _require_positive_int(max_items_per_section, "max_items_per_section")
    if max_items > MAX_STORAGE_SECTION_ITEMS:
        raise DiagnosticsValidationError(
            f"max_items_per_section must be at most {MAX_STORAGE_SECTION_ITEMS}"
        )
    max_scanned_entries = _require_positive_int(
        max_scanned_entries_per_section,
        "max_scanned_entries_per_section",
    )

    sections: list[StorageReportSection] = []
    for entry in entries:
        if not isinstance(entry, StoragePathPlanEntry):
            raise DiagnosticsValidationError("storage report plan entries must be StoragePathPlanEntry")

        root_flags = _TraversalFlags()
        root_stats = _safe_lstat(entry.path, flags=root_flags)
        if root_stats is None:
            if root_flags.sensitive_skipped:
                warning = _SENSITIVE_PATH_WARNING
            elif root_flags.unreadable_paths:
                warning = _UNREADABLE_PATH_WARNING
            else:
                warning = _UNAVAILABLE_PATH_WARNING
            sections.append(
                StorageReportSection(
                    name=entry.section,
                    path=entry.path,
                    bytes=0,
                    status=DiagnosticStatus.UNAVAILABLE,
                    warnings=(warning,),
                )
            )
            continue

        if stat.S_ISLNK(root_stats.st_mode) and not entry.follow_symlinks:
            sections.append(
                StorageReportSection(
                    name=entry.section,
                    path=entry.path,
                    bytes=0,
                    status=DiagnosticStatus.UNAVAILABLE,
                    warnings=(_SYMLINK_SKIPPED_WARNING,),
                )
            )
            continue

        if stat.S_ISREG(root_stats.st_mode):
            sections.append(
                StorageReportSection(
                    name=entry.section,
                    path=entry.path,
                    bytes=max(root_stats.st_size, 0),
                    items=(
                        StorageReportItem(
                            path=entry.path,
                            bytes=max(root_stats.st_size, 0),
                            label=posixpath.basename(entry.path),
                        ),
                    ),
                    limits=(
                        DiagnosticLimit(
                            name="max_depth",
                            unit=DiagnosticLimitUnit.ITEMS,
                            value=entry.max_depth,
                        ),
                        DiagnosticLimit(
                            name="max_items",
                            unit=DiagnosticLimitUnit.ITEMS,
                            value=max_items,
                        ),
                        DiagnosticLimit(
                            name="max_scanned_entries",
                            unit=DiagnosticLimitUnit.ITEMS,
                            value=max_scanned_entries,
                        ),
                    ),
                )
            )
            continue

        if not stat.S_ISDIR(root_stats.st_mode):
            sections.append(
                StorageReportSection(
                    name=entry.section,
                    path=entry.path,
                    bytes=max(root_stats.st_size, 0),
                    warnings=(_UNREADABLE_PATH_WARNING,),
                )
            )
            continue

        state = _StorageSectionTraversalState()
        try:
            with os.scandir(entry.path) as iterator:
                root_children = tuple(sorted(child.path for child in iterator))
        except OSError:
            sections.append(
                StorageReportSection(
                    name=entry.section,
                    path=entry.path,
                    bytes=0,
                    status=DiagnosticStatus.UNAVAILABLE,
                    warnings=(_UNREADABLE_PATH_WARNING,),
                )
            )
            continue

        candidate_items: list[StorageReportItem] = []
        section_bytes = 0
        for child_path in root_children:
            branch_bytes, branch_flags = _branch_size_from_path(
                child_path,
                depth_remaining=entry.max_depth - 1,
                follow_symlinks=entry.follow_symlinks,
                max_scanned_entries=max_scanned_entries,
                state=state,
            )
            section_bytes += branch_bytes
            _merge_flags(state.flags, branch_flags)
            if (
                branch_bytes > 0
                or branch_flags.depth_limit_hit
                or branch_flags.entry_limit_hit
                or branch_flags.unreadable_paths
            ):
                item_warnings = _warnings_from_flags(branch_flags)
                candidate_items.append(
                    StorageReportItem(
                        path=child_path,
                        bytes=branch_bytes,
                        label=posixpath.basename(child_path),
                        warnings=item_warnings,
                    )
                )
            if state.flags.entry_limit_hit:
                break

        ordered_items = tuple(
            sorted(candidate_items, key=lambda item: (-item.bytes, item.path))[:max_items]
        )
        item_limit_hit = len(candidate_items) > max_items
        warnings = _warnings_from_flags(state.flags)
        if item_limit_hit:
            warnings = warnings + ("Only the largest items within the section are shown.",)

        limits = (
            DiagnosticLimit(
                name="max_depth",
                unit=DiagnosticLimitUnit.ITEMS,
                value=entry.max_depth,
                hit=state.flags.depth_limit_hit,
            ),
            DiagnosticLimit(
                name="max_items",
                unit=DiagnosticLimitUnit.ITEMS,
                value=max_items,
                hit=item_limit_hit,
            ),
            DiagnosticLimit(
                name="max_scanned_entries",
                unit=DiagnosticLimitUnit.ITEMS,
                value=max_scanned_entries,
                hit=state.flags.entry_limit_hit,
            ),
        )
        sections.append(
            StorageReportSection(
                name=entry.section,
                path=entry.path,
                bytes=section_bytes,
                items=ordered_items,
                warnings=warnings,
                limits=limits,
            )
        )

    return StorageReport(sections=tuple(sections))


def _infer_proton_log_app_id(path: str) -> int | None:
    match = _PROTON_LOG_APP_ID_PATTERN.fullmatch(posixpath.basename(path))
    if match is None:
        return None
    return int(match.group("app_id"))


def _read_proton_log_excerpt(
    path: str,
    *,
    max_excerpt_characters: int,
) -> tuple[ProtonLogExcerpt | None, tuple[str, ...], bool]:
    try:
        file_size = os.path.getsize(path)
        # Read up to 4 bytes per requested character: UTF-8 encodes a code point in
        # at most 4 bytes, so this guarantees enough bytes to fill the excerpt.
        bytes_to_read = max(4096, max_excerpt_characters * 4)
        with open(path, "rb") as handle:
            if file_size > bytes_to_read:
                handle.seek(max(file_size - bytes_to_read, 0))
                raw = handle.read(bytes_to_read)
                truncated = True
            else:
                raw = handle.read()
                truncated = False
    except OSError:
        return None, (_UNREADABLE_PATH_WARNING,), False

    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
    if len(text) > max_excerpt_characters:
        text = text[-max_excerpt_characters:]
        truncated = True
    if not text.strip():
        return None, (_EMPTY_LOG_WARNING,), False

    excerpt_kwargs: dict[str, Any] = {
        "text": text,
        "truncated": truncated,
        "limits": (
            DiagnosticLimit(
                name="max_excerpt_characters",
                unit=DiagnosticLimitUnit.CHARACTERS,
                value=max_excerpt_characters,
                hit=truncated,
            ),
        ),
    }
    if not truncated:
        line_count = max(1, len(text.splitlines()))
        excerpt_kwargs["line_start"] = 1
        excerpt_kwargs["line_end"] = line_count

    return ProtonLogExcerpt(**excerpt_kwargs), (), truncated


def read_proton_logs(
    paths: Sequence[str] | None = None,
    *,
    home_path: str = "/home/deck",
    max_logs: int = MAX_PROTON_LOG_REFERENCES,
    max_directory_entries: int = _DEFAULT_PROTON_LOG_DIRECTORY_MAX_ENTRIES,
    max_excerpt_characters: int = MAX_PROTON_EXCERPT_CHARACTERS,
    follow_symlinks: bool = False,
) -> ProtonLogReport:
    """Read bounded Proton log summaries from local files or directories."""

    if paths is None:
        selected_paths: tuple[str, ...] = (_normalize_absolute_path(home_path, "home_path"),)
    else:
        if isinstance(paths, (str, bytes)):
            raise DiagnosticsValidationError("proton log paths must be a non-empty sequence")
        selected_paths = tuple(paths)
    if not selected_paths:
        raise DiagnosticsValidationError("proton log paths must be a non-empty sequence")

    normalized_paths = tuple(
        sorted(
            {
                _normalize_absolute_path(path, "proton log path")
                for path in selected_paths
            }
        )
    )
    max_logs = _require_positive_int(max_logs, "max_logs")
    if max_logs > MAX_PROTON_LOG_REFERENCES:
        raise DiagnosticsValidationError(f"max_logs must be at most {MAX_PROTON_LOG_REFERENCES}")
    max_directory_entries = _require_positive_int(max_directory_entries, "max_directory_entries")
    max_excerpt_characters = _require_positive_int(
        max_excerpt_characters,
        "max_excerpt_characters",
    )
    if max_excerpt_characters > MAX_PROTON_EXCERPT_CHARACTERS:
        raise DiagnosticsValidationError(
            "max_excerpt_characters exceeds the bounded Proton excerpt limit"
        )

    warnings: list[str] = []
    candidate_paths: list[tuple[str, float]] = []
    seen_paths: set[str] = set()
    directory_limit_hit = False
    symlink_skipped = False
    sensitive_skipped = False
    unreadable_paths = False
    missing_paths = False

    for requested_path in normalized_paths:
        try:
            _reject_ai_cli_credential_path(requested_path, "proton log path")
        except DiagnosticsValidationError:
            sensitive_skipped = True
            continue

        try:
            stats = os.lstat(requested_path)
        except FileNotFoundError:
            missing_paths = True
            continue
        except OSError:
            unreadable_paths = True
            continue

        if stat.S_ISLNK(stats.st_mode):
            if not follow_symlinks:
                symlink_skipped = True
                continue
            try:
                stats = os.stat(requested_path)
            except FileNotFoundError:
                missing_paths = True
                continue
            except OSError:
                unreadable_paths = True
                continue

        if stat.S_ISDIR(stats.st_mode):
            try:
                with os.scandir(requested_path) as iterator:
                    directory_entries = tuple(sorted(iterator, key=lambda entry: entry.name))
            except OSError:
                unreadable_paths = True
                continue

            if len(directory_entries) > max_directory_entries:
                directory_limit_hit = True
                directory_entries = directory_entries[:max_directory_entries]

            for entry in directory_entries:
                entry_path = _normalize_absolute_path(entry.path, "proton log path")
                try:
                    _reject_ai_cli_credential_path(entry_path, "proton log path")
                except DiagnosticsValidationError:
                    sensitive_skipped = True
                    continue
                try:
                    entry_stats = os.lstat(entry_path)
                except OSError:
                    unreadable_paths = True
                    continue
                if stat.S_ISLNK(entry_stats.st_mode) and not follow_symlinks:
                    symlink_skipped = True
                    continue
                if not stat.S_ISREG(entry_stats.st_mode):
                    continue
                if _PROTON_LOG_APP_ID_PATTERN.fullmatch(entry.name) is None:
                    continue
                if entry_path in seen_paths:
                    continue
                seen_paths.add(entry_path)
                candidate_paths.append((entry_path, entry_stats.st_mtime))
            continue

        if not stat.S_ISREG(stats.st_mode):
            continue
        if requested_path in seen_paths:
            continue
        seen_paths.add(requested_path)
        candidate_paths.append((requested_path, stats.st_mtime))

    ordered_candidates = tuple(sorted(candidate_paths, key=lambda item: (-item[1], item[0])))
    log_limit_hit = len(ordered_candidates) > max_logs
    selected_candidates = ordered_candidates[:max_logs]

    logs: list[ProtonLogReference] = []
    for log_path, modified_at_epoch in selected_candidates:
        excerpt, excerpt_warnings, excerpt_truncated = _read_proton_log_excerpt(
            log_path,
            max_excerpt_characters=max_excerpt_characters,
        )
        log_warnings = excerpt_warnings
        log_limits = (
            DiagnosticLimit(
                name="max_excerpt_characters",
                unit=DiagnosticLimitUnit.CHARACTERS,
                value=max_excerpt_characters,
                hit=excerpt_truncated,
            ),
        )
        logs.append(
            ProtonLogReference(
                path=log_path,
                app_id=_infer_proton_log_app_id(log_path),
                modified_at=datetime.fromtimestamp(
                    modified_at_epoch,
                    tz=timezone.utc,
                ).isoformat(),
                excerpt=excerpt,
                warnings=log_warnings,
                limits=log_limits,
            )
        )

    if missing_paths:
        warnings.append(_UNAVAILABLE_PATH_WARNING)
    if directory_limit_hit:
        warnings.append(_DIRECTORY_SCAN_LIMIT_WARNING)
    if symlink_skipped:
        warnings.append(_SYMLINK_SKIPPED_WARNING)
    if sensitive_skipped:
        warnings.append(_SENSITIVE_PATH_WARNING)
    if unreadable_paths:
        warnings.append(_UNREADABLE_PATH_WARNING)
    if not logs:
        warnings.append(_PROTON_LOG_NOT_FOUND_WARNING)

    report_limits = (
        DiagnosticLimit(
            name="max_logs",
            unit=DiagnosticLimitUnit.ITEMS,
            value=max_logs,
            hit=log_limit_hit,
        ),
        DiagnosticLimit(
            name="max_directory_entries",
            unit=DiagnosticLimitUnit.ITEMS,
            value=max_directory_entries,
            hit=directory_limit_hit,
        ),
        DiagnosticLimit(
            name="max_excerpt_characters",
            unit=DiagnosticLimitUnit.CHARACTERS,
            value=max_excerpt_characters,
            hit=any(
                any(limit.hit for limit in log.limits if limit.name == "max_excerpt_characters")
                for log in logs
            ),
        ),
    )
    report_status = DiagnosticStatus.UNAVAILABLE if not logs else None
    return ProtonLogReport(
        logs=tuple(logs),
        status=report_status,
        warnings=tuple(warnings),
        limits=report_limits,
    )


__all__ = [
    "DiagnosticLimit",
    "DiagnosticLimitUnit",
    "DiagnosticStatus",
    "DiagnosticsValidationError",
    "MAX_DIAGNOSTIC_LIMITS",
    "MAX_DIAGNOSTIC_WARNINGS",
    "MAX_PROTON_EXCERPT_CHARACTERS",
    "MAX_PROTON_LOG_REFERENCES",
    "MAX_STORAGE_PATH_PLAN_DEPTH",
    "MAX_STORAGE_PATH_PLAN_ENTRIES",
    "MAX_STORAGE_PATH_PLAN_LIBRARY_ROOTS",
    "MAX_STORAGE_REPORT_SECTIONS",
    "MAX_STORAGE_SECTION_ITEMS",
    "ProtonLogExcerpt",
    "ProtonLogReference",
    "ProtonLogReport",
    "StoragePathPlanEntry",
    "StorageReport",
    "StorageReportItem",
    "StorageReportSection",
    "StorageSectionName",
    "plan_storage_report_paths",
    "read_proton_logs",
    "read_storage_report",
]
