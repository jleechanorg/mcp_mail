#!/usr/bin/env python3
"""Shared helpers and base classes for CLI integration test harnesses.

This module provides the orchestration framework pattern for running real
CLI tools (Claude, Codex, Cursor, Gemini) in integration tests.

Requires jleechanorg-orchestration framework for CLI profile management.
Install with: pip install jleechanorg-orchestration
"""

from __future__ import annotations

import os
import shlex
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Orchestration framework (optional dependency for real CLI tests)
# Install with: pip install jleechanorg-orchestration
try:
    from orchestration.task_dispatcher import CLI_PROFILES

    ORCHESTRATION_AVAILABLE = True
except ImportError:
    CLI_PROFILES = {}
    ORCHESTRATION_AVAILABLE = False


def _get_branch_name() -> str:
    """Get current git branch name for results directory."""
    try:
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip().replace("/", "-")
    except Exception:
        # Fallback to "unknown-branch" if git command fails
        pass
    return "unknown-branch"


RESULTS_DIR = Path(tempfile.gettempdir()) / "mcp-mail-tests" / _get_branch_name()
PROJECT_ROOT = Path(__file__).parent.parent.parent


@dataclass
class TestResult:
    """Result of a single test."""

    name: str
    passed: bool
    message: str = ""
    skipped: bool = False
    details: dict[str, Any] = field(default_factory=dict)


class BaseCLITest:
    """Base test harness with common functionality for CLI integration tests.

    Uses jleechanorg-orchestration CLI_PROFILES for CLI configuration.
    This provides a Template Method pattern where child classes only define:
        CLI_NAME: str - Key in CLI_PROFILES (e.g., "claude" or "cursor")
        SUITE_NAME: str - Test suite name for reporting
        FILE_PREFIX: str - Prefix for result files

    The base class handles all execution logic, eliminating direct subprocess
    calls in child classes.
    """

    # Subclasses must override these
    CLI_NAME: str = ""  # Key in CLI_PROFILES (e.g., "claude", "cursor", "codex")
    SUITE_NAME: str = ""
    FILE_PREFIX: str = ""

    def __init__(self):
        self.start_time = datetime.now(timezone.utc)
        self.results: list[TestResult] = []
        self.test_marker = f"TEST_{uuid.uuid4().hex[:8]}"

        # Get CLI profile from orchestration framework
        if self.CLI_NAME and self.CLI_NAME in CLI_PROFILES:
            self.cli_profile = CLI_PROFILES[self.CLI_NAME]
        else:
            self.cli_profile = None

    def record(
        self,
        name: str,
        passed: bool,
        message: str = "",
        skip: bool = False,
        details: Optional[dict] = None,
    ) -> None:
        """Record test result with consistent formatting.

        Args:
            name: Test name
            passed: Whether test passed
            message: Result message
            skip: Whether test was skipped
            details: Optional details dictionary
        """
        result = TestResult(
            name=name,
            passed=passed,
            message=message,
            skipped=skip,
            details=details or {},
        )
        self.results.append(result)

        if skip:
            print(f"  SKIP {name}: {message}")
        elif passed:
            print(f"  PASS {name}: {message}")
        else:
            print(f"  FAIL {name}: {message}")

    def check_cli_available(self) -> bool:
        """Check if CLI is available using orchestration CLI_PROFILES.

        Returns:
            True if CLI is installed and responding
        """
        if not ORCHESTRATION_AVAILABLE:
            return False

        if not self.cli_profile:
            raise ValueError(f"CLI_NAME '{self.CLI_NAME}' not found in CLI_PROFILES")

        cli_binary = self.cli_profile.get("binary")
        cli_path = shutil.which(cli_binary)

        if not cli_path:
            return False

        try:
            import subprocess

            result = subprocess.run(
                [cli_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                display_name = self.cli_profile.get("display_name", cli_binary)
                print(f"  {display_name} version: {result.stdout.strip()}")
                return True
        except Exception:
            # CLI not responding to --version, treat as unavailable
            pass
        return False

    def run_cli(
        self,
        prompt: str,
        timeout: int = 60,
        extra_args: Optional[list[str]] = None,
    ) -> tuple[bool, str]:
        """Run CLI with a prompt using orchestration CLI_PROFILES command template.

        This method constructs the command from CLI_PROFILES configuration,
        avoiding direct subprocess calls in child classes.

        Args:
            prompt: The prompt to send to the CLI
            timeout: Command timeout in seconds
            extra_args: Additional arguments to pass to CLI

        Returns:
            Tuple of (success: bool, output: str)
        """
        import subprocess

        if not self.cli_profile:
            raise ValueError(f"CLI_NAME '{self.CLI_NAME}' not found in CLI_PROFILES")

        cli_binary = self.cli_profile.get("binary")
        cli_path = shutil.which(cli_binary)
        if not cli_path:
            return False, f"{cli_binary} not found"

        # Write prompt to temp file (orchestration framework uses file-based prompts)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(prompt)
            prompt_file = f.name

        try:
            # Build command using CLI profile template
            command_template = self.cli_profile.get(
                "command_template", "{binary} -p {prompt_file}"
            )
            cli_command_str = command_template.format(
                binary=cli_path,
                prompt_file=prompt_file,
                continue_flag="",
            )

            # Split into list for safe subprocess execution (shell=False)
            cli_command = shlex.split(cli_command_str)

            # Add any extra arguments
            if extra_args:
                cli_command.extend(extra_args)

            print(f"  Command: {' '.join(cli_command)}")

            # Handle stdin redirection from profile
            stdin_template = self.cli_profile.get("stdin_template", "/dev/null")
            if stdin_template != "/dev/null":
                # Use context manager to ensure file is properly closed
                with open(prompt_file) as stdin_file:
                    result = subprocess.run(
                        cli_command,
                        shell=False,  # Security: avoid shell injection
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        stdin=stdin_file,
                        env={**os.environ, "NO_COLOR": "1"},
                    )
            else:
                result = subprocess.run(
                    cli_command,
                    shell=False,  # Security: avoid shell injection
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    stdin=None,
                    env={**os.environ, "NO_COLOR": "1"},
                )

            return result.returncode == 0, result.stdout + result.stderr

        except subprocess.TimeoutExpired:
            return False, f"Timeout after {timeout}s"
        except FileNotFoundError:
            return False, f"{cli_binary} not found"
        except Exception as e:
            return False, str(e)
        finally:
            # Clean up temp file
            try:
                os.unlink(prompt_file)
            except OSError:
                pass

    def print_summary(self) -> None:
        """Print test results summary."""
        passed = sum(1 for r in self.results if r.passed and not r.skipped)
        failed = sum(1 for r in self.results if not r.passed and not r.skipped)
        skipped = sum(1 for r in self.results if r.skipped)

        print("\n" + "=" * 70)
        print("RESULTS SUMMARY")
        print("=" * 70)
        print(f"  Passed:  {passed}")
        print(f"  Failed:  {failed}")
        print(f"  Skipped: {skipped}")

        if failed > 0:
            print("\nFailed tests:")
            for r in self.results:
                if not r.passed and not r.skipped:
                    print(f"  - {r.name}: {r.message}")

    def save_results(self, output_dir: Optional[Path] = None) -> Path:
        """Save test results to JSON file.

        Args:
            output_dir: Output directory (defaults to RESULTS_DIR)

        Returns:
            Path to saved results file
        """
        import json

        output_dir = output_dir or RESULTS_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{self.FILE_PREFIX}_{timestamp}.json"
        output_path = output_dir / filename

        data = {
            "suite": self.SUITE_NAME,
            "timestamp": self.start_time.isoformat(),
            "cli_name": self.CLI_NAME,
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "skipped": r.skipped,
                    "message": r.message,
                    "details": r.details,
                }
                for r in self.results
            ],
            "summary": {
                "passed": sum(1 for r in self.results if r.passed and not r.skipped),
                "failed": sum(
                    1 for r in self.results if not r.passed and not r.skipped
                ),
                "skipped": sum(1 for r in self.results if r.skipped),
            },
        }

        output_path.write_text(json.dumps(data, indent=2))
        print(f"\nResults saved to: {output_path}")
        return output_path

    def run_all_tests(self) -> int:
        """Run all integration tests for this CLI.

        Override this in child classes to implement specific test logic.

        Returns:
            Exit code (0 = success, 1 = failure)
        """
        display_name = (
            self.cli_profile.get("display_name", self.CLI_NAME)
            if self.cli_profile
            else "Unknown"
        )
        print("=" * 70)
        print(f"{display_name} - MCP Mail Integration Tests (REAL CLI)")
        print("=" * 70)
        print(f"Started: {datetime.now(timezone.utc).isoformat()}\n")

        # Check prerequisites
        print("[TEST] CLI availability...")
        if not ORCHESTRATION_AVAILABLE:
            self.record(
                "orchestration",
                False,
                "orchestration framework not installed - run: pip install jleechanorg-orchestration",
                skip=True,
            )
            return self._finish()

        if self.check_cli_available():
            self.record("cli", True, "Installed and responding")
        else:
            cli_binary = (
                self.cli_profile.get("binary", self.CLI_NAME)
                if self.cli_profile
                else self.CLI_NAME
            )
            self.record(
                "cli",
                False,
                f"Not found - install {cli_binary}",
                skip=True,
            )
            return self._finish()

        # Run CLI test
        print(f"\n[TEST] CLI invocation (real {display_name})...")
        success, output = self.run_cli(f"echo 'test marker: {self.test_marker}'")
        if not success:
            self.record("invocation", False, f"CLI failed: {output[:200]}")
        else:
            self.record("invocation", True, "CLI responded successfully")

        return self._finish()

    def _finish(self) -> int:
        """Print summary, save results, return exit code."""
        self.print_summary()
        self.save_results()
        return 1 if any(not r.passed and not r.skipped for r in self.results) else 0


class ClaudeCLITest(BaseCLITest):
    """Test harness for Claude Code CLI integration tests."""

    CLI_NAME = "claude"
    SUITE_NAME = "claude_mcp_mail_integration"
    FILE_PREFIX = "claude_integration"


class CursorCLITest(BaseCLITest):
    """Test harness for Cursor CLI integration tests."""

    CLI_NAME = "cursor"
    SUITE_NAME = "cursor_mcp_mail_integration"
    FILE_PREFIX = "cursor_integration"


class CodexCLITest(BaseCLITest):
    """Test harness for Codex CLI integration tests."""

    CLI_NAME = "codex"
    SUITE_NAME = "codex_mcp_mail_integration"
    FILE_PREFIX = "codex_integration"


class GeminiCLITest(BaseCLITest):
    """Test harness for Gemini CLI integration tests."""

    CLI_NAME = "gemini"
    SUITE_NAME = "gemini_mcp_mail_integration"
    FILE_PREFIX = "gemini_integration"


def get_available_cli_profiles() -> dict[str, dict]:
    """Get all available CLI profiles from orchestration framework.

    Returns:
        Dictionary of CLI profiles
    """
    return dict(CLI_PROFILES)


def is_cli_available(cli_name: str) -> bool:
    """Check if a specific CLI is available.

    Args:
        cli_name: CLI name (e.g., "claude", "cursor")

    Returns:
        True if CLI is installed
    """
    if cli_name not in CLI_PROFILES:
        return False

    binary = CLI_PROFILES[cli_name].get("binary")
    return shutil.which(binary) is not None
