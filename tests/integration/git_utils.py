"""Git utilities for integration tests.

This module consolidates git operations used across integration tests,
replacing scattered subprocess calls with a clean, reusable interface.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional


class GitRunner:
    """Execute git commands safely with consistent configuration.

    Uses shell=False for security and provides consistent error handling.
    """

    def __init__(self, cwd: Path):
        """Initialize git runner with working directory.

        Args:
            cwd: Working directory for git commands
        """
        self.cwd = cwd

    def run(
        self,
        *args: str,
        check: bool = True,
        capture_output: bool = True,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command safely.

        Args:
            args: Git command arguments (e.g., "init", "add", ".")
            check: Raise exception on non-zero exit
            capture_output: Capture stdout/stderr
            timeout: Command timeout in seconds

        Returns:
            CompletedProcess with command results
        """
        return subprocess.run(
            ["git", *args],
            cwd=str(self.cwd),
            check=check,
            capture_output=capture_output,
            shell=False,
            text=True,
            timeout=timeout,
        )

    def init(self) -> subprocess.CompletedProcess[str]:
        """Initialize a git repository."""
        return self.run("init")

    def config(self, key: str, value: str) -> subprocess.CompletedProcess[str]:
        """Set git config value."""
        return self.run("config", key, value)

    def add(self, *paths: str) -> subprocess.CompletedProcess[str]:
        """Stage files."""
        return self.run("add", *paths)

    def commit(self, message: str) -> subprocess.CompletedProcess[str]:
        """Create a commit."""
        return self.run("commit", "-m", message)

    def checkout(self, ref: str, create: bool = False) -> subprocess.CompletedProcess[str]:
        """Checkout a branch or commit."""
        if create:
            return self.run("checkout", "-b", ref)
        return self.run("checkout", ref)

    def log(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run git log."""
        return self.run("log", *args)

    def rev_parse(self, ref: str) -> str:
        """Get commit SHA for a reference."""
        result = self.run("rev-parse", ref)
        return result.stdout.strip()

    def branch_name(self) -> Optional[str]:
        """Get current branch name or None if detached HEAD."""
        result = self.run("branch", "--show-current")
        return result.stdout.strip() or None


def init_git_repo(
    path: Path,
    user_email: str = "test@example.com",
    user_name: str = "Test Agent",
    disable_gpgsign: bool = True,
) -> GitRunner:
    """Initialize a git repository with standard test configuration.

    This function consolidates the repeated git initialization code
    found throughout integration tests.

    Args:
        path: Path to initialize as a git repository
        user_email: Git user email for commits
        user_name: Git user name for commits
        disable_gpgsign: Disable GPG signing for commits

    Returns:
        GitRunner instance for the initialized repository
    """
    git = GitRunner(path)
    git.init()
    git.config("user.email", user_email)
    git.config("user.name", user_name)
    if disable_gpgsign:
        git.config("commit.gpgsign", "false")
    return git


def create_mcp_mail_repo(
    path: Path,
    initial_commit: bool = True,
) -> GitRunner:
    """Create a git repository with .mcp_mail/ directory structure.

    This sets up the standard .mcp_mail/ directory structure used
    for testing the messaging system.

    Args:
        path: Path for the repository
        initial_commit: Whether to create an initial commit

    Returns:
        GitRunner instance for the repository
    """
    path.mkdir(parents=True, exist_ok=True)
    mcp_mail_dir = path / ".mcp_mail"
    mcp_mail_dir.mkdir(exist_ok=True)

    git = init_git_repo(path)

    # Create .mcp_mail/ structure
    (mcp_mail_dir / ".gitignore").write_text("*.db\n*.db-shm\n*.db-wal\n")
    (mcp_mail_dir / "messages.jsonl").write_text("")

    if initial_commit:
        git.add(".")
        git.commit("Initial commit")

    return git


def commit_with_file(
    git: GitRunner,
    filename: str,
    content: str,
    commit_message: Optional[str] = None,
) -> str:
    """Create a file, stage it, and commit.

    Args:
        git: GitRunner instance
        filename: Relative path for the file
        content: File content
        commit_message: Commit message (defaults to "Add {filename}")

    Returns:
        Commit SHA
    """
    file_path = git.cwd / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)

    git.add(filename)
    message = commit_message or f"Add {filename}"
    git.commit(message)

    return git.rev_parse("HEAD")
