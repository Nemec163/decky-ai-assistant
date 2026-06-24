"""Frozen knowledge data contracts.

Packs, documents, sources, citations, chunks, search results, source records, and
the in-memory source registry. These contracts depend only on the package's
private helpers; they never import filtering, chunking, manifest building, or
search, so this module sits at the base of the package dependency graph.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import Enum
from threading import RLock
from types import MappingProxyType
from typing import Any

from deck_assistant_core.knowledge._helpers import (
    KnowledgeValidationError,
    _coerce_enum,
    _get,
    _headings,
    _optional_text,
    _require_bool,
    _require_instance,
    _require_mapping,
    _require_text,
    _sequence,
    _unique_ids,
    _validate_line_range,
    _validate_non_negative_int,
    _validate_timestamp,
)


KNOWLEDGE_PACK_SCHEMA_VERSION = 1
KNOWLEDGE_SQLITE_INDEX_SCHEMA_VERSION = 1


class SourceType(str, Enum):
    """Supported source origins for knowledge packs."""

    GITHUB_REPO = "github_repo"
    GIT_URL = "git_url"
    DOCS_URL = "docs_url"
    LOCAL_FOLDER = "local_folder"
    PACK_REGISTRY = "pack_registry"


def _source_type(value: SourceType | str) -> SourceType:
    return _coerce_enum(value, SourceType, "unknown source type")


@dataclass(frozen=True)
class SourceLicense:
    """License metadata displayed with cited knowledge."""

    name: str
    spdx_id: str | None = None
    url: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "license name")
        _optional_text(self.spdx_id, "license spdx_id")
        _optional_text(self.url, "license url")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "spdx_id": self.spdx_id,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceLicense":
        data = _require_mapping(data, "license")
        return cls(
            name=_get(data, "name", "license"),
            spdx_id=data.get("spdx_id"),
            url=data.get("url"),
        )


@dataclass(frozen=True)
class SourceRevision:
    """Source revision used to build a pack."""

    value: str
    retrieved_at: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.value, "revision value")
        if self.retrieved_at is not None:
            _validate_timestamp(self.retrieved_at, "revision retrieved_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "retrieved_at": self.retrieved_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceRevision":
        data = _require_mapping(data, "revision")
        return cls(
            value=_get(data, "value", "revision"),
            retrieved_at=data.get("retrieved_at"),
        )


@dataclass(frozen=True)
class ContentHash:
    """A content digest used by manifests, documents, and chunks."""

    algorithm: str
    value: str

    def __post_init__(self) -> None:
        algorithm = _require_text(self.algorithm, "hash algorithm").lower()
        value = _require_text(self.value, "hash value").lower()
        if algorithm != "sha256":
            raise KnowledgeValidationError("hash algorithm must be sha256")
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise KnowledgeValidationError("sha256 hash value must be 64 hex characters")
        object.__setattr__(self, "algorithm", algorithm)
        object.__setattr__(self, "value", value)

    @classmethod
    def sha256_text(cls, text: str) -> "ContentHash":
        if not isinstance(text, str):
            raise KnowledgeValidationError("text to hash must be a string")
        return cls(
            algorithm="sha256",
            value=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContentHash":
        data = _require_mapping(data, "hash")
        return cls(
            algorithm=_get(data, "algorithm", "hash"),
            value=_get(data, "value", "hash"),
        )


@dataclass(frozen=True)
class SourceMetadata:
    """Source-level metadata shared by all documents from one origin."""

    source_id: str
    source_type: SourceType
    title: str
    uri: str
    license: SourceLicense
    revision: SourceRevision
    content_hash: ContentHash

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source id")
        source_type = _source_type(self.source_type)
        _require_text(self.title, "source title")
        _require_text(self.uri, "source uri")
        _require_instance(self.license, SourceLicense, "source license")
        _require_instance(self.revision, SourceRevision, "source revision")
        _require_instance(self.content_hash, ContentHash, "source hash")
        object.__setattr__(self, "source_type", source_type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.source_id,
            "type": self.source_type.value,
            "title": self.title,
            "uri": self.uri,
            "license": self.license.to_dict(),
            "revision": self.revision.to_dict(),
            "hash": self.content_hash.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceMetadata":
        data = _require_mapping(data, "source")
        return cls(
            source_id=_get(data, "id", "source"),
            source_type=_source_type(_get(data, "type", "source")),
            title=_get(data, "title", "source"),
            uri=_get(data, "uri", "source"),
            license=SourceLicense.from_dict(_get(data, "license", "source")),
            revision=SourceRevision.from_dict(_get(data, "revision", "source")),
            content_hash=ContentHash.from_dict(_get(data, "hash", "source")),
        )


@dataclass(frozen=True)
class KnowledgeDocument:
    """One text or Markdown file listed in a knowledge pack manifest."""

    document_id: str
    source_id: str
    path: str
    title: str
    content_type: str
    content_hash: ContentHash
    byte_length: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.document_id, "document id")
        _require_text(self.source_id, "document source_id")
        _require_text(self.path, "document path")
        _require_text(self.title, "document title")
        if self.content_type not in {"text/markdown", "text/plain"}:
            raise KnowledgeValidationError(
                "document content_type must be text/markdown or text/plain"
            )
        _require_instance(self.content_hash, ContentHash, "document hash")
        if self.byte_length is not None:
            if not isinstance(self.byte_length, int) or isinstance(self.byte_length, bool):
                raise KnowledgeValidationError("document byte_length must be an integer")
            if self.byte_length < 0:
                raise KnowledgeValidationError("document byte_length must not be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.document_id,
            "source_id": self.source_id,
            "path": self.path,
            "title": self.title,
            "content_type": self.content_type,
            "hash": self.content_hash.to_dict(),
            "byte_length": self.byte_length,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "KnowledgeDocument":
        data = _require_mapping(data, "document")
        return cls(
            document_id=_get(data, "id", "document"),
            source_id=_get(data, "source_id", "document"),
            path=_get(data, "path", "document"),
            title=_get(data, "title", "document"),
            content_type=_get(data, "content_type", "document"),
            content_hash=ContentHash.from_dict(_get(data, "hash", "document")),
            byte_length=data.get("byte_length"),
        )


@dataclass(frozen=True)
class KnowledgePackManifest:
    """Manifest for a local knowledge pack artifact."""

    pack_id: str
    title: str
    version: str
    created_at: str
    sources: tuple[SourceMetadata, ...]
    documents: tuple[KnowledgeDocument, ...]
    description: str | None = None
    schema_version: int = KNOWLEDGE_PACK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.schema_version, int) or isinstance(self.schema_version, bool):
            raise KnowledgeValidationError("manifest schema_version must be an integer")
        if self.schema_version != KNOWLEDGE_PACK_SCHEMA_VERSION:
            raise KnowledgeValidationError(
                f"knowledge pack schema_version must be {KNOWLEDGE_PACK_SCHEMA_VERSION}"
            )
        _require_text(self.pack_id, "manifest id")
        _require_text(self.title, "manifest title")
        _require_text(self.version, "manifest version")
        _validate_timestamp(self.created_at, "manifest created_at")
        _optional_text(self.description, "manifest description")

        sources = tuple(_sequence(self.sources, "manifest sources"))
        documents = tuple(_sequence(self.documents, "manifest documents"))
        if not sources:
            raise KnowledgeValidationError("manifest sources must not be empty")
        if not documents:
            raise KnowledgeValidationError("manifest documents must not be empty")
        for source in sources:
            _require_instance(source, SourceMetadata, "manifest source")
        for document in documents:
            _require_instance(document, KnowledgeDocument, "manifest document")

        source_ids = _unique_ids((source.source_id for source in sources), "source id")
        _unique_ids((document.document_id for document in documents), "document id")
        for document in documents:
            if document.source_id not in source_ids:
                raise KnowledgeValidationError(
                    f"document {document.document_id} references unknown source {document.source_id}"
                )

        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "documents", documents)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.pack_id,
            "title": self.title,
            "version": self.version,
            "created_at": self.created_at,
            "description": self.description,
            "sources": [source.to_dict() for source in self.sources],
            "documents": [document.to_dict() for document in self.documents],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "KnowledgePackManifest":
        data = _require_mapping(data, "manifest")
        schema_version = _get(data, "schema_version", "manifest")
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise KnowledgeValidationError("manifest schema_version must be an integer")
        sources = _get(data, "sources", "manifest")
        documents = _get(data, "documents", "manifest")
        return cls(
            schema_version=schema_version,
            pack_id=_get(data, "id", "manifest"),
            title=_get(data, "title", "manifest"),
            version=_get(data, "version", "manifest"),
            created_at=_get(data, "created_at", "manifest"),
            description=data.get("description"),
            sources=tuple(SourceMetadata.from_dict(item) for item in _sequence(sources, "sources")),
            documents=tuple(
                KnowledgeDocument.from_dict(item) for item in _sequence(documents, "documents")
            ),
        )


@dataclass(frozen=True)
class KnowledgePackManifestBuildResult:
    """Prepared manifest plus document-id content map for local indexing."""

    manifest: KnowledgePackManifest
    document_contents: Mapping[str, str]

    def __post_init__(self) -> None:
        _require_instance(self.manifest, KnowledgePackManifest, "manifest build result manifest")
        if not isinstance(self.document_contents, Mapping):
            raise KnowledgeValidationError("manifest build result contents must be a mapping")
        contents: dict[str, str] = {}
        for document_id, content in self.document_contents.items():
            document_id = _require_text(document_id, "manifest build result content id")
            if not isinstance(content, str):
                raise KnowledgeValidationError(
                    f"manifest build result content for {document_id} must be a string"
                )
            contents[document_id] = content
        object.__setattr__(self, "document_contents", MappingProxyType(contents))


@dataclass(frozen=True)
class KnowledgeCitation:
    """Citation metadata attached to a returned chunk."""

    source_id: str
    source_type: SourceType
    source_title: str
    source_uri: str
    document_id: str
    document_title: str
    document_path: str
    chunk_id: str
    headings: tuple[str, ...]
    start_line: int
    end_line: int
    license: SourceLicense
    revision: SourceRevision

    def __post_init__(self) -> None:
        _require_text(self.source_id, "citation source_id")
        source_type = _source_type(self.source_type)
        _require_text(self.source_title, "citation source_title")
        _require_text(self.source_uri, "citation source_uri")
        _require_text(self.document_id, "citation document_id")
        _require_text(self.document_title, "citation document_title")
        _require_text(self.document_path, "citation document_path")
        _require_text(self.chunk_id, "citation chunk_id")
        headings = _headings(self.headings, "citation headings")
        _validate_line_range(self.start_line, self.end_line)
        _require_instance(self.license, SourceLicense, "citation license")
        _require_instance(self.revision, SourceRevision, "citation revision")
        object.__setattr__(self, "source_type", source_type)
        object.__setattr__(self, "headings", headings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type.value,
            "source_title": self.source_title,
            "source_uri": self.source_uri,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "document_path": self.document_path,
            "chunk_id": self.chunk_id,
            "headings": list(self.headings),
            "start_line": self.start_line,
            "end_line": self.end_line,
            "license": self.license.to_dict(),
            "revision": self.revision.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "KnowledgeCitation":
        data = _require_mapping(data, "citation")
        return cls(
            source_id=_get(data, "source_id", "citation"),
            source_type=_source_type(_get(data, "source_type", "citation")),
            source_title=_get(data, "source_title", "citation"),
            source_uri=_get(data, "source_uri", "citation"),
            document_id=_get(data, "document_id", "citation"),
            document_title=_get(data, "document_title", "citation"),
            document_path=_get(data, "document_path", "citation"),
            chunk_id=_get(data, "chunk_id", "citation"),
            headings=tuple(_sequence(_get(data, "headings", "citation"), "citation headings")),
            start_line=_get(data, "start_line", "citation"),
            end_line=_get(data, "end_line", "citation"),
            license=SourceLicense.from_dict(_get(data, "license", "citation")),
            revision=SourceRevision.from_dict(_get(data, "revision", "citation")),
        )


@dataclass(frozen=True)
class KnowledgeChunk:
    """A deterministic chunk with source citation."""

    chunk_id: str
    source_id: str
    document_id: str
    text: str
    headings: tuple[str, ...]
    start_line: int
    end_line: int
    content_hash: ContentHash
    citation: KnowledgeCitation

    def __post_init__(self) -> None:
        _require_text(self.chunk_id, "chunk id")
        _require_text(self.source_id, "chunk source_id")
        _require_text(self.document_id, "chunk document_id")
        _require_text(self.text, "chunk text")
        headings = _headings(self.headings, "chunk headings")
        _validate_line_range(self.start_line, self.end_line)
        _require_instance(self.content_hash, ContentHash, "chunk hash")
        _require_instance(self.citation, KnowledgeCitation, "chunk citation")
        if self.citation.chunk_id != self.chunk_id:
            raise KnowledgeValidationError("chunk citation chunk_id does not match chunk id")
        if self.citation.source_id != self.source_id:
            raise KnowledgeValidationError("chunk citation source_id does not match chunk source_id")
        if self.citation.document_id != self.document_id:
            raise KnowledgeValidationError(
                "chunk citation document_id does not match chunk document_id"
            )
        if self.citation.headings != headings:
            raise KnowledgeValidationError("chunk citation headings do not match chunk headings")
        object.__setattr__(self, "headings", headings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.chunk_id,
            "source_id": self.source_id,
            "document_id": self.document_id,
            "text": self.text,
            "headings": list(self.headings),
            "start_line": self.start_line,
            "end_line": self.end_line,
            "hash": self.content_hash.to_dict(),
            "citation": self.citation.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "KnowledgeChunk":
        data = _require_mapping(data, "chunk")
        return cls(
            chunk_id=_get(data, "id", "chunk"),
            source_id=_get(data, "source_id", "chunk"),
            document_id=_get(data, "document_id", "chunk"),
            text=_get(data, "text", "chunk"),
            headings=tuple(_sequence(_get(data, "headings", "chunk"), "chunk headings")),
            start_line=_get(data, "start_line", "chunk"),
            end_line=_get(data, "end_line", "chunk"),
            content_hash=ContentHash.from_dict(_get(data, "hash", "chunk")),
            citation=KnowledgeCitation.from_dict(_get(data, "citation", "chunk")),
        )


@dataclass(frozen=True)
class KnowledgeSearchResult:
    """One scored search hit that preserves the existing chunk and citation contracts."""

    chunk: KnowledgeChunk
    score: float
    matched_terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_instance(self.chunk, KnowledgeChunk, "search result chunk")
        if not isinstance(self.score, (int, float)) or isinstance(self.score, bool):
            raise KnowledgeValidationError("search result score must be a number")
        score = float(self.score)
        if not math.isfinite(score):
            raise KnowledgeValidationError("search result score must be finite")
        if score < 0:
            raise KnowledgeValidationError("search result score must not be negative")
        matched_terms = tuple(
            _require_text(item, "search result matched_terms item")
            for item in _sequence(self.matched_terms, "search result matched_terms")
        )
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "matched_terms", matched_terms)

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id

    @property
    def text(self) -> str:
        return self.chunk.text

    @property
    def citation(self) -> KnowledgeCitation:
        return self.chunk.citation

    def to_dict(self) -> dict[str, Any]:
        # ``matched_terms`` is intentionally omitted from the serialized shape: the
        # MCP dispatcher relies on exactly {chunk_id, text, score, citation}. Keep
        # matched_terms available on the dataclass for in-process callers only.
        return {
            "chunk_id": self.chunk.chunk_id,
            "text": self.chunk.text,
            "score": self.score,
            "citation": self.chunk.citation.to_dict(),
        }


class KnowledgeSourceRegistryError(RuntimeError):
    """Raised when source registry state cannot satisfy a request."""


class KnowledgeSourceNotFound(KnowledgeSourceRegistryError):
    """Raised when a source registry entry is unknown."""


@dataclass(frozen=True)
class KnowledgeSourceRecord:
    """Local enablement and index metadata for one knowledge source."""

    source: SourceMetadata
    enabled: bool = True
    disabled_reason: str | None = None
    pack_id: str | None = None
    document_count: int | None = None
    indexed_byte_length: int | None = None
    last_indexed_at: str | None = None

    def __post_init__(self) -> None:
        _require_instance(self.source, SourceMetadata, "source record source")
        enabled = _require_bool(self.enabled, "source record enabled")
        _optional_text(self.disabled_reason, "source record disabled_reason")
        _optional_text(self.pack_id, "source record pack_id")
        if self.document_count is not None:
            _validate_non_negative_int(self.document_count, "source record document_count")
        if self.indexed_byte_length is not None:
            _validate_non_negative_int(
                self.indexed_byte_length,
                "source record indexed_byte_length",
            )
        if self.last_indexed_at is not None:
            _validate_timestamp(self.last_indexed_at, "source record last_indexed_at")
        if enabled and self.disabled_reason is not None:
            raise KnowledgeValidationError(
                "enabled source record must not include disabled_reason"
            )
        if not enabled and self.disabled_reason is None:
            raise KnowledgeValidationError(
                "disabled source record must include disabled_reason"
            )
        object.__setattr__(self, "enabled", enabled)

    @property
    def source_id(self) -> str:
        return self.source.source_id

    def enable(self) -> "KnowledgeSourceRecord":
        """Return the same record enabled for search/listing."""

        return replace(self, enabled=True, disabled_reason=None)

    def disable(self, reason: str) -> "KnowledgeSourceRecord":
        """Return the same record disabled with a user-visible reason."""

        return replace(
            self,
            enabled=False,
            disabled_reason=_require_text(reason, "disabled reason"),
        )

    def to_source_list_item(self) -> dict[str, Any]:
        """Return the stable shape used by source-listing surfaces."""

        data: dict[str, Any] = {
            "source_id": self.source.source_id,
            "name": self.source.title,
            "kind": self.source.source_type.value,
            "enabled": self.enabled,
            "license": self.source.license.name,
            "url": self.source.uri,
            "revision": self.source.revision.value,
        }
        if self.disabled_reason is not None:
            data["disabled_reason"] = self.disabled_reason
        if self.pack_id is not None:
            data["pack_id"] = self.pack_id
        if self.document_count is not None:
            data["document_count"] = self.document_count
        if self.indexed_byte_length is not None:
            data["indexed_byte_length"] = self.indexed_byte_length
        if self.last_indexed_at is not None:
            data["last_indexed_at"] = self.last_indexed_at
        return data

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "enabled": self.enabled,
            "disabled_reason": self.disabled_reason,
            "pack_id": self.pack_id,
            "document_count": self.document_count,
            "indexed_byte_length": self.indexed_byte_length,
            "last_indexed_at": self.last_indexed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "KnowledgeSourceRecord":
        data = _require_mapping(data, "source record")
        return cls(
            source=SourceMetadata.from_dict(_get(data, "source", "source record")),
            enabled=data.get("enabled", True),
            disabled_reason=data.get("disabled_reason"),
            pack_id=data.get("pack_id"),
            document_count=data.get("document_count"),
            indexed_byte_length=data.get("indexed_byte_length"),
            last_indexed_at=data.get("last_indexed_at"),
        )


class KnowledgeSourceRegistry:
    """In-memory registry for local knowledge source state.

    The registry never fetches, indexes, deletes files, or mutates source
    artifacts. Runtime callers should still stage any persisted source-state
    changes through the approval flow.
    """

    def __init__(self, records: Iterable[KnowledgeSourceRecord] = ()) -> None:
        self._records: dict[str, KnowledgeSourceRecord] = {}
        self._lock = RLock()
        for record in records:
            self.add_source_record(record)

    @classmethod
    def from_manifest(
        cls,
        manifest: KnowledgePackManifest,
        *,
        enabled: bool = True,
        disabled_reason: str | None = None,
    ) -> "KnowledgeSourceRegistry":
        """Create source records from a built manifest without loading an index."""

        _require_instance(manifest, KnowledgePackManifest, "source registry manifest")
        enabled = _require_bool(enabled, "source registry enabled")
        if not enabled:
            _require_text(disabled_reason, "source registry disabled_reason")
        elif disabled_reason is not None:
            raise KnowledgeValidationError(
                "enabled source registry records must not include disabled_reason"
            )

        document_counts = Counter(document.source_id for document in manifest.documents)
        # Group document byte lengths by source in a single pass instead of
        # re-scanning all documents once per source.
        byte_lengths_by_source: dict[str, list[int | None]] = {
            source.source_id: [] for source in manifest.sources
        }
        for document in manifest.documents:
            byte_lengths_by_source[document.source_id].append(document.byte_length)

        byte_totals: dict[str, int | None] = {}
        for source in manifest.sources:
            lengths = byte_lengths_by_source[source.source_id]
            byte_totals[source.source_id] = (
                sum(length for length in lengths if length is not None)
                if all(length is not None for length in lengths)
                else None
            )

        return cls(
            KnowledgeSourceRecord(
                source=source,
                enabled=enabled,
                disabled_reason=disabled_reason,
                pack_id=manifest.pack_id,
                document_count=document_counts[source.source_id],
                indexed_byte_length=byte_totals[source.source_id],
                last_indexed_at=manifest.created_at,
            )
            for source in manifest.sources
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "KnowledgeSourceRegistry":
        data = _require_mapping(data, "source registry")
        sources = _get(data, "sources", "source registry")
        return cls(
            KnowledgeSourceRecord.from_dict(item)
            for item in _sequence(sources, "source registry sources")
        )

    def add_source_record(self, record: KnowledgeSourceRecord) -> KnowledgeSourceRecord:
        """Add a source record, rejecting duplicate source IDs."""

        _require_instance(record, KnowledgeSourceRecord, "source registry record")
        with self._lock:
            if record.source_id in self._records:
                raise KnowledgeSourceRegistryError(
                    f"knowledge source already exists: {record.source_id}"
                )
            self._records[record.source_id] = record
            return record

    def upsert_source_record(self, record: KnowledgeSourceRecord) -> KnowledgeSourceRecord:
        """Insert or replace a source record by source ID."""

        _require_instance(record, KnowledgeSourceRecord, "source registry record")
        with self._lock:
            self._records[record.source_id] = record
            return record

    def get_source_record(self, source_id: str) -> KnowledgeSourceRecord:
        """Return one source record by ID."""

        source_id = _require_text(source_id, "source id")
        with self._lock:
            try:
                return self._records[source_id]
            except KeyError as error:
                raise KnowledgeSourceNotFound(source_id) from error

    def enable_source(self, source_id: str) -> KnowledgeSourceRecord:
        """Enable a source record in memory and clear its disabled reason."""

        with self._lock:
            record = self.get_source_record(source_id).enable()
            self._records[record.source_id] = record
            return record

    def disable_source(self, source_id: str, reason: str) -> KnowledgeSourceRecord:
        """Disable a source record in memory with a user-visible reason."""

        with self._lock:
            record = self.get_source_record(source_id).disable(reason)
            self._records[record.source_id] = record
            return record

    def remove_source(self, source_id: str) -> KnowledgeSourceRecord:
        """Remove a source record from registry state without deleting artifacts."""

        source_id = _require_text(source_id, "source id")
        with self._lock:
            try:
                return self._records.pop(source_id)
            except KeyError as error:
                raise KnowledgeSourceNotFound(source_id) from error

    def list_source_records(
        self,
        *,
        include_disabled: bool = True,
    ) -> tuple[KnowledgeSourceRecord, ...]:
        """Return records in deterministic source ID order."""

        include_disabled = _require_bool(
            include_disabled,
            "source registry include_disabled",
        )
        with self._lock:
            records = tuple(
                sorted(
                    self._records.values(),
                    key=lambda record: (record.source_id.lower(), record.source_id),
                )
            )
        if include_disabled:
            return records
        return tuple(record for record in records if record.enabled)

    def list_source_items(
        self,
        *,
        include_disabled: bool = True,
    ) -> tuple[dict[str, Any], ...]:
        """Return source-listing dictionaries in deterministic order."""

        return tuple(
            record.to_source_list_item()
            for record in self.list_source_records(include_disabled=include_disabled)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": [
                record.to_dict()
                for record in self.list_source_records(include_disabled=True)
            ]
        }
