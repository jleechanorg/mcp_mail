"""Shared fixtures for integration tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.config import get_settings


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

    Args:
        path: Path to initialize as a git repository
    """
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test Agent"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=path,
        check=True,
        capture_output=True,
    )
