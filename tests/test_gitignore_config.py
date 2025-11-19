"""Test that .mcp_mail/.gitignore is correctly configured.

This test prevents regression of the bug where projects/ was incorrectly
added to .gitignore, blocking all agent messages from being tracked in git.

See commit cd86cdd (bug) and b7fde71 (fix).
"""

from __future__ import annotations

from pathlib import Path


def test_mcp_mail_gitignore_does_not_ignore_projects():
    """Ensure .mcp_mail/.gitignore does NOT ignore projects/ directory.

    Bug context:
    - Commit cd86cdd incorrectly added 'projects/' to .mcp_mail/.gitignore
    - This blocked ALL agent messages from being tracked in git
    - Messages are stored in .mcp_mail/projects/<slug>/messages/YYYY/MM/<id>.md
    - Documentation promises messages are "committed alongside code" (README.md:144)

    This test ensures that critical bug doesn't happen again.
    """
    gitignore_path = Path(__file__).parent.parent / ".mcp_mail" / ".gitignore"

    # .mcp_mail/.gitignore must exist
    assert gitignore_path.exists(), ".mcp_mail/.gitignore not found"

    gitignore_content = gitignore_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in gitignore_content.splitlines()]

    # CRITICAL: projects/ must NOT be in .gitignore
    # Messages are stored in projects/<slug>/messages/ and MUST be tracked
    assert "projects/" not in lines, (
        "BUG: 'projects/' found in .mcp_mail/.gitignore! "
        "This blocks agent messages from being tracked in git. "
        "Messages in .mcp_mail/projects/<slug>/messages/ must be committable. "
        "See README.md line 144: 'All agent conversations committed alongside code'"
    )

    # Verify SQLite cache IS correctly ignored (these should be present)
    assert "*.db" in lines, "*.db should be in .gitignore (SQLite cache is local-only)"
    assert "*.db-shm" in lines, "*.db-shm should be in .gitignore"
    assert "*.db-wal" in lines, "*.db-wal should be in .gitignore"

    # Verify test artifacts ARE correctly ignored
    assert ".gitattributes" in lines, ".gitattributes should be in .gitignore (test artifact)"


def test_mcp_mail_gitignore_allows_messages_to_be_tracked():
    """Verify that message files in projects/ would be tracked by git.

    This is an integration-style test that creates a dummy message structure
    and verifies it's not gitignored.
    """
    import subprocess

    # Create a temporary test message file structure
    project_root = Path(__file__).parent.parent
    test_msg_path = project_root / ".mcp_mail" / "projects" / "test-proj" / "messages" / "2025" / "11" / "test.md"

    try:
        # Create the directory structure
        test_msg_path.parent.mkdir(parents=True, exist_ok=True)
        test_msg_path.write_text("# Test message\n", encoding="utf-8")

        # Use git check-ignore to verify the file is NOT ignored
        result = subprocess.run(
            ["git", "check-ignore", "-v", str(test_msg_path)],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )

        # git check-ignore exits with 0 if file IS ignored, 1 if NOT ignored
        # We want exit code 1 (file is NOT ignored)
        assert result.returncode == 1, (
            f"Message file {test_msg_path} is being ignored by git! "
            f"git check-ignore output: {result.stdout}\n"
            "This means agent messages won't be committed to the repository."
        )

    finally:
        # Cleanup: remove test files
        if test_msg_path.exists():
            test_msg_path.unlink()
        # Remove empty directories
        try:
            test_msg_path.parent.rmdir()  # 11/
            test_msg_path.parent.parent.rmdir()  # 2025/
            test_msg_path.parent.parent.parent.rmdir()  # messages/
            test_msg_path.parent.parent.parent.parent.rmdir()  # test-proj/
            # Don't remove projects/ itself as it might be used elsewhere
        except OSError:
            pass  # Directory not empty or already removed
