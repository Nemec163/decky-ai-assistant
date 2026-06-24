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
    ContractCatalogError,
    ToolApprovalMetadata,
    ToolContract,
    ToolRisk,
    export_tool_approval_summary,
    export_tool_catalog,
    get_tool_contract,
    list_tool_contracts,
    validate_tool_approval_summary,
    validate_tool_contract_catalog,
)


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


class ToolContractTests(unittest.TestCase):
    def test_contract_order_is_stable(self) -> None:
        names = tuple(contract.name for contract in list_tool_contracts())

        self.assertEqual(names, EXPECTED_TOOL_ORDER)
        self.assertEqual(contract_module.TOOL_CONTRACTS, list_tool_contracts())

    def test_risk_mapping_matches_roadmap(self) -> None:
        risks = {contract.name: contract.risk for contract in list_tool_contracts()}

        self.assertEqual(
            risks,
            {
                "search_knowledge": ToolRisk.READ_ONLY,
                "list_sources": ToolRisk.READ_ONLY,
                "inspect_current_game": ToolRisk.READ_ONLY,
                "read_proton_logs": ToolRisk.READ_ONLY,
                "get_storage_report": ToolRisk.READ_ONLY,
                "propose_fix": ToolRisk.READ_ONLY,
                "stage_action": ToolRisk.LOW_WRITE,
                "run_approved_action": ToolRisk.VARIABLE,
            },
        )
        self.assertEqual(get_tool_contract("stage_action").core_risk_level, RiskLevel.LOW_WRITE)
        self.assertIsNone(get_tool_contract("run_approved_action").core_risk_level)

    def test_core_risk_values_stay_aligned(self) -> None:
        self.assertEqual(ToolRisk.READ_ONLY.value, RiskLevel.READ_ONLY.value)
        self.assertEqual(ToolRisk.LOW_WRITE.value, RiskLevel.LOW_WRITE.value)
        self.assertEqual(ToolRisk.HIGH_WRITE.value, RiskLevel.HIGH_WRITE.value)
        self.assertEqual(ToolRisk.DANGER.value, RiskLevel.DANGER.value)

    def test_write_and_execution_tools_are_approval_gated(self) -> None:
        gated = {contract.name for contract in list_tool_contracts() if contract.requires_approval}

        self.assertEqual(gated, {"stage_action", "run_approved_action"})

    def test_contracts_use_jsonish_object_schemas(self) -> None:
        for contract in list_tool_contracts():
            with self.subTest(tool=contract.name):
                self.assertIsInstance(contract.input_schema, dict)
                self.assertIsInstance(contract.output_schema, dict)
                self.assertEqual(contract.input_schema["type"], "object")
                self.assertEqual(contract.output_schema["type"], "object")
                self.assertIsInstance(contract.input_schema["properties"], dict)
                self.assertIsInstance(contract.output_schema["properties"], dict)
                json.dumps(contract.input_schema)
                json.dumps(contract.output_schema)

    def test_catalog_version_tracks_tightened_schema_contracts(self) -> None:
        self.assertEqual(CATALOG_VERSION, 3)

    def test_redundant_catalog_alias_is_removed(self) -> None:
        self.assertFalse(hasattr(contract_module, "MCP_TOOL_CONTRACTS"))
        self.assertNotIn("MCP_TOOL_CONTRACTS", contract_module.__all__)
        self.assertFalse(hasattr(deck_assistant_mcp, "MCP_TOOL_CONTRACTS"))

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

        self.assertEqual(
            set(result_schema["required"]),
            {"chunk_id", "text", "citation"},
        )
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
        for field_name in (
            "source_type",
            "document_id",
            "document_title",
            "chunk_id",
            "headings",
            "start_line",
            "end_line",
            "path",
        ):
            self.assertIn(field_name, citation_schema["properties"])

        self.assertEqual(citation_schema["properties"]["source_id"]["minLength"], 1)
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
        self.assertEqual(source_item_schema["properties"]["source_id"]["minLength"], 1)
        self.assertEqual(
            set(source_item_schema["properties"]["kind"]["enum"]),
            {"github_repo", "git_url", "docs_url", "local_folder", "pack_registry"},
        )

    def test_diagnostic_output_schemas_match_core_report_shapes(self) -> None:
        proton_schema = get_tool_contract("read_proton_logs").output_schema

        self.assertEqual(set(proton_schema["required"]), {"status", "warnings", "limits", "logs"})
        self.assertEqual(
            proton_schema["properties"]["status"]["enum"],
            [status.value for status in DiagnosticStatus],
        )
        self.assertEqual(
            proton_schema["properties"]["warnings"]["maxItems"],
            MAX_DIAGNOSTIC_WARNINGS,
        )
        self.assertEqual(
            proton_schema["properties"]["limits"]["maxItems"],
            MAX_DIAGNOSTIC_LIMITS,
        )

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
            set(excerpt_schema["required"]),
            {"text", "truncated", "line_start", "line_end", "status", "warnings", "limits"},
        )
        self.assertEqual(
            excerpt_schema["properties"]["text"]["maxLength"],
            MAX_PROTON_EXCERPT_CHARACTERS,
        )
        self.assertEqual(
            excerpt_schema["properties"]["limits"]["items"]["properties"]["unit"]["enum"],
            [unit.value for unit in DiagnosticLimitUnit],
        )

        storage_schema = get_tool_contract("get_storage_report").output_schema
        self.assertEqual(
            set(storage_schema["required"]),
            {"status", "warnings", "limits", "sections"},
        )
        sections_schema = storage_schema["properties"]["sections"]
        self.assertEqual(sections_schema["maxItems"], MAX_STORAGE_REPORT_SECTIONS)
        section_schema = sections_schema["items"]
        self.assertNotIn("risk", section_schema["properties"])
        self.assertEqual(section_schema["properties"]["path"]["pattern"], "^/")
        self.assertEqual(
            section_schema["properties"]["name"]["enum"],
            [section.value for section in StorageSectionName],
        )
        self.assertEqual(
            set(section_schema["required"]),
            {"name", "path", "bytes", "status", "warnings", "limits", "items"},
        )

        items_schema = section_schema["properties"]["items"]
        self.assertEqual(items_schema["maxItems"], MAX_STORAGE_SECTION_ITEMS)
        item_schema = items_schema["items"]
        self.assertEqual(item_schema["properties"]["path"]["pattern"], "^/")
        self.assertEqual(
            set(item_schema["required"]),
            {"path", "bytes", "label", "status", "warnings"},
        )

    def test_stage_action_input_schema_requires_structured_action_specs(self) -> None:
        action_schema = get_tool_contract("stage_action").input_schema["properties"]["action"]

        self.assertEqual(action_schema["anyOf"], [{"required": ["commands"]}, {"required": ["file_edits"]}])
        self.assertNotIn("shell", action_schema["properties"])
        self.assertNotIn("command", action_schema["properties"])

        command_schema = action_schema["properties"]["commands"]["items"]
        self.assertEqual(command_schema["required"], ["argv"])
        self.assertEqual(command_schema["properties"]["argv"]["minItems"], 1)
        self.assertEqual(command_schema["properties"]["argv"]["items"]["minLength"], 1)

        file_edit_schema = action_schema["properties"]["file_edits"]["items"]
        self.assertEqual(set(file_edit_schema["required"]), {"path", "operation"})
        self.assertIn("diff", file_edit_schema["properties"])
        self.assertIn("temporary", file_edit_schema["properties"])

        backup_schema = action_schema["properties"]["backups"]["items"]
        self.assertEqual(
            set(backup_schema["required"]),
            {"source_path", "backup_path", "reason"},
        )

        rollback_schema = action_schema["properties"]["rollback"]["items"]
        self.assertEqual(rollback_schema["required"], ["description"])
        self.assertEqual(rollback_schema["properties"]["command"]["type"], ["object", "null"])

    def test_action_approval_output_schemas_are_structured_and_token_safe(self) -> None:
        stage_output = get_tool_contract("stage_action").output_schema

        self.assertEqual(stage_output["properties"]["requires_approval"]["const"], True)
        self.assertEqual(stage_output["properties"]["approved_at"]["type"], "null")
        self.assertEqual(
            set(stage_output["required"]),
            {
                "staged_action_id",
                "risk",
                "requires_approval",
                "approval_gate",
                "display_plan",
                "staged_at",
                "approved_at",
            },
        )

        display_plan = stage_output["properties"]["display_plan"]
        self.assertEqual(display_plan["type"], "object")
        self.assertEqual(
            set(display_plan["required"]),
            {
                "action_id",
                "title",
                "risk",
                "approval_gate",
                "commands",
                "file_edits",
                "backups",
                "backup_note",
                "rollback",
                "rollback_note",
                "approved_by_user_at",
                "summary",
            },
        )
        self.assertEqual(
            set(display_plan["properties"]["approval_gate"]["required"]),
            {
                "type",
                "summary",
                "requires_plan",
                "requires_exact_commands_or_diffs",
                "requires_backup_or_note",
                "requires_separate_confirmation",
                "may_execute_after_user_request",
            },
        )
        self.assertEqual(
            set(display_plan["properties"]["summary"]["required"]),
            {"command_count", "file_edit_count", "backup_count", "rollback_step_count"},
        )

        run_input = get_tool_contract("run_approved_action").input_schema
        self.assertIn("approval_token", run_input["properties"])

        run_output = get_tool_contract("run_approved_action").output_schema
        self.assertNotIn("approval_token", run_output["properties"])
        self.assertEqual(
            set(run_output["required"]),
            {"status", "action_id", "risk", "summary", "audit_id", "approval"},
        )

        receipt_schema = run_output["properties"]["approval"]
        self.assertNotIn("approval_token", receipt_schema["properties"])
        self.assertEqual(receipt_schema["properties"]["approval_token_accepted"]["const"], True)
        self.assertEqual(
            set(receipt_schema["required"]),
            {
                "staged_action_id",
                "expected_risk",
                "approval_token_accepted",
                "approved_by_user_at",
            },
        )

    def test_propose_fix_schema_uses_approval_plan_fields_without_variable_risk(self) -> None:
        proposal_schema = get_tool_contract("propose_fix").output_schema["properties"]["proposal"]

        self.assertNotIn("variable", proposal_schema["properties"]["risk"]["enum"])
        self.assertEqual(
            set(proposal_schema["required"]),
            {
                "title",
                "risk",
                "requires_approval",
                "approval_gate",
                "steps",
                "commands",
                "file_edits",
                "backups",
                "rollback",
            },
        )
        self.assertEqual(
            set(proposal_schema["properties"]["commands"]["items"]["required"]),
            {"argv", "risk", "has_redactions"},
        )
        self.assertEqual(
            set(proposal_schema["properties"]["file_edits"]["items"]["required"]),
            {"path", "operation", "temporary", "risk", "has_diff", "diff_line_count"},
        )

    def test_approval_execution_requires_token_shape(self) -> None:
        schema = get_tool_contract("run_approved_action").input_schema

        self.assertEqual(
            set(schema["required"]),
            {"staged_action_id", "approval_token", "expected_risk"},
        )

    def test_catalog_export_is_stable_and_detached(self) -> None:
        exported = export_tool_catalog()
        exported_again = export_tool_catalog()

        self.assertEqual(exported["catalog_version"], CATALOG_VERSION)
        self.assertEqual(exported, exported_again)

        exported["tools"][0]["input_schema"]["properties"]["query"]["minLength"] = 99

        self.assertEqual(
            get_tool_contract("search_knowledge").input_schema["properties"]["query"]["minLength"],
            1,
        )
        self.assertEqual(
            exported_again["tools"][0]["input_schema"]["properties"]["query"]["minLength"],
            1,
        )

    def test_approval_summary_is_stable_jsonish_and_detached(self) -> None:
        summary = export_tool_approval_summary()
        summary_again = export_tool_approval_summary()

        self.assertEqual(summary["catalog_version"], CATALOG_VERSION)
        self.assertEqual(summary, summary_again)
        self.assertEqual(
            tuple(tool["name"] for tool in summary["tools"]),
            EXPECTED_TOOL_ORDER,
        )
        json.dumps(summary)

        summary["tools"][0]["requires_approval"] = True
        summary["groups"]["read_only_tools"].append("mutated")

        self.assertEqual(export_tool_approval_summary(), summary_again)

    def test_approval_summary_groups_match_tool_gates(self) -> None:
        summary = export_tool_approval_summary()
        groups = summary["groups"]

        self.assertEqual(
            groups,
            {
                "read_only_tools": [
                    "search_knowledge",
                    "list_sources",
                    "inspect_current_game",
                    "read_proton_logs",
                    "get_storage_report",
                    "propose_fix",
                ],
                "approval_required_tools": [
                    "stage_action",
                    "run_approved_action",
                ],
                "variable_risk_tools": [
                    "run_approved_action",
                ],
            },
        )

        tools_by_name = {tool["name"]: tool for tool in summary["tools"]}

        self.assertEqual(tools_by_name["search_knowledge"]["approval_gate"], "none")
        self.assertTrue(tools_by_name["search_knowledge"]["read_only"])
        self.assertFalse(tools_by_name["search_knowledge"]["requires_approval"])
        self.assertEqual(tools_by_name["stage_action"]["approval_gate"], "decky_approval")
        self.assertTrue(tools_by_name["stage_action"]["requires_approval"])
        self.assertEqual(tools_by_name["run_approved_action"]["risk"], "variable")
        self.assertTrue(tools_by_name["run_approved_action"]["variable_risk"])
        self.assertEqual(
            ToolApprovalMetadata.from_contract(get_tool_contract("stage_action")).approval_gate,
            "decky_approval",
        )

    def test_approval_summary_validation_rejects_divergence(self) -> None:
        summary = export_tool_approval_summary()
        summary["tools"][0]["requires_approval"] = True

        with self.assertRaisesRegex(
            ContractCatalogError,
            "approval summary tools diverge from tool contracts",
        ):
            validate_tool_approval_summary(
                summary,
                contract_module.TOOL_CONTRACTS,
            )

        summary = export_tool_approval_summary()
        summary["groups"]["approval_required_tools"] = ["run_approved_action"]

        with self.assertRaisesRegex(
            ContractCatalogError,
            "approval summary groups diverge from tool contracts",
        ):
            validate_tool_approval_summary(
                summary,
                contract_module.TOOL_CONTRACTS,
            )

    def test_tool_contract_copies_input_schemas_from_callers(self) -> None:
        input_schema = _minimal_object_schema()
        output_schema = _minimal_object_schema()

        contract = ToolContract(
            name="copy_check",
            risk=ToolRisk.READ_ONLY,
            purpose="Verify schema copies.",
            requires_approval=False,
            input_schema=input_schema,
            output_schema=output_schema,
        )

        input_schema["properties"]["value"]["minLength"] = 5
        output_schema["properties"]["value"]["description"] = "mutated"

        self.assertNotIn("minLength", contract.input_schema["properties"]["value"])
        self.assertNotIn("description", contract.output_schema["properties"]["value"])

    def test_duplicate_tool_names_are_rejected(self) -> None:
        first = _test_contract(name="duplicate_name")
        second = _test_contract(name="duplicate_name")

        with self.assertRaisesRegex(
            ContractCatalogError,
            "duplicate tool contract names: duplicate_name",
        ):
            validate_tool_contract_catalog((first, second))

    def test_risk_and_approval_invariants_are_enforced(self) -> None:
        invalid_catalogs = (
            (
                "read_only approval",
                (_test_contract(name="read_only_gate", risk=ToolRisk.READ_ONLY, requires_approval=True),),
                "read_only and must not require approval",
            ),
            (
                "write without approval",
                (
                    _test_contract(
                        name="write_without_gate",
                        risk=ToolRisk.HIGH_WRITE,
                        requires_approval=False,
                    ),
                ),
                "has risk high_write and must require approval",
            ),
            (
                "variable without approval",
                (
                    _test_contract(
                        name="variable_without_gate",
                        risk=ToolRisk.VARIABLE,
                        requires_approval=False,
                    ),
                ),
                "has risk variable and must require approval",
            ),
        )

        for label, catalog, message in invalid_catalogs:
            with self.subTest(case=label):
                with self.assertRaisesRegex(ContractCatalogError, message):
                    validate_tool_contract_catalog(catalog)

    def test_unknown_tool_lookup_fails(self) -> None:
        with self.assertRaises(KeyError):
            get_tool_contract("unknown_tool")

    def test_no_tool_execution_functions_are_exposed(self) -> None:
        for tool_name in EXPECTED_TOOL_ORDER:
            with self.subTest(tool=tool_name):
                self.assertFalse(hasattr(contract_module, tool_name))
                self.assertFalse(hasattr(decky_ai_assistant_mcp_safe_exports(), tool_name))

        for forbidden_name in ("dispatch_tool", "execute_tool", "run_tool", "serve", "start_server"):
            self.assertFalse(hasattr(contract_module, forbidden_name))


def decky_ai_assistant_mcp_safe_exports() -> object:
    return deck_assistant_mcp


def _minimal_object_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "value": {"type": "string"},
        },
    }


def _test_contract(
    *,
    name: str,
    risk: ToolRisk = ToolRisk.READ_ONLY,
    requires_approval: bool | None = None,
) -> ToolContract:
    if requires_approval is None:
        requires_approval = risk is not ToolRisk.READ_ONLY

    return ToolContract(
        name=name,
        risk=risk,
        purpose=f"Test contract for {name}.",
        requires_approval=requires_approval,
        input_schema=_minimal_object_schema(),
        output_schema=_minimal_object_schema(),
    )


if __name__ == "__main__":
    unittest.main()
