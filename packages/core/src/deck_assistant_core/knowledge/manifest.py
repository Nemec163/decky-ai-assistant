"""Knowledge pack manifest building from supplied content or local folders.

``build_knowledge_pack_manifest`` never reads from disk; the caller supplies
path/content pairs. ``build_local_folder_knowledge_pack_manifest`` uses the
deterministic source inventory to decide which files to open, then reads each
included file through realpath/commonpath and symlink guards with the per-file
byte cap enforced before decoding.
"""

from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Iterable, Mapping

from deck_assistant_core.knowledge._helpers import (
    KnowledgeValidationError,
    _path_value_entries,
    _require_instance,
    _require_text,
)
from deck_assistant_core.knowledge.contracts import (
    ContentHash,
    KnowledgeDocument,
    KnowledgePackManifest,
    KnowledgePackManifestBuildResult,
    SourceMetadata,
)
from deck_assistant_core.knowledge.filtering import (
    DEFAULT_KNOWLEDGE_SOURCE_FILTER_POLICY,
    KnowledgeSourceFilterPolicy,
    KnowledgeSourceInventoryLimits,
    collect_local_folder_knowledge_source_inventory,
    filter_knowledge_source_document,
)


def build_knowledge_pack_manifest(
    *,
    pack_id: str,
    title: str,
    version: str,
    created_at: str,
    source: SourceMetadata,
    document_contents_by_path: Mapping[str, str] | Iterable[tuple[str, str]],
    description: str | None = None,
    policy: KnowledgeSourceFilterPolicy | None = None,
) -> KnowledgePackManifestBuildResult:
    """Build a manifest from provided local text document contents.

    The caller supplies path/content entries directly; this helper never reads
    from disk. Paths are normalized and filtered with the same policy used by
    source indexing candidates.
    """

    _require_instance(source, SourceMetadata, "knowledge pack source")
    if policy is None:
        policy = DEFAULT_KNOWLEDGE_SOURCE_FILTER_POLICY
    _require_instance(policy, KnowledgeSourceFilterPolicy, "knowledge pack source filter policy")

    prepared_by_path: dict[str, tuple[str, str, str | None]] = {}
    for path, content in _path_content_entries(document_contents_by_path):
        if not isinstance(content, str):
            raise KnowledgeValidationError(f"document content for {path} must be a string")
        byte_length = len(content.encode("utf-8"))
        filter_result = filter_knowledge_source_document(
            path,
            byte_size=byte_length,
            policy=policy,
        )
        if not filter_result.is_included:
            raise KnowledgeValidationError(
                "document path is not supported for knowledge pack: "
                f"{path} ({filter_result.reason.value})"
            )
        if filter_result.normalized_path is None or filter_result.content_type is None:
            raise KnowledgeValidationError(f"document path did not resolve to content: {path}")
        if filter_result.normalized_path in prepared_by_path:
            raise KnowledgeValidationError(
                f"duplicate document path: {filter_result.normalized_path}"
            )
        prepared_by_path[filter_result.normalized_path] = (
            content,
            filter_result.content_type,
            filter_result.matched_pattern,
        )

    if not prepared_by_path:
        raise KnowledgeValidationError("knowledge pack documents must not be empty")

    documents: list[KnowledgeDocument] = []
    contents_by_document_id: dict[str, str] = {}
    for normalized_path in sorted(prepared_by_path):
        content, content_type, matched_pattern = prepared_by_path[normalized_path]
        document_id = _document_id_for_path(source.source_id, normalized_path)
        documents.append(
            KnowledgeDocument(
                document_id=document_id,
                source_id=source.source_id,
                path=normalized_path,
                title=_document_title_from_path(normalized_path, matched_pattern),
                content_type=content_type,
                content_hash=ContentHash.sha256_text(content),
                byte_length=len(content.encode("utf-8")),
            )
        )
        contents_by_document_id[document_id] = content

    manifest = KnowledgePackManifest(
        pack_id=pack_id,
        title=title,
        version=version,
        created_at=created_at,
        description=description,
        sources=(source,),
        documents=tuple(documents),
    )
    return KnowledgePackManifestBuildResult(
        manifest=manifest,
        document_contents=contents_by_document_id,
    )


def build_local_folder_knowledge_pack_manifest(
    *,
    root_path: str,
    pack_id: str,
    title: str,
    version: str,
    created_at: str,
    source: SourceMetadata,
    description: str | None = None,
    policy: KnowledgeSourceFilterPolicy | None = None,
    limits: KnowledgeSourceInventoryLimits | None = None,
) -> KnowledgePackManifestBuildResult:
    """Build a manifest from filtered UTF-8 documents in a local folder.

    The helper uses the local-folder inventory contract before reading file
    contents, so hidden, excluded, unsupported, over-limit, and collection-limit
    rejected files are never opened for content reads.
    """

    _require_text(root_path, "local folder root")
    _require_instance(source, SourceMetadata, "local folder source")
    if policy is None:
        policy = DEFAULT_KNOWLEDGE_SOURCE_FILTER_POLICY
    if limits is None:
        limits = KnowledgeSourceInventoryLimits()
    _require_instance(policy, KnowledgeSourceFilterPolicy, "local folder manifest policy")
    _require_instance(limits, KnowledgeSourceInventoryLimits, "local folder manifest limits")

    absolute_root = os.path.abspath(os.fspath(root_path))
    inventory = collect_local_folder_knowledge_source_inventory(
        absolute_root,
        policy=policy,
        limits=limits,
    )
    if not inventory.included_documents:
        raise KnowledgeValidationError(
            "local folder knowledge source has no supported documents"
        )

    document_contents_by_path: list[tuple[str, str]] = []
    for filter_result in inventory.included_documents:
        normalized_path = filter_result.normalized_path
        if normalized_path is None:
            raise KnowledgeValidationError(
                "included local folder document is missing normalized path"
            )
        file_path = _local_folder_document_file_path(absolute_root, normalized_path)
        document_contents_by_path.append(
            (
                normalized_path,
                _read_local_folder_text_document(
                    file_path,
                    normalized_path,
                    max_file_bytes=policy.max_file_bytes,
                ),
            )
        )

    return build_knowledge_pack_manifest(
        pack_id=pack_id,
        title=title,
        version=version,
        created_at=created_at,
        description=description,
        source=source,
        document_contents_by_path=tuple(document_contents_by_path),
        policy=policy,
    )


def _path_content_entries(
    document_contents_by_path: Mapping[str, str] | Iterable[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    return _path_value_entries(
        document_contents_by_path,
        container_error="document contents by path must be a mapping or entries",
        pair_error="document content entries must be path/content pairs",
        path_field="document path",
    )


def _document_id_for_path(source_id: str, normalized_path: str) -> str:
    return f"{source_id}:{normalized_path}"


def _document_title_from_path(normalized_path: str, matched_pattern: str | None) -> str:
    filename = posixpath.basename(normalized_path)
    title = filename
    if matched_pattern is not None and matched_pattern.startswith("."):
        if filename.lower().endswith(matched_pattern):
            title = filename[: -len(matched_pattern)]
    title = re.sub(r"[-_]+", " ", title).strip()
    return title or filename


def _local_folder_document_file_path(absolute_root: str, normalized_path: str) -> str:
    candidate_path = os.path.abspath(
        os.path.join(absolute_root, *normalized_path.split("/"))
    )
    if os.path.islink(candidate_path):
        raise KnowledgeValidationError(
            f"local folder document must not be a symlink: {normalized_path}"
        )

    root_real_path = os.path.realpath(absolute_root)
    candidate_real_path = os.path.realpath(candidate_path)
    try:
        common_path = os.path.commonpath((root_real_path, candidate_real_path))
    except ValueError as exc:
        raise KnowledgeValidationError(
            f"local folder document resolves outside root: {normalized_path}"
        ) from exc
    if common_path != root_real_path:
        raise KnowledgeValidationError(
            f"local folder document resolves outside root: {normalized_path}"
        )
    return candidate_path


def _read_local_folder_text_document(
    file_path: str,
    normalized_path: str,
    *,
    max_file_bytes: int,
) -> str:
    try:
        with open(file_path, "rb") as handle:
            content_bytes = handle.read(max_file_bytes + 1)
    except OSError as exc:
        detail = exc.strerror or str(exc)
        raise KnowledgeValidationError(
            f"could not read local folder document {normalized_path}: {detail}"
        ) from exc

    if len(content_bytes) > max_file_bytes:
        raise KnowledgeValidationError(
            f"local folder document exceeded max_file_bytes while reading: {normalized_path}"
        )
    try:
        return content_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KnowledgeValidationError(
            f"local folder document is not valid UTF-8: {normalized_path}"
        ) from exc
