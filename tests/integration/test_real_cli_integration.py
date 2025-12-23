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
    python -m tests.integration.test_real_cli_integration

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
from rich.console import Console

from tests.integration.test_harness_utils import (
    ORCHESTRATION_AVAILABLE,
    BaseCLITest,
    ClaudeCLITest,
    CodexCLITest,
    CursorCLITest,
    GeminiCLITest,
    is_cli_available,
)

console = Console()

# Skip all tests if orchestration framework is not installed
pytestmark = pytest.mark.skipif(
    not ORCHESTRATION_AVAILABLE,
    reason="jleechanorg-orchestration not installed - run: uv tool install jleechanorg-orchestration",
)


def _run_cli_suite(
    test: BaseCLITest,
    display_name: str,
    cli_missing: str,
    prompt: str,
    require_orchestration: bool = False,
) -> int:
    """Run the common CLI integration flow with consistent logging."""
    console.print("=" * 70)
    console.print(f"[bold]{display_name}[/bold] - MCP Agent Mail Integration Tests")
    console.print("=" * 70)
    console.print(f"[dim]Started:[/dim] {test.start_time.isoformat()}\n")

    if require_orchestration:
        console.print("[bold][TEST][/bold] Orchestration framework...")
        if not ORCHESTRATION_AVAILABLE:
            test.record(
                "orchestration",
                False,
                "Not installed - run: uv tool install jleechanorg-orchestration",
                skip=True,
            )
            return test._finish()
        test.record("orchestration", True, "Available")

    console.print(f"\n[bold][TEST][/bold] {display_name} CLI availability...")
    if not test.check_cli_available():
        test.record("cli", False, cli_missing, skip=True)
        return test._finish()
    test.record("cli", True, "Installed and responding")

    console.print("\n[bold][TEST][/bold] MCP Agent Mail tools via CLI...")
    if not test.validate_mcp_mail_access(timeout=120):
        return test._finish()

    console.print("\n[bold][TEST][/bold] Basic CLI invocation...")
    success, output = test.run_cli(prompt)
    if success and "successful" in output.lower():
        test.record("basic_invocation", True, "CLI responded correctly")
    elif success:
        test.record("basic_invocation", True, f"CLI responded: {output[:100]}...")
    else:
        test.record("basic_invocation", False, f"CLI failed: {output[:200]}")

    return test._finish()


class MCPMailClaudeCLITest(ClaudeCLITest):
    """Claude CLI integration test for MCP Agent Mail.

    This test verifies that Claude Code CLI can interact with
    MCP Agent Mail tools when properly configured.
    """

    def run_all_tests(self) -> int:
        """Run Claude-specific MCP Mail integration tests."""
        return _run_cli_suite(
            test=self,
            display_name="Claude Code",
            cli_missing="Claude not installed - run: npm install -g @anthropic/claude-code",
            prompt="Respond with exactly: 'MCP Mail integration test successful'",
            require_orchestration=True,
        )


class MCPMailCursorCLITest(CursorCLITest):
    """Cursor CLI integration test for MCP Agent Mail.

    Note: cursor-agent CLI may use different storage than Cursor IDE.
    This test is expected to work with Cursor agent configurations.
    """

    def run_all_tests(self) -> int:
        """Run Cursor-specific MCP Mail integration tests."""
        return _run_cli_suite(
            test=self,
            display_name="Cursor Agent",
            cli_missing="cursor-agent not installed",
            prompt="Respond with exactly: 'Cursor MCP Mail test successful'",
        )


class MCPMailCodexCLITest(CodexCLITest):
    """Codex CLI integration test for MCP Agent Mail."""

    def run_all_tests(self) -> int:
        """Run Codex-specific MCP Mail integration tests."""
        return _run_cli_suite(
            test=self,
            display_name="Codex CLI",
            cli_missing="codex not installed",
            prompt="Respond with exactly: 'Codex MCP Mail test successful'",
        )


class MCPMailGeminiCLITest(GeminiCLITest):
    """Gemini CLI integration test for MCP Agent Mail."""

    def run_all_tests(self) -> int:
        """Run Gemini-specific MCP Mail integration tests."""
        return _run_cli_suite(
            test=self,
            display_name="Gemini CLI",
            cli_missing="gemini not installed",
            prompt="Respond with exactly: 'Gemini MCP Mail test successful'",
        )


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
                console.print(f"\n{'=' * 70}")
                console.print(f"[bold]Running {name.upper()} tests...[/bold]")
                console.print(f"{'=' * 70}\n")
                test = cls()
                results.append((name, test.run_all_tests()))
            else:
                console.print(f"\n[cyan]Skipping {name} (not installed)[/cyan]")

        console.print("\n" + "=" * 70)
        console.print("[bold]OVERALL RESULTS[/bold]")
        console.print("=" * 70)
        for name, code in results:
            status = "PASS" if code == 0 else "FAIL"
            color = "green" if code == 0 else "red"
            console.print(f"  {name}: [{color}]{status}[/{color}]")

        sys.exit(1 if any(code != 0 for _, code in results) else 0)
    else:
        if not is_cli_available(args.cli):
            console.print(f"[red]Error:[/red] {args.cli} CLI not installed")
            sys.exit(1)

        test = test_classes[args.cli]()
        sys.exit(test.run_all_tests())
