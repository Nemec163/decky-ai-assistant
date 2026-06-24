from __future__ import annotations

import json
import unittest

from deck_assistant_core import (
    ContentHash,
    DiagnosticStatus,
    KnowledgeDocument,
    KnowledgePackManifest,
    MAX_PROTON_EXCERPT_CHARACTERS,
    ProtonLogReference,
    ProtonLogReport,
    RiskLevel,
    SourceLicense,
    SourceMetadata,
    SourceRevision,
    SourceType,
    StagedActionStore,
    StorageReport,
    StorageReportItem,
    StorageReportSection,
    StorageSectionName,
    build_knowledge_search_index,
)
from deck_assistant_mcp import (
    ContractCatalogDriftError,
    READ_ONLY_SHELL_WARNING,
    TOOL_CONTRACTS,
    create_in_process_tool_dispatcher,
    export_tool_approval_summary,
)
from deck_assistant_mcp.dispatcher import InProcessToolDispatcher


EXPECTED_TOOL_ORDER = (
    "search_knowledge",
    "list_sources",
    "inspect_current_game",
    "read_proton_logs",
    "get_storage_report",
    "propose_fix",
    "stage_action",
    "run_approved_action",
)


class InProcessToolDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dispatcher = create_in_process_tool_dispatcher(TOOL_CONTRACTS)

    def test_catalog_listing_is_deterministic_and_detached(self) -> None:
        names = tuple(contract.name for contract in self.dispatcher.list_tool_contracts())
        exported = self.dispatcher.export_catalog()
        exported_again = self.dispatcher.export_catalog()

        self.assertEqual(names, EXPECTED_TOOL_ORDER)
        self.assertEqual(
            tuple(tool["name"] for tool in exported["tools"]),
            EXPECTED_TOOL_ORDER,
        )
        self.assertEqual(exported, exported_again)

        exported["tools"][0]["input_schema"]["properties"]["query"]["minLength"] = 99

        self.assertEqual(
            self.dispatcher.export_catalog()["tools"][0]["input_schema"]["properties"]["query"][
                "minLength"
            ],
            1,
        )

    def test_unknown_tool_returns_stable_error(self) -> None:
        response = self.dispatcher.dispatch_tool_call("missing_tool", {})

        self.assertFalse(response["ok"])
        self.assertEqual(response["tool"], "missing_tool")
        self.assertEqual(response["error"]["code"], "unknown_tool")
        self.assertEqual(
            response["error"]["details"],
            {"requested_tool": "missing_tool"},
        )

    def test_input_validation_rejects_non_objects_missing_required_fields_and_unknown_keys(self) -> None:
        test_cases = (
            (
                [],
                "$",
                "expected object",
            ),
            (
                {},
                "$",
                "missing required property query",
            ),
            (
                {"query": "shader cache", "unexpected": True},
                "$.unexpected",
                "unexpected property",
            ),
            (
                {"query": "shader cache", "source_ids": [""]},
                "$.source_ids[0]",
                "expected minLength 1",
            ),
        )

        for arguments, path, reason in test_cases:
            with self.subTest(arguments=arguments):
                response = self.dispatcher.dispatch_tool_call("search_knowledge", arguments)

                self.assertFalse(response["ok"])
                self.assertEqual(response["error"]["code"], "invalid_input")
                self.assertEqual(response["error"]["details"]["path"], path)
                self.assertEqual(response["error"]["details"]["reason"], reason)

    def test_read_only_approval_metadata_export_is_stable(self) -> None:
        summary = self.dispatcher.export_approval_summary()
        metadata = self.dispatcher.get_tool_approval_metadata("stage_action")

        self.assertEqual(summary, export_tool_approval_summary())
        self.assertEqual(summary["groups"]["variable_risk_tools"], ["run_approved_action"])
        self.assertEqual(
            metadata,
            {
                "name": "stage_action",
                "risk": "low_write",
                "requires_approval": True,
                "approval_gate": "decky_approval",
                "read_only": False,
                "variable_risk": False,
            },
        )

        summary["tools"][0]["approval_gate"] = "mutated"

        self.assertEqual(
            self.dispatcher.export_approval_summary(),
            export_tool_approval_summary(),
        )

    def test_read_only_calls_return_deterministic_placeholder_results(self) -> None:
        search_response = self.dispatcher.dispatch_tool_call(
            "search_knowledge",
            {"query": "proton logs"},
        )
        inspect_response = self.dispatcher.dispatch_tool_call(
            "inspect_current_game",
            {"include_processes": False},
        )
        proposal_response = self.dispatcher.dispatch_tool_call(
            "propose_fix",
            {"diagnosis": "Shader cache is too large."},
        )
        proton_response = self.dispatcher.dispatch_tool_call("read_proton_logs", {})
        storage_response = self.dispatcher.dispatch_tool_call("get_storage_report", {})

        self.assertTrue(search_response["ok"])
        self.assertEqual(search_response["result"], {"results": []})

        source_response = self.dispatcher.dispatch_tool_call("list_sources", {})
        self.assertTrue(source_response["ok"])
        self.assertEqual(source_response["result"], {"sources": []})

        self.assertTrue(inspect_response["ok"])
        self.assertEqual(inspect_response["result"]["game"], None)
        self.assertEqual(
            inspect_response["result"]["warnings"],
            [READ_ONLY_SHELL_WARNING],
        )

        self.assertTrue(proposal_response["ok"])
        self.assertEqual(
            proposal_response["result"]["proposal"]["risk"],
            RiskLevel.READ_ONLY.value,
        )
        self.assertFalse(proposal_response["result"]["proposal"]["requires_approval"])

        self.assertTrue(proton_response["ok"])
        self.assertEqual(proton_response["result"]["status"], DiagnosticStatus.UNAVAILABLE.value)
        self.assertEqual(proton_response["result"]["warnings"], [READ_ONLY_SHELL_WARNING])
        self.assertEqual(proton_response["result"]["logs"], [])

        self.assertTrue(storage_response["ok"])
        self.assertEqual(storage_response["result"]["status"], DiagnosticStatus.UNAVAILABLE.value)
        self.assertEqual(storage_response["result"]["warnings"], [READ_ONLY_SHELL_WARNING])
        self.assertEqual(storage_response["result"]["sections"], [])

    def test_knowledge_index_powers_search_and_source_listing(self) -> None:
        content = "\n".join(
            (
                "# Shader Cache",
                "Shader cache can improve repeat game launches.",
                "Clear it only while troubleshooting a specific problem.",
            )
        )
        source = SourceMetadata(
            source_id="decky-docs",
            source_type=SourceType.DOCS_URL,
            title="Decky Docs",
            uri="https://docs.decky.xyz/",
            license=SourceLicense(name="MIT", spdx_id="MIT"),
            revision=SourceRevision(value="abc123"),
            content_hash=ContentHash.sha256_text("decky docs source"),
        )
        document = KnowledgeDocument(
            document_id="shader-cache",
            source_id=source.source_id,
            path="docs/shader-cache.md",
            title="Shader Cache",
            content_type="text/markdown",
            content_hash=ContentHash.sha256_text(content),
            byte_length=len(content.encode("utf-8")),
        )
        manifest = KnowledgePackManifest(
            pack_id="core-deck-pack",
            title="Core Deck Pack",
            version="0.1.0",
            created_at="2026-06-21T10:00:00Z",
            sources=(source,),
            documents=(document,),
        )
        dispatcher = create_in_process_tool_dispatcher(
            TOOL_CONTRACTS,
            knowledge_search_index=build_knowledge_search_index(
                manifest,
                {document.document_id: content},
            ),
        )

        search_response = dispatcher.dispatch_tool_call(
            "search_knowledge",
            {
                "query": "shader cache",
                "limit": 1,
                "source_ids": ["decky-docs"],
            },
        )
        source_response = dispatcher.dispatch_tool_call(
            "list_sources",
            {"include_disabled": False},
        )

        self.assertTrue(search_response["ok"])
        self.assertEqual(len(search_response["result"]["results"]), 1)
        result = search_response["result"]["results"][0]
        self.assertEqual(result["chunk_id"], "shader-cache#chunk-0001")
        self.assertIn("Shader cache", result["text"])
        self.assertGreater(result["score"], 0)
        self.assertEqual(
            result["citation"],
            {
                "source_id": "decky-docs",
                "source_type": "docs_url",
                "title": "Decky Docs",
                "url": "https://docs.decky.xyz/",
                "license": "MIT",
                "revision": "abc123",
                "path": "docs/shader-cache.md",
                "document_id": "shader-cache",
                "document_title": "Shader Cache",
                "chunk_id": "shader-cache#chunk-0001",
                "headings": ["Shader Cache"],
                "start_line": 1,
                "end_line": 3,
            },
        )

        self.assertTrue(source_response["ok"])
        self.assertEqual(
            source_response["result"],
            {
                "sources": [
                    {
                        "source_id": "decky-docs",
                        "name": "Decky Docs",
                        "kind": "docs_url",
                        "enabled": True,
                        "license": "MIT",
                        "url": "https://docs.decky.xyz/",
                        "revision": "abc123",
                    }
                ]
            },
        )

    def test_knowledge_source_handler_can_filter_disabled_sources(self) -> None:
        dispatcher = create_in_process_tool_dispatcher(
            TOOL_CONTRACTS,
            list_sources_handler=lambda _: {
                "sources": [
                    {
                        "source_id": "enabled-source",
                        "name": "Enabled Source",
                        "kind": "docs_url",
                        "enabled": True,
                        "license": "MIT",
                        "revision": "abc123",
                        "url": "https://docs.example.test/enabled",
                    },
                    {
                        "source_id": "disabled-source",
                        "name": "Disabled Source",
                        "kind": "docs_url",
                        "enabled": False,
                        "license": "MIT",
                        "revision": "def456",
                        "url": "https://docs.example.test/disabled",
                    },
                ]
            },
        )

        response = dispatcher.dispatch_tool_call(
            "list_sources",
            {"include_disabled": False},
        )

        self.assertTrue(response["ok"])
        self.assertEqual(
            [source["source_id"] for source in response["result"]["sources"]],
            ["enabled-source"],
        )

    def test_knowledge_handlers_validate_schema_and_cross_field_invariants(self) -> None:
        valid_result = {
            "chunk_id": "chunk-1",
            "text": "Shader cache troubleshooting notes.",
            "score": 1.0,
            "citation": {
                "source_id": "decky-docs",
                "source_type": SourceType.DOCS_URL.value,
                "title": "Decky Docs",
                "url": "https://docs.decky.xyz/",
                "license": "MIT",
                "revision": "abc123",
                "path": "docs/shader-cache.md",
                "document_id": "shader-cache",
                "document_title": "Shader Cache",
                "chunk_id": "chunk-1",
                "headings": ["Shader Cache"],
                "start_line": 2,
                "end_line": 3,
            },
        }
        test_cases = (
            (
                "search_knowledge",
                {"query": "shader cache"},
                lambda _: {"results": [{**valid_result, "text": ""}]},
                "$.results[0].text",
                "expected minLength 1",
            ),
            (
                "search_knowledge",
                {"query": "shader cache"},
                lambda _: {"results": [{**valid_result, "score": -1.0}]},
                "$.results[0].score",
                "expected minimum 0",
            ),
            (
                "search_knowledge",
                {"query": "shader cache"},
                lambda _: {"results": [{**valid_result, "score": float("nan")}]},
                "$.results[0].score",
                "expected finite number",
            ),
            (
                "search_knowledge",
                {"query": "shader cache"},
                lambda _: {"results": [valid_result] * 21},
                "$.results",
                "expected at most 20 items",
            ),
            (
                "search_knowledge",
                {"query": "shader cache"},
                lambda _: {
                    "results": [
                        {
                            **valid_result,
                            "citation": {
                                **valid_result["citation"],
                                "chunk_id": "other-chunk",
                            },
                        }
                    ]
                },
                "$.results[0].citation.chunk_id",
                "expected to match result chunk_id 'chunk-1'",
            ),
            (
                "search_knowledge",
                {"query": "shader cache"},
                lambda _: {
                    "results": [
                        {
                            **valid_result,
                            "citation": {
                                **valid_result["citation"],
                                "start_line": 9,
                                "end_line": 3,
                            },
                        }
                    ]
                },
                "$.results[0].citation.end_line",
                "expected end_line >= start_line",
            ),
            (
                "list_sources",
                {},
                lambda _: {
                    "sources": [
                        {
                            "source_id": "bad-source",
                            "name": "Bad Source",
                            "kind": "unknown",
                            "enabled": True,
                            "license": "MIT",
                            "revision": "abc123",
                            "url": "https://docs.example.test/bad",
                        }
                    ]
                },
                "$.sources[0].kind",
                "value is not in enum",
            ),
        )

        for tool_name, arguments, handler, path, reason in test_cases:
            with self.subTest(tool=tool_name, path=path):
                dispatcher = create_in_process_tool_dispatcher(
                    TOOL_CONTRACTS,
                    search_knowledge_handler=(
                        handler if tool_name == "search_knowledge" else None
                    ),
                    list_sources_handler=(handler if tool_name == "list_sources" else None),
                )

                response = dispatcher.dispatch_tool_call(tool_name, arguments)

                self.assertFalse(response["ok"])
                self.assertEqual(response["error"]["code"], "invalid_output")
                self.assertEqual(response["error"]["details"]["path"], path)
                self.assertEqual(response["error"]["details"]["reason"], reason)

    def test_storage_report_handler_accepts_core_report_and_validates_schema(self) -> None:
        seen_arguments = []
        report = StorageReport(
            sections=(
                StorageReportSection(
                    name=StorageSectionName.SHADERCACHE,
                    path="/home/deck/.local/share/Steam/steamapps/shadercache",
                    bytes=128,
                    items=(
                        StorageReportItem(
                            path="/home/deck/.local/share/Steam/steamapps/shadercache/123",
                            bytes=128,
                            label="123",
                        ),
                    ),
                ),
            )
        )

        def handler(arguments):
            seen_arguments.append(dict(arguments))
            return report

        dispatcher = create_in_process_tool_dispatcher(
            TOOL_CONTRACTS,
            get_storage_report_handler=handler,
        )

        response = dispatcher.dispatch_tool_call(
            "get_storage_report",
            {"sections": [StorageSectionName.SHADERCACHE.value]},
        )

        self.assertTrue(response["ok"])
        self.assertEqual(
            seen_arguments,
            [{"sections": [StorageSectionName.SHADERCACHE.value]}],
        )
        self.assertEqual(response["result"], report.to_dict())

        response["result"]["sections"][0]["bytes"] = 999

        self.assertEqual(
            dispatcher.dispatch_tool_call("get_storage_report", {})["result"]["sections"][0][
                "bytes"
            ],
            128,
        )

    def test_storage_reader_dependencies_are_called_only_when_injected(self) -> None:
        calls = []

        def planner(**kwargs):
            calls.append(("planner", kwargs))
            return ("planned-storage-path",)

        def reader(plan):
            calls.append(("reader", tuple(plan)))
            return StorageReport(
                sections=(
                    StorageReportSection(
                        name=StorageSectionName.LOGS,
                        path="/home/deck/.local/share/Steam/logs",
                        bytes=0,
                    ),
                )
            )

        dispatcher = create_in_process_tool_dispatcher(
            TOOL_CONTRACTS,
            storage_path_planner=planner,
            storage_report_reader=reader,
        )

        response = dispatcher.dispatch_tool_call(
            "get_storage_report",
            {"sections": [StorageSectionName.LOGS.value]},
        )

        self.assertTrue(response["ok"])
        self.assertEqual(
            calls,
            [
                ("planner", {"sections": [StorageSectionName.LOGS.value]}),
                ("reader", ("planned-storage-path",)),
            ],
        )
        self.assertEqual(
            response["result"]["sections"][0]["path"],
            "/home/deck/.local/share/Steam/logs",
        )

    def test_proton_log_handler_accepts_core_report_and_filters_requested_app_id(self) -> None:
        seen_arguments = []
        report = ProtonLogReport(
            logs=(
                ProtonLogReference(
                    path="/home/deck/steam-123.log",
                    app_id=123,
                    modified_at="2026-06-21T00:00:00+00:00",
                ),
                ProtonLogReference(
                    path="/home/deck/steam-456.log",
                    app_id=456,
                    modified_at="2026-06-21T00:00:01+00:00",
                ),
            )
        )

        def handler(arguments):
            seen_arguments.append(dict(arguments))
            return report

        dispatcher = create_in_process_tool_dispatcher(
            TOOL_CONTRACTS,
            read_proton_logs_handler=handler,
        )

        response = dispatcher.dispatch_tool_call("read_proton_logs", {"app_id": 123})

        self.assertTrue(response["ok"])
        self.assertEqual(seen_arguments, [{"app_id": 123}])
        self.assertEqual(len(response["result"]["logs"]), 1)
        self.assertEqual(response["result"]["logs"][0]["app_id"], 123)
        self.assertEqual(response["result"]["status"], DiagnosticStatus.OK.value)

    def test_proton_reader_dependency_receives_bounded_excerpt_limit(self) -> None:
        seen_kwargs = []

        def reader(**kwargs):
            seen_kwargs.append(dict(kwargs))
            return ProtonLogReport(
                logs=(),
                status=DiagnosticStatus.UNAVAILABLE,
                warnings=("No Proton logs were found.",),
            )

        dispatcher = create_in_process_tool_dispatcher(
            TOOL_CONTRACTS,
            proton_log_reader=reader,
        )

        response = dispatcher.dispatch_tool_call(
            "read_proton_logs",
            {"max_excerpt_characters": 262144},
        )

        self.assertTrue(response["ok"])
        # The contract input caps excerpt characters; the dispatcher clamps the
        # requested value down to the core reader's own excerpt limit.
        self.assertEqual(
            seen_kwargs,
            [{"max_excerpt_characters": MAX_PROTON_EXCERPT_CHARACTERS}],
        )
        self.assertEqual(response["result"]["status"], DiagnosticStatus.UNAVAILABLE.value)

    def test_propose_fix_handler_accepts_inner_proposal_and_enforces_approval_invariants(self) -> None:
        seen_arguments = []

        def handler(arguments):
            seen_arguments.append(dict(arguments))
            return {
                "title": "Stage shader cache cleanup for review",
                "risk": RiskLevel.LOW_WRITE.value,
                "requires_approval": True,
                "approval_gate": {
                    "type": "approval_required",
                    "summary": "Decky approval is required before local execution.",
                    "requires_plan": True,
                    "requires_exact_commands_or_diffs": False,
                    "requires_backup_or_note": False,
                    "requires_separate_confirmation": False,
                    "may_execute_after_user_request": False,
                },
                "steps": ["Review cleanup candidates in Decky."],
                "commands": [],
                "file_edits": [],
                "backups": [],
                "rollback": [],
            }

        dispatcher = create_in_process_tool_dispatcher(
            TOOL_CONTRACTS,
            propose_fix_handler=handler,
        )

        response = dispatcher.dispatch_tool_call(
            "propose_fix",
            {"diagnosis": "Shader cache is large.", "requested_outcome": "free space"},
        )

        self.assertTrue(response["ok"])
        self.assertEqual(
            seen_arguments,
            [{"diagnosis": "Shader cache is large.", "requested_outcome": "free space"}],
        )
        self.assertEqual(
            response["result"]["proposal"]["risk"],
            RiskLevel.LOW_WRITE.value,
        )
        self.assertTrue(response["result"]["proposal"]["requires_approval"])

    def test_stage_action_records_pending_plan_without_releasing_approval_token(self) -> None:
        token_factory_calls = []
        store = StagedActionStore(
            token_factory=lambda: token_factory_calls.append("called") or "approval-token",
            timestamp_factory=lambda: "2026-06-21T13:00:00+00:00",
        )
        dispatcher = create_in_process_tool_dispatcher(
            TOOL_CONTRACTS,
            staged_action_store=store,
        )

        response = dispatcher.dispatch_tool_call(
            "stage_action",
            {
                "action": {
                    "title": "Create plugin config marker",
                    "risk": RiskLevel.LOW_WRITE.value,
                    "commands": [
                        {
                            "argv": ["touch", "/tmp/decky-ai-assistant-marker"],
                        }
                    ],
                }
            },
        )

        self.assertTrue(response["ok"])
        result = response["result"]
        self.assertEqual(result["risk"], RiskLevel.LOW_WRITE.value)
        self.assertTrue(result["requires_approval"])
        self.assertEqual(result["staged_at"], "2026-06-21T13:00:00+00:00")
        self.assertIsNone(result["approved_at"])
        self.assertEqual(result["staged_action_id"], result["display_plan"]["action_id"])
        self.assertEqual(result["display_plan"]["summary"]["command_count"], 1)
        self.assertEqual(
            result["display_plan"]["commands"][0]["argv"],
            ["touch", "/tmp/decky-ai-assistant-marker"],
        )
        self.assertNotIn("approval_token", json.dumps(result))
        self.assertEqual(token_factory_calls, [])

        staged = store.get_staged_action(
            result["staged_action_id"],
            expected_risk=RiskLevel.LOW_WRITE,
        )
        self.assertEqual(staged.title, "Create plugin config marker")

    def test_stage_action_rejects_approval_unready_action(self) -> None:
        store = StagedActionStore(
            timestamp_factory=lambda: "2026-06-21T13:15:00+00:00",
        )
        dispatcher = create_in_process_tool_dispatcher(
            TOOL_CONTRACTS,
            staged_action_store=store,
        )

        response = dispatcher.dispatch_tool_call(
            "stage_action",
            {
                "action": {
                    "title": "Edit Steam config",
                    "risk": RiskLevel.HIGH_WRITE.value,
                    "file_edits": [
                        {
                            "path": "/home/deck/.steam/steam/config/config.vdf",
                            "operation": "modify",
                        }
                    ],
                }
            },
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_input")
        self.assertEqual(response["error"]["details"]["path"], "$.action")
        self.assertIn(
            "needs an exact diff",
            response["error"]["details"]["reason"],
        )

    def test_invalid_injected_outputs_return_stable_errors(self) -> None:
        test_cases = (
            (
                "get_storage_report",
                {"sections": []},
                lambda _: {
                    "status": "ok",
                    "warnings": [],
                    "limits": [],
                    "sections": [
                        {
                            "name": StorageSectionName.SHADERCACHE.value,
                            "path": "relative/path",
                            "bytes": 0,
                            "status": "ok",
                            "warnings": [],
                            "limits": [],
                            "items": [],
                        }
                    ],
                },
                "$",
                "storage report section path must be an absolute path",
            ),
            (
                "propose_fix",
                {"diagnosis": "Needs a plan."},
                lambda _: {
                    "proposal": {
                        "title": "Unsafe mismatch",
                        "risk": RiskLevel.LOW_WRITE.value,
                        "requires_approval": False,
                        "approval_gate": {
                            "type": "approval_required",
                            "summary": "Decky approval is required before local execution.",
                            "requires_plan": True,
                            "requires_exact_commands_or_diffs": False,
                            "requires_backup_or_note": False,
                            "requires_separate_confirmation": False,
                            "may_execute_after_user_request": False,
                        },
                        "steps": [],
                        "commands": [],
                        "file_edits": [],
                        "backups": [],
                        "rollback": [],
                    }
                },
                "$.proposal.requires_approval",
                f"expected True for risk {RiskLevel.LOW_WRITE.value}",
            ),
        )

        for tool_name, arguments, handler, path, reason in test_cases:
            with self.subTest(tool=tool_name):
                dispatcher = create_in_process_tool_dispatcher(
                    TOOL_CONTRACTS,
                    get_storage_report_handler=(
                        handler if tool_name == "get_storage_report" else None
                    ),
                    propose_fix_handler=(handler if tool_name == "propose_fix" else None),
                )

                response = dispatcher.dispatch_tool_call(tool_name, arguments)

                self.assertFalse(response["ok"])
                self.assertEqual(response["error"]["code"], "invalid_output")
                self.assertEqual(response["error"]["details"]["path"], path)
                self.assertEqual(response["error"]["details"]["reason"], reason)

    def test_conflicting_dependency_injection_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            create_in_process_tool_dispatcher(
                TOOL_CONTRACTS,
                storage_path_planner=lambda **_: (),
            )
        with self.assertRaises(ValueError):
            create_in_process_tool_dispatcher(
                TOOL_CONTRACTS,
                get_storage_report_handler=lambda _: {},
                storage_path_planner=lambda **_: (),
                storage_report_reader=lambda _: {},
            )
        with self.assertRaises(ValueError):
            create_in_process_tool_dispatcher(
                TOOL_CONTRACTS,
                read_proton_logs_handler=lambda _: {},
                proton_log_reader=lambda **_: {},
            )
        with self.assertRaises(ValueError):
            create_in_process_tool_dispatcher(
                TOOL_CONTRACTS,
                search_knowledge_handler=lambda _: {},
                knowledge_search_index=_empty_knowledge_index(),
            )
        with self.assertRaises(ValueError):
            create_in_process_tool_dispatcher(
                TOOL_CONTRACTS,
                list_sources_handler=lambda _: {},
                knowledge_search_index=_empty_knowledge_index(),
            )

    def test_write_and_variable_tools_are_explicitly_refused_without_executor(self) -> None:
        stage_response = self.dispatcher.dispatch_tool_call(
            "stage_action",
            {
                "action": {
                    "title": "Create a backup",
                    "risk": "low_write",
                    "commands": [{"argv": ["mkdir", "-p", "/tmp/decky-ai-assistant"]}],
                }
            },
        )
        run_response = self.dispatcher.dispatch_tool_call(
            "run_approved_action",
            {
                "staged_action_id": "action-123",
                "approval_token": "approval-token",
                "expected_risk": "low_write",
            },
        )

        for tool_name, response, risk in (
            ("stage_action", stage_response, "low_write"),
            ("run_approved_action", run_response, "variable"),
        ):
            with self.subTest(tool=tool_name):
                self.assertFalse(response["ok"])
                self.assertEqual(response["tool"], tool_name)
                self.assertEqual(response["error"]["code"], "tool_refused")
                self.assertEqual(
                    response["error"]["details"],
                    {
                        "risk": risk,
                        "requires_approval": True,
                        "approval_gate": "decky_approval",
                    },
                )

    def test_handler_catalog_alignment_holds_for_shipped_catalog(self) -> None:
        dispatcher = create_in_process_tool_dispatcher(TOOL_CONTRACTS)

        contract_names = {contract.name for contract in TOOL_CONTRACTS}
        handler_names = set(dispatcher._handlers)

        # Every handler backs a real contract.
        self.assertTrue(handler_names <= contract_names)
        # Every non-approval-gated contract has a handler; approval-gated ones
        # (run_approved_action) intentionally do not.
        for contract in TOOL_CONTRACTS:
            if not contract.requires_approval:
                self.assertIn(contract.name, handler_names)
        self.assertNotIn("run_approved_action", handler_names)

    def test_handler_referencing_unknown_tool_fails_at_construction(self) -> None:
        class _DriftingDispatcher(InProcessToolDispatcher):
            def _assert_handler_catalog_alignment(self) -> None:
                self._handlers["ghost_tool"] = self._handle_inspect_current_game
                super()._assert_handler_catalog_alignment()

        with self.assertRaisesRegex(ContractCatalogDriftError, "ghost_tool"):
            _DriftingDispatcher(TOOL_CONTRACTS)

    def test_non_approval_contract_without_handler_fails_at_construction(self) -> None:
        class _DroppingDispatcher(InProcessToolDispatcher):
            def _assert_handler_catalog_alignment(self) -> None:
                self._handlers.pop("get_storage_report", None)
                super()._assert_handler_catalog_alignment()

        with self.assertRaisesRegex(ContractCatalogDriftError, "get_storage_report"):
            _DroppingDispatcher(TOOL_CONTRACTS)

    def test_stage_action_any_of_requires_commands_or_file_edits(self) -> None:
        store = StagedActionStore(
            timestamp_factory=lambda: "2026-06-21T13:30:00+00:00",
        )
        dispatcher = create_in_process_tool_dispatcher(
            TOOL_CONTRACTS,
            staged_action_store=store,
        )

        # Neither commands nor file_edits -> anyOf presence check fails.
        missing = dispatcher.dispatch_tool_call(
            "stage_action",
            {"action": {"title": "Nothing to do", "risk": RiskLevel.LOW_WRITE.value}},
        )
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "invalid_input")
        self.assertEqual(missing["error"]["details"]["path"], "$.action")
        self.assertIn("commands", missing["error"]["details"]["reason"])
        self.assertIn("file_edits", missing["error"]["details"]["reason"])

        # Only file_edits present -> anyOf is satisfied (commands not required).
        edits_only = dispatcher.dispatch_tool_call(
            "stage_action",
            {
                "action": {
                    "title": "Stage a temporary marker edit",
                    "risk": RiskLevel.LOW_WRITE.value,
                    "file_edits": [
                        {
                            "path": "/tmp/decky-ai-assistant-marker",
                            "operation": "create",
                            "temporary": True,
                        }
                    ],
                }
            },
        )
        self.assertTrue(edits_only["ok"])
        self.assertEqual(
            edits_only["result"]["display_plan"]["summary"]["file_edit_count"],
            1,
        )
        self.assertEqual(
            edits_only["result"]["display_plan"]["summary"]["command_count"],
            0,
        )


def _empty_knowledge_index():
    content = "# Empty\nNo indexed runtime knowledge yet."
    source = SourceMetadata(
        source_id="empty-source",
        source_type=SourceType.LOCAL_FOLDER,
        title="Empty Source",
        uri="file:///tmp/empty-source",
        license=SourceLicense(name="MIT", spdx_id="MIT"),
        revision=SourceRevision(value="test"),
        content_hash=ContentHash.sha256_text("empty source"),
    )
    document = KnowledgeDocument(
        document_id="empty-document",
        source_id=source.source_id,
        path="README.md",
        title="Empty",
        content_type="text/markdown",
        content_hash=ContentHash.sha256_text(content),
        byte_length=len(content.encode("utf-8")),
    )
    manifest = KnowledgePackManifest(
        pack_id="empty-pack",
        title="Empty Pack",
        version="0.1.0",
        created_at="2026-06-21T10:00:00Z",
        sources=(source,),
        documents=(document,),
    )
    return build_knowledge_search_index(manifest, {document.document_id: content})


if __name__ == "__main__":
    unittest.main()
