"""Integration tests for project-key anchored storage."""

from __future__ import annotations

import subprocess

import pytest
from fastmcp import Client

from mcp_agent_mail import config as _config
from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.db import ensure_schema
from mcp_agent_mail.storage import ProjectStorageResolutionError, ensure_archive
from mcp_agent_mail.utils import slugify


@pytest.fixture
async def project_repo_env(tmp_path, monkeypatch):
    """Set up a real git repo and enable project-key storage."""

    project_dir = tmp_path / "project-repo"
    project_dir.mkdir()
    subprocess.run(["git", "init"], check=True, cwd=project_dir, capture_output=True)

    archive_root = project_dir / ".mcp_mail"
    db_path = archive_root / "storage.sqlite3"
    archive_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("STORAGE_PROJECT_KEY_ENABLED", "true")
    monkeypatch.setenv("STORAGE_LOCAL_ARCHIVE_ENABLED", "true")
    monkeypatch.setenv("STORAGE_ROOT", ".mcp_mail")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test-agent")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")

    _config.clear_settings_cache()
    await ensure_schema()

    yield {"project_dir": project_dir, "db_path": db_path}

    _config.clear_settings_cache()


@pytest.mark.asyncio
async def test_project_key_storage_writes_into_repo(project_repo_env):
    project_dir = project_repo_env["project_dir"]
    slug = slugify(str(project_dir))

    server = build_mcp_server()

    async with Client(server) as client:
        await client.call_tool(
            "register_agent",
            arguments={
                "project_key": str(project_dir),
                "program": "sender",
                "model": "test",
                "name": "Sender",
                "task_description": "sends",
            },
        )
        await client.call_tool(
            "register_agent",
            arguments={
                "project_key": str(project_dir),
                "program": "receiver",
                "model": "test",
                "name": "Receiver",
                "task_description": "receives",
            },
        )
        await client.call_tool(
            "send_message",
            arguments={
                "project_key": str(project_dir),
                "sender_name": "Sender",
                "to": ["Receiver"],
                "subject": "Repo-local message",
                "body_md": "Stored next to the repo.",
            },
        )

    archive_root = project_dir / ".mcp_mail"
    message_dir = archive_root / "projects" / slug / "messages"
    assert archive_root.exists(), "Archive root should be created inside the project repo"
    assert message_dir.exists(), "Messages should be written under the project repo archive"
    assert list(message_dir.rglob("*.md")), "Message markdown should exist for the project"


@pytest.mark.asyncio
async def test_project_key_storage_requires_git_repo(tmp_path, monkeypatch):
    project_dir = tmp_path / "no-git"
    project_dir.mkdir()

    fallback_root = tmp_path / "fallback-archive"
    fallback_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("STORAGE_PROJECT_KEY_ENABLED", "true")
    monkeypatch.setenv("STORAGE_PROJECT_KEY_PROMPT_ENABLED", "true")
    monkeypatch.setenv("STORAGE_LOCAL_ARCHIVE_ENABLED", "false")
    monkeypatch.setenv("STORAGE_ROOT", str(fallback_root))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{fallback_root}/storage.sqlite3")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test-agent")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")

    _config.clear_settings_cache()
    await ensure_schema()

    server = build_mcp_server()

    with pytest.raises(Exception) as excinfo:
        async with Client(server) as client:
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": str(project_dir),
                    "program": "sender",
                    "model": "test",
                    "name": "Sender",
                    "task_description": "sends",
                },
            )

    message = str(excinfo.value)
    assert "project-key storage" in message.lower() or "project storage" in message.lower()
    assert "prompt" in message.lower() or "choose" in message.lower()
    assert str(project_dir) in message

    _config.clear_settings_cache()


@pytest.mark.asyncio
async def test_project_key_prompt_includes_options(tmp_path, monkeypatch):
    missing = tmp_path / "missing"

    monkeypatch.setenv("STORAGE_PROJECT_KEY_ENABLED", "true")
    monkeypatch.setenv("STORAGE_PROJECT_KEY_PROMPT_ENABLED", "true")
    monkeypatch.setenv("STORAGE_LOCAL_ARCHIVE_ENABLED", "true")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "default-archive"))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test-agent")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")

    _config.clear_settings_cache()
    settings = _config.get_settings()

    slug = slugify(str(missing))
    with pytest.raises(ProjectStorageResolutionError) as excinfo:
        await ensure_archive(settings, slug, project_key=str(missing))

    err = excinfo.value
    prompt = getattr(err, "prompt", {})
    assert prompt.get("kind") == "project_storage_resolution"
    assert any(opt.get("id") == "use_default_archive" for opt in prompt.get("options", []))
    assert any(opt.get("id") == "retry_with_repo_root" for opt in prompt.get("options", []))
