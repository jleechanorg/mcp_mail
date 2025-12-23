#!/usr/bin/env python3
"""Shared helpers and base classes for CLI integration test harnesses.

This module provides the orchestration framework pattern for running real
CLI tools (Claude, Codex, Cursor, Gemini) in integration tests.

Requires the jleechanorg-orchestration framework for CLI profile management.
Install with: ``uv tool install jleechanorg-orchestration``. The framework
exposes ``CLI_PROFILES`` entries such as:

```
CLI_PROFILES = {
    "claude": {
        "binary": "claude",
        "display_name": "Claude Code",
        "command_template": "{binary} -p {prompt_file}",
        "stdin_template": "/dev/null",
    },
}
```

Each profile defines the CLI binary, a command template that accepts a prompt
file, and optional stdin handling. The harness uses these profiles to
construct safe subprocess commands without shell interpolation.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from decouple import Config as DecoupleConfig, RepositoryEnv
from rich.console import Console

# Orchestration framework (optional dependency for real CLI tests)
# Install with: uv tool install jleechanorg-orchestration
try:
    orchestration_module = importlib.import_module("orchestration.task_dispatcher")
    CLI_PROFILES = getattr(orchestration_module, "CLI_PROFILES", {})
    ORCHESTRATION_AVAILABLE = True
except ImportError:
    CLI_PROFILES = {}
    ORCHESTRATION_AVAILABLE = False


def _get_branch_name() -> str:
    """Get current git branch name for results directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip().replace("/", "-")
    except Exception as exc:  # pragma: no cover - best-effort branch detection
        console.print(f"[yellow]WARN:[/yellow] Failed to read git branch name: {exc}")
    return "unknown-branch"


RESULTS_DIR = Path(tempfile.gettempdir()) / "mcp-mail-tests" / _get_branch_name()
PROJECT_ROOT = Path(__file__).parent.parent.parent
MCP_CONFIG_PATH = PROJECT_ROOT / ".mcp.json"
MCP_AGENT_MAIL_SERVER = "mcp-agent-mail"
MCP_EXPECTED_TOOLS = {"register_agent", "send_message", "fetch_inbox"}
ENV_PATH = PROJECT_ROOT / ".env"
console = Console()


def _load_env_value(key: str) -> Optional[str]:
    """Load a value from the repo .env using python-decouple."""
    if not ENV_PATH.exists():
        return None
    decouple_config = DecoupleConfig(RepositoryEnv(str(ENV_PATH)))
    try:
        value = decouple_config(key)
    except Exception:  # pragma: no cover - best-effort for optional env values
        return None
    return value.strip() or None


def _load_bearer_token() -> Optional[str]:
    """Best-effort bearer token lookup for MCP HTTP auth."""
    token = _load_env_value("HTTP_BEARER_TOKEN")
    if token:
        return token
    try:
        if MCP_CONFIG_PATH.exists():
            config = json.loads(MCP_CONFIG_PATH.read_text())
            headers = (
                config.get("mcpServers", {})
                .get(MCP_AGENT_MAIL_SERVER, {})
                .get("headers", {})
            )
            auth_header = headers.get("Authorization", "")
            if auth_header.lower().startswith("bearer "):
                return auth_header.split(" ", 1)[1].strip()
    except Exception:  # pragma: no cover - best-effort parsing
        return None
    return None


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

    def _load_mcp_config(self) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        """Load MCP configuration from the repo-level .mcp.json file."""
        if not MCP_CONFIG_PATH.exists():
            return None, f"MCP config not found at {MCP_CONFIG_PATH}"

        try:
            return json.loads(MCP_CONFIG_PATH.read_text()), None
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"Unable to read MCP config: {exc}"

    def _get_mcp_server_url(self, config: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        """Extract MCP Agent Mail server URL from config."""
        mcp_servers = config.get("mcpServers", {})
        server = mcp_servers.get(MCP_AGENT_MAIL_SERVER)
        if not server:
            return None, f"{MCP_AGENT_MAIL_SERVER} not found in MCP config"

        url = server.get("url")
        if not url:
            return None, f"{MCP_AGENT_MAIL_SERVER} missing url in MCP config"
        return url, None

    def _is_server_reachable(self, url: str, timeout: float = 3.0) -> tuple[bool, str]:
        """Check whether the MCP Agent Mail server port is reachable."""
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        if not host:
            return False, f"Invalid MCP server URL: {url}"

        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True, f"{MCP_AGENT_MAIL_SERVER} reachable at {host}:{port}"
        except OSError as exc:
            return False, f"{MCP_AGENT_MAIL_SERVER} unreachable at {host}:{port} ({exc})"

    def _parse_tool_names_from_output(self, output: str) -> set[str]:
        """Parse tool names from CLI output."""
        match = re.search(r"^\\s*TOOLS:\\s*(?P<tools>.+)$", output, re.IGNORECASE | re.MULTILINE)
        if match:
            tools = match.group("tools")
            return {tool.strip().lower() for tool in tools.split(",") if tool.strip()}
        return set(re.findall(r"\\b[a-z][a-z0-9_-]*[a-z0-9]\\b", output.lower()))

    def _exercise_mcp_mail_tools(
        self,
        server_url: str,
        expected_tools: set[str],
        timeout: int = 90,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Prompt the CLI to list available MCP Agent Mail tools."""
        prompts = [
            (
                "Connect to the configured mcp-agent-mail MCP server and list the tool "
                "names available to you. Respond exactly as 'TOOLS: <comma-separated tool names>'. "
                f"The server URL should be {server_url}.",
                timeout,
            ),
            (
                "Important: respond with exactly one line in this format and nothing else:\n"
                "TOOLS: <comma-separated tool names>\n"
                f"Use the MCP server at {server_url} and do not explain your answer.",
                max(timeout, 180),
            ),
        ]

        last_details: dict[str, Any] = {}
        for attempt, (prompt, attempt_timeout) in enumerate(prompts, start=1):
            success, output = self.run_cli(prompt, timeout=attempt_timeout)
            if not success:
                last_details = {"output": output[:500], "attempt": attempt}
                message = f"MCP tool prompt failed: {output[:200]}"
                if attempt < len(prompts):
                    console.print(f"[yellow]WARN:[/yellow] {message} (attempt {attempt}); retrying...")
                    continue
                return False, message, last_details

            tool_names = self._parse_tool_names_from_output(output)
            missing_tools = expected_tools - tool_names
            last_details = {"tools": sorted(tool_names), "attempt": attempt, "output": output[:500]}

            if not missing_tools:
                return True, "MCP Agent Mail tools available", last_details

            message = f"Missing expected tools: {', '.join(sorted(missing_tools))}"
            if attempt < len(prompts):
                console.print(f"[yellow]WARN:[/yellow] {message} (attempt {attempt}); retrying...")
                continue
            return False, message, last_details

        return False, "Unable to validate MCP Agent Mail tools", last_details

    def validate_mcp_mail_access(self, timeout: int = 90) -> bool:
        """Validate MCP Agent Mail configuration and tool availability via CLI."""
        config, error = self._load_mcp_config()
        if error:
            self.record("mcp_config", False, error, skip=True)
            return False

        if config is None:
            self.record("mcp_config", False, "MCP config unavailable", skip=True)
            return False

        server_url, url_error = self._get_mcp_server_url(config)
        if url_error or not server_url:
            self.record("mcp_config", False, url_error or "Unknown MCP config error", skip=True)
            return False

        reachable, reach_msg = self._is_server_reachable(server_url)
        if not reachable:
            self.record("mcp_server", False, reach_msg, skip=True)
            return False
        self.record("mcp_server", True, reach_msg)

        tool_success, tool_msg, details = self._exercise_mcp_mail_tools(
            server_url=server_url,
            expected_tools=MCP_EXPECTED_TOOLS,
            timeout=timeout,
        )
        self.record("mcp_tools", tool_success, tool_msg, details=details)

        return tool_success

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
            console.print(f"[cyan]SKIP[/cyan] {name}: {message}")
        elif passed:
            console.print(f"[green]PASS[/green] {name}: {message}")
        else:
            console.print(f"[red]FAIL[/red] {name}: {message}")

    def check_cli_available(self) -> bool:
        """Check if CLI is available using orchestration CLI_PROFILES.

        Returns:
            True if CLI is installed and responding
        """
        if not ORCHESTRATION_AVAILABLE:
            return False

        if not self.cli_profile:
            raise ValueError(f"CLI_NAME '{self.CLI_NAME}' not found in CLI_PROFILES")

        cli_binary = self.cli_profile.get("binary") or self.CLI_NAME
        if not cli_binary:
            return False
        cli_path = shutil.which(cli_binary)

        if not cli_path:
            return False

        try:
            result = subprocess.run(
                [cli_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                display_name = self.cli_profile.get("display_name", cli_binary)
                console.print(f"[green]{display_name} version:[/green] {result.stdout.strip()}")
                return True
        except Exception as exc:  # pragma: no cover - CLI availability best-effort
            console.print(f"[yellow]WARN:[/yellow] Failed to check CLI availability: {exc}")
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
        if not self.cli_profile:
            raise ValueError(f"CLI_NAME '{self.CLI_NAME}' not found in CLI_PROFILES")

        cli_binary = self.cli_profile.get("binary") or self.CLI_NAME
        if not cli_binary:
            return False, "CLI binary not configured"
        cli_path = shutil.which(cli_binary)
        if not cli_path:
            return False, f"{cli_binary} not found"

        prompt_file: Optional[Path] = None
        try:
            # Write prompt to temp file (orchestration framework uses file-based prompts)
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write(prompt)
                prompt_file = Path(f.name)
        except OSError as exc:
            return False, f"Failed to write prompt file: {exc}"

        try:
            # Build command using CLI profile template
            command_template = self.cli_profile.get("command_template", "{binary} -p {prompt_file}")
            cli_command_str = command_template.format(
                binary=shlex.quote(cli_path),
                prompt_file=shlex.quote(str(prompt_file)),
                continue_flag="",
            )

            # Split into list for safe subprocess execution (shell=False)
            cli_command = shlex.split(cli_command_str)

            # Add any extra arguments
            if extra_args:
                cli_command.extend(extra_args)

            console.print(f"[blue]Command:[/blue] {' '.join(cli_command)}")

            # Handle stdin redirection from profile
            stdin_template = self.cli_profile.get("stdin_template", "/dev/null")
            with contextlib.ExitStack() as stack:
                if stdin_template == "/dev/null":
                    stdin_file = subprocess.DEVNULL
                else:
                    stdin_path = Path(stdin_template.format(prompt_file=str(prompt_file)))
                    stdin_file = stack.enter_context(stdin_path.open())

                env = {**os.environ, "NO_COLOR": "1"}
                if self.CLI_NAME == "codex":
                    bearer_token = _load_bearer_token()
                    if bearer_token:
                        env["HTTP_BEARER_TOKEN"] = bearer_token

                result = subprocess.run(
                    cli_command,
                    shell=False,  # Security: avoid shell injection
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    stdin=stdin_file,
                    env=env,
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
            with contextlib.suppress(OSError):
                if prompt_file:
                    prompt_file.unlink()

    def print_summary(self) -> None:
        """Print test results summary."""
        passed = sum(1 for r in self.results if r.passed and not r.skipped)
        failed = sum(1 for r in self.results if not r.passed and not r.skipped)
        skipped = sum(1 for r in self.results if r.skipped)

        console.print("\n" + "=" * 70)
        console.print("[bold]RESULTS SUMMARY[/bold]")
        console.print("=" * 70)
        console.print(f"[green]Passed:[/green]  {passed}")
        console.print(f"[red]Failed:[/red]  {failed}")
        console.print(f"[cyan]Skipped:[/cyan] {skipped}")

        if failed > 0:
            console.print("\n[red]Failed tests:[/red]")
            for r in self.results:
                if not r.passed and not r.skipped:
                    console.print(f"  - {r.name}: {r.message}")

    def save_results(self, output_dir: Optional[Path] = None) -> Path:
        """Save test results to JSON file.

        Args:
            output_dir: Output directory (defaults to RESULTS_DIR)

        Returns:
            Path to saved results file
        """
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
                "failed": sum(1 for r in self.results if not r.passed and not r.skipped),
                "skipped": sum(1 for r in self.results if r.skipped),
            },
        }

        output_path.write_text(json.dumps(data, indent=2))
        console.print(f"\n[green]Results saved to:[/green] {output_path}")
        return output_path

    def run_all_tests(self) -> int:
        """Run all integration tests for this CLI.

        Override this in child classes to implement specific test logic.

        Returns:
            Exit code (0 = success, 1 = failure)
        """
        display_name = self.cli_profile.get("display_name", self.CLI_NAME) if self.cli_profile else "Unknown"
        console.print("=" * 70)
        console.print(f"[bold]{display_name}[/bold] - MCP Mail Integration Tests (REAL CLI)")
        console.print("=" * 70)
        console.print(f"[dim]Started:[/dim] {datetime.now(timezone.utc).isoformat()}\n")

        # Check prerequisites
        console.print("[bold][TEST][/bold] CLI availability...")
        if not ORCHESTRATION_AVAILABLE:
            self.record(
                "orchestration",
                False,
                "orchestration framework not installed - run: uv tool install jleechanorg-orchestration",
                skip=True,
            )
            return self._finish()

        if self.check_cli_available():
            self.record("cli", True, "Installed and responding")
        else:
            cli_binary = self.cli_profile.get("binary", self.CLI_NAME) if self.cli_profile else self.CLI_NAME
            self.record(
                "cli",
                False,
                f"Not found - install {cli_binary}",
                skip=True,
            )
            return self._finish()

        # Run CLI test
        console.print(f"\n[bold][TEST][/bold] CLI invocation (real {display_name})...")
        success, output = self.run_cli(
            f"Respond with exactly: 'CLI test marker {self.test_marker} received'"
        )
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

    binary = CLI_PROFILES[cli_name].get("binary") or cli_name
    if not binary:
        return False
    return shutil.which(binary) is not None
