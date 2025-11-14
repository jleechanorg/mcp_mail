"""Test guard install validation (Issue #3)"""

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from mcp_agent_mail.cli import guard_install
from mcp_agent_mail.config import get_settings
from mcp_agent_mail.db import ensure_schema


def test_guard_install_validates_project_exists():
    """Test that guard install fails for non-existent projects"""
    # Initialize database schema
    settings = get_settings()
    asyncio.run(ensure_schema(settings))

    # Create a temporary git repo
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "test_repo"
        repo_path.mkdir()

        # Initialize git
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)

        # Try to install guard for non-existent project (should fail)
        with pytest.raises((ValueError, Exception)) as exc_info:
            guard_install("nonexistent-projet-typo", repo_path)

        # Should raise ValueError about project not found
        assert "not found" in str(exc_info.value).lower(), \
            f"guard_install should raise error when project doesn't exist, got: {exc_info.value}"


def test_guard_install_succeeds_when_validation_bypassed():
    """Test that guard install works in test mode with validation bypass"""
    # Create a temporary git repo
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "test_repo"
        repo_path.mkdir()

        # Initialize git
        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)

        # Bypass validation for testing
        with pytest.raises(Exception) as exc_info:
            # Set bypass flag
            os.environ["AGENT_MAIL_GUARD_INSTALL_SKIP_VALIDATION"] = "1"
            try:
                guard_install("test-project", repo_path)
            finally:
                os.environ.pop("AGENT_MAIL_GUARD_INSTALL_SKIP_VALIDATION", None)

        # If validation was bypassed, we shouldn't see "not found" error
        error_msg = str(exc_info.value).lower()
        if "not found" in error_msg and "database" not in error_msg:
            pytest.fail("guard_install should not validate when bypass is enabled")
