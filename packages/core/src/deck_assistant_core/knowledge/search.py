"""In-memory and persisted SQLite FTS5/BM25 search over manifest chunks.

Two index implementations share the same deterministic chunking and the same
``KnowledgeSearchResult`` contract: an in-memory BM25 index and a persisted
SQLite FTS5 index. FTS query terms are tokenized to ``[a-z0-9]+`` and quoted, and
source-id filters are passed as bound parameters, so neither path interpolates
untrusted text into SQL.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from deck_assistant_core.knowledge._helpers import (
    KnowledgeValidationError,
    _require_instance,
    _require_text,
    _sequence,
    _validate_positive_int,
)
from deck_assistant_core.knowledge.chunking import chunk_document
from deck_assistant_core.knowledge.contracts import (
    KNOWLEDGE_SQLITE_INDEX_SCHEMA_VERSION,
    ContentHash,
    KnowledgeChunk,
    KnowledgePackManifest,
    KnowledgeSearchResult,
)


_BM25_K1 = 1.2
_BM25_B = 0.75
_SEARCH_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class _KnowledgeSearchEntry:
    """One indexed chunk plus its term statistics for in-memory BM25 scoring."""

    position: int
    chunk: KnowledgeChunk
    term_counts: Mapping[str, int]
    term_total: int


class KnowledgeSearchIndex:
    """Deterministic in-memory BM25-style index over manifest document chunks."""

    __slots__ = (
        "_average_chunk_terms",
        "_chunks",
        "_document_frequency",
        "_entries",
        "_manifest",
    )

    def __init__(
        self,
        manifest: KnowledgePackManifest,
        document_contents: Mapping[str, str],
        *,
        max_chunk_chars: int = 1200,
    ) -> None:
        _require_instance(manifest, KnowledgePackManifest, "search index manifest")
        if not isinstance(document_contents, Mapping):
            raise KnowledgeValidationError("document contents must be a mapping")
        _validate_positive_int(max_chunk_chars, "max_chunk_chars")

        chunks = _chunk_manifest_documents(
            manifest,
            document_contents,
            max_chunk_chars=max_chunk_chars,
        )
        entries, document_frequency, average_chunk_terms = _build_search_entries(chunks)

        self._manifest = manifest
        self._chunks = chunks
        self._entries = entries
        self._document_frequency = document_frequency
        self._average_chunk_terms = average_chunk_terms

    @property
    def manifest(self) -> KnowledgePackManifest:
        return self._manifest

    @property
    def chunks(self) -> tuple[KnowledgeChunk, ...]:
        return self._chunks

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        source_ids: Sequence[str] | None = None,
    ) -> tuple[KnowledgeSearchResult, ...]:
        """Return the highest-scoring cited chunks for a plain-text query."""

        _require_text(query, "search query")
        _validate_positive_int(limit, "search limit")
        source_id_filter = _source_id_filter(source_ids)
        query_terms = _search_terms(query)
        if not query_terms:
            return ()

        query_counts = Counter(query_terms)
        query_terms_in_order = _unique_terms(query_terms)
        scored: list[tuple[float, int, tuple[str, ...], KnowledgeChunk]] = []
        # One "entry" is one indexed chunk; the entry count is the corpus size N
        # used by the BM25 IDF term.
        chunk_count = len(self._entries)
        for entry in self._entries:
            if source_id_filter is not None and entry.chunk.source_id not in source_id_filter:
                continue
            score = _bm25_score(
                entry=entry,
                query_counts=query_counts,
                document_frequency=self._document_frequency,
                chunk_count=chunk_count,
                average_chunk_terms=self._average_chunk_terms,
            )
            rounded_score = round(score, 6)
            if rounded_score <= 0:
                continue
            matched_terms = tuple(
                term for term in query_terms_in_order if entry.term_counts.get(term, 0) > 0
            )
            scored.append((rounded_score, entry.position, matched_terms, entry.chunk))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(
            KnowledgeSearchResult(
                chunk=chunk,
                score=score,
                matched_terms=matched_terms,
            )
            for score, _, matched_terms, chunk in scored[:limit]
        )


class SQLiteKnowledgeSearchIndex:
    """Persistent SQLite FTS5/BM25 index over manifest document chunks."""

    __slots__ = ("_cached_chunks", "_connection", "_database_path", "_manifest")

    def __init__(self, database_path: str) -> None:
        database_path = _require_text(database_path, "sqlite knowledge index path")
        if database_path != ":memory:" and not os.path.isfile(database_path):
            raise KnowledgeValidationError(
                "sqlite knowledge index path must be an existing file"
            )

        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        try:
            manifest = _load_sqlite_index_manifest(connection)
        except Exception:
            connection.close()
            raise

        self._database_path = database_path
        self._connection = connection
        self._manifest = manifest
        self._cached_chunks: tuple[KnowledgeChunk, ...] | None = None

    @property
    def database_path(self) -> str:
        return self._database_path

    @property
    def manifest(self) -> KnowledgePackManifest:
        return self._manifest

    @property
    def chunks(self) -> tuple[KnowledgeChunk, ...]:
        # The chunk table is immutable for an opened index, so deserialize it once
        # and cache it; repeated ``.chunks`` access is then as cheap as the
        # in-memory index's property.
        if self._cached_chunks is None:
            rows = self._connection.execute(
                "SELECT chunk_json FROM chunks ORDER BY position"
            ).fetchall()
            self._cached_chunks = tuple(
                KnowledgeChunk.from_dict(json.loads(row["chunk_json"])) for row in rows
            )
        return self._cached_chunks

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        source_ids: Sequence[str] | None = None,
    ) -> tuple[KnowledgeSearchResult, ...]:
        """Return FTS5/BM25-scored cited chunks for a plain-text query."""

        _require_text(query, "search query")
        _validate_positive_int(limit, "search limit")
        source_id_filter = _source_id_filter(source_ids)
        query_terms = _search_terms(query)
        if not query_terms or source_id_filter == frozenset():
            return ()

        fts_query = _sqlite_fts5_query(query_terms)
        sql = [
            "SELECT c.chunk_json, bm25(chunk_fts) AS rank",
            "FROM chunk_fts",
            "JOIN chunks c ON c.id = chunk_fts.rowid",
            "WHERE chunk_fts MATCH ?",
        ]
        parameters: list[Any] = [fts_query]
        if source_id_filter is not None:
            source_ids_in_order = tuple(sorted(source_id_filter))
            placeholders = ", ".join("?" for _ in source_ids_in_order)
            sql.append(f"AND c.source_id IN ({placeholders})")
            parameters.extend(source_ids_in_order)
        sql.append("ORDER BY rank, c.position")
        sql.append("LIMIT ?")
        parameters.append(limit)

        rows = self._connection.execute("\n".join(sql), parameters).fetchall()
        query_terms_in_order = _unique_terms(query_terms)
        results: list[KnowledgeSearchResult] = []
        for row in rows:
            chunk = KnowledgeChunk.from_dict(json.loads(row["chunk_json"]))
            # Re-tokenize the matched chunk text to recover matched_terms. This is
            # bounded by ``limit`` (default 5) rows, so it stays cheap; the FTS
            # table does not expose per-row term positions to recover them directly.
            chunk_terms = set(_search_terms(chunk.text))
            matched_terms = tuple(
                term for term in query_terms_in_order if term in chunk_terms
            )
            score = round(max(0.0, -float(row["rank"])), 6)
            results.append(
                KnowledgeSearchResult(
                    chunk=chunk,
                    score=score,
                    matched_terms=matched_terms,
                )
            )
        return tuple(results)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SQLiteKnowledgeSearchIndex":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def build_knowledge_search_index(
    manifest: KnowledgePackManifest,
    document_contents: Mapping[str, str],
    *,
    max_chunk_chars: int = 1200,
) -> KnowledgeSearchIndex:
    """Build an in-memory search index from a manifest and document-id content map."""

    return KnowledgeSearchIndex(
        manifest,
        document_contents,
        max_chunk_chars=max_chunk_chars,
    )


def build_sqlite_knowledge_search_index(
    database_path: str,
    manifest: KnowledgePackManifest,
    document_contents: Mapping[str, str],
    *,
    max_chunk_chars: int = 1200,
    overwrite: bool = False,
) -> SQLiteKnowledgeSearchIndex:
    """Build a SQLite FTS5/BM25 index file and return an opened reader.

    The index is written to a temporary file in the target directory and then
    atomically moved into place, so callers never observe a partially-written
    database. Existing files are preserved unless ``overwrite`` is explicit.
    """

    database_path = _require_text(database_path, "sqlite knowledge index path")
    if database_path == ":memory:":
        raise KnowledgeValidationError("sqlite knowledge index path must be a file path")
    _require_instance(manifest, KnowledgePackManifest, "sqlite knowledge index manifest")
    _validate_positive_int(max_chunk_chars, "max_chunk_chars")

    absolute_path = os.path.abspath(os.fspath(database_path))
    parent_directory = os.path.dirname(absolute_path) or "."
    if not os.path.isdir(parent_directory):
        raise KnowledgeValidationError(
            "sqlite knowledge index parent directory must exist"
        )
    if os.path.isdir(absolute_path):
        raise KnowledgeValidationError("sqlite knowledge index path must not be a directory")
    if os.path.exists(absolute_path) and not overwrite:
        raise KnowledgeValidationError(
            "sqlite knowledge index path already exists; pass overwrite=True to replace it"
        )

    chunks = _chunk_manifest_documents(
        manifest,
        document_contents,
        max_chunk_chars=max_chunk_chars,
    )
    temporary_handle = tempfile.NamedTemporaryFile(
        prefix=".knowledge-index-",
        suffix=".sqlite3",
        dir=parent_directory,
        delete=False,
    )
    temporary_path = temporary_handle.name
    temporary_handle.close()

    try:
        connection = sqlite3.connect(temporary_path)
        try:
            _initialize_sqlite_index_database(connection, manifest, chunks)
        finally:
            connection.close()
        os.replace(temporary_path, absolute_path)
    except Exception:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise

    return SQLiteKnowledgeSearchIndex(absolute_path)


def _chunk_manifest_documents(
    manifest: KnowledgePackManifest,
    document_contents: Mapping[str, str],
    *,
    max_chunk_chars: int,
) -> tuple[KnowledgeChunk, ...]:
    sources_by_id = {source.source_id: source for source in manifest.sources}
    content_ids = set(_validated_content_keys(document_contents))
    document_ids = {document.document_id for document in manifest.documents}
    missing_ids = sorted(document_ids - content_ids)
    if missing_ids:
        raise KnowledgeValidationError(f"missing document content: {missing_ids[0]}")
    unexpected_ids = sorted(content_ids - document_ids)
    if unexpected_ids:
        raise KnowledgeValidationError(f"unknown document content: {unexpected_ids[0]}")

    chunks: list[KnowledgeChunk] = []
    for document in manifest.documents:
        content = document_contents[document.document_id]
        if not isinstance(content, str):
            raise KnowledgeValidationError(
                f"document content for {document.document_id} must be a string"
            )
        if ContentHash.sha256_text(content) != document.content_hash:
            raise KnowledgeValidationError(
                f"document content hash does not match manifest: {document.document_id}"
            )
        byte_length = len(content.encode("utf-8"))
        if document.byte_length is not None and document.byte_length != byte_length:
            raise KnowledgeValidationError(
                f"document byte_length does not match content: {document.document_id}"
            )
        chunks.extend(
            chunk_document(
                sources_by_id[document.source_id],
                document,
                content,
                max_chars=max_chunk_chars,
            )
        )
    return tuple(chunks)


def _initialize_sqlite_index_database(
    connection: sqlite3.Connection,
    manifest: KnowledgePackManifest,
    chunks: Sequence[KnowledgeChunk],
) -> None:
    _ensure_sqlite_fts5(connection)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            position INTEGER NOT NULL UNIQUE,
            chunk_id TEXT NOT NULL UNIQUE,
            source_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            chunk_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE VIRTUAL TABLE chunk_fts
        USING fts5(chunk_id UNINDEXED, text, tokenize='unicode61')
        """
    )
    connection.executemany(
        "INSERT INTO metadata (key, value) VALUES (?, ?)",
        (
            ("schema_version", str(KNOWLEDGE_SQLITE_INDEX_SCHEMA_VERSION)),
            (
                "manifest_json",
                json.dumps(manifest.to_dict(), sort_keys=True, separators=(",", ":")),
            ),
        ),
    )

    for position, chunk in enumerate(chunks):
        cursor = connection.execute(
            """
            INSERT INTO chunks
              (position, chunk_id, source_id, document_id, chunk_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                position,
                chunk.chunk_id,
                chunk.source_id,
                chunk.document_id,
                json.dumps(chunk.to_dict(), sort_keys=True, separators=(",", ":")),
            ),
        )
        connection.execute(
            "INSERT INTO chunk_fts (rowid, chunk_id, text) VALUES (?, ?, ?)",
            (cursor.lastrowid, chunk.chunk_id, chunk.text),
        )

    connection.commit()


def _load_sqlite_index_manifest(connection: sqlite3.Connection) -> KnowledgePackManifest:
    _ensure_sqlite_fts5(connection)
    try:
        rows = connection.execute("SELECT key, value FROM metadata").fetchall()
    except sqlite3.Error as exc:
        raise KnowledgeValidationError(
            "sqlite knowledge index schema is missing or invalid"
        ) from exc
    metadata = {row["key"]: row["value"] for row in rows}
    schema_version = metadata.get("schema_version")
    if schema_version != str(KNOWLEDGE_SQLITE_INDEX_SCHEMA_VERSION):
        raise KnowledgeValidationError(
            "sqlite knowledge index schema_version is unsupported"
        )
    manifest_json = metadata.get("manifest_json")
    if manifest_json is None:
        raise KnowledgeValidationError("sqlite knowledge index is missing manifest")
    try:
        manifest_data = json.loads(manifest_json)
    except json.JSONDecodeError as exc:
        raise KnowledgeValidationError(
            "sqlite knowledge index manifest is not valid JSON"
        ) from exc
    return KnowledgePackManifest.from_dict(manifest_data)


def _ensure_sqlite_fts5(connection: sqlite3.Connection) -> None:
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE temp._deck_assistant_fts5_check USING fts5(value)"
        )
        connection.execute("DROP TABLE temp._deck_assistant_fts5_check")
    except sqlite3.OperationalError as exc:
        raise KnowledgeValidationError("sqlite FTS5 support is required") from exc


def _validated_content_keys(document_contents: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(_require_text(key, "document content id") for key in document_contents)


def _build_search_entries(
    chunks: Sequence[KnowledgeChunk],
) -> tuple[tuple[_KnowledgeSearchEntry, ...], Mapping[str, int], float]:
    entries: list[_KnowledgeSearchEntry] = []
    # ``document_frequency`` counts, per term, how many chunks (entries) contain it.
    document_frequency: Counter[str] = Counter()
    total_terms = 0

    for position, chunk in enumerate(chunks):
        term_counts = Counter(_search_terms(chunk.text))
        document_frequency.update(term_counts.keys())
        term_total = sum(term_counts.values())
        total_terms += term_total
        entries.append(
            _KnowledgeSearchEntry(
                position=position,
                chunk=chunk,
                term_counts=MappingProxyType(dict(term_counts)),
                term_total=term_total,
            )
        )

    average_chunk_terms = total_terms / len(entries) if entries and total_terms else 1.0
    return (
        tuple(entries),
        MappingProxyType(dict(document_frequency)),
        average_chunk_terms,
    )


def _bm25_score(
    *,
    entry: _KnowledgeSearchEntry,
    query_counts: Mapping[str, int],
    document_frequency: Mapping[str, int],
    chunk_count: int,
    average_chunk_terms: float,
) -> float:
    """Score one chunk (``entry``) against the query using Okapi BM25.

    ``chunk_count`` is the corpus size N (number of indexed chunks) and
    ``document_frequency[term]`` is how many chunks contain ``term``; together
    they form the IDF term. ``entry.term_total`` is the chunk length used for
    length normalization against ``average_chunk_terms``.
    """

    if chunk_count <= 0 or entry.term_total <= 0:
        return 0.0

    score = 0.0
    length_ratio = entry.term_total / average_chunk_terms
    for term, query_frequency in query_counts.items():
        term_frequency = entry.term_counts.get(term, 0)
        if term_frequency <= 0:
            continue
        chunks_with_term = document_frequency.get(term, 0)
        if chunks_with_term <= 0:
            continue
        idf = math.log(
            1
            + (chunk_count - chunks_with_term + 0.5)
            / (chunks_with_term + 0.5)
        )
        denominator = term_frequency + _BM25_K1 * (1 - _BM25_B + _BM25_B * length_ratio)
        score += (
            query_frequency
            * idf
            * (term_frequency * (_BM25_K1 + 1))
            / denominator
        )
    return score


def _search_terms(text: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _SEARCH_TOKEN_RE.finditer(text.lower()))


def _sqlite_fts5_query(terms: Sequence[str]) -> str:
    return " OR ".join(f'"{term}"' for term in _unique_terms(terms))


def _unique_terms(terms: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique.append(term)
    return tuple(unique)


def _source_id_filter(source_ids: Sequence[str] | None) -> frozenset[str] | None:
    if source_ids is None:
        return None
    return frozenset(
        _require_text(item, "source_ids item")
        for item in _sequence(source_ids, "source_ids")
    )
