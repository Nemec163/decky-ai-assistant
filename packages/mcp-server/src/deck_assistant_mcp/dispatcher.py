"""In-process MCP tool dispatcher shell with no transport dependency."""

from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from deck_assistant_core.diagnostics import (
    MAX_DIAGNOSTIC_WARNINGS,
    MAX_PROTON_EXCERPT_CHARACTERS,
    DiagnosticStatus,
    DiagnosticsValidationError,
    ProtonLogReport,
    StorageReport,
)
from deck_assistant_core.knowledge import (
    KnowledgeSearchIndex,
    KnowledgeValidationError,
)
from deck_assistant_core.actions import (
    ActionValidationError,
    BackupSpec,
    CommandSpec,
    FileEditSpec,
    RollbackStep,
    StagedAction,
    StagedActionStore,
    StagedActionStoreError,
)
from deck_assistant_core.risk import ApprovalRequirement, RiskLevel

from deck_assistant_mcp.contracts import (
    ToolApprovalMetadata,
    ToolContract,
    ToolRisk,
    export_tool_approval_summary,
    export_tool_catalog,
    validate_tool_contract_catalog,
)


READ_ONLY_SHELL_WARNING = (
    "This in-process dispatcher shell exposes only deterministic read-only placeholders."
)

# All injected tool handlers share the same signature: they take the validated
# tool arguments mapping and return a result the dispatcher re-validates.
ToolHandler = Callable[[Mapping[str, Any]], Any]
StoragePathPlanner = Callable[..., Sequence[Any]]
StorageReportReader = Callable[[Sequence[Any]], Any]
ProtonLogReader = Callable[..., Any]


class ContractCatalogDriftError(RuntimeError):
    """Raised at dispatcher construction when handlers drift from the catalog."""


class _SchemaValidationError(ValueError):
    """Internal error used to produce stable input-validation payloads."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


@dataclass(frozen=True)
class ToolDispatchError:
    """Stable error payload for in-process dispatcher calls."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("dispatch error code must not be empty")
        if not self.message.strip():
            raise ValueError("dispatch error message must not be empty")
        object.__setattr__(self, "details", deepcopy(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": deepcopy(self.details),
        }


class InProcessToolDispatcher:
    """Safe shell around the static MCP contract catalog."""

    def __init__(
        self,
        contracts: Sequence[ToolContract],
        *,
        search_knowledge_handler: ToolHandler | None = None,
        list_sources_handler: ToolHandler | None = None,
        knowledge_search_index: KnowledgeSearchIndex | None = None,
        staged_action_store: StagedActionStore | None = None,
        get_storage_report_handler: ToolHandler | None = None,
        read_proton_logs_handler: ToolHandler | None = None,
        propose_fix_handler: ToolHandler | None = None,
        storage_path_planner: StoragePathPlanner | None = None,
        storage_report_reader: StorageReportReader | None = None,
        proton_log_reader: ProtonLogReader | None = None,
    ) -> None:
        if get_storage_report_handler is not None and (
            storage_path_planner is not None or storage_report_reader is not None
        ):
            raise ValueError(
                "provide either get_storage_report_handler or storage reader dependencies"
            )
        if (storage_path_planner is None) != (storage_report_reader is None):
            raise ValueError(
                "storage_path_planner and storage_report_reader must be provided together"
            )
        if read_proton_logs_handler is not None and proton_log_reader is not None:
            raise ValueError(
                "provide either read_proton_logs_handler or proton_log_reader"
            )
        if search_knowledge_handler is not None and knowledge_search_index is not None:
            raise ValueError(
                "provide either search_knowledge_handler or knowledge_search_index"
            )
        if list_sources_handler is not None and knowledge_search_index is not None:
            raise ValueError(
                "provide either list_sources_handler or knowledge_search_index"
            )

        self._contracts = validate_tool_contract_catalog(contracts)
        self._contracts_by_name = {
            contract.name: contract for contract in self._contracts
        }
        self._search_knowledge_handler = search_knowledge_handler
        self._list_sources_handler = list_sources_handler
        self._knowledge_search_index = knowledge_search_index
        self._staged_action_store = staged_action_store
        self._get_storage_report_handler = get_storage_report_handler
        self._read_proton_logs_handler = read_proton_logs_handler
        self._propose_fix_handler = propose_fix_handler
        self._storage_path_planner = storage_path_planner
        self._storage_report_reader = storage_report_reader
        self._proton_log_reader = proton_log_reader
        self._handlers: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
            "search_knowledge": self._handle_search_knowledge,
            "list_sources": self._handle_list_sources,
            "inspect_current_game": self._handle_inspect_current_game,
            "read_proton_logs": self._handle_read_proton_logs,
            "get_storage_report": self._handle_get_storage_report,
            "propose_fix": self._handle_propose_fix,
            "stage_action": self._handle_stage_action,
        }
        self._assert_handler_catalog_alignment()

    def _assert_handler_catalog_alignment(self) -> None:
        """Convert handler/catalog drift into a load-time failure.

        Every handler must back a real contract, and every non-approval-gated
        contract must have a handler. Approval-gated contracts (e.g.
        ``run_approved_action``) intentionally have no handler so they are
        refused; ``stage_action`` is the one approval-gated tool with a handler
        because it stages without executing.
        """

        unknown_handlers = sorted(
            name for name in self._handlers if name not in self._contracts_by_name
        )
        if unknown_handlers:
            raise ContractCatalogDriftError(
                "dispatcher handlers reference tools absent from the catalog: "
                + ", ".join(unknown_handlers)
            )

        missing_handlers = sorted(
            contract.name
            for contract in self._contracts
            if not contract.requires_approval and contract.name not in self._handlers
        )
        if missing_handlers:
            raise ContractCatalogDriftError(
                "non-approval-gated contracts lack a dispatcher handler: "
                + ", ".join(missing_handlers)
            )

    def list_tool_contracts(self) -> tuple[ToolContract, ...]:
        """Return contracts in deterministic order."""

        return self._contracts

    def export_catalog(self) -> dict[str, Any]:
        """Return a detached tool catalog export."""

        return export_tool_catalog(self._contracts)

    def export_approval_summary(self) -> dict[str, Any]:
        """Return detached approval metadata for all tools."""

        return export_tool_approval_summary(self._contracts)

    def get_tool_approval_metadata(self, tool_name: str) -> dict[str, Any]:
        """Return detached approval metadata for a single tool."""

        contract = self._contracts_by_name.get(tool_name)
        if contract is None:
            raise KeyError(tool_name)
        return ToolApprovalMetadata.from_contract(contract).to_dict()

    def dispatch_tool_call(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate and dispatch a tool call without transport or local execution."""

        contract = self._contracts_by_name.get(tool_name)
        if contract is None:
            return self._error_response(
                tool_name,
                ToolDispatchError(
                    code="unknown_tool",
                    message=f"Unknown tool: {tool_name}",
                    details={"requested_tool": tool_name},
                ),
            )

        normalized_arguments: Any = {} if arguments is None else arguments
        try:
            _validate_schema(contract.input_schema, normalized_arguments)
        except _SchemaValidationError as error:
            return self._error_response(
                tool_name,
                ToolDispatchError(
                    code="invalid_input",
                    message=f"Input for {tool_name} failed validation",
                    details={"path": error.path, "reason": error.reason},
                ),
            )

        if contract.requires_approval and not (
            tool_name == "stage_action" and self._staged_action_store is not None
        ):
            return self._error_response(
                tool_name,
                ToolDispatchError(
                    code="tool_refused",
                    message=(
                        f"{tool_name} cannot run in the in-process dispatcher shell "
                        "without Decky approval and executor integration"
                    ),
                    details={
                        "risk": contract.risk.value,
                        "requires_approval": contract.requires_approval,
                        "approval_gate": "decky_approval",
                    },
                ),
            )

        handler = self._handlers.get(tool_name)
        if handler is None:
            return self._error_response(
                tool_name,
                ToolDispatchError(
                    code="tool_unimplemented",
                    message=f"{tool_name} is not implemented in the in-process dispatcher shell",
                    details={"risk": contract.risk.value},
                ),
            )

        try:
            result = handler(normalized_arguments)
            _validate_schema(contract.output_schema, result)
            _validate_output_invariants(tool_name, result)
        except _SchemaValidationError as error:
            return self._error_response(
                tool_name,
                ToolDispatchError(
                    code="invalid_output",
                    message=f"Output for {tool_name} failed validation",
                    details={"path": error.path, "reason": error.reason},
                ),
            )
        except DiagnosticsValidationError as error:
            return self._error_response(
                tool_name,
                ToolDispatchError(
                    code="invalid_output",
                    message=f"Output for {tool_name} failed core diagnostics validation",
                    details={"path": "$", "reason": str(error)},
                ),
            )
        except KnowledgeValidationError as error:
            return self._error_response(
                tool_name,
                ToolDispatchError(
                    code="invalid_output",
                    message=f"Output for {tool_name} failed core knowledge validation",
                    details={"path": "$", "reason": str(error)},
                ),
            )
        except ActionValidationError as error:
            return self._error_response(
                tool_name,
                ToolDispatchError(
                    code="invalid_input",
                    message=f"Input for {tool_name} failed action validation",
                    details={"path": "$.action", "reason": str(error)},
                ),
            )
        except StagedActionStoreError as error:
            return self._error_response(
                tool_name,
                ToolDispatchError(
                    code="staging_failed",
                    message=f"{tool_name} could not update staged action state",
                    details={"reason": str(error)},
                ),
            )

        return {
            "ok": True,
            "tool": tool_name,
            "result": deepcopy(result),
        }

    @staticmethod
    def _error_response(tool_name: str, error: ToolDispatchError) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": tool_name,
            "error": error.to_dict(),
        }

    def _handle_search_knowledge(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if self._search_knowledge_handler is not None:
            return _normalize_knowledge_search_response(
                self._search_knowledge_handler(arguments)
            )

        if self._knowledge_search_index is None:
            return {"results": []}

        return _knowledge_search_results_response(
            self._knowledge_search_index.search(
                arguments["query"],
                limit=int(arguments.get("limit", 5)),
                source_ids=arguments.get("source_ids"),
            )
        )

    def _handle_list_sources(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        include_disabled = bool(arguments.get("include_disabled", True))
        if self._list_sources_handler is not None:
            return _normalize_knowledge_sources_response(
                self._list_sources_handler(arguments),
                include_disabled=include_disabled,
            )

        if self._knowledge_search_index is None:
            return {"sources": []}

        return _knowledge_sources_response(
            self._knowledge_search_index.manifest.sources,
            include_disabled=include_disabled,
        )

    def _handle_inspect_current_game(self, _: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "game": None,
            "detection_method": "dispatcher_shell_unimplemented",
            "warnings": [READ_ONLY_SHELL_WARNING],
        }

    def _handle_read_proton_logs(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if self._read_proton_logs_handler is not None:
            return _normalize_proton_log_report(
                self._read_proton_logs_handler(arguments),
                requested_app_id=arguments.get("app_id"),
            )

        if self._proton_log_reader is not None:
            reader_kwargs: dict[str, Any] = {}
            # The contract input now caps excerpt characters directly (no bytes vs
            # characters conversion); clamp to the core reader's own excerpt limit
            # so the effective behavior matches the bounded reader exactly.
            max_excerpt_characters = arguments.get("max_excerpt_characters")
            if max_excerpt_characters is not None:
                reader_kwargs["max_excerpt_characters"] = min(
                    int(max_excerpt_characters),
                    MAX_PROTON_EXCERPT_CHARACTERS,
                )
            return _normalize_proton_log_report(
                self._proton_log_reader(**reader_kwargs),
                requested_app_id=arguments.get("app_id"),
            )

        return {
            "status": DiagnosticStatus.UNAVAILABLE.value,
            "warnings": [READ_ONLY_SHELL_WARNING],
            "limits": [],
            "logs": [],
        }

    def _handle_get_storage_report(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if self._get_storage_report_handler is not None:
            return _normalize_storage_report(self._get_storage_report_handler(arguments))

        if self._storage_path_planner is not None and self._storage_report_reader is not None:
            planner_kwargs: dict[str, Any] = {}
            if "sections" in arguments:
                planner_kwargs["sections"] = arguments["sections"]
            plan = self._storage_path_planner(**planner_kwargs)
            return _normalize_storage_report(self._storage_report_reader(plan))

        return {
            "status": DiagnosticStatus.UNAVAILABLE.value,
            "warnings": [READ_ONLY_SHELL_WARNING],
            "limits": [],
            "sections": [],
        }

    def _handle_propose_fix(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if self._propose_fix_handler is not None:
            return _normalize_fix_proposal(self._propose_fix_handler(arguments))

        return {
            "proposal": {
                "title": "Manual review required",
                "risk": RiskLevel.READ_ONLY.value,
                "requires_approval": False,
                "approval_gate": _approval_gate_payload(RiskLevel.READ_ONLY),
                "steps": [],
                "commands": [],
                "file_edits": [],
                "backups": [],
                "rollback": [],
            }
        }

    def _handle_stage_action(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if self._staged_action_store is None:
            raise StagedActionStoreError("staged action store is not configured")

        action = _staged_action_from_input(arguments["action"])
        display_plan = action.render_approval_plan()
        metadata = self._staged_action_store.stage_action(action)
        return {
            "staged_action_id": metadata.action_id,
            "risk": metadata.risk.value,
            "requires_approval": True,
            "approval_gate": display_plan["approval_gate"],
            "display_plan": display_plan,
            "staged_at": metadata.staged_at,
            "approved_at": metadata.approved_at,
        }


def create_in_process_tool_dispatcher(
    contracts: Sequence[ToolContract],
    *,
    search_knowledge_handler: ToolHandler | None = None,
    list_sources_handler: ToolHandler | None = None,
    knowledge_search_index: KnowledgeSearchIndex | None = None,
    staged_action_store: StagedActionStore | None = None,
    get_storage_report_handler: ToolHandler | None = None,
    read_proton_logs_handler: ToolHandler | None = None,
    propose_fix_handler: ToolHandler | None = None,
    storage_path_planner: StoragePathPlanner | None = None,
    storage_report_reader: StorageReportReader | None = None,
    proton_log_reader: ProtonLogReader | None = None,
) -> InProcessToolDispatcher:
    """Construct a dispatcher shell for a validated contract catalog."""

    return InProcessToolDispatcher(
        contracts,
        search_knowledge_handler=search_knowledge_handler,
        list_sources_handler=list_sources_handler,
        knowledge_search_index=knowledge_search_index,
        staged_action_store=staged_action_store,
        get_storage_report_handler=get_storage_report_handler,
        read_proton_logs_handler=read_proton_logs_handler,
        propose_fix_handler=propose_fix_handler,
        storage_path_planner=storage_path_planner,
        storage_report_reader=storage_report_reader,
        proton_log_reader=proton_log_reader,
    )


def _staged_action_from_input(action_data: Any) -> StagedAction:
    data = _to_output_mapping(action_data, "staged action")
    return StagedAction.create(
        title=_required_output_value(data, "title", "staged action"),
        risk=RiskLevel(_required_output_value(data, "risk", "staged action")),
        commands=tuple(
            CommandSpec.from_dict(_to_output_mapping(command, "staged action command"))
            for command in data.get("commands", ())
        ),
        file_edits=tuple(
            FileEditSpec.from_dict(_to_output_mapping(file_edit, "staged action file edit"))
            for file_edit in data.get("file_edits", ())
        ),
        backups=tuple(
            BackupSpec.from_dict(_to_output_mapping(backup, "staged action backup"))
            for backup in data.get("backups", ())
        ),
        backup_note=data.get("backup_note"),
        rollback=tuple(
            RollbackStep.from_dict(_to_output_mapping(step, "staged action rollback"))
            for step in data.get("rollback", ())
        ),
        rollback_note=data.get("rollback_note"),
    )


def _normalize_knowledge_search_response(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        data = _to_output_mapping(value, "knowledge search")
        if "results" not in data:
            raise _SchemaValidationError("$", "missing required property results")
        return _knowledge_search_results_response(data["results"])

    return _knowledge_search_results_response(value)


def _knowledge_search_results_response(results: Any) -> dict[str, Any]:
    return {
        "results": [
            _knowledge_search_result_payload(result)
            for result in _output_sequence(results, "knowledge search results")
        ]
    }


def _knowledge_search_result_payload(result: Any) -> dict[str, Any]:
    data = _to_output_mapping(result, "knowledge search result")
    payload: dict[str, Any] = {
        "chunk_id": _required_output_value(data, "chunk_id", "knowledge search result"),
        "text": _required_output_value(data, "text", "knowledge search result"),
        "citation": _knowledge_citation_payload(
            _required_output_value(data, "citation", "knowledge search result")
        ),
    }
    if "score" in data:
        payload["score"] = data["score"]
    return payload


def _knowledge_citation_payload(citation: Any) -> dict[str, Any]:
    data = _to_output_mapping(citation, "knowledge citation")
    payload: dict[str, Any] = {
        "source_id": _required_output_value(data, "source_id", "knowledge citation"),
        "title": _required_output_any(
            data,
            ("title", "source_title"),
            "knowledge citation",
        ),
        "url": data.get("url", data.get("source_uri")),
        "license": _knowledge_license_text(
            _required_output_value(data, "license", "knowledge citation")
        ),
        "revision": _knowledge_revision_text(
            _required_output_value(data, "revision", "knowledge citation")
        ),
        "path": data.get("path", data.get("document_path")),
    }
    for source_name, output_name in (
        ("source_type", "source_type"),
        ("document_id", "document_id"),
        ("document_title", "document_title"),
        ("chunk_id", "chunk_id"),
        ("start_line", "start_line"),
        ("end_line", "end_line"),
    ):
        if source_name in data:
            payload[output_name] = data[source_name]
    if "headings" in data:
        headings = data["headings"]
        payload["headings"] = (
            list(headings)
            if isinstance(headings, Sequence)
            and not isinstance(headings, (str, bytes, bytearray))
            else headings
        )
    return payload


def _normalize_knowledge_sources_response(
    value: Any,
    *,
    include_disabled: bool,
) -> dict[str, Any]:
    if isinstance(value, Mapping):
        data = _to_output_mapping(value, "knowledge sources")
        if "sources" not in data:
            raise _SchemaValidationError("$", "missing required property sources")
        sources = data["sources"]
    else:
        sources = value

    return _knowledge_sources_response(sources, include_disabled=include_disabled)


def _knowledge_sources_response(
    sources: Any,
    *,
    include_disabled: bool,
) -> dict[str, Any]:
    normalized_sources = [
        _knowledge_source_payload(source)
        for source in _output_sequence(sources, "knowledge sources")
    ]
    if not include_disabled:
        normalized_sources = [source for source in normalized_sources if source["enabled"]]
    return {"sources": normalized_sources}


def _knowledge_source_payload(source: Any) -> dict[str, Any]:
    data = _to_output_mapping(source, "knowledge source")
    payload: dict[str, Any] = {
        "source_id": _required_output_any(
            data,
            ("source_id", "id"),
            "knowledge source",
        ),
        "name": _required_output_any(data, ("name", "title"), "knowledge source"),
        "kind": _required_output_any(data, ("kind", "type"), "knowledge source"),
        "enabled": data["enabled"] if "enabled" in data else True,
        "license": _knowledge_license_text(
            _required_output_value(data, "license", "knowledge source")
        ),
        "url": data.get("url", data.get("uri")),
    }
    if "revision" in data:
        payload["revision"] = _knowledge_revision_text(data["revision"])
    return payload


def _knowledge_license_text(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _required_output_value(value, "name", "knowledge license")
    return value


def _knowledge_revision_text(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _required_output_value(value, "value", "knowledge revision")
    return value


def _normalize_storage_report(value: Any) -> dict[str, Any]:
    return _coerce_core_report(
        StorageReport,
        _to_output_mapping(value, "storage report"),
    )


def _normalize_proton_log_report(
    value: Any,
    *,
    requested_app_id: Any,
) -> dict[str, Any]:
    report = _coerce_core_report(
        ProtonLogReport,
        _to_output_mapping(value, "proton log report"),
    )
    if requested_app_id is None:
        return report

    app_id = int(requested_app_id)
    logs = [log for log in report["logs"] if log["app_id"] == app_id]
    if len(logs) == len(report["logs"]):
        return report

    warnings = list(report["warnings"])
    if not logs and len(warnings) < MAX_DIAGNOSTIC_WARNINGS:
        warnings.append("No Proton logs matched the requested Steam app id.")

    filtered = {
        **report,
        "status": DiagnosticStatus.UNAVAILABLE.value if not logs else report["status"],
        "warnings": warnings,
        "logs": logs,
    }
    return ProtonLogReport.from_dict(filtered).to_dict()


def _normalize_fix_proposal(value: Any) -> dict[str, Any]:
    proposal = _to_output_mapping(value, "fix proposal")
    if "proposal" in proposal:
        return proposal
    return {"proposal": proposal}


def _to_output_mapping(value: Any, output_name: str) -> Mapping[str, Any]:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        raise _SchemaValidationError("$", f"{output_name} output must be an object")
    return deepcopy(value)


def _output_sequence(value: Any, output_name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _SchemaValidationError("$", f"{output_name} output must be an array")
    return value


def _required_output_value(
    data: Mapping[str, Any],
    name: str,
    output_name: str,
) -> Any:
    if name not in data:
        raise _SchemaValidationError("$", f"{output_name} missing required property {name}")
    return data[name]


def _required_output_any(
    data: Mapping[str, Any],
    names: Sequence[str],
    output_name: str,
) -> Any:
    for name in names:
        if name in data:
            return data[name]
    raise _SchemaValidationError(
        "$",
        f"{output_name} missing required property {names[0]}",
    )


def _coerce_core_report(report_type: Any, data: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return report_type.from_dict(data).to_dict()
    except KeyError as error:
        missing_property = str(error.args[0]) if error.args else "unknown"
        raise _SchemaValidationError(
            "$",
            f"missing required property {missing_property}",
        ) from error
    except TypeError as error:
        raise _SchemaValidationError("$", str(error)) from error


def _validate_output_invariants(tool_name: str, result: Mapping[str, Any]) -> None:
    if tool_name == "search_knowledge":
        _validate_knowledge_search_invariants(result)
    if tool_name == "propose_fix":
        _validate_fix_proposal_invariants(result)


def _validate_knowledge_search_invariants(result: Mapping[str, Any]) -> None:
    for index, search_result in enumerate(result["results"]):
        citation = search_result["citation"]
        citation_chunk_id = citation.get("chunk_id")
        result_chunk_id = search_result["chunk_id"]
        if citation_chunk_id is not None and citation_chunk_id != result_chunk_id:
            raise _SchemaValidationError(
                f"$.results[{index}].citation.chunk_id",
                f"expected to match result chunk_id {result_chunk_id!r}",
            )

        start_line = citation.get("start_line")
        end_line = citation.get("end_line")
        if start_line is not None and end_line is not None and end_line < start_line:
            raise _SchemaValidationError(
                f"$.results[{index}].citation.end_line",
                "expected end_line >= start_line",
            )


def _validate_fix_proposal_invariants(result: Mapping[str, Any]) -> None:
    proposal = result["proposal"]
    risk = RiskLevel(proposal["risk"])
    expected_gate = _approval_gate_payload(risk)
    expected_requires_approval = risk is not RiskLevel.READ_ONLY

    if proposal["requires_approval"] != expected_requires_approval:
        raise _SchemaValidationError(
            "$.proposal.requires_approval",
            f"expected {expected_requires_approval} for risk {risk.value}",
        )

    gate = proposal["approval_gate"]
    for field_name, expected_value in expected_gate.items():
        if field_name == "summary":
            continue
        if gate[field_name] != expected_value:
            raise _SchemaValidationError(
                f"$.proposal.approval_gate.{field_name}",
                f"expected {expected_value!r} for risk {risk.value}",
            )


def _approval_gate_payload(risk: RiskLevel) -> dict[str, Any]:
    requirement = ApprovalRequirement.for_risk(risk)
    gate_type = "approval_required"
    if risk is RiskLevel.READ_ONLY:
        gate_type = "user_request"
    elif risk is RiskLevel.DANGER:
        gate_type = "separate_confirmation_required"

    return {
        "type": gate_type,
        "summary": _approval_gate_summary(risk),
        "requires_plan": requirement.requires_plan,
        "requires_exact_commands_or_diffs": requirement.requires_exact_commands_or_diffs,
        "requires_backup_or_note": requirement.requires_backup_or_note,
        "requires_separate_confirmation": requirement.requires_separate_confirmation,
        "may_execute_after_user_request": requirement.may_execute_after_user_request,
    }


def _approval_gate_summary(risk: RiskLevel) -> str:
    if risk is RiskLevel.READ_ONLY:
        return "Read-only response only; no Decky approval is required."
    if risk is RiskLevel.DANGER:
        return "Dangerous actions require separate explicit confirmation in Decky."
    return "Decky approval is required before local execution."


def _validate_schema(schema: Mapping[str, Any], value: Any, path: str = "$") -> None:
    schema_type = schema.get("type")
    if schema_type is not None:
        allowed_types = (
            tuple(schema_type) if isinstance(schema_type, list) else (schema_type,)
        )
        if not any(_matches_type(type_name, value) for type_name in allowed_types):
            expected = " or ".join(str(type_name) for type_name in allowed_types)
            raise _SchemaValidationError(path, f"expected {expected}")

        active_type = _select_type(allowed_types, value)
        if active_type == "object":
            _validate_object_value(schema, value, path)
        elif active_type == "array":
            _validate_array_schema(schema, value, path)
        elif active_type == "string":
            _validate_string_schema(schema, value, path)
        elif active_type == "integer":
            _validate_integer_schema(schema, value, path)
        elif active_type == "number":
            _validate_number_schema(schema, value, path)
        elif active_type == "boolean":
            _validate_boolean_schema(value, path)
        elif active_type == "null":
            _validate_null_schema(value, path)
    elif "properties" in schema or "required" in schema:
        _validate_object_value(schema, value, path)

    if "const" in schema and value != schema["const"]:
        raise _SchemaValidationError(path, f"expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise _SchemaValidationError(path, "value is not in enum")

    _validate_any_of_required(schema, value, path)


def _validate_any_of_required(schema: Mapping[str, Any], value: Any, path: str) -> None:
    """Enforce the catalog's only ``anyOf`` use: at least one branch's required keys are present.

    The base schema (type, properties, per-property constraints) is already
    validated by the caller, so each branch only contributes additional
    required-key presence checks. We do not re-validate the whole object per
    branch; we just require that some branch's required keys all appear.
    """

    branches = schema.get("anyOf")
    if branches is None:
        return
    if not isinstance(value, Mapping):
        # anyOf required-key checks only apply to objects; non-objects are
        # already rejected by the base type validation above.
        return

    required_groups: list[list[str]] = []
    for branch in branches:
        required_keys = list(branch.get("required", []))
        if all(key in value for key in required_keys):
            return
        required_groups.append(required_keys)

    options = " or ".join(
        "+".join(group) if group else "(none)" for group in required_groups
    )
    raise _SchemaValidationError(path, f"must include one of: {options}")


def _matches_type(type_name: str, value: Any) -> bool:
    if type_name == "object":
        return isinstance(value, Mapping)
    if type_name == "array":
        return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "null":
        return value is None
    return True


def _select_type(type_names: Sequence[str], value: Any) -> str | None:
    for type_name in type_names:
        if _matches_type(type_name, value):
            return type_name
    return None


def _validate_object_value(schema: Mapping[str, Any], value: Any, path: str) -> None:
    if not isinstance(value, Mapping):
        raise _SchemaValidationError(path, "expected object")

    properties = schema.get("properties", {})
    required = schema.get("required", [])
    for name in required:
        if name not in value:
            raise _SchemaValidationError(path, f"missing required property {name}")

    if schema.get("additionalProperties") is False:
        allowed = set(properties)
        for name in value:
            if name not in allowed:
                raise _SchemaValidationError(f"{path}.{name}", "unexpected property")

    for name, property_schema in properties.items():
        if name in value:
            _validate_schema(property_schema, value[name], f"{path}.{name}")


def _validate_array_schema(schema: Mapping[str, Any], value: Any, path: str) -> None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _SchemaValidationError(path, "expected array")

    if "minItems" in schema and len(value) < schema["minItems"]:
        raise _SchemaValidationError(path, f"expected at least {schema['minItems']} items")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        raise _SchemaValidationError(path, f"expected at most {schema['maxItems']} items")

    item_schema = schema.get("items")
    if item_schema is None:
        return
    for index, item in enumerate(value):
        _validate_schema(item_schema, item, f"{path}[{index}]")


def _validate_string_schema(schema: Mapping[str, Any], value: Any, path: str) -> None:
    if not isinstance(value, str):
        raise _SchemaValidationError(path, "expected string")

    if "minLength" in schema and len(value) < schema["minLength"]:
        raise _SchemaValidationError(path, f"expected minLength {schema['minLength']}")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        raise _SchemaValidationError(path, f"expected maxLength {schema['maxLength']}")

    pattern = schema.get("pattern")
    if pattern is not None and re.match(pattern, value) is None:
        raise _SchemaValidationError(path, f"value does not match pattern {pattern}")


def _validate_integer_schema(schema: Mapping[str, Any], value: Any, path: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _SchemaValidationError(path, "expected integer")
    if "minimum" in schema and value < schema["minimum"]:
        raise _SchemaValidationError(path, f"expected minimum {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        raise _SchemaValidationError(path, f"expected maximum {schema['maximum']}")


def _validate_number_schema(schema: Mapping[str, Any], value: Any, path: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise _SchemaValidationError(path, "expected number")
    if not math.isfinite(value):
        raise _SchemaValidationError(path, "expected finite number")
    if "minimum" in schema and value < schema["minimum"]:
        raise _SchemaValidationError(path, f"expected minimum {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        raise _SchemaValidationError(path, f"expected maximum {schema['maximum']}")


def _validate_boolean_schema(value: Any, path: str) -> None:
    if not isinstance(value, bool):
        raise _SchemaValidationError(path, "expected boolean")


def _validate_null_schema(value: Any, path: str) -> None:
    if value is not None:
        raise _SchemaValidationError(path, "expected null")


__all__ = [
    "ContractCatalogDriftError",
    "InProcessToolDispatcher",
    "READ_ONLY_SHELL_WARNING",
    "ToolDispatchError",
    "create_in_process_tool_dispatcher",
]
