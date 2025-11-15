"""Tests for pre-push guard functionality."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from mcp_agent_mail.config import get_settings
from mcp_agent_mail.guard import render_prepush_script
from mcp_agent_mail.storage import ensure_archive, write_file_reservation_record


def _init_git_repo(repo_path: Path) -> None:
    """Initialize a git repository with dummy config."""
    subprocess.run(["git", "init"], cwd=str(repo_path), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_path), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo_path), check=True)


def _create_commit(repo_path: Path, filename: str, content: str = "test") -> None:
    """Create a file and commit it."""
    file_path = repo_path / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)

    subprocess.run(["git", "add", filename], cwd=str(repo_path), check=True)
    subprocess.run(
        ["git", "commit", "-m", f"Add {filename}"],
        cwd=str(repo_path),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _resolve_local_sha(repo_path: Path, local_ref: str) -> str:
    """Return a commit SHA for the requested ref, falling back to HEAD if needed."""
    branch_name = local_ref.split("/")[-1]
    for candidate in (branch_name, "HEAD"):
        result = subprocess.run(
            ["git", "rev-parse", candidate],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    raise RuntimeError(f"Unable to resolve commit for {local_ref} in {repo_path}")


def _run_prepush_hook(
    script_path: Path,
    repo_path: Path,
    agent_name: str,
    local_ref: str = "refs/heads/main",
    remote_ref: str = "refs/heads/main",
) -> subprocess.CompletedProcess:
    """Run the pre-push hook script."""
    # Get the local SHA
    local_sha = _resolve_local_sha(repo_path, local_ref)

    # Simulate pre-push hook stdin
    # Format: <local ref> <local sha> <remote ref> <remote sha>
    hook_input = f"{local_ref} {local_sha} {remote_ref} 0000000000000000000000000000000000000000\n"

    env = os.environ.copy()
    env["AGENT_NAME"] = agent_name
    env["WORKTREES_ENABLED"] = "1"

    return subprocess.run(
        ["python", str(script_path)],
        cwd=str(repo_path),
        env=env,
        input=hook_input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _skip_presubmit_in_script(script_text):
    """Remove presubmit commands from generated scripts during tests."""
    # Find and remove the PRESUBMIT_COMMANDS block
    lines = script_text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip from PRESUBMIT_COMMANDS until # Gate
        if "PRESUBMIT_COMMANDS = (" in line:
            # Skip until we find '# Gate'
            start_i = i
            while i < len(lines) and "# Gate" not in lines[i]:
                i += 1
            if i >= len(lines):
                raise ValueError(f"Could not find '# Gate' comment after PRESUBMIT_COMMANDS at line {start_i}")
            # Now i points to '# Gate' line, add it
            result.append(lines[i])
            i += 1
            continue
        result.append(line)
        i += 1

    return "\n".join(result)


@pytest.mark.asyncio
async def test_prepush_no_conflicts(isolated_env, tmp_path: Path):
    """Test pre-push guard with no file reservation conflicts."""
    settings = get_settings()
    archive = await ensure_archive(settings, "myproject")

    # Render pre-push script
    script_text = _skip_presubmit_in_script(render_prepush_script(archive))
    script_path = tmp_path / "prepush.py"
    script_path.write_text(script_text)

    # Create a git repo and make a commit
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_commit(repo_path, "src/app.py", "print('hello')")

    # Run pre-push hook - should pass with no reservations
    proc = _run_prepush_hook(script_path, repo_path, "TestAgent")
    assert proc.returncode == 0, proc.stderr


@pytest.mark.asyncio
async def test_prepush_conflict_detected(isolated_env, tmp_path: Path):
    """Test pre-push guard detects conflicts with file reservations."""
    settings = get_settings()
    archive = await ensure_archive(settings, "myproject")

    # Create a file reservation held by another agent
    await write_file_reservation_record(
        archive,
        {
            "agent": "OtherAgent",
            "path_pattern": "src/app.py",
            "exclusive": True,
        },
    )

    # Render pre-push script
    script_text = _skip_presubmit_in_script(render_prepush_script(archive))
    script_path = tmp_path / "prepush.py"
    script_path.write_text(script_text)

    # Create a git repo and make a commit touching the reserved file
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_commit(repo_path, "src/app.py", "print('modified')")

    # Run pre-push hook - should block
    proc = _run_prepush_hook(script_path, repo_path, "TestAgent")
    assert proc.returncode == 1
    assert "Exclusive file_reservation conflicts" in proc.stderr


@pytest.mark.asyncio
async def test_prepush_warn_mode(isolated_env, tmp_path: Path):
    """Test pre-push guard in warn mode (advisory only)."""
    settings = get_settings()
    archive = await ensure_archive(settings, "myproject")

    # Create a file reservation
    await write_file_reservation_record(
        archive,
        {
            "agent": "OtherAgent",
            "path_pattern": "src/*.py",
            "exclusive": True,
        },
    )

    # Render pre-push script
    script_text = _skip_presubmit_in_script(render_prepush_script(archive))
    script_path = tmp_path / "prepush.py"
    script_path.write_text(script_text)

    # Create a git repo and make a commit
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_commit(repo_path, "src/main.py", "print('hello')")

    # Run pre-push hook in warn mode
    env = os.environ.copy()
    env["AGENT_NAME"] = "TestAgent"
    env["WORKTREES_ENABLED"] = "1"
    env["AGENT_MAIL_GUARD_MODE"] = "warn"

    local_sha = _resolve_local_sha(repo_path, "refs/heads/main")

    hook_input = f"refs/heads/main {local_sha} refs/heads/main 0000000000000000000000000000000000000000\n"

    proc = subprocess.run(
        ["python", str(script_path)],
        cwd=str(repo_path),
        env=env,
        input=hook_input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Should pass in warn mode but print warning
    assert proc.returncode == 0
    assert "advisory mode" in proc.stderr.lower()


@pytest.mark.asyncio
async def test_prepush_multiple_commits(isolated_env, tmp_path: Path):
    """Test pre-push guard checks all commits in push."""
    settings = get_settings()
    archive = await ensure_archive(settings, "myproject")

    # Create a file reservation
    await write_file_reservation_record(
        archive,
        {
            "agent": "OtherAgent",
            "path_pattern": "src/config.py",
            "exclusive": True,
        },
    )

    # Render pre-push script
    script_text = _skip_presubmit_in_script(render_prepush_script(archive))
    script_path = tmp_path / "prepush.py"
    script_path.write_text(script_text)

    # Create a git repo with multiple commits
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)

    # First commit - safe
    _create_commit(repo_path, "src/app.py", "print('hello')")

    # Second commit - conflicts with reservation
    _create_commit(repo_path, "src/config.py", "DB_HOST = 'localhost'")

    # Third commit - safe again
    _create_commit(repo_path, "src/utils.py", "def helper(): pass")

    # Run pre-push hook - should detect conflict in second commit
    proc = _run_prepush_hook(script_path, repo_path, "TestAgent")
    assert proc.returncode == 1
    assert "src/config.py" in proc.stderr


@pytest.mark.asyncio
async def test_prepush_glob_pattern_matching(isolated_env, tmp_path: Path):
    """Test pre-push guard with glob pattern file reservations."""
    settings = get_settings()
    archive = await ensure_archive(settings, "myproject")

    # Create a glob pattern reservation
    await write_file_reservation_record(
        archive,
        {
            "agent": "OtherAgent",
            "path_pattern": "tests/**/*.py",
            "exclusive": True,
        },
    )

    # Render pre-push script
    script_text = _skip_presubmit_in_script(render_prepush_script(archive))
    script_path = tmp_path / "prepush.py"
    script_path.write_text(script_text)

    # Create a git repo
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)

    # Commit a file matching the glob pattern
    _create_commit(repo_path, "tests/unit/test_foo.py", "def test_foo(): pass")

    # Run pre-push hook - should detect conflict
    proc = _run_prepush_hook(script_path, repo_path, "TestAgent")
    assert proc.returncode == 1


@pytest.mark.asyncio
async def test_prepush_gate_disabled(isolated_env, tmp_path: Path):
    """Test pre-push guard exits early when WORKTREES_ENABLED=0."""
    settings = get_settings()
    archive = await ensure_archive(settings, "myproject")

    # Create a file reservation
    await write_file_reservation_record(
        archive,
        {
            "agent": "OtherAgent",
            "path_pattern": "**/*.py",
            "exclusive": True,
        },
    )

    # Render pre-push script
    script_text = _skip_presubmit_in_script(render_prepush_script(archive))
    script_path = tmp_path / "prepush.py"
    script_path.write_text(script_text)

    # Create a git repo
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_commit(repo_path, "src/app.py", "print('test')")

    # Run pre-push hook with gate disabled
    env = os.environ.copy()
    env["AGENT_NAME"] = "TestAgent"
    env["WORKTREES_ENABLED"] = "0"

    local_sha = _resolve_local_sha(repo_path, "refs/heads/main")

    hook_input = f"refs/heads/main {local_sha} refs/heads/main 0000000000000000000000000000000000000000\n"

    proc = subprocess.run(
        ["python", str(script_path)],
        cwd=str(repo_path),
        env=env,
        input=hook_input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Should pass when gate is disabled
    assert proc.returncode == 0


@pytest.mark.asyncio
async def test_prepush_self_reservation_allowed(isolated_env, tmp_path: Path):
    """Test that agent can push changes to files they have reserved."""
    settings = get_settings()
    archive = await ensure_archive(settings, "myproject")

    # Agent reserves a file for themselves
    await write_file_reservation_record(
        archive,
        {
            "agent": "TestAgent",
            "path_pattern": "src/app.py",
            "exclusive": True,
        },
    )

    # Render pre-push script
    script_text = _skip_presubmit_in_script(render_prepush_script(archive))
    script_path = tmp_path / "prepush.py"
    script_path.write_text(script_text)

    # Create a git repo and modify the reserved file
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_git_repo(repo_path)
    _create_commit(repo_path, "src/app.py", "print('my changes')")

    # Run pre-push hook with same agent name
    proc = _run_prepush_hook(script_path, repo_path, "TestAgent")

    # Should pass - agent can push changes to their own reservations
    assert proc.returncode == 0
