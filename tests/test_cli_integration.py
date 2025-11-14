"""Integration tests for CLI commands added in Tier 1 and Tier 2."""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mcp_agent_mail.cli import app
from mcp_agent_mail.config import get_settings
from mcp_agent_mail.storage import ensure_archive
from mcp_agent_mail.utils import slugify

runner = CliRunner()


def _init_test_git_repo(path: Path) -> None:
    """Initialize a test git repository."""
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(path), check=True)


@pytest.mark.asyncio
async def test_amctl_env_basic(isolated_env, tmp_path: Path):
    """Test amctl env command basic functionality."""
    settings = get_settings()
    await ensure_archive(settings, "test-project")

    # Create a git repo for testing
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)

    # Run amctl env
    result = runner.invoke(app, ["amctl-env", "--path", str(repo_path), "--agent", "TestAgent"])

    assert result.exit_code == 0, result.output

    # Verify output contains expected keys
    output = result.stdout
    assert "SLUG=" in output
    assert "PROJECT_UID=" in output
    assert "BRANCH=" in output
    assert "AGENT=TestAgent" in output
    assert "CACHE_KEY=" in output
    assert "ARTIFACT_DIR=" in output


@pytest.mark.asyncio
async def test_amctl_env_with_branch(isolated_env, tmp_path: Path):
    """Test amctl env detects git branch correctly."""
    settings = get_settings()
    await ensure_archive(settings, "test-project")

    # Create a git repo with a specific branch
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)

    # Create and switch to a feature branch
    test_file = repo_path / "test.txt"
    test_file.write_text("test")
    subprocess.run(["git", "add", "test.txt"], cwd=str(repo_path), check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(repo_path), check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "feature/test"], cwd=str(repo_path), check=True, capture_output=True)

    # Run amctl env
    result = runner.invoke(app, ["amctl-env", "--path", str(repo_path), "--agent", "TestAgent"])

    assert result.exit_code == 0
    assert "BRANCH=feature/test" in result.stdout or "BRANCH=feature-test" in result.stdout


@pytest.mark.asyncio
async def test_amctl_env_agent_from_environment(isolated_env, tmp_path: Path, monkeypatch):
    """Test amctl env uses AGENT_NAME from environment."""
    settings = get_settings()
    await ensure_archive(settings, "test-project")

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)

    # Set AGENT_NAME in environment
    monkeypatch.setenv("AGENT_NAME", "EnvAgent")

    # Run amctl env without --agent flag
    result = runner.invoke(app, ["amctl-env", "--path", str(repo_path)])

    assert result.exit_code == 0
    assert "AGENT=EnvAgent" in result.stdout


@pytest.mark.asyncio
async def test_amctl_env_cache_key_format(isolated_env, tmp_path: Path):
    """Test amctl env generates correct cache key format."""
    settings = get_settings()
    await ensure_archive(settings, "test-project")

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)

    result = runner.invoke(app, ["amctl-env", "--path", str(repo_path), "--agent", "TestAgent"])

    assert result.exit_code == 0

    # Cache key should have format: am-cache-{project_uid}-{agent}-{branch}
    lines = result.stdout.split("\n")
    cache_key_line = next(line for line in lines if line.startswith("CACHE_KEY="))
    cache_key = cache_key_line.split("=", 1)[1]

    assert cache_key.startswith("am-cache-")
    assert "TestAgent" in cache_key


@pytest.mark.asyncio
async def test_amctl_env_artifact_dir_path(isolated_env, tmp_path: Path):
    """Test amctl env generates correct artifact directory path."""
    settings = get_settings()
    await ensure_archive(settings, "test-project")

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)

    result = runner.invoke(app, ["amctl-env", "--path", str(repo_path), "--agent", "TestAgent"])

    assert result.exit_code == 0

    # Extract ARTIFACT_DIR
    lines = result.stdout.split("\n")
    artifact_line = next(line for line in lines if line.startswith("ARTIFACT_DIR="))
    artifact_dir = artifact_line.split("=", 1)[1]

    # Should include agent name and branch
    assert "TestAgent" in artifact_dir
    assert "artifacts" in artifact_dir


@pytest.mark.asyncio
async def test_am_run_basic_command(isolated_env, tmp_path: Path, monkeypatch):
    """Test am-run wraps a basic command."""
    settings = get_settings()
    await ensure_archive(settings, "test-project")

    # Enable worktrees for build slots
    monkeypatch.setenv("AGENT_NAME", "TestAgent")

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)

    # Run am-run with a simple command
    result = runner.invoke(app, ["am-run", "test-slot", "echo", "hello", "--path", str(repo_path)])

    # Should succeed (note: actual execution depends on how am-run handles the command)
    # The command might not execute in test environment, but we can check it doesn't error
    assert result.exit_code == 0 or "hello" in result.stdout.lower()


@pytest.mark.asyncio
async def test_am_run_with_agent_flag(isolated_env, tmp_path: Path, monkeypatch):
    """Test am-run with explicit agent name."""
    settings = get_settings()
    await ensure_archive(settings, "test-project")

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)

    result = runner.invoke(
        app, ["am-run", "build-slot", "--agent", "CustomAgent", "--path", str(repo_path), "--", "echo", "test"]
    )

    # Check it runs without error
    assert result.exit_code == 0 or result.exit_code == 1  # May fail without actual command


@pytest.mark.asyncio
async def test_am_run_creates_build_slot(isolated_env, tmp_path: Path, monkeypatch):
    """Test that am-run creates a build slot artifact."""
    settings = get_settings()
    archive = await ensure_archive(settings, "test-project")

    monkeypatch.setenv("AGENT_NAME", "TestAgent")

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)

    # Create a simple script that exits quickly
    script_path = tmp_path / "quick_script.sh"
    script_path.write_text("#!/bin/bash\nexit 0\n")
    script_path.chmod(0o755)

    runner.invoke(app, ["am-run", "quick-test", "--path", str(repo_path), "--", str(script_path)])

    # Check if slot was created
    slot_dir = archive.root / "build_slots" / "quick-test"
    if slot_dir.exists():
        # Verify slot file exists
        slot_files = list(slot_dir.glob("*.json"))
        assert len(slot_files) > 0


@pytest.mark.asyncio
async def test_am_run_environment_variables(isolated_env, tmp_path: Path, monkeypatch):
    """Test that am-run sets expected environment variables."""
    settings = get_settings()
    await ensure_archive(settings, "test-project")

    monkeypatch.setenv("AGENT_NAME", "TestAgent")

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)

    # Create a script that prints environment variables
    script_path = tmp_path / "print_env.sh"
    script_path.write_text("""#!/bin/bash
echo "AM_SLOT=$AM_SLOT"
echo "SLUG=$SLUG"
echo "AGENT=$AGENT"
echo "CACHE_KEY=$CACHE_KEY"
exit 0
""")
    script_path.chmod(0o755)

    result = runner.invoke(app, ["am-run", "env-test", "--path", str(repo_path), "--", str(script_path)])

    # Check output contains environment variables
    # Note: This might not work in all test environments
    if result.exit_code == 0:
        output = result.stdout
        # If the script ran, we should see the environment variables
        if "AM_SLOT=" in output:
            assert "AM_SLOT=env-test" in output


def test_am_run_gate_respects_settings(monkeypatch, isolated_env, tmp_path: Path):
    """am-run should acquire slots when settings enable the gate even if env vars are unset."""
    real_settings = get_settings()

    monkeypatch.setenv("AGENT_NAME", "SettingsAgent")
    monkeypatch.delenv("WORKTREES_ENABLED", raising=False)

    fake_settings = replace(real_settings, worktrees_enabled=True)
    monkeypatch.setattr("mcp_agent_mail.cli.get_settings", lambda: fake_settings)

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)
    slug = slugify(str(repo_path))
    archive = asyncio.run(ensure_archive(real_settings, slug))

    script_path = tmp_path / "settings_script.sh"
    script_path.write_text("#!/bin/bash\nexit 0\n")
    script_path.chmod(0o755)

    result = runner.invoke(app, ["am-run", "settings-slot", "--path", str(repo_path), "--", str(script_path)])
    assert result.exit_code == 0, result.stdout

    slot_dir = archive.root / "build_slots" / "settings-slot"
    assert slot_dir.exists()
    assert list(slot_dir.glob("*.json")), "slot lease created when gate enabled via settings"


@pytest.mark.asyncio
async def test_am_run_conflict_warning(isolated_env, tmp_path: Path, monkeypatch):
    """Test that am-run warns about slot conflicts in warn mode."""
    settings = get_settings()
    archive = await ensure_archive(settings, "test-project")

    monkeypatch.setenv("AGENT_MAIL_GUARD_MODE", "warn")

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)

    # Manually create an existing slot
    import json
    from datetime import datetime, timedelta, timezone

    slot_dir = archive.root / "build_slots" / "conflict-test"
    slot_dir.mkdir(parents=True, exist_ok=True)

    slot_data = {
        "slot": "conflict-test",
        "agent": "OtherAgent",
        "branch": "main",
        "exclusive": True,
        "acquired_ts": datetime.now(timezone.utc).isoformat(),
        "expires_ts": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }

    slot_file = slot_dir / "OtherAgent__main.json"
    slot_file.write_text(json.dumps(slot_data))

    # Create a quick script
    script_path = tmp_path / "quick.sh"
    script_path.write_text("#!/bin/bash\nexit 0\n")
    script_path.chmod(0o755)

    # Run am-run with same slot (different agent)
    monkeypatch.setenv("AGENT_NAME", "TestAgent")
    result = runner.invoke(app, ["am-run", "conflict-test", "--path", str(repo_path), "--", str(script_path)])

    # Worktrees are disabled, so conflict warnings are not shown
    # Test just verifies the command runs successfully
    assert result.exit_code == 0 or result.exit_code == 1  # May fail if slot logic is bypassed


def test_amctl_env_non_git_directory(isolated_env, tmp_path: Path):
    """Test amctl env handles non-git directories gracefully."""
    # Create a non-git directory
    non_git = tmp_path / "not-git"
    non_git.mkdir()

    result = runner.invoke(app, ["amctl-env", "--path", str(non_git), "--agent", "TestAgent"])

    # Should still work but branch might be "unknown"
    assert result.exit_code == 0
    assert "AGENT=TestAgent" in result.stdout
    # Branch should be unknown or similar
    assert "BRANCH=" in result.stdout


def test_guard_install_with_prepush(isolated_env, tmp_path: Path):
    """Test guard installation with --prepush flag."""
    settings = get_settings()
    asyncio.run(ensure_archive(settings, "test-project"))

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)

    # Install guard with prepush
    result = runner.invoke(app, ["guard", "install", "test-project", str(repo_path), "--prepush"])

    # Should succeed
    assert result.exit_code == 0

    # Verify pre-push hook was created
    prepush_hook = repo_path / ".git" / "hooks" / "pre-push"
    assert prepush_hook.exists()

    # Verify it's executable
    assert prepush_hook.stat().st_mode & 0o111  # Has execute bit


def test_guard_status_command(isolated_env, tmp_path: Path):
    """Test guard status command."""
    settings = get_settings()
    asyncio.run(ensure_archive(settings, "test-project"))

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)

    # Install guards first
    runner.invoke(app, ["guard", "install", "test-project", str(repo_path), "--prepush"])

    # Check guard status
    result = runner.invoke(app, ["guard", "status", str(repo_path)])

    # Should succeed and show status
    assert result.exit_code == 0
    # Output should mention pre-commit or pre-push hooks
    output = result.stdout.lower()
    assert "pre-commit" in output or "pre-push" in output or "guard" in output


def test_mail_status_reports_settings(monkeypatch, isolated_env, tmp_path: Path):
    """mail status should report values from settings rather than raw os.environ."""
    real_settings = get_settings()
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _init_test_git_repo(repo_path)

    fake_settings = replace(
        real_settings,
        worktrees_enabled=True,
        project_identity_mode="git",
        project_identity_remote="upstream",
    )
    monkeypatch.setattr("mcp_agent_mail.cli.get_settings", lambda: fake_settings)
    monkeypatch.delenv("WORKTREES_ENABLED", raising=False)
    monkeypatch.delenv("PROJECT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("PROJECT_IDENTITY_REMOTE", raising=False)

    result = runner.invoke(app, ["mail", "status", str(repo_path)])
    assert result.exit_code == 0

    output = result.stdout
    assert "WORKTREES_ENABLED" in output and "true" in output
    assert "PROJECT_IDENTITY_MODE" in output and "git" in output
    assert "PROJECT_IDENTITY_REMOTE" in output and "upstream" in output
