#!/usr/bin/env python3
"""Real CLI Multi-Agent Coordination Test Runner.

This script replaces direct subprocess/bash calls to Claude, Codex, and Gemini CLIs
with the orchestration framework pattern for cleaner, safer CLI invocations.

Usage:
    # Run with default CLI (claude)
    python testing_llm/run_real_cli_test.py

    # Run with specific CLI
    python testing_llm/run_real_cli_test.py --cli codex
    python testing_llm/run_real_cli_test.py --cli gemini

    # Run both with/without project_key (default)
    python testing_llm/run_real_cli_test.py --project-key-mode both

    # Run only without project_key
    python testing_llm/run_real_cli_test.py --project-key-mode without

    # Dry run (don't execute CLIs)
    python testing_llm/run_real_cli_test.py --dry-run

Requirements:
    uv tool install jleechanorg-orchestration
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(PROJECT_ROOT))
from tests.integration.test_harness_utils import (  # noqa: E402
    MCP_AGENT_MAIL_SERVER,
    load_bearer_token,
)

# Orchestration framework for CLI profiles
try:
    orchestration_module = importlib.import_module("orchestration.task_dispatcher")
    CLI_PROFILES = getattr(orchestration_module, "CLI_PROFILES", {})
    ORCHESTRATION_AVAILABLE = True
except ImportError:
    CLI_PROFILES = {}
    ORCHESTRATION_AVAILABLE = False

# CLI configuration mapping (extends orchestration profiles with MCP-specific settings)
MCP_CLI_CONFIG = {
    "claude": {
        "mcp_config_env": "MCP_CONFIG",
        "mcp_config_file": ".mcp.json",  # relative to the working directory where the CLI runs
        "extra_args": ["--dangerously-skip-permissions"],
    },
    "codex": {
        "mcp_config_env": "MCP_CONFIG",
        "mcp_config_file": ".codex/config.toml",  # relative to current working directory
        "extra_args": ["--yolo"],
    },
    "gemini": {
        "mcp_config_env": "GEMINI_CONFIG",
        "mcp_config_file": "./examples/gemini.mcp.json",  # relative to current working directory
        "extra_args": [
            "--approval-mode",
            "yolo",
            "--allowed-mcp-server-names",
            MCP_AGENT_MAIL_SERVER,
        ],
    },
}


def get_timestamp() -> str:
    """Get timestamp for unique identifiers."""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def setup_test_directory() -> Path:
    """Create test evidence directory."""
    timestamp = get_timestamp()
    test_dir = Path(tempfile.gettempdir()) / f"real_cli_multiagent_{timestamp}"

    for subdir in ["prompts", "outputs", "evidence"]:
        (test_dir / subdir).mkdir(parents=True, exist_ok=True)

    print(f"Test directory: {test_dir}")
    return test_dir


def check_cli_available(cli_name: str) -> tuple[bool, str]:
    """Check if a CLI is available.

    Uses orchestration framework CLI_PROFILES if available.

    Returns:
        Tuple of (available: bool, binary_path_or_error: str)
    """
    if not ORCHESTRATION_AVAILABLE:
        return False, "Orchestration framework not installed"

    if cli_name not in CLI_PROFILES:
        return False, f"CLI '{cli_name}' not in CLI_PROFILES"

    binary = CLI_PROFILES[cli_name].get("binary") or cli_name
    if not binary:
        return False, f"CLI '{cli_name}' missing binary configuration"
    binary_path = shutil.which(binary)

    if not binary_path:
        return False, f"Binary '{binary}' not found in PATH"

    return True, binary_path


def build_cli_command(
    cli_name: str,
    prompt: str,
    prompt_file: Path,
) -> list[str]:
    """Build CLI command using orchestration framework pattern.

    This replaces direct subprocess calls like:
        claude -p --dangerously-skip-permissions "$PROMPT"

    With a structured command built from CLI_PROFILES.

    Args:
        cli_name: CLI name (claude, codex, gemini)
        prompt: The prompt text
        prompt_file: Path to write prompt file

    Returns:
        Command as list of strings (for subprocess with shell=False)
    """
    if cli_name not in CLI_PROFILES:
        raise ValueError(f"Unknown CLI: {cli_name}")

    profile = CLI_PROFILES[cli_name]
    mcp_config = MCP_CLI_CONFIG.get(cli_name, {})

    binary = profile.get("binary") or cli_name
    if not binary:
        raise ValueError(f"CLI '{cli_name}' missing binary configuration")
    binary_path = shutil.which(binary)
    if not binary_path:
        raise FileNotFoundError(f"CLI binary not found: {binary}")

    # Write prompt to file
    try:
        prompt_file.write_text(prompt)
    except OSError as exc:
        raise OSError(f"Failed to write prompt file: {exc}") from exc

    # Build command using template from profile
    command_template = profile.get("command_template", "{binary} -p {prompt_file}")

    # Format the command template
    command_str = command_template.format(
        binary=shlex.quote(binary_path),
        prompt_file=shlex.quote(str(prompt_file)),
        continue_flag="",
    )

    # Parse into list (shell=False for security)
    command = shlex.split(command_str)

    # Add any MCP-specific extra args
    extra_args = mcp_config.get("extra_args", [])
    for arg in extra_args:
        if arg not in command:
            command.append(arg)

    return command


def run_cli_agent(
    cli_name: str,
    agent_name: str,
    prompt: str,
    test_dir: Path,
    dry_run: bool = False,
) -> tuple[
    bool,
    str,
    Optional[subprocess.Popen[str]],
    Optional[contextlib.ExitStack],
]:
    """Run a CLI agent with the given prompt.

    Uses the orchestration framework pattern instead of direct subprocess calls.

    Args:
        cli_name: CLI to use (claude, codex, gemini)
        agent_name: Name for this agent instance
        prompt: The prompt to send
        test_dir: Test directory for outputs
        dry_run: If True, don't actually execute

    Returns:
        Tuple of (success, message, process, output_stack)
    """
    prompt_file = test_dir / "prompts" / f"{agent_name}_task.txt"
    output_file = test_dir / "outputs" / f"{agent_name}_output.txt"

    try:
        command = build_cli_command(cli_name, prompt, prompt_file)
    except (ValueError, FileNotFoundError, OSError) as e:
        return False, str(e), None, None

    # Set up environment with MCP config
    env = os.environ.copy()
    mcp_config: dict[str, Any] = MCP_CLI_CONFIG.get(cli_name, {})
    config_env = mcp_config.get("mcp_config_env")
    config_file = mcp_config.get("mcp_config_file")
    if isinstance(config_env, str) and config_env and isinstance(config_file, str) and config_file:
        env[config_env] = config_file
    env["NO_COLOR"] = "1"  # Disable color output for cleaner logs

    bearer_token = load_bearer_token()
    if bearer_token:
        env["HTTP_BEARER_TOKEN"] = bearer_token

    print(f"  Command: {' '.join(command)}")
    print(f"  Output: {output_file}")

    if dry_run:
        return True, "Dry run - command not executed", None, None

    output_stack: Optional[contextlib.ExitStack] = None
    try:
        output_stack = contextlib.ExitStack()
        output_handle = output_stack.enter_context(output_file.open("w"))

        stdin_template = CLI_PROFILES.get(cli_name, {}).get("stdin_template", "/dev/null")
        if stdin_template == "/dev/null":
            stdin_handle: Any = subprocess.DEVNULL
        else:
            stdin_path = Path(stdin_template.format(prompt_file=str(prompt_file)))
            if not stdin_path.exists():
                raise FileNotFoundError(f"stdin template path does not exist for {cli_name}: {stdin_path}")
            stdin_handle = output_stack.enter_context(stdin_path.open())

        # Start process (non-blocking)
        process = subprocess.Popen(
            command,
            stdout=output_handle,
            stderr=subprocess.STDOUT,
            stdin=stdin_handle,
            env=env,
            cwd=str(PROJECT_ROOT),
            shell=False,  # Security: avoid shell injection
            text=True,
        )

        pid_message = f"Started with PID {process.pid}" if process else "Started"
        return True, pid_message, process, output_stack

    except Exception as e:
        if output_stack:
            output_stack.close()
        return False, f"Failed to start: {e}", None, None


def _register_block(
    *,
    project_key: Optional[str],
    agent_name: str,
    program: str,
    model: str,
    task_description: str,
) -> str:
    project_line = f'   - project_key: "{project_key}"\n' if project_key else ""
    return (
        "1. Register yourself using the mcp-agent-mail MCP server:\n"
        "   - Use tool: register_agent\n"
        f"{project_line}"
        f'   - name: "{agent_name}"\n'
        f'   - program: "{program}"\n'
        f'   - model: "{model}"\n'
        f'   - task_description: "{task_description}"\n'
    )


def create_agent_prompts(run_id: str, project_key: Optional[str]) -> dict[str, str]:
    """Create prompts for each agent.

    Args:
        run_id: Unique run identifier
        project_key: Project key for MCP Agent Mail (optional)

    Returns:
        Dictionary mapping agent name to prompt
    """
    prompts = {
        f"FrontendDev-{run_id}": f"""You are Agent1 (FrontendDev-{run_id}). Your task:

{
            _register_block(
                project_key=project_key,
                agent_name=f"FrontendDev-{run_id}",
                program="cli-agent",
                model="test",
                task_description="React UI Development",
            )
        }

2. Send a message to BackendDev-{run_id}:
   - Use tool: send_message
   - to: ["BackendDev-{run_id}"]
   - subject: "Need API endpoint for dashboard"
   - body_md: "Hi BackendDev! Can you create GET /api/dashboard/stats endpoint?"
   - importance: "high"

3. Wait 5 seconds, then check your inbox:
   - Use tool: fetch_inbox
   - limit: 5
   - include_bodies: true

4. Print a summary of your agent registration, message sent, and messages received.
""",
        f"BackendDev-{run_id}": f"""You are Agent2 (BackendDev-{run_id}). Your task:

1. Wait 3 seconds for Agent1 to register and send message

2. Register yourself using mcp-agent-mail:
{
            _register_block(
                project_key=project_key,
                agent_name=f"BackendDev-{run_id}",
                program="cli-agent",
                model="test",
                task_description="FastAPI Backend Development",
            )
        }

3. Check your inbox and look for message from FrontendDev-{run_id}

4. Send message to DatabaseAdmin-{run_id}:
   - to: ["DatabaseAdmin-{run_id}"]
   - subject: "Need help with user stats query"
   - body_md: "Can you help optimize: SELECT * FROM user_activity WHERE date > NOW() - INTERVAL '7 days'?"

5. Reply to FrontendDev-{run_id}:
   - to: ["FrontendDev-{run_id}"]
   - subject: "Re: Need API endpoint for dashboard"
   - body_md: "Working on it! Asked DatabaseAdmin for help."

6. Print summary showing messages received and sent.
""",
        f"DatabaseAdmin-{run_id}": f"""You are Agent3 (DatabaseAdmin-{run_id}). Your task:

1. Wait 6 seconds for other agents to start

2. Register yourself using mcp-agent-mail:
{
            _register_block(
                project_key=project_key,
                agent_name=f"DatabaseAdmin-{run_id}",
                program="cli-agent",
                model="test",
                task_description="PostgreSQL Database Management",
            )
        }

3. Check your inbox and look for message from BackendDev-{run_id}

4. Send optimized query to BackendDev-{run_id}:
   - to: ["BackendDev-{run_id}"]
   - subject: "Re: Need help with user stats query"
   - body_md: "Here's the optimized query with proper indexing."
   - importance: "high"

5. Print summary showing agent registration, messages received, and messages sent.
""",
    }
    return prompts


def run_multi_agent_test(
    *,
    cli_name: str = "claude",
    dry_run: bool = False,
    timeout: int = 120,
    project_key_mode: str = "with",
) -> dict:
    """Run the multi-agent coordination test.

    This replaces the bash script approach in REAL_CLAUDE_MULTI_AGENT_TEST.md
    with Python using the orchestration framework.

    Args:
        cli_name: Which CLI to use (claude, codex, gemini)
        dry_run: If True, don't actually execute CLIs
        timeout: Timeout for each agent in seconds
        project_key_mode: "with" for project_key, "without" for no project key

    Returns:
        Test results dictionary
    """
    print("=" * 70)
    print("Real CLI Multi-Agent Coordination Test")
    print(f"CLI: {cli_name}")
    print(f"Project key mode: {project_key_mode}")
    print("=" * 70)

    agents: list[dict[str, Any]] = []
    results: dict[str, Any] = {
        "cli": cli_name,
        "timestamp": datetime.now().isoformat(),
        "agents": agents,
        "status": "pending",
    }

    # Check prerequisites
    print("\n[CHECK] Prerequisites...")

    if not ORCHESTRATION_AVAILABLE:
        print("  FAIL: Orchestration framework not installed")
        print("  Run: uv tool install jleechanorg-orchestration")
        results["status"] = "failed"
        results["error"] = "Orchestration framework not installed"
        return results
    print("  PASS: Orchestration framework available")

    available, msg = check_cli_available(cli_name)
    if not available:
        print(f"  FAIL: {msg}")
        results["status"] = "failed"
        results["error"] = msg
        return results
    print(f"  PASS: {cli_name} CLI available at {msg}")

    # Setup test directory
    test_dir = setup_test_directory()
    results["test_dir"] = str(test_dir)

    # Create unique identifiers
    run_id = get_timestamp()
    project_key = None
    if project_key_mode == "with":
        project_key = f"/tmp/real_cli_test_project_{run_id}"

    results["run_id"] = run_id
    results["project_key"] = project_key
    results["project_key_mode"] = project_key_mode

    # Create prompts
    prompts = create_agent_prompts(run_id, project_key)

    # Start agents
    print("\n[RUN] Starting agents...")
    processes: list[tuple[dict[str, Any], subprocess.Popen[str], Optional[contextlib.ExitStack]]] = []

    for i, (agent_name, prompt) in enumerate(prompts.items()):
        print(f"\n  Starting {agent_name}...")

        # Stagger agent starts
        if i > 0:
            delay = 2 * i
            print(f"  Waiting {delay}s before starting...")
            if not dry_run:
                time.sleep(delay)

        success, msg, process, output_stack = run_cli_agent(
            cli_name=cli_name,
            agent_name=agent_name,
            prompt=prompt,
            test_dir=test_dir,
            dry_run=dry_run,
        )

        agent_pid = process.pid if process else None
        agent_record: dict[str, Any] = {
            "name": agent_name,
            "started": success,
            "message": msg,
            "pid": agent_pid,
            "exit_code": None,
            "timed_out": False,
            "completed": False,
        }
        agents.append(agent_record)

        if process:
            processes.append((agent_record, process, output_stack))
        elif output_stack:
            output_stack.close()

        if success:
            print(f"  PASS: {msg}")
        else:
            print(f"  FAIL: {msg}")

    # Wait for completion
    if not dry_run and processes:
        print("\n[WAIT] Waiting for agents to complete...")
        for agent_record, process, output_stack in processes:
            try:
                process.wait(timeout=timeout)
                agent_record["exit_code"] = process.returncode
                agent_record["completed"] = True
                status_label = "DONE" if process.returncode == 0 else "FAIL"
                if process.returncode != 0:
                    agent_record["message"] = f"Exited with code {process.returncode}"
                print(f"  {status_label}: {agent_record['name']} (exit code: {process.returncode})")
            except subprocess.TimeoutExpired:
                agent_record["timed_out"] = True
                agent_record["message"] = f"Timed out after {timeout}s"
                print(f"  TIMEOUT: {agent_record['name']} - killing process")
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    agent_record["message"] = f"Timed out after {timeout}s (kill did not terminate in 5s)"
                    agent_record["exit_code"] = process.poll()
                else:
                    agent_record["exit_code"] = process.returncode
            finally:
                if output_stack:
                    output_stack.close()

    # Collect evidence
    print("\n[EVIDENCE] Collecting results...")

    # Save test summary
    summary_file = test_dir / "TEST_SUMMARY.txt"
    summary_text = f"""Real CLI Multi-Agent Coordination Test
======================================

Test Directory: {test_dir}
Timestamp: {results["timestamp"]}
CLI: {cli_name}
Run ID: {run_id}
Project key mode: {project_key_mode}
Project key: {project_key if project_key else "(none)"}

Agents:
"""
    for agent in agents:
        status = "PASS"
        if not agent["started"]:
            status = "FAIL"
        elif agent.get("timed_out"):
            status = "TIMEOUT"
        elif agent.get("exit_code") not in (None, 0):
            status = f"FAIL (exit {agent['exit_code']})"

        summary_text += f"  - {agent['name']}: {status} ({agent['message']})\n"

    summary_text += f"""
Message Flow:
  1. FrontendDev -> BackendDev: "Need API endpoint for dashboard"
  2. BackendDev -> DatabaseAdmin: "Need help with user stats query"
  3. BackendDev -> FrontendDev: "Working on it!"
  4. DatabaseAdmin -> BackendDev: "Here's the optimized query..."

Evidence Files:
  - Prompts: {test_dir}/prompts/
  - Outputs: {test_dir}/outputs/
"""

    summary_file.write_text(summary_text)
    print(f"  Summary: {summary_file}")

    # Determine overall status
    all_started = all(a["started"] for a in agents)
    no_timeouts = all(not a.get("timed_out") for a in agents if a["started"])
    exit_codes_ok = all(a.get("exit_code") in (None, 0) for a in agents if a["started"] and not a.get("timed_out"))

    all_success = all_started and no_timeouts and exit_codes_ok
    results["status"] = "success" if all_success else "failed"

    print("\n" + "=" * 70)
    print(f"Test {'PASSED' if results['status'] == 'success' else 'FAILED'}")
    print(f"Evidence: {test_dir}")
    print("=" * 70)

    return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run real CLI multi-agent coordination test using orchestration framework"
    )
    parser.add_argument(
        "--cli",
        choices=["claude", "codex", "gemini"],
        default="claude",
        help="Which CLI to use (default: claude)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually execute CLIs, just show what would run",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout per agent in seconds (default: 120)",
    )
    parser.add_argument(
        "--project-key-mode",
        choices=["with", "without", "both"],
        default="both",
        help="Run with project key, without, or both (default: both)",
    )

    args = parser.parse_args()

    modes = ["with", "without"] if args.project_key_mode == "both" else [args.project_key_mode]
    suite_results: list[dict[str, Any]] = []
    for mode in modes:
        suite_results.append(
            run_multi_agent_test(
                cli_name=args.cli,
                dry_run=args.dry_run,
                timeout=args.timeout,
                project_key_mode=mode,
            )
        )

    all_success = all(result["status"] == "success" for result in suite_results)

    sys.exit(0 if all_success else 1)


if __name__ == "__main__":
    main()
