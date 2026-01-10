#!/usr/bin/env python3
"""Real CLI Integration Tests for MCP Agent Mail.

These tests invoke actual CLI tools (Claude, Cursor, Codex, Gemini) using the
orchestration framework and verify MCP Agent Mail functionality.

Usage:
    # Run Claude integration test
    python -m pytest tests/integration/test_orch_cli_integration.py -k claude -v

    # Run all real CLI tests (requires CLIs installed)
    python -m pytest tests/integration/test_orch_cli_integration.py -v

    # Run as standalone script
    python tests/integration/test_orch_cli_integration.py

Requirements:
    - uv tool install jleechanorg-orchestration
    - Claude/Cursor/Codex/Gemini CLIs installed (tests skip if not available)

Note:
    These tests are designed to be skipped gracefully if the required CLI
    tools are not installed. They are meant for local validation, not CI.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import pytest

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from tests.integration.test_harness_utils import (  # noqa: E402
    ORCHESTRATION_AVAILABLE,
    PROJECT_ROOT,
    ClaudeCLITest,
    CodexCLITest,
    CursorCLITest,
    GeminiCLITest,
    is_cli_available,
    load_bearer_token,
)

# Skip all tests if orchestration framework is not installed
pytestmark = pytest.mark.skipif(
    not ORCHESTRATION_AVAILABLE,
    reason="jleechanorg-orchestration not installed - run: uv tool install jleechanorg-orchestration",
)


class MCPMailClaudeCLITest(ClaudeCLITest):
    """Claude CLI integration test for MCP Agent Mail.

    This test verifies that Claude Code CLI can interact with
    MCP Agent Mail tools when properly configured.
    """

    def run_all_tests(self) -> int:
        """Run Claude-specific MCP Mail integration tests."""
        print("=" * 70)
        print("Claude Code - MCP Agent Mail Integration Tests")
        print("=" * 70)
        print(f"Started: {self.start_time.isoformat()}\n")

        # Context manager to patch .claude/settings.json with auth token.
        # This is best-effort and always restores in finally, but note that a hard kill
        # (e.g., SIGKILL) can still leave the patched settings on disk.
        @contextlib.contextmanager
        def patched_settings():
            settings_path = PROJECT_ROOT / ".claude" / "settings.json"
            if not settings_path.exists():
                yield
                return

            original_content = settings_path.read_text(encoding="utf-8")
            try:
                # Load token and inject into settings
                token = load_bearer_token()
                if token:
                    config = json.loads(original_content)
                    server = config.get("mcpServers", {}).get("mcp-agent-mail")
                    if isinstance(server, dict):
                        headers = server.get("headers")
                        if not isinstance(headers, dict):
                            headers = {}
                        headers["Authorization"] = f"Bearer {token}"
                        server["headers"] = headers
                        settings_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
                        print(f"[SETUP] Patched {settings_path} with auth token for test")
            except Exception as e:
                print(f"[SETUP] Warning: Failed to patch settings: {e}")

            try:
                yield
            finally:
                try:
                    settings_path.write_text(original_content, encoding="utf-8")
                    print(f"[TEARDOWN] Restored {settings_path}")
                except Exception as e:
                    print(f"[TEARDOWN] Warning: Failed to restore settings: {e}")

        with patched_settings():
            # Check prerequisites
            print("[TEST] Orchestration framework...")
            if not ORCHESTRATION_AVAILABLE:
                self.record(
                    "orchestration",
                    False,
                    "Not installed - run: uv tool install jleechanorg-orchestration",
                    skip=True,
                )
                return self._finish()
            self.record("orchestration", True, "Available")

            print("\n[TEST] Claude CLI availability...")
            if not self.check_cli_available():
                self.record(
                    "cli",
                    False,
                    "Claude not installed - run: npm install -g @anthropic/claude-code",
                    skip=True,
                )
                return self._finish()
            self.record("cli", True, "Installed and responding")

            print("\n[TEST] MCP Agent Mail tools via CLI...")
            if not self.validate_mcp_mail_access(timeout=120):
                return self._finish()

            # Basic CLI invocation test
            print("\n[TEST] Basic CLI invocation...")
            success, output = self.run_cli("Respond with exactly: 'MCP Mail integration test successful'")
            if success and "successful" in output.lower():
                self.record("basic_invocation", True, "CLI responded correctly")
            elif success:
                self.record("basic_invocation", True, f"CLI responded: {output[:100]}...")
            else:
                self.record("basic_invocation", False, f"CLI failed: {output[:200]}")

            return self._finish()


class MCPMailCursorCLITest(CursorCLITest):
    """Cursor CLI integration test for MCP Agent Mail.

    Note: cursor-agent CLI may use different storage than Cursor IDE.
    This test is expected to work with Cursor agent configurations.
    """

    def run_all_tests(self) -> int:
        """Run Cursor-specific MCP Mail integration tests."""
        print("=" * 70)
        print("Cursor Agent - MCP Agent Mail Integration Tests")
        print("=" * 70)
        print(f"Started: {self.start_time.isoformat()}\n")

        print("[TEST] Cursor CLI availability...")
        if not self.check_cli_available():
            self.record(
                "cli",
                False,
                "cursor-agent not installed",
                skip=True,
            )
            return self._finish()
        self.record("cli", True, "Installed and responding")

        print("\n[TEST] MCP Agent Mail tools via CLI...")
        if not self.validate_mcp_mail_access(timeout=120):
            return self._finish()

        # Basic CLI invocation test
        print("\n[TEST] Basic CLI invocation...")
        success, output = self.run_cli("Respond with exactly: 'MCP Mail integration test successful'")
        if success:
            self.record("basic_invocation", True, "CLI responded")
        else:
            self.record("basic_invocation", False, f"CLI failed: {output[:200]}")

        return self._finish()


class MCPMailCodexCLITest(CodexCLITest):
    """Codex CLI integration test for MCP Agent Mail."""

    def run_all_tests(self) -> int:
        """Run Codex-specific MCP Mail integration tests."""
        print("=" * 70)
        print("Codex CLI - MCP Agent Mail Integration Tests")
        print("=" * 70)
        print(f"Started: {self.start_time.isoformat()}\n")

        print("[TEST] Codex CLI availability...")
        if not self.check_cli_available():
            self.record(
                "cli",
                False,
                "codex not installed",
                skip=True,
            )
            return self._finish()
        self.record("cli", True, "Installed and responding")

        print("\n[TEST] MCP Agent Mail tools via CLI...")
        if not self.validate_mcp_mail_access(timeout=120):
            return self._finish()

        # Basic CLI invocation test
        print("\n[TEST] Basic CLI invocation...")
        success, output = self.run_cli("Respond with exactly: 'MCP Mail integration test successful'")
        if success:
            self.record("basic_invocation", True, "CLI responded")
        else:
            self.record("basic_invocation", False, f"CLI failed: {output[:200]}")

        return self._finish()


class MCPMailGeminiCLITest(GeminiCLITest):
    """Gemini CLI integration test for MCP Agent Mail."""

    def run_all_tests(self) -> int:
        """Run Gemini-specific MCP Mail integration tests."""
        print("=" * 70)
        print("Gemini CLI - MCP Agent Mail Integration Tests")
        print("=" * 70)
        print(f"Started: {self.start_time.isoformat()}\n")

        print("[TEST] Gemini CLI availability...")
        if not self.check_cli_available():
            self.record(
                "cli",
                False,
                "gemini not installed",
                skip=True,
            )
            return self._finish()
        self.record("cli", True, "Installed and responding")

        print("\n[TEST] MCP Agent Mail tools via CLI...")
        if not self.validate_mcp_mail_access(timeout=120):
            return self._finish()

        # Basic CLI invocation test
        print("\n[TEST] Basic CLI invocation...")
        success, output = self.run_cli("Respond with exactly: 'MCP Mail integration test successful'")
        if success:
            self.record("basic_invocation", True, "CLI responded")
        else:
            self.record("basic_invocation", False, f"CLI failed: {output[:200]}")

        return self._finish()


# Pytest test functions that wrap the harness classes


@pytest.mark.skipif(not is_cli_available("claude"), reason="Claude CLI not installed")
def test_claude_cli_integration():
    """Test Claude CLI integration with MCP Agent Mail."""
    test = MCPMailClaudeCLITest()
    exit_code = test.run_all_tests()
    assert exit_code == 0, "Claude CLI integration tests failed"


@pytest.mark.skipif(not is_cli_available("cursor"), reason="Cursor CLI not installed")
def test_cursor_cli_integration():
    """Test Cursor CLI integration with MCP Agent Mail.

    Note: Cursor CLI uses ~/.cursor/mcp.json for MCP configuration.
    Ensure the mcp-agent-mail server includes Authorization header:

    {
      "mcpServers": {
        "mcp-agent-mail": {
          "type": "http",
          "url": "http://127.0.0.1:8765/mcp/",
          "headers": {
            "Authorization": "Bearer <token>"
          }
        }
      }
    }
    """
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
