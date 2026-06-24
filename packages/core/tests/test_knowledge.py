from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from deck_assistant_core import (
    ContentHash,
    DEFAULT_KNOWLEDGE_SOURCE_MAX_FILE_BYTES,
    KnowledgeDocument,
    KnowledgePackManifest,
    KnowledgePackManifestBuildResult,
    KnowledgeSearchIndex,
    KnowledgeSourceFilterDecision,
    KnowledgeSourceFilterPolicy,
    KnowledgeSourceFilterReason,
    KnowledgeValidationError,
    SourceLicense,
    SourceMetadata,
    SourceRevision,
    SourceType,
    SQLiteKnowledgeSearchIndex,
    build_knowledge_pack_manifest,
    build_knowledge_search_index,
    build_local_folder_knowledge_pack_manifest,
    build_sqlite_knowledge_search_index,
    chunk_document,
    filter_knowledge_source_document,
    normalize_source_document_path,
    should_include_knowledge_source_document,
)
from deck_assistant_core.knowledge import (
    KnowledgeSourceInventory,
    KnowledgeSourceInventoryLimits,
    KnowledgeSourceNotFound,
    KnowledgeSourceRecord,
    KnowledgeSourceRegistry,
    KnowledgeSourceRegistryError,
    build_knowledge_source_inventory,
    collect_local_folder_knowledge_source_inventory,
)


def _sqlite_fts5_available() -> bool:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE test_fts USING fts5(value)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        connection.close()


class KnowledgeContractTests(unittest.TestCase):
    def test_manifest_round_trip_preserves_schema(self) -> None:
        content = "# Steam Deck Basics\nUse Gaming Mode for the default experience.\n"
        source = _source()
        document = _document(content)
        manifest = KnowledgePackManifest(
            pack_id="core-deck-pack",
            title="Core Deck Pack",
            version="0.1.0",
            created_at="2026-06-21T10:00:00Z",
            description="Small local Steam Deck reference pack.",
            sources=(source,),
            documents=(document,),
        )

        data = manifest.to_dict()
        restored = KnowledgePackManifest.from_dict(json.loads(json.dumps(data)))

        self.assertEqual(restored.to_dict(), data)
        self.assertEqual(restored.schema_version, 1)
        self.assertEqual(restored.sources[0].source_type, SourceType.DOCS_URL)
        self.assertEqual(restored.documents[0].content_hash, ContentHash.sha256_text(content))

    def test_chunk_document_preserves_headings_and_citations(self) -> None:
        content = "\n".join(
            (
                "# Deck Setup",
                "Intro line.",
                "",
                "## Shader Cache",
                "Cache line one.",
                "Cache line two.",
                "",
                "## Proton Logs",
                "Logs line.",
            )
        )
        source = _source()
        document = _document(content)

        chunks = chunk_document(source, document, content, max_chars=90)
        repeated = chunk_document(source, document, content, max_chars=90)

        self.assertEqual(
            [chunk.to_dict() for chunk in chunks],
            [chunk.to_dict() for chunk in repeated],
        )
        self.assertEqual(
            [chunk.chunk_id for chunk in chunks],
            [
                "steam-deck-basics#chunk-0001",
                "steam-deck-basics#chunk-0002",
                "steam-deck-basics#chunk-0003",
            ],
        )

        self.assertEqual(chunks[0].headings, ("Deck Setup",))
        self.assertEqual(chunks[0].start_line, 1)
        self.assertEqual(chunks[0].end_line, 2)

        self.assertEqual(chunks[1].headings, ("Deck Setup", "Shader Cache"))
        self.assertEqual(chunks[1].citation.headings, ("Deck Setup", "Shader Cache"))
        self.assertEqual(chunks[1].citation.source_title, "Steam Deck Docs")
        self.assertEqual(chunks[1].citation.document_path, "docs/steam-deck-basics.md")
        self.assertEqual(chunks[1].citation.license.name, "Creative Commons Attribution 4.0")
        self.assertEqual(chunks[1].start_line, 4)
        self.assertEqual(chunks[1].end_line, 6)

        self.assertEqual(chunks[2].headings, ("Deck Setup", "Proton Logs"))

    def test_plain_text_chunking_does_not_parse_markdown_headings(self) -> None:
        content = "# Literal line in a text file\nStill plain text."
        source = _source()
        document = KnowledgeDocument(
            document_id="plain-notes",
            source_id=source.source_id,
            path="notes/plain.txt",
            title="Plain Notes",
            content_type="text/plain",
            content_hash=ContentHash.sha256_text(content),
            byte_length=len(content.encode("utf-8")),
        )

        chunks = chunk_document(source, document, content)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].headings, ())
        self.assertEqual(chunks[0].text, content)

    def test_search_index_returns_deterministic_scored_cited_chunks(self) -> None:
        source = _source()
        shader_content = "\n".join(
            (
                "# Shader Cache",
                "Shader cache can improve repeat game launches.",
                "Clear shader cache only while troubleshooting a specific problem.",
            )
        )
        storage_content = "\n".join(
            (
                "# Cache Cleanup",
                "Cache cleanup can free storage after troubleshooting.",
            )
        )
        shader_document = _document_with(
            shader_content,
            document_id="shader-cache",
            source=source,
            path="docs/shader-cache.md",
            title="Shader Cache",
        )
        storage_document = _document_with(
            storage_content,
            document_id="cache-cleanup",
            source=source,
            path="docs/cache-cleanup.md",
            title="Cache Cleanup",
        )
        manifest = _manifest(source, shader_document, storage_document)

        index = build_knowledge_search_index(
            manifest,
            {
                shader_document.document_id: shader_content,
                storage_document.document_id: storage_content,
            },
        )
        results = index.search("shader cache", limit=5)
        repeated = index.search("shader cache", limit=5)

        self.assertIsInstance(index, KnowledgeSearchIndex)
        self.assertEqual(
            [result.to_dict() for result in results],
            [result.to_dict() for result in repeated],
        )
        self.assertEqual(
            [result.chunk.document_id for result in results],
            ["shader-cache", "cache-cleanup"],
        )
        self.assertGreater(results[0].score, results[1].score)
        self.assertEqual(results[0].chunk_id, results[0].chunk.chunk_id)
        self.assertEqual(results[0].citation, results[0].chunk.citation)
        self.assertEqual(
            results[0].citation.license.name,
            "Creative Commons Attribution 4.0",
        )
        self.assertEqual(set(results[0].to_dict()), {"chunk_id", "text", "score", "citation"})
        self.assertEqual(results[0].matched_terms, ("shader", "cache"))

    def test_search_index_filters_by_source_id_and_limit(self) -> None:
        decky_source = _source(
            source_id="decky-docs",
            title="Decky Docs",
            uri="https://docs.decky.xyz/",
        )
        proton_source = _source(
            source_id="proton-docs",
            title="Proton Docs",
            uri="https://github.com/ValveSoftware/Proton",
        )
        decky_content = "# Logs\nDecky logs capture plugin failures."
        proton_content = "# Logs\nProton logs capture game launch failures."
        decky_document = _document_with(
            decky_content,
            document_id="decky-logs",
            source=decky_source,
            path="docs/decky-logs.md",
            title="Decky Logs",
        )
        proton_document = _document_with(
            proton_content,
            document_id="proton-logs",
            source=proton_source,
            path="docs/proton-logs.md",
            title="Proton Logs",
        )
        manifest = KnowledgePackManifest(
            pack_id="multi-source-pack",
            title="Multi Source Pack",
            version="0.1.0",
            created_at="2026-06-21T10:00:00Z",
            sources=(decky_source, proton_source),
            documents=(decky_document, proton_document),
        )
        index = build_knowledge_search_index(
            manifest,
            {
                decky_document.document_id: decky_content,
                proton_document.document_id: proton_content,
            },
        )

        limited = index.search("logs failures", limit=1)
        filtered = index.search("logs failures", source_ids=("proton-docs",), limit=5)

        self.assertEqual(len(limited), 1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].chunk.source_id, "proton-docs")
        self.assertIn("Proton logs", filtered[0].text)

    @unittest.skipUnless(_sqlite_fts5_available(), "sqlite3 FTS5 is not available")
    def test_sqlite_search_index_persists_bm25_results(self) -> None:
        source = _source()
        shader_content = "\n".join(
            (
                "# Shader Cache",
                "Shader cache can improve repeat game launches.",
                "Clear shader cache only while troubleshooting a specific problem.",
            )
        )
        storage_content = "\n".join(
            (
                "# Cache Cleanup",
                "Cache cleanup can free storage after troubleshooting.",
            )
        )
        shader_document = _document_with(
            shader_content,
            document_id="shader-cache",
            source=source,
            path="docs/shader-cache.md",
            title="Shader Cache",
        )
        storage_document = _document_with(
            storage_content,
            document_id="cache-cleanup",
            source=source,
            path="docs/cache-cleanup.md",
            title="Cache Cleanup",
        )
        manifest = _manifest(source, shader_document, storage_document)

        with tempfile.TemporaryDirectory() as root:
            database_path = os.path.join(root, "knowledge.sqlite3")
            index = build_sqlite_knowledge_search_index(
                database_path,
                manifest,
                {
                    shader_document.document_id: shader_content,
                    storage_document.document_id: storage_content,
                },
            )
            try:
                results = index.search("shader cache", limit=5)
                repeated = index.search("shader cache", limit=5)
            finally:
                index.close()

            with SQLiteKnowledgeSearchIndex(database_path) as reopened:
                reopened_results = reopened.search("shader cache", limit=5)
                reopened_manifest = reopened.manifest
                reopened_chunks = reopened.chunks

        self.assertEqual(
            [result.to_dict() for result in results],
            [result.to_dict() for result in repeated],
        )
        self.assertEqual(
            [result.to_dict() for result in reopened_results],
            [result.to_dict() for result in results],
        )
        self.assertEqual(reopened_manifest.to_dict(), manifest.to_dict())
        self.assertEqual(
            [chunk.chunk_id for chunk in reopened_chunks],
            ["shader-cache#chunk-0001", "cache-cleanup#chunk-0001"],
        )
        self.assertEqual(
            [result.chunk.document_id for result in results],
            ["shader-cache", "cache-cleanup"],
        )
        self.assertGreater(results[0].score, results[1].score)
        self.assertEqual(results[0].matched_terms, ("shader", "cache"))
        self.assertEqual(results[0].citation.document_path, "docs/shader-cache.md")

    @unittest.skipUnless(_sqlite_fts5_available(), "sqlite3 FTS5 is not available")
    def test_sqlite_search_index_chunks_property_is_cached_and_stable(self) -> None:
        # M13: repeated `.chunks` access must reuse one deserialized tuple instead of
        # re-reading and re-deserializing the whole table each time.
        content = "# Steam Deck Basics\nUse Gaming Mode for the default experience.\n"
        source = _source()
        document = _document(content)
        manifest = _manifest(source, document)

        with tempfile.TemporaryDirectory() as root:
            database_path = os.path.join(root, "knowledge.sqlite3")
            with build_sqlite_knowledge_search_index(
                database_path,
                manifest,
                {document.document_id: content},
            ) as index:
                first = index.chunks
                second = index.chunks

                self.assertIs(first, second)
                self.assertEqual(
                    [chunk.chunk_id for chunk in first],
                    [chunk.to_dict()["id"] for chunk in second],
                )

    def test_search_result_to_dict_omits_matched_terms(self) -> None:
        # L15: matched_terms is intentionally not serialized; the MCP dispatcher
        # depends on exactly {chunk_id, text, score, citation}.
        source = _source()
        content = "# Shader Cache\nShader cache improves repeat launches.\n"
        document = _document_with(
            content,
            document_id="shader-cache",
            source=source,
            path="docs/shader-cache.md",
            title="Shader Cache",
        )
        manifest = _manifest(source, document)
        index = build_knowledge_search_index(manifest, {document.document_id: content})

        results = index.search("shader cache")

        self.assertEqual(results[0].matched_terms, ("shader", "cache"))
        self.assertEqual(
            set(results[0].to_dict()),
            {"chunk_id", "text", "score", "citation"},
        )
        self.assertNotIn("matched_terms", results[0].to_dict())

    @unittest.skipUnless(_sqlite_fts5_available(), "sqlite3 FTS5 is not available")
    def test_sqlite_search_index_filters_by_source_id(self) -> None:
        decky_source = _source(
            source_id="decky-docs",
            title="Decky Docs",
            uri="https://docs.decky.xyz/",
        )
        proton_source = _source(
            source_id="proton-docs",
            title="Proton Docs",
            uri="https://github.com/ValveSoftware/Proton",
        )
        decky_content = "# Logs\nDecky logs capture plugin failures."
        proton_content = "# Logs\nProton logs capture game launch failures."
        decky_document = _document_with(
            decky_content,
            document_id="decky-logs",
            source=decky_source,
            path="docs/decky-logs.md",
            title="Decky Logs",
        )
        proton_document = _document_with(
            proton_content,
            document_id="proton-logs",
            source=proton_source,
            path="docs/proton-logs.md",
            title="Proton Logs",
        )
        manifest = KnowledgePackManifest(
            pack_id="multi-source-pack",
            title="Multi Source Pack",
            version="0.1.0",
            created_at="2026-06-21T10:00:00Z",
            sources=(decky_source, proton_source),
            documents=(decky_document, proton_document),
        )

        with tempfile.TemporaryDirectory() as root:
            database_path = os.path.join(root, "knowledge.sqlite3")
            with build_sqlite_knowledge_search_index(
                database_path,
                manifest,
                {
                    decky_document.document_id: decky_content,
                    proton_document.document_id: proton_content,
                },
            ) as index:
                limited = index.search("logs failures", limit=1)
                filtered = index.search(
                    "logs failures",
                    source_ids=("proton-docs",),
                    limit=5,
                )
                empty_filtered = index.search(
                    "logs failures",
                    source_ids=(),
                    limit=5,
                )

        self.assertEqual(len(limited), 1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].chunk.source_id, "proton-docs")
        self.assertIn("Proton logs", filtered[0].text)
        self.assertEqual(empty_filtered, ())

    @unittest.skipUnless(_sqlite_fts5_available(), "sqlite3 FTS5 is not available")
    def test_sqlite_search_index_requires_explicit_overwrite(self) -> None:
        content = "# Steam Deck Basics\nUse Gaming Mode for the default experience.\n"
        source = _source()
        document = _document(content)
        manifest = _manifest(source, document)
        contents = {document.document_id: content}

        with tempfile.TemporaryDirectory() as root:
            database_path = os.path.join(root, "knowledge.sqlite3")
            build_sqlite_knowledge_search_index(
                database_path,
                manifest,
                contents,
            ).close()

            with self.assertRaisesRegex(KnowledgeValidationError, "already exists"):
                build_sqlite_knowledge_search_index(
                    database_path,
                    manifest,
                    contents,
                )

            replacement = build_sqlite_knowledge_search_index(
                database_path,
                manifest,
                contents,
                overwrite=True,
            )
            try:
                results = replacement.search("Gaming Mode")
            finally:
                replacement.close()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk.document_id, document.document_id)

    @unittest.skipUnless(_sqlite_fts5_available(), "sqlite3 FTS5 is not available")
    def test_sqlite_search_index_rejects_foreign_database_schema(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            database_path = os.path.join(root, "foreign.sqlite3")
            connection = sqlite3.connect(database_path)
            try:
                connection.execute("CREATE TABLE other_data (value TEXT)")
                connection.commit()
            finally:
                connection.close()

            with self.assertRaisesRegex(KnowledgeValidationError, "schema"):
                SQLiteKnowledgeSearchIndex(database_path)

    def test_search_index_validates_manifest_content_mapping(self) -> None:
        content = "# Steam Deck Basics\nUse Gaming Mode for the default experience.\n"
        source = _source()
        document = _document(content)
        manifest = _manifest(source, document)

        with self.assertRaises(KnowledgeValidationError):
            build_knowledge_search_index(manifest, {})

        with self.assertRaises(KnowledgeValidationError):
            build_knowledge_search_index(
                manifest,
                {
                    document.document_id: content,
                    "unexpected-document": "extra",
                },
            )

        with self.assertRaises(KnowledgeValidationError):
            build_knowledge_search_index(manifest, {document.document_id: "wrong content"})

        wrong_length_document = KnowledgeDocument(
            document_id=document.document_id,
            source_id=document.source_id,
            path=document.path,
            title=document.title,
            content_type=document.content_type,
            content_hash=document.content_hash,
            byte_length=document.byte_length + 1 if document.byte_length is not None else 1,
        )
        with self.assertRaises(KnowledgeValidationError):
            build_knowledge_search_index(
                _manifest(source, wrong_length_document),
                {document.document_id: content},
            )

    def test_build_knowledge_pack_manifest_is_deterministic(self) -> None:
        source = _source()
        markdown_content = "# Steam Deck Basics\nUse Gaming Mode.\n"
        text_content = "Plain note for launch troubleshooting.\n"
        result = build_knowledge_pack_manifest(
            pack_id="core-deck-pack",
            title="Core Deck Pack",
            version="0.1.0",
            created_at="2026-06-21T10:00:00Z",
            description="Small local Steam Deck reference pack.",
            source=source,
            document_contents_by_path={
                "notes/plain-note.txt": text_content,
                ".\\docs\\guides\\..\\steam-deck-basics.md": markdown_content,
            },
        )
        repeated = build_knowledge_pack_manifest(
            pack_id="core-deck-pack",
            title="Core Deck Pack",
            version="0.1.0",
            created_at="2026-06-21T10:00:00Z",
            description="Small local Steam Deck reference pack.",
            source=source,
            document_contents_by_path=(
                (".\\docs\\guides\\..\\steam-deck-basics.md", markdown_content),
                ("notes/plain-note.txt", text_content),
            ),
        )

        self.assertIsInstance(result, KnowledgePackManifestBuildResult)
        self.assertEqual(result.manifest.to_dict(), repeated.manifest.to_dict())
        self.assertEqual(dict(result.document_contents), dict(repeated.document_contents))
        self.assertEqual(
            [document.path for document in result.manifest.documents],
            ["docs/steam-deck-basics.md", "notes/plain-note.txt"],
        )
        self.assertEqual(
            [document.document_id for document in result.manifest.documents],
            [
                "steam-deck-docs:docs/steam-deck-basics.md",
                "steam-deck-docs:notes/plain-note.txt",
            ],
        )
        self.assertEqual(
            [document.content_type for document in result.manifest.documents],
            ["text/markdown", "text/plain"],
        )
        self.assertEqual(
            result.document_contents["steam-deck-docs:docs/steam-deck-basics.md"],
            markdown_content,
        )

    def test_build_knowledge_pack_manifest_rejects_duplicate_normalized_path(self) -> None:
        with self.assertRaisesRegex(KnowledgeValidationError, "duplicate document path"):
            build_knowledge_pack_manifest(
                pack_id="bad-pack",
                title="Bad Pack",
                version="0.1.0",
                created_at="2026-06-21T10:00:00Z",
                source=_source(),
                document_contents_by_path=(
                    ("docs/setup.md", "# Setup\n"),
                    ("./docs/guides/../setup.md", "# Other Setup\n"),
                ),
            )

    def test_build_knowledge_pack_manifest_rejects_unsupported_file(self) -> None:
        with self.assertRaisesRegex(KnowledgeValidationError, "unsupported_format"):
            build_knowledge_pack_manifest(
                pack_id="bad-pack",
                title="Bad Pack",
                version="0.1.0",
                created_at="2026-06-21T10:00:00Z",
                source=_source(),
                document_contents_by_path={"scripts/index.py": "print('skip')\n"},
            )

    def test_build_knowledge_pack_manifest_rejects_empty_path_and_invalid_content(
        self,
    ) -> None:
        with self.assertRaisesRegex(KnowledgeValidationError, "document path"):
            build_knowledge_pack_manifest(
                pack_id="bad-pack",
                title="Bad Pack",
                version="0.1.0",
                created_at="2026-06-21T10:00:00Z",
                source=_source(),
                document_contents_by_path={"": "# Empty Path\n"},
            )

        with self.assertRaisesRegex(KnowledgeValidationError, "must be a string"):
            build_knowledge_pack_manifest(
                pack_id="bad-pack",
                title="Bad Pack",
                version="0.1.0",
                created_at="2026-06-21T10:00:00Z",
                source=_source(),
                document_contents_by_path={"docs/setup.md": b"# Setup\n"},
            )

    def test_build_knowledge_pack_manifest_hash_and_byte_length_feed_search_index(
        self,
    ) -> None:
        content = "# Shader Café\nShader cache notes use UTF-8 text.\n"
        result = build_knowledge_pack_manifest(
            pack_id="core-deck-pack",
            title="Core Deck Pack",
            version="0.1.0",
            created_at="2026-06-21T10:00:00Z",
            source=_source(),
            document_contents_by_path={"docs/shader-cafe.md": content},
        )
        document = result.manifest.documents[0]

        self.assertEqual(document.content_hash, ContentHash.sha256_text(content))
        self.assertEqual(document.byte_length, len(content.encode("utf-8")))

        index = build_knowledge_search_index(result.manifest, result.document_contents)
        results = index.search("shader cache")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk.document_id, document.document_id)
        self.assertEqual(results[0].citation.document_path, "docs/shader-cafe.md")

    def test_empty_required_fields_raise_validation_errors(self) -> None:
        with self.assertRaises(KnowledgeValidationError):
            SourceLicense(name="")

        with self.assertRaises(KnowledgeValidationError):
            KnowledgeDocument(
                document_id="",
                source_id="steam-deck-docs",
                path="docs/file.md",
                title="File",
                content_type="text/markdown",
                content_hash=ContentHash.sha256_text("content"),
            )

    def test_manifest_rejects_incorrect_source_references(self) -> None:
        source = _source()
        document = KnowledgeDocument(
            document_id="orphan-doc",
            source_id="missing-source",
            path="docs/orphan.md",
            title="Orphan",
            content_type="text/markdown",
            content_hash=ContentHash.sha256_text("orphan"),
        )

        with self.assertRaises(KnowledgeValidationError):
            KnowledgePackManifest(
                pack_id="bad-pack",
                title="Bad Pack",
                version="0.1.0",
                created_at="2026-06-21T10:00:00Z",
                sources=(source,),
                documents=(document,),
            )

    def test_manifest_rejects_duplicate_documents_and_bad_schema(self) -> None:
        content = "# Duplicate\n"
        source = _source()
        document = _document(content)

        with self.assertRaises(KnowledgeValidationError):
            KnowledgePackManifest(
                pack_id="bad-pack",
                title="Bad Pack",
                version="0.1.0",
                created_at="2026-06-21T10:00:00Z",
                sources=(source,),
                documents=(document, document),
            )

        data = KnowledgePackManifest(
            pack_id="good-pack",
            title="Good Pack",
            version="0.1.0",
            created_at="2026-06-21T10:00:00Z",
            sources=(source,),
            documents=(document,),
        ).to_dict()
        data["schema_version"] = 2

        with self.assertRaises(KnowledgeValidationError):
            KnowledgePackManifest.from_dict(data)

    def test_filter_includes_supported_documents_after_path_normalization(self) -> None:
        markdown_result = filter_knowledge_source_document(
            ".\\docs\\guides\\..\\guides\\setup.md",
            byte_size=2048,
        )
        plain_result = filter_knowledge_source_document("./docs/../LICENSE")

        self.assertEqual(markdown_result.normalized_path, "docs/guides/setup.md")
        self.assertEqual(markdown_result.decision, KnowledgeSourceFilterDecision.INCLUDE)
        self.assertEqual(
            markdown_result.reason,
            KnowledgeSourceFilterReason.INCLUDED_SUPPORTED_TEXT_DOCUMENT,
        )
        self.assertEqual(markdown_result.content_type, "text/markdown")
        self.assertEqual(markdown_result.matched_pattern, ".md")
        self.assertTrue(markdown_result.is_included)

        self.assertEqual(plain_result.normalized_path, "LICENSE")
        self.assertEqual(plain_result.content_type, "text/plain")
        self.assertEqual(plain_result.matched_pattern, "license")
        self.assertTrue(should_include_knowledge_source_document("./docs/../LICENSE"))

    def test_filter_excludes_vendor_and_lockfile_paths(self) -> None:
        vendor_result = filter_knowledge_source_document("docs/vendor/guide.md")
        lockfile_result = filter_knowledge_source_document("frontend/pnpm-lock.yaml")

        self.assertEqual(vendor_result.decision, KnowledgeSourceFilterDecision.EXCLUDE)
        self.assertEqual(vendor_result.reason, KnowledgeSourceFilterReason.EXCLUDED_DIRECTORY)
        self.assertEqual(vendor_result.normalized_path, "docs/vendor/guide.md")

        self.assertEqual(lockfile_result.decision, KnowledgeSourceFilterDecision.EXCLUDE)
        self.assertEqual(
            lockfile_result.reason,
            KnowledgeSourceFilterReason.EXCLUDED_FILE_NAME,
        )
        self.assertEqual(lockfile_result.normalized_path, "frontend/pnpm-lock.yaml")

    def test_filter_excludes_hidden_paths(self) -> None:
        hidden_file = filter_knowledge_source_document(".github/copilot-instructions.md")
        hidden_nested = filter_knowledge_source_document("docs/.drafts/setup.md")

        self.assertEqual(hidden_file.decision, KnowledgeSourceFilterDecision.EXCLUDE)
        self.assertEqual(
            hidden_file.reason,
            KnowledgeSourceFilterReason.EXCLUDED_HIDDEN_PATH,
        )
        self.assertEqual(
            hidden_nested.reason,
            KnowledgeSourceFilterReason.EXCLUDED_HIDDEN_PATH,
        )

    def test_filter_excludes_binary_and_unsupported_formats(self) -> None:
        binary_result = filter_knowledge_source_document("docs/manual.pdf")
        unsupported_result = filter_knowledge_source_document("scripts/index.py")

        self.assertEqual(binary_result.reason, KnowledgeSourceFilterReason.EXCLUDED_BINARY_SUFFIX)
        self.assertFalse(binary_result.is_included)
        self.assertEqual(unsupported_result.reason, KnowledgeSourceFilterReason.UNSUPPORTED_FORMAT)
        self.assertFalse(should_include_knowledge_source_document("scripts/index.py"))

    def test_filter_respects_deck_friendly_size_limit(self) -> None:
        allowed = filter_knowledge_source_document(
            "docs/steam-deck.md",
            byte_size=DEFAULT_KNOWLEDGE_SOURCE_MAX_FILE_BYTES,
        )
        too_large = filter_knowledge_source_document(
            "docs/steam-deck.md",
            byte_size=DEFAULT_KNOWLEDGE_SOURCE_MAX_FILE_BYTES + 1,
        )
        smaller_policy = KnowledgeSourceFilterPolicy(max_file_bytes=32)
        custom_limit = filter_knowledge_source_document(
            "docs/readme.txt",
            byte_size=33,
            policy=smaller_policy,
        )

        self.assertEqual(allowed.decision, KnowledgeSourceFilterDecision.INCLUDE)
        self.assertEqual(too_large.reason, KnowledgeSourceFilterReason.FILE_TOO_LARGE)
        self.assertEqual(too_large.content_type, "text/markdown")
        self.assertEqual(too_large.max_file_bytes, DEFAULT_KNOWLEDGE_SOURCE_MAX_FILE_BYTES)
        self.assertEqual(custom_limit.reason, KnowledgeSourceFilterReason.FILE_TOO_LARGE)
        self.assertEqual(custom_limit.max_file_bytes, 32)

    def test_normalize_source_document_path_handles_edge_cases(self) -> None:
        self.assertEqual(
            normalize_source_document_path("./docs//notes/../setup.txt"),
            "docs/setup.txt",
        )
        self.assertEqual(
            normalize_source_document_path("guides\\nested\\\\install.rst"),
            "guides/nested/install.rst",
        )

        for value in ("../README.md", "/tmp/README.md", "C:\\repo\\README.md", "."):
            with self.subTest(value=value):
                with self.assertRaises(KnowledgeValidationError):
                    normalize_source_document_path(value)

    def test_build_knowledge_source_inventory_is_deterministic(self) -> None:
        result = build_knowledge_source_inventory(
            (
                ("notes/b-note.txt", 10),
                ("docs/vendor/guide.md", 20),
                ("docs/a-guide.md", 12),
                ("frontend/pnpm-lock.yaml", 18),
                ("docs/manual.pdf", 30),
                (".github/copilot-instructions.md", 14),
            )
        )
        repeated = build_knowledge_source_inventory(
            {
                "frontend/pnpm-lock.yaml": 18,
                "docs/manual.pdf": 30,
                "notes/b-note.txt": 10,
                "docs/vendor/guide.md": 20,
                ".github/copilot-instructions.md": 14,
                "docs/a-guide.md": 12,
            }
        )

        self.assertIsInstance(result, KnowledgeSourceInventory)
        self.assertEqual(
            [item.normalized_path for item in result.included_documents],
            ["docs/a-guide.md", "notes/b-note.txt"],
        )
        self.assertEqual(
            [(item.normalized_path, item.reason) for item in result.rejected_documents],
            [
                (".github/copilot-instructions.md", KnowledgeSourceFilterReason.EXCLUDED_HIDDEN_PATH),
                ("docs/manual.pdf", KnowledgeSourceFilterReason.EXCLUDED_BINARY_SUFFIX),
                ("docs/vendor/guide.md", KnowledgeSourceFilterReason.EXCLUDED_DIRECTORY),
                ("frontend/pnpm-lock.yaml", KnowledgeSourceFilterReason.EXCLUDED_FILE_NAME),
            ],
        )
        self.assertEqual(result.included_total_bytes, 22)
        self.assertEqual(
            [item.normalized_path for item in repeated.included_documents],
            [item.normalized_path for item in result.included_documents],
        )
        self.assertEqual(
            [(item.normalized_path, item.reason) for item in repeated.rejected_documents],
            [(item.normalized_path, item.reason) for item in result.rejected_documents],
        )

    def test_build_knowledge_source_inventory_enforces_count_and_total_byte_limits(
        self,
    ) -> None:
        inventory = build_knowledge_source_inventory(
            (
                ("docs/a.md", 10),
                ("docs/b.md", 8),
                ("docs/c.md", 5),
            ),
            limits=KnowledgeSourceInventoryLimits(
                max_document_count=2,
                max_total_bytes=15,
            ),
        )

        self.assertEqual(
            [item.normalized_path for item in inventory.included_documents],
            ["docs/a.md", "docs/c.md"],
        )
        self.assertEqual(inventory.included_total_bytes, 15)
        self.assertEqual(len(inventory.rejected_documents), 1)
        self.assertEqual(
            inventory.rejected_documents[0].normalized_path,
            "docs/b.md",
        )
        self.assertEqual(
            inventory.rejected_documents[0].reason,
            KnowledgeSourceFilterReason.MAX_TOTAL_BYTES_REACHED,
        )
        self.assertEqual(inventory.rejected_documents[0].max_total_bytes, 15)

        count_limited = build_knowledge_source_inventory(
            (
                ("docs/a.md", 10),
                ("docs/b.md", 8),
                ("docs/c.md", 5),
            ),
            limits=KnowledgeSourceInventoryLimits(max_document_count=1),
        )
        self.assertEqual(
            [item.normalized_path for item in count_limited.included_documents],
            ["docs/a.md"],
        )
        self.assertEqual(
            [item.reason for item in count_limited.rejected_documents],
            [
                KnowledgeSourceFilterReason.MAX_DOCUMENT_COUNT_REACHED,
                KnowledgeSourceFilterReason.MAX_DOCUMENT_COUNT_REACHED,
            ],
        )
        self.assertEqual(
            [item.max_document_count for item in count_limited.rejected_documents],
            [1, 1],
        )

    def test_collect_local_folder_inventory_skips_pruned_and_rejected_paths(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _write_text(os.path.join(root, "docs", "guide.md"), "# Guide\n")
            _write_text(os.path.join(root, "notes", "plain.txt"), "Plain note.\n")
            _write_text(os.path.join(root, ".draft.md"), "# Hidden\n")
            _write_text(os.path.join(root, "frontend", "pnpm-lock.yaml"), "lock: true\n")
            _write_text(os.path.join(root, "docs", "manual.pdf"), "pdf\n")
            _write_text(os.path.join(root, "docs", "vendor", "skip.md"), "# Skip\n")
            _write_text(os.path.join(root, ".hidden", "secret.md"), "# Secret\n")

            inventory = collect_local_folder_knowledge_source_inventory(root)

        self.assertIsInstance(inventory, KnowledgeSourceInventory)
        self.assertEqual(
            [item.normalized_path for item in inventory.included_documents],
            ["docs/guide.md", "notes/plain.txt"],
        )
        self.assertEqual(
            [(item.normalized_path, item.reason) for item in inventory.rejected_documents],
            [
                (".draft.md", KnowledgeSourceFilterReason.EXCLUDED_HIDDEN_PATH),
                (".hidden", KnowledgeSourceFilterReason.EXCLUDED_HIDDEN_PATH),
                ("docs/manual.pdf", KnowledgeSourceFilterReason.EXCLUDED_BINARY_SUFFIX),
                ("docs/vendor", KnowledgeSourceFilterReason.EXCLUDED_DIRECTORY),
                ("frontend/pnpm-lock.yaml", KnowledgeSourceFilterReason.EXCLUDED_FILE_NAME),
            ],
        )

    def test_build_local_folder_knowledge_pack_manifest_reads_only_filtered_text_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = _source(
                source_id="local-docs",
                source_type=SourceType.LOCAL_FOLDER,
                title="Local Docs",
                uri=root,
            )
            _write_text(os.path.join(root, "docs", "guide.md"), "# Guide\n")
            _write_text(os.path.join(root, "notes", "plain.txt"), "Plain note.\n")
            _write_bytes(os.path.join(root, "docs", "manual.pdf"), b"\xff\xfe")
            _write_bytes(os.path.join(root, ".draft.md"), b"\xff\xfe")
            _write_bytes(os.path.join(root, ".hidden", "secret.md"), b"\xff\xfe")
            _write_bytes(os.path.join(root, "docs", "vendor", "skip.md"), b"\xff\xfe")
            _write_text(os.path.join(root, "frontend", "pnpm-lock.yaml"), "lock: true\n")

            result = build_local_folder_knowledge_pack_manifest(
                root_path=root,
                pack_id="local-pack",
                title="Local Pack",
                version="0.1.0",
                created_at="2026-06-21T10:00:00Z",
                source=source,
            )
            repeated = build_local_folder_knowledge_pack_manifest(
                root_path=root,
                pack_id="local-pack",
                title="Local Pack",
                version="0.1.0",
                created_at="2026-06-21T10:00:00Z",
                source=source,
            )

        self.assertEqual(result.manifest.to_dict(), repeated.manifest.to_dict())
        self.assertEqual(dict(result.document_contents), dict(repeated.document_contents))
        self.assertEqual(
            [document.path for document in result.manifest.documents],
            ["docs/guide.md", "notes/plain.txt"],
        )
        self.assertEqual(
            dict(result.document_contents),
            {
                "local-docs:docs/guide.md": "# Guide\n",
                "local-docs:notes/plain.txt": "Plain note.\n",
            },
        )

    def test_build_local_folder_knowledge_pack_manifest_applies_inventory_limits(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = _source(
                source_id="limited-docs",
                source_type=SourceType.LOCAL_FOLDER,
                uri=root,
            )
            _write_text(os.path.join(root, "docs", "a.md"), "1234567890")
            _write_text(os.path.join(root, "docs", "b.md"), "12345678")
            _write_text(os.path.join(root, "docs", "c.md"), "12345")

            total_limited = build_local_folder_knowledge_pack_manifest(
                root_path=root,
                pack_id="limited-pack",
                title="Limited Pack",
                version="0.1.0",
                created_at="2026-06-21T10:00:00Z",
                source=source,
                limits=KnowledgeSourceInventoryLimits(max_total_bytes=15),
            )
            count_limited = build_local_folder_knowledge_pack_manifest(
                root_path=root,
                pack_id="limited-pack",
                title="Limited Pack",
                version="0.1.0",
                created_at="2026-06-21T10:00:00Z",
                source=source,
                limits=KnowledgeSourceInventoryLimits(max_document_count=1),
            )

        self.assertEqual(
            [document.path for document in total_limited.manifest.documents],
            ["docs/a.md", "docs/c.md"],
        )
        self.assertEqual(
            [document.path for document in count_limited.manifest.documents],
            ["docs/a.md"],
        )

    @unittest.skipIf(os.name == "nt", "backslash filenames are not portable on Windows")
    def test_build_local_folder_knowledge_pack_manifest_rejects_duplicate_normalized_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            _write_text(os.path.join(root, "docs", "setup.md"), "# Setup\n")
            _write_text(os.path.join(root, "docs\\setup.md"), "# Other Setup\n")

            with self.assertRaisesRegex(
                KnowledgeValidationError,
                "duplicate source file path: docs/setup.md",
            ):
                build_local_folder_knowledge_pack_manifest(
                    root_path=root,
                    pack_id="duplicate-pack",
                    title="Duplicate Pack",
                    version="0.1.0",
                    created_at="2026-06-21T10:00:00Z",
                    source=_source(
                        source_id="duplicate-docs",
                        source_type=SourceType.LOCAL_FOLDER,
                        uri=root,
                    ),
                )

    def test_build_local_folder_knowledge_pack_manifest_rejects_invalid_utf8(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as root:
            _write_bytes(os.path.join(root, "docs", "bad.md"), b"\xff\xfe")

            with self.assertRaisesRegex(
                KnowledgeValidationError,
                "not valid UTF-8: docs/bad.md",
            ):
                build_local_folder_knowledge_pack_manifest(
                    root_path=root,
                    pack_id="bad-utf8-pack",
                    title="Bad UTF-8 Pack",
                    version="0.1.0",
                    created_at="2026-06-21T10:00:00Z",
                    source=_source(
                        source_id="bad-utf8-docs",
                        source_type=SourceType.LOCAL_FOLDER,
                        uri=root,
                    ),
                )

    def test_source_record_enforces_enablement_reason_and_listing_shape(self) -> None:
        source = _source(
            source_id="decky-docs",
            title="Decky Docs",
            uri="https://docs.decky.xyz/",
        )
        record = KnowledgeSourceRecord(
            source=source,
            pack_id="core-deck-pack",
            document_count=2,
            indexed_byte_length=128,
            last_indexed_at="2026-06-21T10:00:00Z",
        )

        self.assertEqual(
            record.to_source_list_item(),
            {
                "source_id": "decky-docs",
                "name": "Decky Docs",
                "kind": "docs_url",
                "enabled": True,
                "license": "Creative Commons Attribution 4.0",
                "url": "https://docs.decky.xyz/",
                "revision": "2026-06-21",
                "pack_id": "core-deck-pack",
                "document_count": 2,
                "indexed_byte_length": 128,
                "last_indexed_at": "2026-06-21T10:00:00Z",
            },
        )

        disabled = record.disable("License review required")
        self.assertFalse(disabled.enabled)
        self.assertEqual(disabled.disabled_reason, "License review required")
        self.assertTrue(disabled.enable().enabled)
        self.assertIsNone(disabled.enable().disabled_reason)

        with self.assertRaisesRegex(
            KnowledgeValidationError,
            "disabled source record must include disabled_reason",
        ):
            KnowledgeSourceRecord(source=source, enabled=False)

        with self.assertRaisesRegex(
            KnowledgeValidationError,
            "enabled source record must not include disabled_reason",
        ):
            KnowledgeSourceRecord(
                source=source,
                enabled=True,
                disabled_reason="Stale",
            )

        with self.assertRaisesRegex(
            KnowledgeValidationError,
            "source record enabled must be a boolean",
        ):
            KnowledgeSourceRecord(source=source, enabled="yes")  # type: ignore[arg-type]

    def test_source_registry_tracks_enable_disable_remove_and_round_trip(self) -> None:
        decky_source = _source(
            source_id="decky-docs",
            title="Decky Docs",
            uri="https://docs.decky.xyz/",
        )
        proton_source = _source(
            source_id="proton-docs",
            title="Proton Docs",
            uri="https://github.com/ValveSoftware/Proton",
        )
        decky_guide = _document_with(
            "# Decky\nDecky docs.",
            document_id="decky-guide",
            source=decky_source,
            path="docs/decky-guide.md",
            title="Decky Guide",
        )
        decky_setup = _document_with(
            "# Setup\nDecky setup.",
            document_id="decky-setup",
            source=decky_source,
            path="docs/decky-setup.md",
            title="Decky Setup",
        )
        proton_logs = _document_with(
            "# Proton Logs\nLog notes.",
            document_id="proton-logs",
            source=proton_source,
            path="docs/proton-logs.md",
            title="Proton Logs",
        )
        manifest = KnowledgePackManifest(
            pack_id="core-deck-pack",
            title="Core Deck Pack",
            version="0.1.0",
            created_at="2026-06-21T10:00:00Z",
            sources=(proton_source, decky_source),
            documents=(decky_guide, proton_logs, decky_setup),
        )
        registry = KnowledgeSourceRegistry.from_manifest(manifest)

        self.assertEqual(
            [record.source_id for record in registry.list_source_records()],
            ["decky-docs", "proton-docs"],
        )
        self.assertEqual(registry.get_source_record("decky-docs").document_count, 2)
        self.assertEqual(registry.get_source_record("proton-docs").document_count, 1)
        self.assertEqual(
            registry.get_source_record("decky-docs").indexed_byte_length,
            decky_guide.byte_length + decky_setup.byte_length,
        )

        disabled = registry.disable_source("proton-docs", "User disabled source")
        self.assertFalse(disabled.enabled)
        self.assertEqual(
            [record.source_id for record in registry.list_source_records(include_disabled=False)],
            ["decky-docs"],
        )
        self.assertEqual(
            registry.list_source_items(include_disabled=False)[0]["source_id"],
            "decky-docs",
        )

        restored = KnowledgeSourceRegistry.from_dict(json.loads(json.dumps(registry.to_dict())))
        self.assertEqual(restored.to_dict(), registry.to_dict())

        enabled = registry.enable_source("proton-docs")
        self.assertTrue(enabled.enabled)
        self.assertIsNone(enabled.disabled_reason)

        removed = registry.remove_source("decky-docs")
        self.assertEqual(removed.source_id, "decky-docs")
        with self.assertRaises(KnowledgeSourceNotFound):
            registry.get_source_record("decky-docs")

    def test_source_registry_rejects_duplicate_adds_and_supports_upsert(self) -> None:
        registry = KnowledgeSourceRegistry()
        record = KnowledgeSourceRecord(source=_source(source_id="decky-docs"))
        registry.add_source_record(record)

        with self.assertRaisesRegex(
            KnowledgeSourceRegistryError,
            "knowledge source already exists: decky-docs",
        ):
            registry.add_source_record(record)

        replacement = KnowledgeSourceRecord(
            source=_source(source_id="decky-docs", title="Updated Decky Docs"),
            pack_id="updated-pack",
        )
        registry.upsert_source_record(replacement)

        self.assertEqual(registry.get_source_record("decky-docs").source.title, "Updated Decky Docs")
        self.assertEqual(registry.get_source_record("decky-docs").pack_id, "updated-pack")


def _source(
    *,
    source_id: str = "steam-deck-docs",
    source_type: SourceType = SourceType.DOCS_URL,
    title: str = "Steam Deck Docs",
    uri: str = "https://help.steampowered.com/en/faqs/view/6121-ECCD-D643-BAA8",
) -> SourceMetadata:
    return SourceMetadata(
        source_id=source_id,
        source_type=source_type,
        title=title,
        uri=uri,
        license=SourceLicense(
            name="Creative Commons Attribution 4.0",
            spdx_id="CC-BY-4.0",
            url="https://creativecommons.org/licenses/by/4.0/",
        ),
        revision=SourceRevision(
            value="2026-06-21",
            retrieved_at="2026-06-21T10:00:00Z",
        ),
        content_hash=ContentHash.sha256_text(f"{source_id}-source"),
    )


def _document(content: str) -> KnowledgeDocument:
    return _document_with(
        content,
        document_id="steam-deck-basics",
        source=_source(),
        path="docs/steam-deck-basics.md",
        title="Steam Deck Basics",
    )


def _document_with(
    content: str,
    *,
    document_id: str,
    source: SourceMetadata,
    path: str,
    title: str,
    content_type: str = "text/markdown",
) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id,
        source_id=source.source_id,
        path=path,
        title=title,
        content_type=content_type,
        content_hash=ContentHash.sha256_text(content),
        byte_length=len(content.encode("utf-8")),
    )


def _manifest(
    source: SourceMetadata,
    *documents: KnowledgeDocument,
) -> KnowledgePackManifest:
    return KnowledgePackManifest(
        pack_id="core-deck-pack",
        title="Core Deck Pack",
        version="0.1.0",
        created_at="2026-06-21T10:00:00Z",
        sources=(source,),
        documents=documents,
    )


def _write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _write_bytes(path: str, content: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)


if __name__ == "__main__":
    unittest.main()
