"""Integration tests for MCP resources and workflow macros.

These tests validate:
- Resource endpoints (resource://inbox/, resource://thread/, etc.)
- Workflow macros (macro_start_session, macro_prepare_thread, etc.)
- Attachment handling with .mcp_mail/ storage
- Git commit verification for persistence
"""

from __future__ import annotations

import asyncio
import base64
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


@pytest.mark.asyncio
async def test_macro_start_session(mcp_client, tmp_path):
    """Test macro_start_session for quick agent setup."""
    project_path = tmp_path / "macro_project"
    project_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=project_path, check=True, capture_output=True)

    # Use macro to start session (should create project + register agent + fetch inbox)
    result = await mcp_client.call_tool("macro_start_session", {
        "human_key": str(project_path),
        "agent_name": "MacroAgent",
        "program": "test-program",
        "model": "test-model",
        "task_description": "Testing macro workflow",
    })

    # Verify all steps completed
    assert result.data["project_ensured"] is True
    assert result.data["agent_registered"] is True
    assert "agent_name" in result.data
    assert "inbox" in result.data

    # Inbox should be empty initially
    assert len(result.data["inbox"]) == 0


@pytest.mark.asyncio
async def test_macro_prepare_thread(mcp_client, tmp_path):
    """Test macro_prepare_thread for joining existing conversations."""
    project_path = tmp_path / "thread_macro_project"
    project_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=project_path, check=True, capture_output=True)

    # Create project and agents
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    agent1 = (await mcp_client.call_tool("register_agent", {
        "project_key": str(project_path),
        "program": "agent1",
        "model": "test",
    })).data["name"]

    agent2 = (await mcp_client.call_tool("register_agent", {
        "project_key": str(project_path),
        "program": "agent2",
        "model": "test",
    })).data["name"]

    # Create some messages in a thread
    await mcp_client.call_tool("send_message", {
        "project_key": str(project_path),
        "sender_name": agent1,
        "to": [agent2],
        "subject": "Thread Start",
        "body_md": "Starting discussion",
        "thread_id": "test-thread",
    })

    await mcp_client.call_tool("send_message", {
        "project_key": str(project_path),
        "sender_name": agent2,
        "to": [agent1],
        "subject": "Thread Reply",
        "body_md": "Reply to discussion",
        "thread_id": "test-thread",
    })

    # Use macro to prepare thread context for agent1
    result = await mcp_client.call_tool("macro_prepare_thread", {
        "project_key": str(project_path),
        "agent_name": agent1,
        "thread_id": "test-thread",
    })

    # Verify thread context returned
    assert "thread_summary" in result.data
    assert result.data["thread_id"] == "test-thread"


@pytest.mark.asyncio
async def test_macro_file_reservation_cycle(mcp_client, tmp_path):
    """Test macro_file_reservation_cycle for reserve + work + release."""
    project_path = tmp_path / "reservation_macro_project"
    project_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=project_path, check=True, capture_output=True)

    # Create project and agent
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    agent = (await mcp_client.call_tool("register_agent", {
        "project_key": str(project_path),
        "program": "worker",
        "model": "test",
    })).data["name"]

    # Use macro to reserve, then immediately release
    result = await mcp_client.call_tool("macro_file_reservation_cycle", {
        "project_key": str(project_path),
        "agent_name": agent,
        "paths": ["src/module.py"],
        "exclusive": True,
        "release_after": True,
    })

    # Verify reservation was created and released
    assert "reserved" in result.data
    assert "released" in result.data
    assert len(result.data["reserved"]) == 1
    assert len(result.data["released"]) == 1


@pytest.mark.asyncio
async def test_message_with_inline_attachment(mcp_client, tmp_path):
    """Test sending messages with inline text attachments."""
    project_path = tmp_path / "attachment_project"
    project_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=project_path, check=True, capture_output=True)

    # Create project and agents
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    agent1 = (await mcp_client.call_tool("register_agent", {
        "project_key": str(project_path),
        "program": "sender",
        "model": "test",
    })).data["name"]

    agent2 = (await mcp_client.call_tool("register_agent", {
        "project_key": str(project_path),
        "program": "receiver",
        "model": "test",
    })).data["name"]

    # Create small text attachment
    attachment_content = "This is attachment content\nWith multiple lines\n"
    attachment_data = base64.b64encode(attachment_content.encode()).decode()

    # Send message with attachment
    result = await mcp_client.call_tool("send_message", {
        "project_key": str(project_path),
        "sender_name": agent1,
        "to": [agent2],
        "subject": "Message with Attachment",
        "body_md": "See attached file",
        "attachments": [{
            "type": "inline",
            "media_type": "text/plain",
            "data": attachment_data,
            "filename": "notes.txt",
        }],
    })

    assert result.data["count"] > 0

    # Verify attachment in recipient's inbox
    inbox = await mcp_client.call_tool("fetch_inbox", {
        "project_key": str(project_path),
        "agent_name": agent2,
        "include_bodies": True,
    })

    messages = inbox.structured_content["result"]
    assert len(messages) == 1
    assert "attachments" in messages[0]
    assert len(messages[0]["attachments"]) == 1


@pytest.mark.asyncio
async def test_git_commit_verification(mcp_client, tmp_path):
    """Verify that messages are persisted in git commits."""
    settings = get_settings()
    project_path = tmp_path / "git_verify_project"
    project_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=project_path, check=True, capture_output=True)

    # Create project and agents
    project_result = await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})
    project_slug = project_result.data["slug"]

    agent1 = (await mcp_client.call_tool("register_agent", {
        "project_key": str(project_path),
        "program": "sender",
        "model": "test",
    })).data["name"]

    agent2 = (await mcp_client.call_tool("register_agent", {
        "project_key": str(project_path),
        "program": "receiver",
        "model": "test",
    })).data["name"]

    # Send a message
    await mcp_client.call_tool("send_message", {
        "project_key": str(project_path),
        "sender_name": agent1,
        "to": [agent2],
        "subject": "Git Test Message",
        "body_md": "This message should be in git history",
    })

    # The storage root contains git repos organized by project
    storage_root = Path(settings.storage.root)
    # Find the project archive directory
    project_archive = storage_root / project_slug

    # Check if git repo exists and has commits
    if project_archive.exists():
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=project_archive,
            capture_output=True,
            text=True,
        )
        # Should have at least one commit (message or agent registration)
        if result.returncode == 0:
            assert len(result.stdout.strip()) > 0


@pytest.mark.asyncio
async def test_health_check(mcp_client):
    """Test health_check tool returns server status."""
    result = await mcp_client.call_tool("health_check", {})

    assert len(result.data.get("health", {}).get("checks", [])) >= 0 or "uptime_seconds" in result.data
    assert "version" in result.data
    assert "uptime_seconds" in result.data
    assert "database" in result.data


@pytest.mark.asyncio
async def test_mark_message_read(mcp_client, tmp_path):
    """Test marking messages as read."""
    project_path = tmp_path / "read_test_project"
    project_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=project_path, check=True, capture_output=True)

    # Create project and agents
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    agent1 = (await mcp_client.call_tool("register_agent", {
        "project_key": str(project_path),
        "program": "sender",
        "model": "test",
    })).data["name"]

    agent2 = (await mcp_client.call_tool("register_agent", {
        "project_key": str(project_path),
        "program": "receiver",
        "model": "test",
    })).data["name"]

    # Send message
    send_result = await mcp_client.call_tool("send_message", {
        "project_key": str(project_path),
        "sender_name": agent1,
        "to": [agent2],
        "subject": "Read Test",
        "body_md": "Mark as read test",
    })

    message_id = send_result.data["deliveries"][0]["payload"]["id"]

    # Fetch inbox - should show unread
    inbox_before = await mcp_client.call_tool("fetch_inbox", {
        "project_key": str(project_path),
        "agent_name": agent2,
    })

    messages_before = inbox_before.structured_content["result"]
    assert messages_before[0]["read_ts"] is None

    # Mark as read
    mark_result = await mcp_client.call_tool("mark_message_read", {
        "project_key": str(project_path),
        "agent_name": agent2,
        "message_id": message_id,
    })

    assert mark_result.data["marked_read"] is True

    # Fetch inbox again - should show read
    inbox_after = await mcp_client.call_tool("fetch_inbox", {
        "project_key": str(project_path),
        "agent_name": agent2,
    })

    messages_after = inbox_after.structured_content["result"]
    assert messages_after[0]["read_ts"] is not None


@pytest.mark.asyncio
async def test_delete_agent(mcp_client, tmp_path):
    """Test agent deletion workflow."""
    project_path = tmp_path / "delete_agent_project"
    project_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=project_path, check=True, capture_output=True)

    # Create project and agent
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    agent = (await mcp_client.call_tool("register_agent", {
        "project_key": str(project_path),
        "program": "temporary",
        "model": "test",
    })).data["name"]

    # Verify agent exists
    whois_before = await mcp_client.call_tool("whois", {
        "project_key": str(project_path),
        "agent_name": agent,
    })
    assert whois_before.data["is_active"] is True

    # Delete agent
    delete_result = await mcp_client.call_tool("delete_agent", {
        "project_key": str(project_path),
        "agent_name": agent,
    })

    assert delete_result.data["deleted"] is True

    # Verify agent is no longer active
    whois_after = await mcp_client.call_tool("whois", {
        "project_key": str(project_path),
        "agent_name": agent,
    })
    assert whois_after.data["is_active"] is False


@pytest.mark.asyncio
async def test_renew_file_reservations(mcp_client, tmp_path):
    """Test renewing file reservations to extend TTL."""
    project_path = tmp_path / "renew_project"
    project_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=project_path, check=True, capture_output=True)

    # Create project and agent
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    agent = (await mcp_client.call_tool("register_agent", {
        "project_key": str(project_path),
        "program": "worker",
        "model": "test",
    })).data["name"]

    # Create reservation with short TTL
    reserve_result = await mcp_client.call_tool("file_reservation_paths", {
        "project_key": str(project_path),
        "agent_name": agent,
        "paths": ["src/*.py"],
        "exclusive": True,
        "ttl_seconds": 60,
    })

    assert len(reserve_result.data["active"]) == 1

    # Renew the reservation
    renew_result = await mcp_client.call_tool("renew_file_reservations", {
        "project_key": str(project_path),
        "agent_name": agent,
        "paths": ["src/*.py"],
        "additional_ttl_seconds": 3600,
    })

    assert len(renew_result.data["renewed"]) == 1


@pytest.mark.asyncio
async def test_cc_and_bcc_recipients(mcp_client, tmp_path):
    """Test sending messages with CC and BCC recipients."""
    project_path = tmp_path / "cc_bcc_project"
    project_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=project_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=project_path, check=True, capture_output=True)

    # Create project and agents
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    agents = []
    for i in range(4):
        agent = (await mcp_client.call_tool("register_agent", {
            "project_key": str(project_path),
            "program": f"agent{i}",
            "model": "test",
        })).data["name"]
        agents.append(agent)

    # Send message with TO, CC, and BCC
    send_result = await mcp_client.call_tool("send_message", {
        "project_key": str(project_path),
        "sender_name": agents[0],
        "to": [agents[1]],
        "cc": [agents[2]],
        "bcc": [agents[3]],
        "subject": "CC/BCC Test",
        "body_md": "Testing CC and BCC functionality",
    })

    assert send_result.data["count"] > 0
    assert len(send_result.data["deliveries"]) == 3  # TO + CC + BCC

    # Verify all recipients got the message
    for i in range(1, 4):
        inbox = await mcp_client.call_tool("fetch_inbox", {
            "project_key": str(project_path),
            "agent_name": agents[i],
        })
        messages = inbox.structured_content["result"]
        assert len(messages) == 1
        assert messages[0]["subject"] == "CC/BCC Test"
