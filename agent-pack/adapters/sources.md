# Adapter Source Notes

Verified on 2026-06-21.

## Codex

- Official source: https://developers.openai.com/codex/mcp
- MCP servers are configured in `~/.codex/config.toml` or trusted project `.codex/config.toml`.
- Stdio servers use `[mcp_servers.<name>]` with `command`, optional `args`, optional `env`, and tool approval options.
- `codex mcp` can add and manage servers.

## Claude Code

- Official source: https://code.claude.com/docs/en/mcp
- Project-scoped servers use `.mcp.json`.
- Local stdio servers use `type: "stdio"`, `command`, optional `args`, and optional `env`.
- Project-scoped MCP servers require approval before use.
