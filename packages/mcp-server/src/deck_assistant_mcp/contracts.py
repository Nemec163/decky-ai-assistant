"""Static MCP tool contracts.

This package intentionally stops at contract description. It has no MCP
transport dependency, no server loop, and no local action execution entrypoint.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

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


class ContractCatalogError(ValueError):
    """Raised when static MCP contract catalog invariants are violated."""


@dataclass(frozen=True)
class ToolContract:
    """Stable JSON-like contract for an MCP tool."""

    name: str
    risk: ToolRisk
    purpose: str
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
    def core_risk_level(self) -> RiskLevel:
        """Return the core risk level for this tool."""

        return RiskLevel(self.risk.value)

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-serializable representation."""

        return {
            "name": self.name,
            "risk": self.risk.value,
            "purpose": self.purpose,
            "input_schema": deepcopy(self.input_schema),
            "output_schema": deepcopy(self.output_schema),
        }


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
CATALOG_VERSION = 5
# Local cap on knowledge search results. deck_assistant_core exposes no
# equivalent MAX_* constant, so this stays module-local; revisit if core adds one.
_MAX_KNOWLEDGE_SEARCH_RESULTS = 20


def validate_tool_contract_catalog(
    contracts: Sequence[ToolContract],
) -> tuple[ToolContract, ...]:
    """Validate and freeze a tool catalog in stable order."""

    catalog = tuple(contracts)
    _validate_unique_tool_names(catalog)
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


TOOL_CONTRACTS = validate_tool_contract_catalog(
    (
        ToolContract(
            name="search_knowledge",
            risk=ToolRisk.READ_ONLY,
            purpose="Search enabled local knowledge packs and return cited chunks.",
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
                                "kind": {
                                    "type": "string",
                                    "enum": _enum_values(SourceType),
                                },
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
            input_schema=_object_schema(
                properties={
                    "app_id": {
                        "type": ["integer", "null"],
                        "description": (
                            "Optional Steam app id when the caller already knows it."
                        ),
                    },
                    "include_processes": {
                        "type": "boolean",
                        "default": False,
                    },
                },
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
            input_schema=_object_schema(
                properties={
                    "app_id": {
                        "type": ["integer", "null"],
                        "description": (
                            "Optional Steam app id; current app may be used when omitted."
                        ),
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
                },
            ),
            output_schema=_proton_log_report_schema(),
        ),
        ToolContract(
            name="get_storage_report",
            risk=ToolRisk.READ_ONLY,
            purpose="Report Deck storage usage for caches, compatdata, logs, and media.",
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
            purpose="Convert diagnostics into a concise fix plan and risk classification.",
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
                            "steps": _string_array_schema(),
                            "commands": {
                                "type": "array",
                                "items": _command_spec_schema(),
                            },
                            "file_edits": {
                                "type": "array",
                                "items": _file_edit_spec_schema(),
                            },
                        },
                        required=(
                            "title",
                            "risk",
                            "steps",
                            "commands",
                            "file_edits",
                        ),
                    )
                },
                required=("proposal",),
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
    "ToolContract",
    "ToolRisk",
    "export_tool_catalog",
    "get_tool_contract",
    "list_tool_contracts",
    "validate_tool_contract_catalog",
]
