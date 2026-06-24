"""Deterministic local source filtering, decisions, and inventory collection.

Filtering happens entirely on path strings and supplied byte sizes before any
file content is read. The local-folder inventory walker prunes excluded and
hidden directories during traversal and never opens files for content.
"""

from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from deck_assistant_core.knowledge._helpers import (
    KnowledgeValidationError,
    _coerce_enum,
    _optional_text,
    _path_value_entries,
    _require_instance,
    _require_text,
    _sequence,
    _validate_non_negative_int,
    _validate_positive_int,
)


DEFAULT_KNOWLEDGE_SOURCE_MAX_FILE_BYTES = 256 * 1024

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:($|/)")


class KnowledgeSourceMatchKind(str, Enum):
    """Path pattern type used by the source file filter."""

    SUFFIX = "suffix"
    EXACT_NAME = "exact_name"


def _source_match_kind(value: KnowledgeSourceMatchKind | str) -> KnowledgeSourceMatchKind:
    return _coerce_enum(value, KnowledgeSourceMatchKind, "unknown source match kind")


@dataclass(frozen=True)
class KnowledgeSourceFormat:
    """A supported text document format for future source indexing."""

    pattern: str
    match_kind: KnowledgeSourceMatchKind
    content_type: str

    def __post_init__(self) -> None:
        pattern = _require_text(self.pattern, "source format pattern").lower()
        match_kind = _source_match_kind(self.match_kind)
        if self.content_type not in {"text/markdown", "text/plain"}:
            raise KnowledgeValidationError(
                "source format content_type must be text/markdown or text/plain"
            )
        if match_kind is KnowledgeSourceMatchKind.SUFFIX and not pattern.startswith("."):
            raise KnowledgeValidationError("suffix source format patterns must start with '.'")
        object.__setattr__(self, "pattern", pattern)
        object.__setattr__(self, "match_kind", match_kind)

    def matches(self, normalized_path: str) -> bool:
        filename = posixpath.basename(normalized_path).lower()
        if self.match_kind is KnowledgeSourceMatchKind.EXACT_NAME:
            return filename == self.pattern
        return filename.endswith(self.pattern)


@dataclass(frozen=True)
class KnowledgeSourceFilterPolicy:
    """Deterministic local filtering rules for knowledge source files."""

    supported_formats: tuple[KnowledgeSourceFormat, ...] = field(
        default_factory=lambda: _DEFAULT_KNOWLEDGE_SOURCE_FORMATS
    )
    excluded_directory_names: tuple[str, ...] = field(
        default_factory=lambda: _DEFAULT_EXCLUDED_DIRECTORY_NAMES
    )
    excluded_file_names: tuple[str, ...] = field(
        default_factory=lambda: _DEFAULT_EXCLUDED_FILE_NAMES
    )
    excluded_binary_suffixes: tuple[str, ...] = field(
        default_factory=lambda: _DEFAULT_EXCLUDED_BINARY_SUFFIXES
    )
    max_file_bytes: int = DEFAULT_KNOWLEDGE_SOURCE_MAX_FILE_BYTES

    def __post_init__(self) -> None:
        supported_formats = tuple(_sequence(self.supported_formats, "supported_formats"))
        if not supported_formats:
            raise KnowledgeValidationError("supported_formats must not be empty")
        for item in supported_formats:
            _require_instance(item, KnowledgeSourceFormat, "supported format")
        if not isinstance(self.max_file_bytes, int) or isinstance(self.max_file_bytes, bool):
            raise KnowledgeValidationError("max_file_bytes must be an integer")
        if self.max_file_bytes <= 0:
            raise KnowledgeValidationError("max_file_bytes must be positive")

        object.__setattr__(self, "supported_formats", supported_formats)
        object.__setattr__(
            self,
            "excluded_directory_names",
            _normalized_name_list(self.excluded_directory_names, "excluded_directory_names"),
        )
        object.__setattr__(
            self,
            "excluded_file_names",
            _normalized_name_list(self.excluded_file_names, "excluded_file_names"),
        )
        object.__setattr__(
            self,
            "excluded_binary_suffixes",
            _normalized_suffix_list(self.excluded_binary_suffixes, "excluded_binary_suffixes"),
        )

    def match_format(self, normalized_path: str) -> KnowledgeSourceFormat | None:
        for document_format in self.supported_formats:
            if document_format.matches(normalized_path):
                return document_format
        return None


class KnowledgeSourceFilterDecision(str, Enum):
    """Whether a source file should be indexed into knowledge."""

    INCLUDE = "include"
    EXCLUDE = "exclude"


def _source_filter_decision(
    value: KnowledgeSourceFilterDecision | str,
) -> KnowledgeSourceFilterDecision:
    return _coerce_enum(
        value,
        KnowledgeSourceFilterDecision,
        "unknown source filter decision",
    )


class KnowledgeSourceFilterReason(str, Enum):
    """Stable reason codes for source filtering decisions."""

    INCLUDED_SUPPORTED_TEXT_DOCUMENT = "included_supported_text_document"
    INVALID_PATH = "invalid_path"
    EXCLUDED_HIDDEN_PATH = "excluded_hidden_path"
    EXCLUDED_DIRECTORY = "excluded_directory"
    EXCLUDED_FILE_NAME = "excluded_file_name"
    EXCLUDED_BINARY_SUFFIX = "excluded_binary_suffix"
    UNSUPPORTED_FORMAT = "unsupported_format"
    FILE_TOO_LARGE = "file_too_large"
    MAX_DOCUMENT_COUNT_REACHED = "max_document_count_reached"
    MAX_TOTAL_BYTES_REACHED = "max_total_bytes_reached"


def _source_filter_reason(value: KnowledgeSourceFilterReason | str) -> KnowledgeSourceFilterReason:
    return _coerce_enum(value, KnowledgeSourceFilterReason, "unknown source filter reason")


def _excluded_segment_reason(
    lower_segment: str,
    policy: KnowledgeSourceFilterPolicy,
) -> KnowledgeSourceFilterReason | None:
    """Return the exclusion reason for a lowercased path segment, or ``None``.

    Shared by file and directory filtering so the excluded-directory and
    hidden-segment rules cannot drift apart between the two call sites.
    """

    if lower_segment in policy.excluded_directory_names:
        return KnowledgeSourceFilterReason.EXCLUDED_DIRECTORY
    if lower_segment.startswith("."):
        return KnowledgeSourceFilterReason.EXCLUDED_HIDDEN_PATH
    return None


@dataclass(frozen=True)
class KnowledgeSourceFilterResult:
    """Deterministic include/exclude result for one source file candidate."""

    path: str
    normalized_path: str | None
    decision: KnowledgeSourceFilterDecision
    reason: KnowledgeSourceFilterReason
    content_type: str | None = None
    matched_pattern: str | None = None
    byte_size: int | None = None
    max_file_bytes: int | None = None
    max_document_count: int | None = None
    max_total_bytes: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.path, "source filter path")
        if self.normalized_path is not None:
            _require_text(self.normalized_path, "source filter normalized_path")
        decision = _source_filter_decision(self.decision)
        reason = _source_filter_reason(self.reason)
        _optional_text(self.content_type, "source filter content_type")
        _optional_text(self.matched_pattern, "source filter matched_pattern")
        if self.content_type is not None and self.content_type not in {
            "text/markdown",
            "text/plain",
        }:
            raise KnowledgeValidationError(
                "source filter content_type must be text/markdown or text/plain"
            )
        if self.byte_size is not None:
            _validate_non_negative_int(self.byte_size, "source filter byte_size")
        if self.max_file_bytes is not None:
            _validate_positive_int(self.max_file_bytes, "source filter max_file_bytes")
        if self.max_document_count is not None:
            _validate_positive_int(self.max_document_count, "source filter max_document_count")
        if self.max_total_bytes is not None:
            _validate_positive_int(self.max_total_bytes, "source filter max_total_bytes")
        object.__setattr__(self, "decision", decision)
        object.__setattr__(self, "reason", reason)

    @property
    def is_included(self) -> bool:
        return self.decision is KnowledgeSourceFilterDecision.INCLUDE


def normalize_source_document_path(path: str) -> str:
    """Normalize a candidate source file path to a stable relative POSIX path."""

    text = _require_text(path, "source path").strip()
    normalized_separators = text.replace("\\", "/")
    if normalized_separators.startswith("/") or _WINDOWS_DRIVE_RE.match(
        normalized_separators
    ):
        raise KnowledgeValidationError("source path must be relative")
    normalized_path = posixpath.normpath(normalized_separators)
    if normalized_path in {"", ".", ".."}:
        raise KnowledgeValidationError(
            "source path must resolve to a file within the source root"
        )
    if normalized_path.startswith("../"):
        raise KnowledgeValidationError("source path must stay within the source root")
    return normalized_path


def filter_knowledge_source_document(
    path: str,
    *,
    byte_size: int | None = None,
    policy: KnowledgeSourceFilterPolicy | None = None,
) -> KnowledgeSourceFilterResult:
    """Classify whether a relative source file should be indexed."""

    _require_text(path, "source filter path")
    if policy is None:
        policy = DEFAULT_KNOWLEDGE_SOURCE_FILTER_POLICY
    _require_instance(policy, KnowledgeSourceFilterPolicy, "source filter policy")
    if byte_size is not None:
        _validate_non_negative_int(byte_size, "source filter byte_size")

    try:
        normalized_path = normalize_source_document_path(path)
    except KnowledgeValidationError:
        return KnowledgeSourceFilterResult(
            path=path,
            normalized_path=None,
            decision=KnowledgeSourceFilterDecision.EXCLUDE,
            reason=KnowledgeSourceFilterReason.INVALID_PATH,
            byte_size=byte_size,
            max_file_bytes=policy.max_file_bytes,
        )

    lower_segments = tuple(segment.lower() for segment in normalized_path.split("/"))
    for segment in lower_segments[:-1]:
        directory_reason = _excluded_segment_reason(segment, policy)
        if directory_reason is not None:
            return KnowledgeSourceFilterResult(
                path=path,
                normalized_path=normalized_path,
                decision=KnowledgeSourceFilterDecision.EXCLUDE,
                reason=directory_reason,
                byte_size=byte_size,
                max_file_bytes=policy.max_file_bytes,
            )

    filename = lower_segments[-1]
    if filename.startswith("."):
        return KnowledgeSourceFilterResult(
            path=path,
            normalized_path=normalized_path,
            decision=KnowledgeSourceFilterDecision.EXCLUDE,
            reason=KnowledgeSourceFilterReason.EXCLUDED_HIDDEN_PATH,
            byte_size=byte_size,
            max_file_bytes=policy.max_file_bytes,
        )
    if filename in policy.excluded_file_names:
        return KnowledgeSourceFilterResult(
            path=path,
            normalized_path=normalized_path,
            decision=KnowledgeSourceFilterDecision.EXCLUDE,
            reason=KnowledgeSourceFilterReason.EXCLUDED_FILE_NAME,
            byte_size=byte_size,
            max_file_bytes=policy.max_file_bytes,
        )

    document_format = policy.match_format(normalized_path)
    if document_format is None:
        if any(filename.endswith(suffix) for suffix in policy.excluded_binary_suffixes):
            return KnowledgeSourceFilterResult(
                path=path,
                normalized_path=normalized_path,
                decision=KnowledgeSourceFilterDecision.EXCLUDE,
                reason=KnowledgeSourceFilterReason.EXCLUDED_BINARY_SUFFIX,
                byte_size=byte_size,
                max_file_bytes=policy.max_file_bytes,
            )
        return KnowledgeSourceFilterResult(
            path=path,
            normalized_path=normalized_path,
            decision=KnowledgeSourceFilterDecision.EXCLUDE,
            reason=KnowledgeSourceFilterReason.UNSUPPORTED_FORMAT,
            byte_size=byte_size,
            max_file_bytes=policy.max_file_bytes,
        )

    if byte_size is not None and byte_size > policy.max_file_bytes:
        return KnowledgeSourceFilterResult(
            path=path,
            normalized_path=normalized_path,
            decision=KnowledgeSourceFilterDecision.EXCLUDE,
            reason=KnowledgeSourceFilterReason.FILE_TOO_LARGE,
            content_type=document_format.content_type,
            matched_pattern=document_format.pattern,
            byte_size=byte_size,
            max_file_bytes=policy.max_file_bytes,
        )

    return KnowledgeSourceFilterResult(
        path=path,
        normalized_path=normalized_path,
        decision=KnowledgeSourceFilterDecision.INCLUDE,
        reason=KnowledgeSourceFilterReason.INCLUDED_SUPPORTED_TEXT_DOCUMENT,
        content_type=document_format.content_type,
        matched_pattern=document_format.pattern,
        byte_size=byte_size,
        max_file_bytes=policy.max_file_bytes,
    )


def should_include_knowledge_source_document(
    path: str,
    *,
    byte_size: int | None = None,
    policy: KnowledgeSourceFilterPolicy | None = None,
) -> bool:
    """Return whether a source file should be included under the active policy."""

    return filter_knowledge_source_document(path, byte_size=byte_size, policy=policy).is_included


@dataclass(frozen=True)
class KnowledgeSourceInventoryLimits:
    """Optional collection-wide limits applied after per-file filtering."""

    max_document_count: int | None = None
    max_total_bytes: int | None = None

    def __post_init__(self) -> None:
        if self.max_document_count is not None:
            _validate_positive_int(self.max_document_count, "inventory max_document_count")
        if self.max_total_bytes is not None:
            _validate_positive_int(self.max_total_bytes, "inventory max_total_bytes")


@dataclass(frozen=True)
class KnowledgeSourceInventory:
    """Deterministic included/rejected source candidates for one collection pass."""

    included_documents: tuple[KnowledgeSourceFilterResult, ...]
    rejected_documents: tuple[KnowledgeSourceFilterResult, ...]
    included_total_bytes: int

    def __post_init__(self) -> None:
        included_documents = tuple(_sequence(self.included_documents, "included_documents"))
        rejected_documents = tuple(_sequence(self.rejected_documents, "rejected_documents"))
        for item in included_documents:
            _require_instance(item, KnowledgeSourceFilterResult, "included document")
            if item.decision is not KnowledgeSourceFilterDecision.INCLUDE:
                raise KnowledgeValidationError("included_documents must contain only include results")
        for item in rejected_documents:
            _require_instance(item, KnowledgeSourceFilterResult, "rejected document")
            if item.decision is not KnowledgeSourceFilterDecision.EXCLUDE:
                raise KnowledgeValidationError("rejected_documents must contain only exclude results")
        _validate_non_negative_int(self.included_total_bytes, "included_total_bytes")
        if self.included_total_bytes != sum(item.byte_size or 0 for item in included_documents):
            raise KnowledgeValidationError(
                "included_total_bytes must equal the sum of included document byte_size values"
            )
        object.__setattr__(self, "included_documents", included_documents)
        object.__setattr__(self, "rejected_documents", rejected_documents)

    @property
    def included_document_count(self) -> int:
        return len(self.included_documents)


def build_knowledge_source_inventory(
    file_entries: Mapping[str, int] | Iterable[tuple[str, int]],
    *,
    policy: KnowledgeSourceFilterPolicy | None = None,
    limits: KnowledgeSourceInventoryLimits | None = None,
) -> KnowledgeSourceInventory:
    """Prepare deterministic included and rejected source candidates from file entries."""

    if policy is None:
        policy = DEFAULT_KNOWLEDGE_SOURCE_FILTER_POLICY
    if limits is None:
        limits = KnowledgeSourceInventoryLimits()
    _require_instance(policy, KnowledgeSourceFilterPolicy, "inventory policy")
    _require_instance(limits, KnowledgeSourceInventoryLimits, "inventory limits")

    eligible_results: list[KnowledgeSourceFilterResult] = []
    rejected_results: list[KnowledgeSourceFilterResult] = []
    seen_normalized_paths: set[str] = set()
    for path, byte_size in _path_size_entries(file_entries):
        filter_result = filter_knowledge_source_document(
            path,
            byte_size=byte_size,
            policy=policy,
        )
        if filter_result.normalized_path is not None:
            if filter_result.normalized_path in seen_normalized_paths:
                raise KnowledgeValidationError(
                    f"duplicate source file path: {filter_result.normalized_path}"
                )
            seen_normalized_paths.add(filter_result.normalized_path)
        if filter_result.is_included:
            eligible_results.append(filter_result)
        else:
            rejected_results.append(filter_result)

    eligible_results.sort(key=_source_inventory_sort_key)

    included_documents: list[KnowledgeSourceFilterResult] = []
    total_bytes = 0
    for filter_result in eligible_results:
        byte_size = filter_result.byte_size or 0
        if (
            limits.max_document_count is not None
            and len(included_documents) >= limits.max_document_count
        ):
            rejected_results.append(
                _replace_source_filter_result(
                    filter_result,
                    decision=KnowledgeSourceFilterDecision.EXCLUDE,
                    reason=KnowledgeSourceFilterReason.MAX_DOCUMENT_COUNT_REACHED,
                    max_document_count=limits.max_document_count,
                    max_total_bytes=limits.max_total_bytes,
                )
            )
            continue
        if (
            limits.max_total_bytes is not None
            and total_bytes + byte_size > limits.max_total_bytes
        ):
            rejected_results.append(
                _replace_source_filter_result(
                    filter_result,
                    decision=KnowledgeSourceFilterDecision.EXCLUDE,
                    reason=KnowledgeSourceFilterReason.MAX_TOTAL_BYTES_REACHED,
                    max_document_count=limits.max_document_count,
                    max_total_bytes=limits.max_total_bytes,
                )
            )
            continue

        included_documents.append(filter_result)
        total_bytes += byte_size

    rejected_results.sort(key=_source_inventory_sort_key)
    return KnowledgeSourceInventory(
        included_documents=tuple(included_documents),
        rejected_documents=tuple(rejected_results),
        included_total_bytes=total_bytes,
    )


def collect_local_folder_knowledge_source_inventory(
    root_path: str,
    *,
    policy: KnowledgeSourceFilterPolicy | None = None,
    limits: KnowledgeSourceInventoryLimits | None = None,
) -> KnowledgeSourceInventory:
    """Walk a local folder and build a deterministic source inventory without indexing."""

    _require_text(root_path, "local folder root")
    if policy is None:
        policy = DEFAULT_KNOWLEDGE_SOURCE_FILTER_POLICY
    if limits is None:
        limits = KnowledgeSourceInventoryLimits()
    _require_instance(policy, KnowledgeSourceFilterPolicy, "local folder policy")
    _require_instance(limits, KnowledgeSourceInventoryLimits, "local folder limits")

    absolute_root = os.path.abspath(os.fspath(root_path))
    if not os.path.isdir(absolute_root):
        raise KnowledgeValidationError("local folder root must be an existing directory")

    file_entries: list[tuple[str, int]] = []
    pruned_directories: list[KnowledgeSourceFilterResult] = []
    for current_root, directory_names, file_names in os.walk(
        absolute_root,
        topdown=True,
        followlinks=False,
    ):
        relative_root = os.path.relpath(current_root, absolute_root)
        relative_root = "" if relative_root == "." else relative_root.replace(os.sep, "/")

        sorted_directories = sorted(directory_names, key=lambda item: (item.lower(), item))
        retained_directories: list[str] = []
        for directory_name in sorted_directories:
            relative_path = (
                directory_name if not relative_root else f"{relative_root}/{directory_name}"
            )
            pruned_result = _directory_inventory_exclusion(relative_path, policy)
            if pruned_result is not None:
                pruned_directories.append(pruned_result)
                continue
            retained_directories.append(directory_name)
        directory_names[:] = retained_directories

        for file_name in sorted(file_names, key=lambda item: (item.lower(), item)):
            relative_path = file_name if not relative_root else f"{relative_root}/{file_name}"
            file_path = os.path.join(current_root, file_name)
            if not os.path.isfile(file_path):
                continue
            file_entries.append((relative_path, os.path.getsize(file_path)))

    inventory = build_knowledge_source_inventory(
        file_entries,
        policy=policy,
        limits=limits,
    )
    if not pruned_directories:
        return inventory

    rejected_documents = tuple(
        sorted(
            (*inventory.rejected_documents, *pruned_directories),
            key=_source_inventory_sort_key,
        )
    )
    return KnowledgeSourceInventory(
        included_documents=inventory.included_documents,
        rejected_documents=rejected_documents,
        included_total_bytes=inventory.included_total_bytes,
    )


def _directory_inventory_exclusion(
    relative_path: str,
    policy: KnowledgeSourceFilterPolicy,
) -> KnowledgeSourceFilterResult | None:
    normalized_path = normalize_source_document_path(relative_path)
    last_segment = normalized_path.split("/")[-1].lower()
    reason = _excluded_segment_reason(last_segment, policy)
    if reason is None:
        return None
    return KnowledgeSourceFilterResult(
        path=relative_path,
        normalized_path=normalized_path,
        decision=KnowledgeSourceFilterDecision.EXCLUDE,
        reason=reason,
        max_file_bytes=policy.max_file_bytes,
    )


def _replace_source_filter_result(
    result: KnowledgeSourceFilterResult,
    *,
    decision: KnowledgeSourceFilterDecision,
    reason: KnowledgeSourceFilterReason,
    max_document_count: int | None = None,
    max_total_bytes: int | None = None,
) -> KnowledgeSourceFilterResult:
    return KnowledgeSourceFilterResult(
        path=result.path,
        normalized_path=result.normalized_path,
        decision=decision,
        reason=reason,
        content_type=result.content_type,
        matched_pattern=result.matched_pattern,
        byte_size=result.byte_size,
        max_file_bytes=result.max_file_bytes,
        max_document_count=max_document_count,
        max_total_bytes=max_total_bytes,
    )


def _source_inventory_sort_key(
    result: KnowledgeSourceFilterResult,
) -> tuple[bool, str, str]:
    normalized_path = result.normalized_path
    stable_path = (normalized_path or result.path.replace("\\", "/")).lower()
    return (
        normalized_path is None,
        stable_path,
        result.path,
    )


def _path_size_entries(
    file_entries: Mapping[str, int] | Iterable[tuple[str, int]],
) -> tuple[tuple[str, int], ...]:
    def _validate_byte_size(value: Any, path: str) -> None:
        _validate_non_negative_int(value, f"file entry byte_size for {path}")

    return _path_value_entries(
        file_entries,
        container_error="file entries must be a mapping or entries",
        pair_error="file entries must be path/byte_size pairs",
        path_field="file entry path",
        value_validator=_validate_byte_size,
    )


def _normalized_name_list(values: Any, field_name: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for item in _sequence(values, field_name):
        normalized.append(_require_text(item, field_name).lower())
    return tuple(normalized)


def _normalized_suffix_list(values: Any, field_name: str) -> tuple[str, ...]:
    normalized = _normalized_name_list(values, field_name)
    for item in normalized:
        if not item.startswith("."):
            raise KnowledgeValidationError(f"{field_name} values must start with '.'")
    return normalized


_DEFAULT_KNOWLEDGE_SOURCE_FORMATS = (
    KnowledgeSourceFormat(".md", KnowledgeSourceMatchKind.SUFFIX, "text/markdown"),
    KnowledgeSourceFormat(".markdown", KnowledgeSourceMatchKind.SUFFIX, "text/markdown"),
    KnowledgeSourceFormat(".mdx", KnowledgeSourceMatchKind.SUFFIX, "text/markdown"),
    KnowledgeSourceFormat(".txt", KnowledgeSourceMatchKind.SUFFIX, "text/plain"),
    KnowledgeSourceFormat(".rst", KnowledgeSourceMatchKind.SUFFIX, "text/plain"),
    KnowledgeSourceFormat(".adoc", KnowledgeSourceMatchKind.SUFFIX, "text/plain"),
    KnowledgeSourceFormat(".asciidoc", KnowledgeSourceMatchKind.SUFFIX, "text/plain"),
    KnowledgeSourceFormat(".json", KnowledgeSourceMatchKind.SUFFIX, "text/plain"),
    KnowledgeSourceFormat(".jsonl", KnowledgeSourceMatchKind.SUFFIX, "text/plain"),
    KnowledgeSourceFormat(".yaml", KnowledgeSourceMatchKind.SUFFIX, "text/plain"),
    KnowledgeSourceFormat(".yml", KnowledgeSourceMatchKind.SUFFIX, "text/plain"),
    KnowledgeSourceFormat(".toml", KnowledgeSourceMatchKind.SUFFIX, "text/plain"),
    KnowledgeSourceFormat(".ini", KnowledgeSourceMatchKind.SUFFIX, "text/plain"),
    KnowledgeSourceFormat(".cfg", KnowledgeSourceMatchKind.SUFFIX, "text/plain"),
    KnowledgeSourceFormat("readme", KnowledgeSourceMatchKind.EXACT_NAME, "text/plain"),
    KnowledgeSourceFormat("license", KnowledgeSourceMatchKind.EXACT_NAME, "text/plain"),
    KnowledgeSourceFormat("copying", KnowledgeSourceMatchKind.EXACT_NAME, "text/plain"),
    KnowledgeSourceFormat("notice", KnowledgeSourceMatchKind.EXACT_NAME, "text/plain"),
    KnowledgeSourceFormat("authors", KnowledgeSourceMatchKind.EXACT_NAME, "text/plain"),
    KnowledgeSourceFormat("changelog", KnowledgeSourceMatchKind.EXACT_NAME, "text/plain"),
    KnowledgeSourceFormat("changes", KnowledgeSourceMatchKind.EXACT_NAME, "text/plain"),
    KnowledgeSourceFormat("history", KnowledgeSourceMatchKind.EXACT_NAME, "text/plain"),
)

_DEFAULT_EXCLUDED_DIRECTORY_NAMES = (
    ".cache",
    ".git",
    ".hg",
    ".mypy_cache",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".svelte-kit",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "third-party",
    "third_party",
    "vendor",
    "venv",
)

_DEFAULT_EXCLUDED_FILE_NAMES = (
    "bun.lock",
    "bun.lockb",
    "cargo.lock",
    "composer.lock",
    "gemfile.lock",
    "npm-shrinkwrap.json",
    "package-lock.json",
    "pipfile.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
)

_DEFAULT_EXCLUDED_BINARY_SUFFIXES = (
    ".7z",
    ".avi",
    ".bin",
    ".bz2",
    ".class",
    ".dll",
    ".dmg",
    ".doc",
    ".docx",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mov",
    ".mp3",
    ".mp4",
    ".o",
    ".otf",
    ".pdf",
    ".png",
    ".pyc",
    ".so",
    ".tar",
    ".ttf",
    ".wav",
    ".webm",
    ".webp",
    ".xz",
    ".zip",
)

DEFAULT_KNOWLEDGE_SOURCE_FILTER_POLICY = KnowledgeSourceFilterPolicy()
