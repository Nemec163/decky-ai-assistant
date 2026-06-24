"""Static MCP tool contracts.

This package intentionally stops at contract description. It has no MCP
transport dependency, no server loop, and no local action execution entrypoint.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

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
from deck_assistant_core.knowledge import SourceType
from deck_assistant_core.risk import RiskLevel


class ToolRisk(str, Enum):
    """Risk labels exposed by MCP tool contracts."""

    READ_ONLY = RiskLevel.READ_ONLY.value
    LOW_WRITE = RiskLevel.LOW_WRITE.value
    HIGH_WRITE = RiskLevel.HIGH_WRITE.value
    DANGER = RiskLevel.DANGER.value
    VARIABLE = "variable"


class ContractCatalogError(ValueError):
    """Raised when static MCP contract catalog invariants are violated."""


@dataclass(frozen=True)
class ToolContract:
    """Stable JSON-like contract for an MCP tool."""

    name: str
    risk: ToolRisk
    purpose: str
    requires_approval: bool
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool contract name must not be empty")
        if not self.purpose.strip():
            raise ValueError(f"{self.name} purpose must not be empty")
        input_schema = deepcopy(self.input_schema)
        output_schema = deepcopy(self.output_schema)
        _assert_object_schema_shape(self.name, "input_schema", input_schema)
        _assert_object_schema_shape(self.name, "output_schema", output_schema)
        object.__setattr__(self, "input_schema", input_schema)
        object.__setattr__(self, "output_schema", output_schema)

    @property
    def core_risk_level(self) -> RiskLevel | None:
        """Return the core risk level when the tool has a fixed risk."""

        if self.risk is ToolRisk.VARIABLE:
            return None
        return RiskLevel(self.risk.value)

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-serializable representation."""

        return {
            "name": self.name,
            "risk": self.risk.value,
            "purpose": self.purpose,
            "requires_approval": self.requires_approval,
            "input_schema": deepcopy(self.input_schema),
            "output_schema": deepcopy(self.output_schema),
        }


@dataclass(frozen=True)
class ToolApprovalMetadata:
    """Stable approval summary for UI and adapter consumers."""

    name: str
    risk: ToolRisk
    requires_approval: bool
    approval_gate: str

    @classmethod
    def from_contract(cls, contract: ToolContract) -> "ToolApprovalMetadata":
        return cls(
            name=contract.name,
            risk=contract.risk,
            requires_approval=contract.requires_approval,
            approval_gate=_approval_gate_for_contract(contract),
        )

    @property
    def read_only(self) -> bool:
        return self.risk is ToolRisk.READ_ONLY

    @property
    def variable_risk(self) -> bool:
        return self.risk is ToolRisk.VARIABLE

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-serializable representation."""

        return {
            "name": self.name,
            "risk": self.risk.value,
            "requires_approval": self.requires_approval,
            "approval_gate": self.approval_gate,
            "read_only": self.read_only,
            "variable_risk": self.variable_risk,
        }


def _approval_gate_for_contract(contract: ToolContract) -> str:
    return "decky_approval" if contract.requires_approval else "none"


def _object_schema(
    *,
    properties: dict[str, Any] | None = None,
    required: tuple[str, ...] = (),
    additional_properties: bool = False,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": additional_properties,
        "properties": properties or {},
    }
    if required:
        schema["required"] = list(required)
    return schema


def _nullable_object_schema(
    *,
    properties: dict[str, Any] | None = None,
    required: tuple[str, ...] = (),
    additional_properties: bool = False,
) -> dict[str, Any]:
    schema = _object_schema(
        properties=properties,
        required=required,
        additional_properties=additional_properties,
    )
    schema["type"] = ["object", "null"]
    return schema


def _enum_values(enum_type: type[Enum]) -> list[str]:
    return [str(member.value) for member in enum_type]


def _citation_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "source_id": {"type": "string", "minLength": 1},
            "source_type": {"type": "string", "enum": _enum_values(SourceType)},
            "title": {"type": "string", "minLength": 1},
            "url": {"type": "string", "minLength": 1},
            "license": {"type": "string", "minLength": 1},
            "revision": {"type": "string", "minLength": 1},
            "path": {"type": "string", "minLength": 1},
            "document_id": {"type": "string", "minLength": 1},
            "document_title": {"type": "string", "minLength": 1},
            "chunk_id": {"type": "string", "minLength": 1},
            "headings": _string_array_schema(item_min_length=1),
            "start_line": {"type": "integer", "minimum": 1},
            "end_line": {"type": "integer", "minimum": 1},
        },
        required=(
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
        ),
    )


def _string_array_schema(
    *,
    max_items: int | None = None,
    item_min_length: int | None = None,
) -> dict[str, Any]:
    item_schema: dict[str, Any] = {"type": "string"}
    if item_min_length is not None:
        item_schema["minLength"] = item_min_length
    schema: dict[str, Any] = {"type": "array", "items": item_schema}
    if max_items is not None:
        schema["maxItems"] = max_items
    return schema


def _risk_schema() -> dict[str, Any]:
    return {"type": "string", "enum": _enum_values(RiskLevel)}


def _absolute_path_schema() -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "pattern": "^/"}


def _diagnostic_status_schema() -> dict[str, Any]:
    return {"type": "string", "enum": _enum_values(DiagnosticStatus)}


def _diagnostic_warnings_schema() -> dict[str, Any]:
    return _string_array_schema(max_items=MAX_DIAGNOSTIC_WARNINGS)


def _diagnostic_limit_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "name": {"type": "string", "minLength": 1},
            "unit": {"type": "string", "enum": _enum_values(DiagnosticLimitUnit)},
            "value": {"type": "integer", "minimum": 0},
            "hit": {"type": "boolean"},
        },
        required=("name", "unit", "value", "hit"),
    )


def _diagnostic_limits_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": MAX_DIAGNOSTIC_LIMITS,
        "items": _diagnostic_limit_schema(),
    }


def _proton_log_excerpt_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "text": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_PROTON_EXCERPT_CHARACTERS,
            },
            "truncated": {"type": "boolean"},
            "line_start": {"type": ["integer", "null"], "minimum": 1},
            "line_end": {"type": ["integer", "null"], "minimum": 1},
            "status": _diagnostic_status_schema(),
            "warnings": _diagnostic_warnings_schema(),
            "limits": _diagnostic_limits_schema(),
        },
        required=(
            "text",
            "truncated",
            "line_start",
            "line_end",
            "status",
            "warnings",
            "limits",
        ),
    )


def _proton_log_reference_schema() -> dict[str, Any]:
    excerpt_schema = _proton_log_excerpt_schema()
    return _object_schema(
        properties={
            "path": _absolute_path_schema(),
            "app_id": {"type": ["integer", "null"], "minimum": 1},
            "modified_at": {"type": ["string", "null"], "format": "date-time"},
            "status": _diagnostic_status_schema(),
            "warnings": _diagnostic_warnings_schema(),
            "limits": _diagnostic_limits_schema(),
            "excerpt": _nullable_object_schema(
                properties=excerpt_schema["properties"],
                required=tuple(excerpt_schema["required"]),
            ),
        },
        required=(
            "path",
            "app_id",
            "modified_at",
            "status",
            "warnings",
            "limits",
            "excerpt",
        ),
    )


def _proton_log_report_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "status": _diagnostic_status_schema(),
            "warnings": _diagnostic_warnings_schema(),
            "limits": _diagnostic_limits_schema(),
            "logs": {
                "type": "array",
                "maxItems": MAX_PROTON_LOG_REFERENCES,
                "items": _proton_log_reference_schema(),
            },
        },
        required=("status", "warnings", "limits", "logs"),
    )


def _storage_report_item_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "path": _absolute_path_schema(),
            "bytes": {"type": "integer", "minimum": 0},
            "label": {"type": ["string", "null"]},
            "status": _diagnostic_status_schema(),
            "warnings": _diagnostic_warnings_schema(),
        },
        required=("path", "bytes", "label", "status", "warnings"),
    )


def _storage_report_section_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "name": {"type": "string", "enum": _enum_values(StorageSectionName)},
            "path": _absolute_path_schema(),
            "bytes": {"type": "integer", "minimum": 0},
            "status": _diagnostic_status_schema(),
            "warnings": _diagnostic_warnings_schema(),
            "limits": _diagnostic_limits_schema(),
            "items": {
                "type": "array",
                "maxItems": MAX_STORAGE_SECTION_ITEMS,
                "items": _storage_report_item_schema(),
            },
        },
        required=("name", "path", "bytes", "status", "warnings", "limits", "items"),
    )


def _storage_report_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "status": _diagnostic_status_schema(),
            "warnings": _diagnostic_warnings_schema(),
            "limits": _diagnostic_limits_schema(),
            "sections": {
                "type": "array",
                "maxItems": MAX_STORAGE_REPORT_SECTIONS,
                "items": _storage_report_section_schema(),
            },
        },
        required=("status", "warnings", "limits", "sections"),
    )


def _command_spec_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "argv": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "cwd": {"type": ["string", "null"]},
        },
        required=("argv",),
    )


def _file_edit_spec_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "path": {"type": "string", "minLength": 1},
            "operation": {"type": "string", "minLength": 1},
            "diff": {"type": ["string", "null"]},
            "temporary": {"type": "boolean", "default": False},
        },
        required=("path", "operation"),
    )


def _backup_spec_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "source_path": {"type": "string", "minLength": 1},
            "backup_path": {"type": "string", "minLength": 1},
            "reason": {"type": "string", "minLength": 1},
        },
        required=("source_path", "backup_path", "reason"),
    )


def _rollback_step_schema() -> dict[str, Any]:
    command_schema = _command_spec_schema()
    return _object_schema(
        properties={
            "description": {"type": "string", "minLength": 1},
            "command": _nullable_object_schema(
                properties=command_schema["properties"],
                required=tuple(command_schema["required"]),
            ),
        },
        required=("description",),
    )


def _staged_action_schema() -> dict[str, Any]:
    schema = _object_schema(
        properties={
            "title": {"type": "string", "minLength": 1},
            "risk": _risk_schema(),
            "commands": {
                "type": "array",
                "minItems": 1,
                "items": _command_spec_schema(),
            },
            "file_edits": {
                "type": "array",
                "minItems": 1,
                "items": _file_edit_spec_schema(),
            },
            "backups": {"type": "array", "items": _backup_spec_schema()},
            "backup_note": {"type": ["string", "null"]},
            "rollback": {"type": "array", "items": _rollback_step_schema()},
            "rollback_note": {"type": ["string", "null"]},
        },
        required=("title", "risk"),
    )
    schema["anyOf"] = [{"required": ["commands"]}, {"required": ["file_edits"]}]
    return schema


def _approval_gate_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "type": {
                "type": "string",
                "enum": [
                    "user_request",
                    "approval_required",
                    "separate_confirmation_required",
                ],
            },
            "summary": {"type": "string", "minLength": 1},
            "requires_plan": {"type": "boolean"},
            "requires_exact_commands_or_diffs": {"type": "boolean"},
            "requires_backup_or_note": {"type": "boolean"},
            "requires_separate_confirmation": {"type": "boolean"},
            "may_execute_after_user_request": {"type": "boolean"},
        },
        required=(
            "type",
            "summary",
            "requires_plan",
            "requires_exact_commands_or_diffs",
            "requires_backup_or_note",
            "requires_separate_confirmation",
            "may_execute_after_user_request",
        ),
    )


def _approval_command_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "argv": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "cwd": {"type": ["string", "null"]},
            "risk": _risk_schema(),
            "has_redactions": {"type": "boolean"},
        },
        required=("argv", "risk", "has_redactions"),
    )


def _approval_file_edit_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "path": {"type": "string", "minLength": 1},
            "operation": {"type": "string", "minLength": 1},
            "temporary": {"type": "boolean"},
            "risk": _risk_schema(),
            "has_diff": {"type": "boolean"},
            "diff_line_count": {"type": "integer", "minimum": 0},
        },
        required=("path", "operation", "temporary", "risk", "has_diff", "diff_line_count"),
    )


def _approval_backup_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "source_path": {"type": "string", "minLength": 1},
            "backup_path": {"type": "string", "minLength": 1},
            "reason": {"type": "string", "minLength": 1},
        },
        required=("source_path", "backup_path", "reason"),
    )


def _approval_rollback_step_schema() -> dict[str, Any]:
    command_schema = _approval_command_schema()
    return _object_schema(
        properties={
            "description": {"type": "string", "minLength": 1},
            "command": _nullable_object_schema(
                properties=command_schema["properties"],
                required=tuple(command_schema["required"]),
            ),
        },
        required=("description",),
    )


def _approval_plan_summary_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "command_count": {"type": "integer", "minimum": 0},
            "file_edit_count": {"type": "integer", "minimum": 0},
            "backup_count": {"type": "integer", "minimum": 0},
            "rollback_step_count": {"type": "integer", "minimum": 0},
        },
        required=("command_count", "file_edit_count", "backup_count", "rollback_step_count"),
    )


def _approval_plan_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "action_id": {"type": "string", "minLength": 1},
            "title": {"type": "string", "minLength": 1},
            "risk": _risk_schema(),
            "approval_gate": _approval_gate_schema(),
            "commands": {"type": "array", "items": _approval_command_schema()},
            "file_edits": {"type": "array", "items": _approval_file_edit_schema()},
            "backups": {"type": "array", "items": _approval_backup_schema()},
            "backup_note": {"type": ["string", "null"]},
            "rollback": {"type": "array", "items": _approval_rollback_step_schema()},
            "rollback_note": {"type": ["string", "null"]},
            "approved_by_user_at": {"type": ["string", "null"], "format": "date-time"},
            "summary": _approval_plan_summary_schema(),
        },
        required=(
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
        ),
    )


def _run_approval_receipt_schema() -> dict[str, Any]:
    return _object_schema(
        properties={
            "staged_action_id": {"type": "string", "minLength": 1},
            "expected_risk": _risk_schema(),
            "approval_token_accepted": {"type": "boolean", "const": True},
            "approved_by_user_at": {"type": ["string", "null"], "format": "date-time"},
        },
        required=(
            "staged_action_id",
            "expected_risk",
            "approval_token_accepted",
            "approved_by_user_at",
        ),
    )


def _assert_object_schema_shape(tool_name: str, field_name: str, schema: dict[str, Any]) -> None:
    # Author-time invariant: a malformed contract schema is one conceptual
    # failure, so raise a single error type (ContractCatalogError) regardless
    # of which structural expectation was violated.
    if not isinstance(schema, dict):
        raise ContractCatalogError(f"{tool_name} {field_name} must be a dict")
    if schema.get("type") != "object":
        raise ContractCatalogError(f"{tool_name} {field_name} must describe an object")
    if not isinstance(schema.get("properties"), dict):
        raise ContractCatalogError(f"{tool_name} {field_name} must include properties dict")


# Bump CATALOG_VERSION whenever a documented contract input/output schema, tool
# name, or risk level changes (see docs/interfaces.md); consumers key cache and
# compatibility checks off this integer.
CATALOG_VERSION = 3
# Local cap on knowledge search results. deck_assistant_core exposes no
# equivalent MAX_* constant, so this stays module-local; revisit if core adds one.
_MAX_KNOWLEDGE_SEARCH_RESULTS = 20


def validate_tool_contract_catalog(
    contracts: Sequence[ToolContract],
) -> tuple[ToolContract, ...]:
    """Validate and freeze a tool catalog in stable order."""

    catalog = tuple(contracts)
    _validate_unique_tool_names(catalog)
    _validate_approval_risk_invariants(catalog)
    return catalog


def _validate_unique_tool_names(contracts: Sequence[ToolContract]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for contract in contracts:
        if contract.name in seen and contract.name not in duplicates:
            duplicates.append(contract.name)
            continue
        seen.add(contract.name)

    if duplicates:
        duplicate_names = ", ".join(sorted(duplicates))
        raise ContractCatalogError(f"duplicate tool contract names: {duplicate_names}")


def _validate_approval_risk_invariants(contracts: Sequence[ToolContract]) -> None:
    for contract in contracts:
        if contract.risk is ToolRisk.READ_ONLY and contract.requires_approval:
            raise ContractCatalogError(
                f"{contract.name} is read_only and must not require approval"
            )
        if contract.risk is not ToolRisk.READ_ONLY and not contract.requires_approval:
            raise ContractCatalogError(
                f"{contract.name} has risk {contract.risk.value} and must require approval"
            )


TOOL_CONTRACTS = validate_tool_contract_catalog(
    (
    ToolContract(
        name="search_knowledge",
        risk=ToolRisk.READ_ONLY,
        purpose="Search enabled local knowledge packs and return cited chunks.",
        requires_approval=False,
        input_schema=_object_schema(
            properties={
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Plain-language search query.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_KNOWLEDGE_SEARCH_RESULTS,
                    "default": 5,
                },
                "source_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "description": "Optional source ids to search within.",
                },
            },
            required=("query",),
        ),
        output_schema=_object_schema(
            properties={
                "results": {
                    "type": "array",
                    "maxItems": _MAX_KNOWLEDGE_SEARCH_RESULTS,
                    "items": _object_schema(
                        properties={
                            "chunk_id": {"type": "string", "minLength": 1},
                            "text": {"type": "string", "minLength": 1},
                            "score": {"type": "number", "minimum": 0},
                            "citation": _citation_schema(),
                        },
                        required=("chunk_id", "text", "citation"),
                    ),
                }
            },
            required=("results",),
        ),
    ),
    ToolContract(
        name="list_sources",
        risk=ToolRisk.READ_ONLY,
        purpose="List knowledge sources, enabled state, license, and revision metadata.",
        requires_approval=False,
        input_schema=_object_schema(
            properties={
                "include_disabled": {
                    "type": "boolean",
                    "default": True,
                }
            }
        ),
        output_schema=_object_schema(
            properties={
                "sources": {
                    "type": "array",
                    "items": _object_schema(
                        properties={
                            "source_id": {"type": "string", "minLength": 1},
                            "name": {"type": "string", "minLength": 1},
                            "kind": {"type": "string", "enum": _enum_values(SourceType)},
                            "enabled": {"type": "boolean"},
                            "license": {"type": "string", "minLength": 1},
                            "revision": {"type": "string", "minLength": 1},
                            "url": {"type": "string", "minLength": 1},
                        },
                        required=(
                            "source_id",
                            "name",
                            "kind",
                            "enabled",
                            "license",
                            "revision",
                            "url",
                        ),
                    ),
                }
            },
            required=("sources",),
        ),
    ),
    ToolContract(
        name="inspect_current_game",
        risk=ToolRisk.READ_ONLY,
        purpose="Inspect selected or current Steam app context where available.",
        requires_approval=False,
        input_schema=_object_schema(
            properties={
                "app_id": {
                    "type": ["integer", "null"],
                    "description": "Optional Steam app id when the caller already knows it.",
                },
                "include_processes": {
                    "type": "boolean",
                    "default": False,
                },
            }
        ),
        output_schema=_object_schema(
            properties={
                "game": _nullable_object_schema(
                    properties={
                        "app_id": {"type": "integer"},
                        "name": {"type": "string"},
                        "install_path": {"type": ["string", "null"]},
                        "compat_tool": {"type": ["string", "null"]},
                    },
                    required=("app_id", "name", "install_path", "compat_tool"),
                ),
                "detection_method": {"type": "string"},
                "warnings": _diagnostic_warnings_schema(),
            },
            required=("game", "detection_method", "warnings"),
        ),
    ),
    ToolContract(
        name="read_proton_logs",
        risk=ToolRisk.READ_ONLY,
        purpose="Locate and summarize Proton logs for a Steam app without mutating files.",
        requires_approval=False,
        input_schema=_object_schema(
            properties={
                "app_id": {
                    "type": ["integer", "null"],
                    "description": "Optional Steam app id; current app may be used when omitted.",
                },
                "max_excerpt_characters": {
                    "type": "integer",
                    "minimum": 1024,
                    "maximum": 262144,
                    "default": 65536,
                    "description": (
                        "Upper bound on returned excerpt characters; the reader "
                        "additionally clamps to its own internal excerpt limit."
                    ),
                },
            }
        ),
        output_schema=_proton_log_report_schema(),
    ),
    ToolContract(
        name="get_storage_report",
        risk=ToolRisk.READ_ONLY,
        purpose="Report Deck storage usage for caches, compatdata, logs, and media.",
        requires_approval=False,
        input_schema=_object_schema(
            properties={
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": _enum_values(StorageSectionName),
                    },
                    "default": _enum_values(StorageSectionName),
                }
            }
        ),
        output_schema=_storage_report_schema(),
    ),
    ToolContract(
        name="propose_fix",
        risk=ToolRisk.READ_ONLY,
        purpose="Convert diagnostics into a human-reviewable plan and risk classification.",
        requires_approval=False,
        input_schema=_object_schema(
            properties={
                "diagnosis": {
                    "type": "string",
                    "minLength": 1,
                },
                "evidence": {
                    "type": "array",
                    "items": _object_schema(
                        properties={
                            "source": {"type": "string"},
                            "summary": {"type": "string"},
                            "citation": {"type": ["object", "null"]},
                        },
                        required=("source", "summary"),
                    ),
                },
                "requested_outcome": {"type": ["string", "null"]},
            },
            required=("diagnosis",),
        ),
        output_schema=_object_schema(
            properties={
                "proposal": _object_schema(
                    properties={
                        "title": {"type": "string", "minLength": 1},
                        "risk": _risk_schema(),
                        "requires_approval": {"type": "boolean"},
                        "approval_gate": _approval_gate_schema(),
                        "steps": _string_array_schema(),
                        "commands": {"type": "array", "items": _approval_command_schema()},
                        "file_edits": {"type": "array", "items": _approval_file_edit_schema()},
                        "backups": {"type": "array", "items": _approval_backup_schema()},
                        "rollback": {"type": "array", "items": _approval_rollback_step_schema()},
                    },
                    required=(
                        "title",
                        "risk",
                        "requires_approval",
                        "approval_gate",
                        "steps",
                        "commands",
                        "file_edits",
                        "backups",
                        "rollback",
                    ),
                )
            },
            required=("proposal",),
        ),
    ),
    ToolContract(
        name="stage_action",
        risk=ToolRisk.LOW_WRITE,
        purpose="Prepare an approval-ready action record; never execute commands or file edits.",
        requires_approval=True,
        input_schema=_object_schema(
            properties={
                "action": _staged_action_schema()
            },
            required=("action",),
        ),
        output_schema=_object_schema(
            properties={
                "staged_action_id": {"type": "string", "minLength": 1},
                "risk": _risk_schema(),
                "requires_approval": {"type": "boolean", "const": True},
                "approval_gate": _approval_gate_schema(),
                "display_plan": _approval_plan_schema(),
                "staged_at": {"type": "string", "format": "date-time"},
                "approved_at": {"type": "null"},
            },
            required=(
                "staged_action_id",
                "risk",
                "requires_approval",
                "approval_gate",
                "display_plan",
                "staged_at",
                "approved_at",
            ),
        ),
    ),
    ToolContract(
        name="run_approved_action",
        risk=ToolRisk.VARIABLE,
        purpose="Run only an already staged action that carries a Decky-side approval token.",
        requires_approval=True,
        input_schema=_object_schema(
            properties={
                "staged_action_id": {"type": "string", "minLength": 1},
                "approval_token": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Opaque token issued by Decky approval UI.",
                },
                "expected_risk": _risk_schema(),
            },
            required=("staged_action_id", "approval_token", "expected_risk"),
        ),
        output_schema=_object_schema(
            properties={
                "status": {
                    "type": "string",
                    "enum": ["queued", "running", "succeeded", "failed", "rejected"],
                },
                "action_id": {"type": "string", "minLength": 1},
                "risk": _risk_schema(),
                "summary": {"type": "string"},
                "audit_id": {"type": ["string", "null"]},
                "approval": _run_approval_receipt_schema(),
            },
            required=("status", "action_id", "risk", "summary", "audit_id", "approval"),
        ),
    ),
    )
)

TOOL_CONTRACTS_BY_NAME: dict[str, ToolContract] = {
    contract.name: contract for contract in TOOL_CONTRACTS
}


def export_tool_catalog(
    contracts: Sequence[ToolContract] | None = None,
) -> dict[str, Any]:
    """Return a detached, JSON-serializable catalog export."""

    active_contracts = (
        TOOL_CONTRACTS if contracts is None else validate_tool_contract_catalog(contracts)
    )
    return {
        "catalog_version": CATALOG_VERSION,
        "tools": [contract.to_dict() for contract in active_contracts],
    }


def export_tool_approval_summary(
    contracts: Sequence[ToolContract] | None = None,
) -> dict[str, Any]:
    """Return detached approval and gating metadata for tool consumers."""

    active_contracts = (
        TOOL_CONTRACTS if contracts is None else validate_tool_contract_catalog(contracts)
    )
    summary = {
        "catalog_version": CATALOG_VERSION,
        "tools": [
            ToolApprovalMetadata.from_contract(contract).to_dict()
            for contract in active_contracts
        ],
        "groups": _approval_summary_groups(active_contracts),
    }
    validate_tool_approval_summary(summary, active_contracts)
    return summary


def validate_tool_approval_summary(
    summary: Mapping[str, Any],
    contracts: Sequence[ToolContract],
) -> None:
    """Validate approval summary metadata against tool contract invariants."""

    active_contracts = validate_tool_contract_catalog(contracts)
    expected_tools = [
        ToolApprovalMetadata.from_contract(contract).to_dict()
        for contract in active_contracts
    ]
    expected_groups = _approval_summary_groups(active_contracts)

    if summary.get("catalog_version") != CATALOG_VERSION:
        raise ContractCatalogError("approval summary catalog_version diverges from catalog")
    if summary.get("tools") != expected_tools:
        raise ContractCatalogError("approval summary tools diverge from tool contracts")
    if summary.get("groups") != expected_groups:
        raise ContractCatalogError("approval summary groups diverge from tool contracts")


def _approval_summary_groups(contracts: Sequence[ToolContract]) -> dict[str, list[str]]:
    return {
        "read_only_tools": [
            contract.name for contract in contracts if contract.risk is ToolRisk.READ_ONLY
        ],
        "approval_required_tools": [
            contract.name for contract in contracts if contract.requires_approval
        ],
        "variable_risk_tools": [
            contract.name for contract in contracts if contract.risk is ToolRisk.VARIABLE
        ],
    }


def list_tool_contracts() -> tuple[ToolContract, ...]:
    """Return contracts in stable presentation order."""

    return TOOL_CONTRACTS


def get_tool_contract(name: str) -> ToolContract:
    """Return one contract by tool name."""

    return TOOL_CONTRACTS_BY_NAME[name]


__all__ = [
    "CATALOG_VERSION",
    "ContractCatalogError",
    "TOOL_CONTRACTS",
    "TOOL_CONTRACTS_BY_NAME",
    "ToolApprovalMetadata",
    "ToolContract",
    "ToolRisk",
    "export_tool_approval_summary",
    "export_tool_catalog",
    "get_tool_contract",
    "list_tool_contracts",
    "validate_tool_approval_summary",
    "validate_tool_contract_catalog",
]
