"""Knowledge pack contracts, source filtering, chunking, and local search indexes.

This package defines local data contracts only. It does not fetch sources, start
MCP servers, or touch UI state. Persistent indexes are explicit local SQLite
files built from caller-supplied manifest content.

The package is split into cohesive modules:

- ``contracts``  -- frozen packs/documents/sources/citations/chunks/records/registry
- ``filtering``  -- deterministic filter policy, decisions, and source inventory
- ``chunking``   -- Markdown/plain-text chunking with citations
- ``manifest``   -- manifest building from supplied content or local folders
- ``search``     -- in-memory and SQLite FTS5/BM25 indexes

Every public name the package previously exported from ``knowledge.py`` is
re-exported here so ``import deck_assistant_core.knowledge`` and the lazy exports
in ``deck_assistant_core.__init__`` continue to resolve unchanged.
"""

from __future__ import annotations

from deck_assistant_core.knowledge._helpers import KnowledgeValidationError
from deck_assistant_core.knowledge.chunking import chunk_document
from deck_assistant_core.knowledge.contracts import (
    KNOWLEDGE_PACK_SCHEMA_VERSION,
    KNOWLEDGE_SQLITE_INDEX_SCHEMA_VERSION,
    ContentHash,
    KnowledgeChunk,
    KnowledgeCitation,
    KnowledgeDocument,
    KnowledgePackManifest,
    KnowledgePackManifestBuildResult,
    KnowledgeSearchResult,
    KnowledgeSourceNotFound,
    KnowledgeSourceRecord,
    KnowledgeSourceRegistry,
    KnowledgeSourceRegistryError,
    SourceLicense,
    SourceMetadata,
    SourceRevision,
    SourceType,
)
from deck_assistant_core.knowledge.filtering import (
    DEFAULT_KNOWLEDGE_SOURCE_FILTER_POLICY,
    DEFAULT_KNOWLEDGE_SOURCE_MAX_FILE_BYTES,
    KnowledgeSourceFilterDecision,
    KnowledgeSourceFilterPolicy,
    KnowledgeSourceFilterReason,
    KnowledgeSourceFilterResult,
    KnowledgeSourceFormat,
    KnowledgeSourceInventory,
    KnowledgeSourceInventoryLimits,
    KnowledgeSourceMatchKind,
    build_knowledge_source_inventory,
    collect_local_folder_knowledge_source_inventory,
    filter_knowledge_source_document,
    normalize_source_document_path,
    should_include_knowledge_source_document,
)
from deck_assistant_core.knowledge.manifest import (
    build_knowledge_pack_manifest,
    build_local_folder_knowledge_pack_manifest,
)
from deck_assistant_core.knowledge.search import (
    KnowledgeSearchIndex,
    SQLiteKnowledgeSearchIndex,
    build_knowledge_search_index,
    build_sqlite_knowledge_search_index,
)


__all__ = [
    "ContentHash",
    "DEFAULT_KNOWLEDGE_SOURCE_FILTER_POLICY",
    "DEFAULT_KNOWLEDGE_SOURCE_MAX_FILE_BYTES",
    "KNOWLEDGE_PACK_SCHEMA_VERSION",
    "KNOWLEDGE_SQLITE_INDEX_SCHEMA_VERSION",
    "KnowledgeChunk",
    "KnowledgeCitation",
    "KnowledgeDocument",
    "KnowledgePackManifest",
    "KnowledgePackManifestBuildResult",
    "KnowledgeSearchIndex",
    "KnowledgeSearchResult",
    "KnowledgeSourceFilterDecision",
    "KnowledgeSourceFilterPolicy",
    "KnowledgeSourceFilterReason",
    "KnowledgeSourceFilterResult",
    "KnowledgeSourceFormat",
    "KnowledgeSourceInventory",
    "KnowledgeSourceInventoryLimits",
    "KnowledgeSourceMatchKind",
    "KnowledgeSourceNotFound",
    "KnowledgeSourceRecord",
    "KnowledgeSourceRegistry",
    "KnowledgeSourceRegistryError",
    "KnowledgeValidationError",
    "SQLiteKnowledgeSearchIndex",
    "SourceLicense",
    "SourceMetadata",
    "SourceRevision",
    "SourceType",
    "build_knowledge_pack_manifest",
    "build_knowledge_search_index",
    "build_knowledge_source_inventory",
    "build_local_folder_knowledge_pack_manifest",
    "build_sqlite_knowledge_search_index",
    "chunk_document",
    "collect_local_folder_knowledge_source_inventory",
    "filter_knowledge_source_document",
    "normalize_source_document_path",
    "should_include_knowledge_source_document",
]
