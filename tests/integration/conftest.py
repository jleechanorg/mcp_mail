"""Shared fixtures for integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.config import get_settings

# Import git utilities - consolidates scattered subprocess calls
from tests.integration.git_utils import GitRunner, init_git_repo as _init_git_repo


@pytest.fixture
async def mcp_server_with_storage(isolated_env, tmp_path):
    """Create an MCP server instance with isolated storage."""
    settings = get_settings()

    # Create storage directory structure
    storage_root = Path(settings.storage.root)
    storage_root.mkdir(parents=True, exist_ok=True)

    # Build server
    server = build_mcp_server()

    return server


@pytest.fixture
async def mcp_client(mcp_server_with_storage):
    """Create an MCP client connected to the test server."""
    async with Client(mcp_server_with_storage) as client:
        yield client


def init_git_repo(path: Path) -> None:
    """Initialize a git repository with basic configuration.

    This function wraps the git_utils.init_git_repo for backward compatibility
    with existing tests. Unlike the underlying utility, this wrapper returns
    None. Use the git_repo fixture if you need a GitRunner instance.

    Args:
        path: Path to initialize as a git repository
    """
    _init_git_repo(path)


@pytest.fixture
def git_repo(tmp_path) -> GitRunner:
    """Provide a pre-initialized git repository for testing.

    Returns:
        GitRunner instance for the initialized repository
    """
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    return _init_git_repo(repo_path)
