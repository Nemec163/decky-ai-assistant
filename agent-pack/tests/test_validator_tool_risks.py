"""Cross-check the agent-pack validator's tool/risk table against the real contracts.

The validator in ``agent-pack/scripts/validate_agent_pack.py`` hardcodes
``MCP_TOOL_RISKS`` so it can run on the stdlib alone without importing the MCP
server. That table can silently drift from the authoritative ``TOOL_CONTRACTS``
catalog in ``deck_assistant_mcp``. This test imports both and asserts they agree.

Run via CI / final verification, e.g.::

    PYTHONPATH=packages/core/src:packages/mcp-server/src \
        python3 -m unittest discover -s agent-pack/tests
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPO_ROOT / "agent-pack" / "scripts" / "validate_agent_pack.py"

# Ensure the bundled Python source packages are importable without installation.
for src in (
    REPO_ROOT / "packages" / "core" / "src",
    REPO_ROOT / "packages" / "mcp-server" / "src",
):
    src_str = str(src)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_agent_pack", VALIDATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ValidatorToolRiskAgreementTest(unittest.TestCase):
    def test_validator_table_matches_tool_contracts(self) -> None:
        validator = _load_validator()
        from deck_assistant_mcp import TOOL_CONTRACTS

        validator_table = dict(validator.MCP_TOOL_RISKS)
        contract_table = {
            contract.name: contract.risk.value
            for contract in TOOL_CONTRACTS
        }

        self.assertEqual(
            set(validator_table),
            set(contract_table),
            "validator MCP_TOOL_RISKS tool names diverge from TOOL_CONTRACTS",
        )
        self.assertEqual(
            validator_table,
            contract_table,
            "validator MCP_TOOL_RISKS risk levels diverge from TOOL_CONTRACTS",
        )

    def test_validator_risks_are_canonical(self) -> None:
        validator = _load_validator()
        for tool, risk in validator.MCP_TOOL_RISKS.items():
            self.assertIn(
                risk,
                validator.VALID_RISKS,
                f"{tool} uses non-canonical risk {risk!r}",
            )


if __name__ == "__main__":
    unittest.main()
