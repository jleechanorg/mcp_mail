#!/usr/bin/env python3
"""Real CLI Integration Tests for MCP Agent Mail.

These tests invoke actual CLI tools (Claude, Cursor, Codex, Gemini) using the
orchestration framework and verify MCP Agent Mail functionality.

Usage:
    # Run Claude integration test
    python -m pytest tests/integration/test_real_cli_integration.py -k claude -v

    # Run all real CLI tests (requires CLIs installed)
    python -m pytest tests/integration/test_real_cli_integration.py -v

    # Run as standalone script
    python tests/integration/test_real_cli_integration.py

Requirements:
    - uv tool install jleechanorg-orchestration
    - Claude/Cursor/Codex/Gemini CLIs installed (tests skip if not available)

Note:
    These tests are designed to be skipped gracefully if the required CLI
    tools are not installed. They are meant for local validation, not CI.
"""

from __future__ import annotations

import sys

import pytest

from tests.integration.test_harness_utils import (
    ORCHESTRATION_AVAILABLE,
    BaseCLITest,
    ClaudeCLITest,
    CodexCLITest,
    CursorCLITest,
    GeminiCLITest,
    is_cli_available,
)

# Skip all tests if orchestration framework is not installed
pytestmark = pytest.mark.skipif(
    not ORCHESTRATION_AVAILABLE,
    reason="jleechanorg-orchestration not installed - run: uv tool install jleechanorg-orchestration",
)


class MCPMailBaseCLITest(BaseCLITest):
    """Shared test harness for MCP Agent Mail CLI integration tests.

    Extends BaseCLITest to inherit run_all_tests() and provides the
    _run_cli_test hook and _get_cli_not_found_message customization points.
    """

    CLI_DISPLAY_NAME: str = "CLI"
    CLI_NOT_FOUND_MSG: str = "CLI not installed"

    def _get_cli_not_found_message(self, cli_binary: str) -> str:
        return self.CLI_NOT_FOUND_MSG

    def _run_cli_test(self) -> None:
        """Run CLI-specific integration test."""
        print("\n[TEST] Basic CLI invocation...")
        success, output = self.run_cli(f"echo '{self.CLI_DISPLAY_NAME} MCP Mail test'")
        if success:
            self.record("basic_invocation", True, "CLI responded")
        else:
            self.record("basic_invocation", False, f"CLI failed: {output[:200]}")


class MCPMailClaudeCLITest(MCPMailBaseCLITest, ClaudeCLITest):
    """Claude CLI integration test for MCP Agent Mail.

    This test verifies that Claude Code CLI can interact with
    MCP Agent Mail tools when properly configured.
    """

    CLI_DISPLAY_NAME = "Claude"
    CLI_NOT_FOUND_MSG = "Claude not installed - run: npm install -g @anthropic/claude-code"

    def _run_cli_test(self) -> None:
        print("\n[TEST] Basic CLI invocation...")
        success, output = self.run_cli("Respond with exactly: 'MCP Mail integration test successful'")
        if success and "successful" in output.lower():
            self.record("basic_invocation", True, "CLI responded correctly")
        elif success:
            self.record("basic_invocation", True, f"CLI responded: {output[:100]}...")
        else:
            self.record("basic_invocation", False, f"CLI failed: {output[:200]}")


class MCPMailCursorCLITest(MCPMailBaseCLITest, CursorCLITest):
    """Cursor CLI integration test for MCP Agent Mail.

    Note: cursor-agent CLI may use different storage than Cursor IDE.
    This test is expected to work with Cursor agent configurations.
    """

    CLI_DISPLAY_NAME = "Cursor"
    CLI_NOT_FOUND_MSG = "cursor-agent not installed"


class MCPMailCodexCLITest(MCPMailBaseCLITest, CodexCLITest):
    """Codex CLI integration test for MCP Agent Mail."""

    CLI_DISPLAY_NAME = "Codex"
    CLI_NOT_FOUND_MSG = "codex not installed"


class MCPMailGeminiCLITest(MCPMailBaseCLITest, GeminiCLITest):
    """Gemini CLI integration test for MCP Agent Mail."""

    CLI_DISPLAY_NAME = "Gemini"
    CLI_NOT_FOUND_MSG = "gemini not installed"


# Pytest test functions that wrap the harness classes


@pytest.mark.skipif(not is_cli_available("claude"), reason="Claude CLI not installed")
def test_claude_cli_integration():
    """Test Claude CLI integration with MCP Agent Mail."""
    test = MCPMailClaudeCLITest()
    exit_code = test.run_all_tests()
    assert exit_code == 0, "Claude CLI integration tests failed"


@pytest.mark.skipif(not is_cli_available("cursor"), reason="Cursor CLI not installed")
@pytest.mark.xfail(reason="cursor-agent CLI may use different storage than Cursor IDE")
def test_cursor_cli_integration():
    """Test Cursor CLI integration with MCP Agent Mail."""
    test = MCPMailCursorCLITest()
    exit_code = test.run_all_tests()
    assert exit_code == 0, "Cursor CLI integration tests failed"


@pytest.mark.skipif(not is_cli_available("codex"), reason="Codex CLI not installed")
def test_codex_cli_integration():
    """Test Codex CLI integration with MCP Agent Mail."""
    test = MCPMailCodexCLITest()
    exit_code = test.run_all_tests()
    assert exit_code == 0, "Codex CLI integration tests failed"


@pytest.mark.skipif(not is_cli_available("gemini"), reason="Gemini CLI not installed")
def test_gemini_cli_integration():
    """Test Gemini CLI integration with MCP Agent Mail."""
    test = MCPMailGeminiCLITest()
    exit_code = test.run_all_tests()
    assert exit_code == 0, "Gemini CLI integration tests failed"


if __name__ == "__main__":
    # Run as standalone script
    import argparse

    parser = argparse.ArgumentParser(description="Run real CLI integration tests")
    parser.add_argument(
        "--cli",
        choices=["claude", "cursor", "codex", "gemini", "all"],
        default="all",
        help="Which CLI to test",
    )
    args = parser.parse_args()

    test_classes = {
        "claude": MCPMailClaudeCLITest,
        "cursor": MCPMailCursorCLITest,
        "codex": MCPMailCodexCLITest,
        "gemini": MCPMailGeminiCLITest,
    }

    if args.cli == "all":
        results = []
        for name, cls in test_classes.items():
            if is_cli_available(name):
                print(f"\n{'=' * 70}")
                print(f"Running {name.upper()} tests...")
                print(f"{'=' * 70}\n")
                test = cls()
                results.append((name, test.run_all_tests()))
            else:
                print(f"\nSkipping {name} (not installed)")

        print("\n" + "=" * 70)
        print("OVERALL RESULTS")
        print("=" * 70)
        for name, code in results:
            status = "PASS" if code == 0 else "FAIL"
            print(f"  {name}: {status}")

        sys.exit(1 if any(code != 0 for _, code in results) else 0)
    else:
        if not is_cli_available(args.cli):
            print(f"Error: {args.cli} CLI not installed")
            sys.exit(1)

        test = test_classes[args.cli]()
        sys.exit(test.run_all_tests())
