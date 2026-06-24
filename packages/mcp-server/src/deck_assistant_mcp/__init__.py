"""Contract exports for the Decky AI Assistant MCP package."""

from deck_assistant_mcp.contracts import (
    CATALOG_VERSION,
    ContractCatalogError,
    TOOL_CONTRACTS,
    TOOL_CONTRACTS_BY_NAME,
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
from deck_assistant_mcp.dispatcher import (
    ContractCatalogDriftError,
    InProcessToolDispatcher,
    READ_ONLY_SHELL_WARNING,
    ToolDispatchError,
    create_in_process_tool_dispatcher,
)
from deck_assistant_mcp.server import (
    DEFAULT_PROTOCOL_VERSION,
    McpStdioServer,
    SERVER_NAME,
    SERVER_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    build_default_dispatcher,
)

__all__ = [
    "CATALOG_VERSION",
    "ContractCatalogDriftError",
    "ContractCatalogError",
    "DEFAULT_PROTOCOL_VERSION",
    "InProcessToolDispatcher",
    "McpStdioServer",
    "READ_ONLY_SHELL_WARNING",
    "SERVER_NAME",
    "SERVER_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "TOOL_CONTRACTS",
    "TOOL_CONTRACTS_BY_NAME",
    "ToolDispatchError",
    "ToolApprovalMetadata",
    "ToolContract",
    "ToolRisk",
    "build_default_dispatcher",
    "create_in_process_tool_dispatcher",
    "export_tool_approval_summary",
    "export_tool_catalog",
    "get_tool_contract",
    "list_tool_contracts",
    "validate_tool_approval_summary",
    "validate_tool_contract_catalog",
]
