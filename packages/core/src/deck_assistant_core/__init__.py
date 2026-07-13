"""Shared domain contracts for Decky AI Assistant.

Exports stay stable, but modules load lazily so consumers can use one contract
surface without importing unrelated subsystems.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "apply_cli_permission_bypass": (
        "deck_assistant_core.cli",
        "apply_cli_permission_bypass",
    ),
    "CliAuthResult": ("deck_assistant_core.cli", "CliAuthResult"),
    "CliAuthState": ("deck_assistant_core.cli", "CliAuthState"),
    "CliDetectionResult": ("deck_assistant_core.cli", "CliDetectionResult"),
    "CliLaunchPlan": ("deck_assistant_core.cli", "CliLaunchPlan"),
    "CliLaunchStatus": ("deck_assistant_core.cli", "CliLaunchStatus"),
    "CliProfileHealth": ("deck_assistant_core.cli", "CliProfileHealth"),
    "CliProfileHealthStatus": ("deck_assistant_core.cli", "CliProfileHealthStatus"),
    "CliPermissionBypassPlan": ("deck_assistant_core.cli", "CliPermissionBypassPlan"),
    "CliPermissionBypassStatus": ("deck_assistant_core.cli", "CliPermissionBypassStatus"),
    "CliProbeStatus": ("deck_assistant_core.cli", "CliProbeStatus"),
    "CliProfile": ("deck_assistant_core.cli", "CliProfile"),
    "CliProfileError": ("deck_assistant_core.cli", "CliProfileError"),
    "CliSetupAction": ("deck_assistant_core.cli", "CliSetupAction"),
    "CliSetupPlan": ("deck_assistant_core.cli", "CliSetupPlan"),
    "CliSetupStatus": ("deck_assistant_core.cli", "CliSetupStatus"),
    "ContentHash": ("deck_assistant_core.knowledge", "ContentHash"),
    "DiagnosticLimit": ("deck_assistant_core.diagnostics", "DiagnosticLimit"),
    "DiagnosticLimitUnit": ("deck_assistant_core.diagnostics", "DiagnosticLimitUnit"),
    "DiagnosticStatus": ("deck_assistant_core.diagnostics", "DiagnosticStatus"),
    "DiagnosticsValidationError": (
        "deck_assistant_core.diagnostics",
        "DiagnosticsValidationError",
    ),
    "DEFAULT_KNOWLEDGE_SOURCE_FILTER_POLICY": (
        "deck_assistant_core.knowledge",
        "DEFAULT_KNOWLEDGE_SOURCE_FILTER_POLICY",
    ),
    "DEFAULT_KNOWLEDGE_SOURCE_MAX_FILE_BYTES": (
        "deck_assistant_core.knowledge",
        "DEFAULT_KNOWLEDGE_SOURCE_MAX_FILE_BYTES",
    ),
    "KNOWN_CLI_PROFILES": ("deck_assistant_core.cli", "KNOWN_CLI_PROFILES"),
    "KNOWLEDGE_PACK_SCHEMA_VERSION": (
        "deck_assistant_core.knowledge",
        "KNOWLEDGE_PACK_SCHEMA_VERSION",
    ),
    "KNOWLEDGE_SQLITE_INDEX_SCHEMA_VERSION": (
        "deck_assistant_core.knowledge",
        "KNOWLEDGE_SQLITE_INDEX_SCHEMA_VERSION",
    ),
    "KnowledgeChunk": ("deck_assistant_core.knowledge", "KnowledgeChunk"),
    "KnowledgeCitation": ("deck_assistant_core.knowledge", "KnowledgeCitation"),
    "KnowledgeDocument": ("deck_assistant_core.knowledge", "KnowledgeDocument"),
    "KnowledgePackManifest": ("deck_assistant_core.knowledge", "KnowledgePackManifest"),
    "KnowledgePackManifestBuildResult": (
        "deck_assistant_core.knowledge",
        "KnowledgePackManifestBuildResult",
    ),
    "KnowledgeSearchIndex": ("deck_assistant_core.knowledge", "KnowledgeSearchIndex"),
    "KnowledgeSearchResult": ("deck_assistant_core.knowledge", "KnowledgeSearchResult"),
    "KnowledgeSourceFilterDecision": (
        "deck_assistant_core.knowledge",
        "KnowledgeSourceFilterDecision",
    ),
    "KnowledgeSourceFilterPolicy": (
        "deck_assistant_core.knowledge",
        "KnowledgeSourceFilterPolicy",
    ),
    "KnowledgeSourceFilterReason": (
        "deck_assistant_core.knowledge",
        "KnowledgeSourceFilterReason",
    ),
    "KnowledgeSourceFilterResult": (
        "deck_assistant_core.knowledge",
        "KnowledgeSourceFilterResult",
    ),
    "KnowledgeSourceFormat": ("deck_assistant_core.knowledge", "KnowledgeSourceFormat"),
    "KnowledgeSourceInventory": (
        "deck_assistant_core.knowledge",
        "KnowledgeSourceInventory",
    ),
    "KnowledgeSourceInventoryLimits": (
        "deck_assistant_core.knowledge",
        "KnowledgeSourceInventoryLimits",
    ),
    "KnowledgeSourceMatchKind": ("deck_assistant_core.knowledge", "KnowledgeSourceMatchKind"),
    "KnowledgeSourceNotFound": (
        "deck_assistant_core.knowledge",
        "KnowledgeSourceNotFound",
    ),
    "KnowledgeSourceRecord": (
        "deck_assistant_core.knowledge",
        "KnowledgeSourceRecord",
    ),
    "KnowledgeSourceRegistry": (
        "deck_assistant_core.knowledge",
        "KnowledgeSourceRegistry",
    ),
    "KnowledgeSourceRegistryError": (
        "deck_assistant_core.knowledge",
        "KnowledgeSourceRegistryError",
    ),
    "KnowledgeValidationError": ("deck_assistant_core.knowledge", "KnowledgeValidationError"),
    "MAX_DIAGNOSTIC_LIMITS": ("deck_assistant_core.diagnostics", "MAX_DIAGNOSTIC_LIMITS"),
    "MAX_DIAGNOSTIC_WARNINGS": ("deck_assistant_core.diagnostics", "MAX_DIAGNOSTIC_WARNINGS"),
    "MAX_PROTON_EXCERPT_CHARACTERS": (
        "deck_assistant_core.diagnostics",
        "MAX_PROTON_EXCERPT_CHARACTERS",
    ),
    "MAX_PROTON_LOG_REFERENCES": (
        "deck_assistant_core.diagnostics",
        "MAX_PROTON_LOG_REFERENCES",
    ),
    "MAX_STORAGE_PATH_PLAN_DEPTH": (
        "deck_assistant_core.diagnostics",
        "MAX_STORAGE_PATH_PLAN_DEPTH",
    ),
    "MAX_STORAGE_PATH_PLAN_ENTRIES": (
        "deck_assistant_core.diagnostics",
        "MAX_STORAGE_PATH_PLAN_ENTRIES",
    ),
    "MAX_STORAGE_PATH_PLAN_LIBRARY_ROOTS": (
        "deck_assistant_core.diagnostics",
        "MAX_STORAGE_PATH_PLAN_LIBRARY_ROOTS",
    ),
    "MAX_STORAGE_REPORT_SECTIONS": (
        "deck_assistant_core.diagnostics",
        "MAX_STORAGE_REPORT_SECTIONS",
    ),
    "MAX_STORAGE_SECTION_ITEMS": (
        "deck_assistant_core.diagnostics",
        "MAX_STORAGE_SECTION_ITEMS",
    ),
    "NativeAgentPackError": ("deck_assistant_core.agent_pack", "NativeAgentPackError"),
    "NativeAgentPackInstallPlan": (
        "deck_assistant_core.agent_pack",
        "NativeAgentPackInstallPlan",
    ),
    "NativeAgentPackInstallResult": (
        "deck_assistant_core.agent_pack",
        "NativeAgentPackInstallResult",
    ),
    "NativeAgentPackStatus": ("deck_assistant_core.agent_pack", "NativeAgentPackStatus"),
    "ProbeResult": ("deck_assistant_core.cli", "ProbeResult"),
    "ProtonLogExcerpt": ("deck_assistant_core.diagnostics", "ProtonLogExcerpt"),
    "ProtonLogReference": ("deck_assistant_core.diagnostics", "ProtonLogReference"),
    "ProtonLogReport": ("deck_assistant_core.diagnostics", "ProtonLogReport"),
    "PtySessionError": ("deck_assistant_core.pty_session", "PtySessionError"),
    "PtySessionManager": ("deck_assistant_core.pty_session", "PtySessionManager"),
    "PtySessionNotFound": ("deck_assistant_core.pty_session", "PtySessionNotFound"),
    "PtySessionSnapshot": ("deck_assistant_core.pty_session", "PtySessionSnapshot"),
    "RiskLevel": ("deck_assistant_core.risk", "RiskLevel"),
    "SourceLicense": ("deck_assistant_core.knowledge", "SourceLicense"),
    "SourceMetadata": ("deck_assistant_core.knowledge", "SourceMetadata"),
    "SourceRevision": ("deck_assistant_core.knowledge", "SourceRevision"),
    "SourceType": ("deck_assistant_core.knowledge", "SourceType"),
    "SQLiteKnowledgeSearchIndex": (
        "deck_assistant_core.knowledge",
        "SQLiteKnowledgeSearchIndex",
    ),
    "StoragePathPlanEntry": ("deck_assistant_core.diagnostics", "StoragePathPlanEntry"),
    "StorageReport": ("deck_assistant_core.diagnostics", "StorageReport"),
    "StorageReportItem": ("deck_assistant_core.diagnostics", "StorageReportItem"),
    "StorageReportSection": ("deck_assistant_core.diagnostics", "StorageReportSection"),
    "StorageSectionName": ("deck_assistant_core.diagnostics", "StorageSectionName"),
    "check_cli_auth": ("deck_assistant_core.cli", "check_cli_auth"),
    "build_cli_probe_env": ("deck_assistant_core.cli", "build_cli_probe_env"),
    "build_knowledge_search_index": (
        "deck_assistant_core.knowledge",
        "build_knowledge_search_index",
    ),
    "build_sqlite_knowledge_search_index": (
        "deck_assistant_core.knowledge",
        "build_sqlite_knowledge_search_index",
    ),
    "build_knowledge_pack_manifest": (
        "deck_assistant_core.knowledge",
        "build_knowledge_pack_manifest",
    ),
    "build_local_folder_knowledge_pack_manifest": (
        "deck_assistant_core.knowledge",
        "build_local_folder_knowledge_pack_manifest",
    ),
    "classify_command": ("deck_assistant_core.risk", "classify_command"),
    "classify_file_edit": ("deck_assistant_core.risk", "classify_file_edit"),
    "chunk_document": ("deck_assistant_core.knowledge", "chunk_document"),
    "build_knowledge_source_inventory": (
        "deck_assistant_core.knowledge",
        "build_knowledge_source_inventory",
    ),
    "collect_local_folder_knowledge_source_inventory": (
        "deck_assistant_core.knowledge",
        "collect_local_folder_knowledge_source_inventory",
    ),
    "detect_cli": ("deck_assistant_core.cli", "detect_cli"),
    "filter_knowledge_source_document": (
        "deck_assistant_core.knowledge",
        "filter_knowledge_source_document",
    ),
    "get_cli_profile": ("deck_assistant_core.cli", "get_cli_profile"),
    "list_cli_profiles": ("deck_assistant_core.cli", "list_cli_profiles"),
    "managed_cli_bin_dirs": ("deck_assistant_core.cli", "managed_cli_bin_dirs"),
    "managed_cli_cache_home": ("deck_assistant_core.cli", "managed_cli_cache_home"),
    "managed_cli_config_home": ("deck_assistant_core.cli", "managed_cli_config_home"),
    "managed_cli_data_dir": ("deck_assistant_core.cli", "managed_cli_data_dir"),
    "managed_cli_node_bin_dirs": ("deck_assistant_core.cli", "managed_cli_node_bin_dirs"),
    "managed_cli_npm_bin_dir": ("deck_assistant_core.cli", "managed_cli_npm_bin_dir"),
    "managed_cli_npm_prefix": ("deck_assistant_core.cli", "managed_cli_npm_prefix"),
    "managed_cli_user_home": ("deck_assistant_core.cli", "managed_cli_user_home"),
    "max_risk": ("deck_assistant_core.risk", "max_risk"),
    "normalize_source_document_path": (
        "deck_assistant_core.knowledge",
        "normalize_source_document_path",
    ),
    "should_include_knowledge_source_document": (
        "deck_assistant_core.knowledge",
        "should_include_knowledge_source_document",
    ),
    "plan_cli_launch": ("deck_assistant_core.cli", "plan_cli_launch"),
    "plan_cli_setup_action": ("deck_assistant_core.cli", "plan_cli_setup_action"),
    "plan_cli_permission_bypass": (
        "deck_assistant_core.cli",
        "plan_cli_permission_bypass",
    ),
    "plan_native_agent_pack_install": (
        "deck_assistant_core.agent_pack",
        "plan_native_agent_pack_install",
    ),
    "plan_storage_report_paths": (
        "deck_assistant_core.diagnostics",
        "plan_storage_report_paths",
    ),
    "read_proton_logs": ("deck_assistant_core.diagnostics", "read_proton_logs"),
    "read_storage_report": ("deck_assistant_core.diagnostics", "read_storage_report"),
    "resolve_executable": ("deck_assistant_core.cli", "resolve_executable"),
    "install_native_agent_pack": (
        "deck_assistant_core.agent_pack",
        "install_native_agent_pack",
    ),
    "is_bypass_enabled": (
        "deck_assistant_core.profile_permissions",
        "is_bypass_enabled",
    ),
    "normalize_profile_name": (
        "deck_assistant_core.profile_permissions",
        "normalize_profile_name",
    ),
    "parse_profile_permissions": (
        "deck_assistant_core.profile_permissions",
        "parse_profile_permissions",
    ),
    "serialize_profile_permissions": (
        "deck_assistant_core.profile_permissions",
        "serialize_profile_permissions",
    ),
    "list_native_agent_pack_targets": (
        "deck_assistant_core.agent_pack",
        "list_native_agent_pack_targets",
    ),
    "summarize_cli_profile_health": (
        "deck_assistant_core.cli",
        "summarize_cli_profile_health",
    ),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
