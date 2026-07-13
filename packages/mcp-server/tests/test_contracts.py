from __future__ import annotations

import json
import unittest

import deck_assistant_mcp
import deck_assistant_mcp.contracts as contract_module
from deck_assistant_core import RiskLevel
from deck_assistant_core.diagnostics import (
    MAX_DIAGNOSTIC_LIMITS,
    MAX_DIAGNOSTIC_WARNINGS,
    MAX_PROTON_EXCERPT_CHARACTERS,
    MAX_PROTON_LOG_REFERENCES,
    MAX_STORAGE_REPORT_SECTIONS,
    MAX_STORAGE_SECTION_ITEMS,
    DiagnosticLimitUnit,
    DiagnosticStatus,
    StorageSectionName,
)
from deck_assistant_mcp import (
    CATALOG_VERSION,
    ToolRisk,
    get_tool_contract,
    list_tool_contracts,
)


EXPECTED_TOOL_ORDER = (
    "search_knowledge",
    "list_sources",
    "inspect_current_game",
    "read_proton_logs",
    "get_storage_report",
    "propose_fix",
)


class ToolContractTests(unittest.TestCase):
    def test_contract_order_is_stable(self) -> None:
        names = tuple(contract.name for contract in list_tool_contracts())

        self.assertEqual(names, EXPECTED_TOOL_ORDER)
        self.assertEqual(contract_module.TOOL_CONTRACTS, list_tool_contracts())

    def test_catalog_version_tracks_terminal_first_contracts(self) -> None:
        self.assertEqual(CATALOG_VERSION, 5)

    def test_risk_mapping_is_read_and_plan_only(self) -> None:
        risks = {contract.name: contract.risk for contract in list_tool_contracts()}

        self.assertEqual(
            risks,
            {tool_name: ToolRisk.READ_ONLY for tool_name in EXPECTED_TOOL_ORDER},
        )
        self.assertEqual(get_tool_contract("propose_fix").core_risk_level, RiskLevel.READ_ONLY)
        self.assertEqual(ToolRisk.READ_ONLY.value, RiskLevel.READ_ONLY.value)
        self.assertEqual(ToolRisk.LOW_WRITE.value, RiskLevel.LOW_WRITE.value)
        self.assertEqual(ToolRisk.HIGH_WRITE.value, RiskLevel.HIGH_WRITE.value)
        self.assertEqual(ToolRisk.DANGER.value, RiskLevel.DANGER.value)

    def test_removed_catalog_alias_stays_absent(self) -> None:
        self.assertFalse(hasattr(contract_module, "MCP_TOOL_CONTRACTS"))
        self.assertNotIn("MCP_TOOL_CONTRACTS", contract_module.__all__)
        self.assertFalse(hasattr(deck_assistant_mcp, "MCP_TOOL_CONTRACTS"))

    def test_contracts_use_jsonish_object_schemas(self) -> None:
        for contract in list_tool_contracts():
            with self.subTest(tool=contract.name):
                self.assertIsInstance(contract.input_schema, dict)
                self.assertIsInstance(contract.output_schema, dict)
                self.assertEqual(contract.input_schema["type"], "object")
                self.assertEqual(contract.output_schema["type"], "object")
                self.assertIsInstance(contract.input_schema["properties"], dict)
                self.assertIsInstance(contract.output_schema["properties"], dict)
                json.dumps(contract.to_dict())

    def test_read_proton_logs_caps_excerpt_characters_not_bytes(self) -> None:
        input_schema = get_tool_contract("read_proton_logs").input_schema

        self.assertNotIn("max_bytes", input_schema["properties"])
        excerpt = input_schema["properties"]["max_excerpt_characters"]
        self.assertEqual(excerpt["type"], "integer")
        self.assertEqual(excerpt["minimum"], 1024)
        self.assertEqual(excerpt["maximum"], 262144)
        self.assertEqual(excerpt["default"], 65536)
        self.assertIn("excerpt characters", excerpt["description"])

    def test_knowledge_output_schemas_include_precise_citation_metadata(self) -> None:
        search_schema = get_tool_contract("search_knowledge").output_schema
        result_schema = search_schema["properties"]["results"]["items"]
        self.assertEqual(search_schema["properties"]["results"]["maxItems"], 20)

        self.assertEqual(set(result_schema["required"]), {"chunk_id", "text", "citation"})
        self.assertIn("score", result_schema["properties"])

        citation_schema = result_schema["properties"]["citation"]
        self.assertEqual(
            set(citation_schema["required"]),
            {
                "source_id",
                "source_type",
                "title",
                "url",
                "license",
                "revision",
                "path",
                "document_id",
                "document_title",
                "chunk_id",
                "headings",
                "start_line",
                "end_line",
            },
        )
        self.assertEqual(
            set(citation_schema["properties"]["source_type"]["enum"]),
            {"github_repo", "git_url", "docs_url", "local_folder", "pack_registry"},
        )
        self.assertEqual(result_schema["properties"]["text"]["minLength"], 1)
        self.assertEqual(result_schema["properties"]["score"]["minimum"], 0)

        source_schema = get_tool_contract("list_sources").output_schema
        source_item_schema = source_schema["properties"]["sources"]["items"]
        self.assertEqual(
            set(source_item_schema["required"]),
            {"source_id", "name", "kind", "enabled", "license", "revision", "url"},
        )

    def test_diagnostic_output_schemas_match_core_report_shapes(self) -> None:
        proton_schema = get_tool_contract("read_proton_logs").output_schema

        self.assertEqual(set(proton_schema["required"]), {"status", "warnings", "limits", "logs"})
        self.assertEqual(
            proton_schema["properties"]["status"]["enum"],
            [status.value for status in DiagnosticStatus],
        )
        self.assertEqual(proton_schema["properties"]["warnings"]["maxItems"], MAX_DIAGNOSTIC_WARNINGS)
        self.assertEqual(proton_schema["properties"]["limits"]["maxItems"], MAX_DIAGNOSTIC_LIMITS)

        logs_schema = proton_schema["properties"]["logs"]
        self.assertEqual(logs_schema["maxItems"], MAX_PROTON_LOG_REFERENCES)
        log_schema = logs_schema["items"]
        self.assertEqual(
            set(log_schema["required"]),
            {"path", "app_id", "modified_at", "status", "warnings", "limits", "excerpt"},
        )
        self.assertEqual(log_schema["properties"]["path"]["pattern"], "^/")

        excerpt_schema = log_schema["properties"]["excerpt"]
        self.assertEqual(excerpt_schema["type"], ["object", "null"])
        self.assertEqual(
            excerpt_schema["properties"]["text"]["maxLength"],
            MAX_PROTON_EXCERPT_CHARACTERS,
        )
        self.assertEqual(
            excerpt_schema["properties"]["limits"]["items"]["properties"]["unit"]["enum"],
            [unit.value for unit in DiagnosticLimitUnit],
        )

        storage_schema = get_tool_contract("get_storage_report").output_schema
        self.assertEqual(set(storage_schema["required"]), {"status", "warnings", "limits", "sections"})
        sections_schema = storage_schema["properties"]["sections"]
        self.assertEqual(sections_schema["maxItems"], MAX_STORAGE_REPORT_SECTIONS)
        section_schema = sections_schema["items"]
        self.assertEqual(section_schema["properties"]["path"]["pattern"], "^/")
        self.assertEqual(
            section_schema["properties"]["name"]["enum"],
            [section.value for section in StorageSectionName],
        )
        self.assertEqual(section_schema["properties"]["items"]["maxItems"], MAX_STORAGE_SECTION_ITEMS)

    def test_propose_fix_output_schema_is_plan_only(self) -> None:
        proposal_schema = get_tool_contract("propose_fix").output_schema["properties"]["proposal"]

        self.assertEqual(
            set(proposal_schema["required"]),
            {"title", "risk", "steps", "commands", "file_edits"},
        )
        self.assertEqual(proposal_schema["properties"]["risk"]["enum"], [risk.value for risk in RiskLevel])
        self.assertEqual(
            proposal_schema["properties"]["commands"]["items"]["required"],
            ["argv"],
        )
        self.assertEqual(
            set(proposal_schema["properties"]["file_edits"]["items"]["required"]),
            {"path", "operation"},
        )


if __name__ == "__main__":
    unittest.main()
