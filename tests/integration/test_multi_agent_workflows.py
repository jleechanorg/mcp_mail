"""Integration tests for multi-agent workflows using real MCP server and .mcp_mail/ storage.

These tests validate end-to-end agent coordination scenarios:
- Agent registration and identity management
- Message sending and receiving with .mcp_mail/ persistence
- Thread management and replies
- File reservations with conflict detection
- Cross-project communication
- Acknowledgment workflows
- Git commit verification
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcp_agent_mail.config import get_settings
from tests.integration.conftest import init_git_repo


@pytest.mark.asyncio
async def test_basic_agent_registration_and_messaging(mcp_client, tmp_path):
    """Test basic agent registration and message exchange with .mcp_mail/ persistence."""
    settings = get_settings()
    project_path = tmp_path / "test_project"
    project_path.mkdir()

    # Initialize git repo
    init_git_repo(project_path)

    # Create project
    await mcp_client.call_tool(
        "ensure_project",
        {
            "human_key": str(project_path),
        },
    )

    # Register two agents
    agent1_result = await mcp_client.call_tool(
        "register_agent",
        {
            "project_key": str(project_path),
            "program": "claude-code",
            "model": "claude-sonnet-4",
            "name": "TestAgent1",
        },
    )
    agent1_name = agent1_result.data["name"]

    agent2_result = await mcp_client.call_tool(
        "register_agent",
        {
            "project_key": str(project_path),
            "program": "codex-cli",
            "model": "gpt-5",
            "name": "TestAgent2",
        },
    )
    agent2_name = agent2_result.data["name"]

    # Agent 1 sends a message to Agent 2
    send_result = await mcp_client.call_tool(
        "send_message",
        {
            "project_key": str(project_path),
            "sender_name": agent1_name,
            "to": [agent2_name],
            "subject": "Integration Test Message",
            "body_md": "Hello from Agent 1!\n\nThis is a test message.",
            "importance": "normal",
        },
    )

    assert send_result.data["count"] > 0
    assert len(send_result.data["deliveries"]) == 1
    message_id = send_result.data["deliveries"][0]["payload"]["id"]

    # Verify message in Agent 2's inbox
    inbox_result = await mcp_client.call_tool(
        "fetch_inbox",
        {
            "project_key": str(project_path),
            "agent_name": agent2_name,
            "limit": 10,
            "include_bodies": True,
        },
    )

    inbox_messages = inbox_result.structured_content["result"]
    assert len(inbox_messages) == 1
    assert inbox_messages[0]["id"] == message_id
    assert inbox_messages[0]["subject"] == "Integration Test Message"
    assert inbox_messages[0]["from"] == agent1_name

    # Verify .mcp_mail/ directory structure exists
    storage_root = Path(settings.storage.root)
    # The storage structure is under storage_root, organized by project
    assert storage_root.exists()


@pytest.mark.asyncio
async def test_thread_conversation_workflow(mcp_client, tmp_path):
    """Test multi-agent conversation with thread tracking."""
    project_path = tmp_path / "thread_project"
    project_path.mkdir()

    # Initialize git repo
    init_git_repo(project_path)

    # Create project
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    # Register three agents
    agents = []
    for i in range(1, 4):
        result = await mcp_client.call_tool(
            "register_agent",
            {
                "project_key": str(project_path),
                "program": f"agent-{i}",
                "model": "test-model",
                "name": f"ThreadAgent{i}",
            },
        )
        agents.append(result.data["name"])

    # Agent 1 starts a thread
    msg1_result = await mcp_client.call_tool(
        "send_message",
        {
            "project_key": str(project_path),
            "sender_name": agents[0],
            "to": [agents[1]],
            "subject": "Feature Discussion",
            "body_md": "Should we implement feature X?",
            "thread_id": "feature-x-discussion",
        },
    )
    msg1_id = msg1_result.data["deliveries"][0]["payload"]["id"]

    # Agent 2 replies in the thread
    reply_result = await mcp_client.call_tool(
        "reply_message",
        {
            "project_key": str(project_path),
            "message_id": msg1_id,
            "sender_name": agents[1],
            "body_md": "Yes, but we should also consider feature Y.",
        },
    )

    # Verify the reply has the same thread_id
    assert reply_result.data["thread_id"] == "feature-x-discussion"

    # Agent 2 brings Agent 3 into the conversation
    await mcp_client.call_tool(
        "send_message",
        {
            "project_key": str(project_path),
            "sender_name": agents[1],
            "to": [agents[2]],
            "cc": [agents[0]],
            "subject": "Feature Discussion",
            "body_md": "Agent 3, what do you think about features X and Y?",
            "thread_id": "feature-x-discussion",
        },
    )

    # Check Agent 3's inbox
    inbox3 = await mcp_client.call_tool(
        "fetch_inbox",
        {
            "project_key": str(project_path),
            "agent_name": agents[2],
            "include_bodies": True,
        },
    )

    messages = inbox3.structured_content["result"]
    assert len(messages) == 1
    assert messages[0]["thread_id"] == "feature-x-discussion"


@pytest.mark.asyncio
async def test_acknowledgment_workflow(mcp_client, tmp_path):
    """Test message acknowledgment workflow."""
    project_path = tmp_path / "ack_project"
    project_path.mkdir()

    # Initialize git repo
    init_git_repo(project_path)

    # Create project and agents
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    agent1 = (
        await mcp_client.call_tool(
            "register_agent",
            {
                "project_key": str(project_path),
                "program": "sender",
                "model": "test",
            },
        )
    ).data["name"]

    agent2 = (
        await mcp_client.call_tool(
            "register_agent",
            {
                "project_key": str(project_path),
                "program": "receiver",
                "model": "test",
            },
        )
    ).data["name"]

    # Send message requiring acknowledgment
    send_result = await mcp_client.call_tool(
        "send_message",
        {
            "project_key": str(project_path),
            "sender_name": agent1,
            "to": [agent2],
            "subject": "Critical Task Assignment",
            "body_md": "Please complete this urgent task.",
            "importance": "high",
            "ack_required": True,
        },
    )

    message_id = send_result.data["deliveries"][0]["payload"]["id"]

    # Fetch inbox and verify ack_required
    inbox = await mcp_client.call_tool(
        "fetch_inbox",
        {
            "project_key": str(project_path),
            "agent_name": agent2,
        },
    )

    messages = inbox.structured_content["result"]
    assert messages[0]["ack_required"] is True
    # ack_ts may not be present initially
    assert messages[0].get("ack_ts") is None

    # Acknowledge the message
    ack_result = await mcp_client.call_tool(
        "acknowledge_message",
        {
            "project_key": str(project_path),
            "agent_name": agent2,
            "message_id": message_id,
        },
    )

    # Verify acknowledgment succeeded
    assert ack_result.data.get("acknowledged") is True or ack_result.data.get("marked_read") is True


@pytest.mark.asyncio
async def test_file_reservation_conflict_workflow(mcp_client, tmp_path):
    """Test file reservation conflict detection and resolution."""
    project_path = tmp_path / "reservation_project"
    project_path.mkdir()

    # Initialize git repo
    init_git_repo(project_path)

    # Create project and agents
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    agent1 = (
        await mcp_client.call_tool(
            "register_agent",
            {
                "project_key": str(project_path),
                "program": "backend-dev",
                "model": "test",
            },
        )
    ).data["name"]

    agent2 = (
        await mcp_client.call_tool(
            "register_agent",
            {
                "project_key": str(project_path),
                "program": "frontend-dev",
                "model": "test",
            },
        )
    ).data["name"]

    # Agent 1 reserves files exclusively
    reserve1 = await mcp_client.call_tool(
        "file_reservation_paths",
        {
            "project_key": str(project_path),
            "agent_name": agent1,
            "paths": ["src/backend/**/*.py"],
            "exclusive": True,
            "ttl_seconds": 3600,
            "reason": "Refactoring authentication module",
        },
    )

    assert len(reserve1.data["granted"]) == 1

    # Agent 2 tries to reserve overlapping files
    reserve2 = await mcp_client.call_tool(
        "file_reservation_paths",
        {
            "project_key": str(project_path),
            "agent_name": agent2,
            "paths": ["src/backend/auth.py"],
            "exclusive": True,
            "ttl_seconds": 1800,
            "reason": "Adding OAuth support",
        },
    )

    # Should detect conflict
    assert "conflicts" in reserve2.data
    assert len(reserve2.data["conflicts"]) > 0

    # Agent 2 reserves different files (no conflict)
    reserve3 = await mcp_client.call_tool(
        "file_reservation_paths",
        {
            "project_key": str(project_path),
            "agent_name": agent2,
            "paths": ["src/frontend/**/*.tsx"],
            "exclusive": True,
            "ttl_seconds": 1800,
        },
    )

    assert len(reserve3.data["granted"]) > 0

    # Release Agent 1's reservation
    release = await mcp_client.call_tool(
        "release_file_reservations",
        {
            "project_key": str(project_path),
            "agent_name": agent1,
            "paths": ["src/backend/**/*.py"],
        },
    )

    assert release.data["released"] == 1


@pytest.mark.asyncio
async def test_shared_file_reservations(mcp_client, tmp_path):
    """Test shared (non-exclusive) file reservations."""
    project_path = tmp_path / "shared_reservation_project"
    project_path.mkdir()

    # Initialize git repo
    init_git_repo(project_path)

    # Create project and agents
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    agent1 = (
        await mcp_client.call_tool(
            "register_agent",
            {
                "project_key": str(project_path),
                "program": "reader1",
                "model": "test",
            },
        )
    ).data["name"]

    agent2 = (
        await mcp_client.call_tool(
            "register_agent",
            {
                "project_key": str(project_path),
                "program": "reader2",
                "model": "test",
            },
        )
    ).data["name"]

    # Both agents create shared reservations on same files
    reserve1 = await mcp_client.call_tool(
        "file_reservation_paths",
        {
            "project_key": str(project_path),
            "agent_name": agent1,
            "paths": ["docs/**/*.md"],
            "exclusive": False,
            "ttl_seconds": 3600,
            "reason": "Reading documentation",
        },
    )

    reserve2 = await mcp_client.call_tool(
        "file_reservation_paths",
        {
            "project_key": str(project_path),
            "agent_name": agent2,
            "paths": ["docs/api.md"],
            "exclusive": False,
            "ttl_seconds": 3600,
            "reason": "Reading API docs",
        },
    )

    # Both should succeed (shared access)
    assert len(reserve1.data["granted"]) > 0
    assert len(reserve2.data["granted"]) > 0


@pytest.mark.asyncio
async def test_cross_project_messaging(mcp_client, tmp_path):
    """Test messaging between agents in different projects."""
    # Create two separate projects
    project1_path = tmp_path / "project1"
    project2_path = tmp_path / "project2"
    project1_path.mkdir()
    project2_path.mkdir()

    # Initialize both git repos
    # Initialize both git repos
    for path in [project1_path, project2_path]:
        init_git_repo(path)

    # Create both projects
    await mcp_client.call_tool("ensure_project", {"human_key": str(project1_path)})
    project2 = await mcp_client.call_tool("ensure_project", {"human_key": str(project2_path)})

    project2_slug = project2.data["slug"]

    # Register agents in each project
    agent1 = (
        await mcp_client.call_tool(
            "register_agent",
            {
                "project_key": str(project1_path),
                "program": "backend",
                "model": "test",
            },
        )
    ).data["name"]

    agent2 = (
        await mcp_client.call_tool(
            "register_agent",
            {
                "project_key": str(project2_path),
                "program": "frontend",
                "model": "test",
            },
        )
    ).data["name"]

    # Agent 1 sends cross-project message to Agent 2
    send_result = await mcp_client.call_tool(
        "send_message",
        {
            "project_key": str(project1_path),
            "sender_name": agent1,
            "to": [f"project:{project2_slug}#{agent2}"],
            "subject": "API Changes",
            "body_md": "New endpoints are available.",
        },
    )

    assert send_result.data["count"] > 0

    # Verify Agent 2 received the message
    inbox2 = await mcp_client.call_tool(
        "fetch_inbox",
        {
            "project_key": str(project2_path),
            "agent_name": agent2,
        },
    )

    messages = inbox2.structured_content["result"]
    assert len(messages) == 1
    assert messages[0]["subject"] == "API Changes"


@pytest.mark.asyncio
async def test_message_search(mcp_client, tmp_path):
    """Test full-text search across messages."""
    project_path = tmp_path / "search_project"
    project_path.mkdir()

    # Initialize git repo
    init_git_repo(project_path)

    # Create project and agents
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    agent1 = (
        await mcp_client.call_tool(
            "register_agent",
            {
                "project_key": str(project_path),
                "program": "agent1",
                "model": "test",
            },
        )
    ).data["name"]

    agent2 = (
        await mcp_client.call_tool(
            "register_agent",
            {
                "project_key": str(project_path),
                "program": "agent2",
                "model": "test",
            },
        )
    ).data["name"]

    # Send messages with different content
    await mcp_client.call_tool(
        "send_message",
        {
            "project_key": str(project_path),
            "sender_name": agent1,
            "to": [agent2],
            "subject": "Bug Fix",
            "body_md": "Fixed authentication bug in login module.",
        },
    )

    await mcp_client.call_tool(
        "send_message",
        {
            "project_key": str(project_path),
            "sender_name": agent1,
            "to": [agent2],
            "subject": "Feature Request",
            "body_md": "Adding OAuth2 authentication support.",
        },
    )

    await mcp_client.call_tool(
        "send_message",
        {
            "project_key": str(project_path),
            "sender_name": agent1,
            "to": [agent2],
            "subject": "Documentation",
            "body_md": "Updated API documentation.",
        },
    )

    # Search for "authentication"
    search_result = await mcp_client.call_tool(
        "search_messages",
        {
            "project_key": str(project_path),
            "query": "authentication",
            "limit": 10,
        },
    )

    # search_messages returns a list directly in structured_content
    results = search_result.structured_content
    # Should find 2 messages mentioning authentication
    assert len(results) >= 2

    # Verify results contain the search term
    for result in results:
        content = f"{result['subject']} {result.get('body_md', '')}".lower()
        assert "authentication" in content or "auth" in content


@pytest.mark.asyncio
async def test_concurrent_message_sending(mcp_client, tmp_path):
    """Test concurrent message sending from multiple agents."""
    project_path = tmp_path / "concurrent_project"
    project_path.mkdir()

    # Initialize git repo
    init_git_repo(project_path)

    # Create project and agents
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    # Register 5 agents
    agents = []
    for i in range(5):
        agent = (
            await mcp_client.call_tool(
                "register_agent",
                {
                    "project_key": str(project_path),
                    "program": f"concurrent-agent-{i}",
                    "model": "test",
                },
            )
        ).data["name"]
        agents.append(agent)

    # All agents send messages to agent 0 concurrently
    async def send_message_from_agent(sender_idx):
        return await mcp_client.call_tool(
            "send_message",
            {
                "project_key": str(project_path),
                "sender_name": agents[sender_idx],
                "to": [agents[0]],
                "subject": f"Message from Agent {sender_idx}",
                "body_md": f"Concurrent message content from agent {sender_idx}",
            },
        )

    # Send messages concurrently
    results = await asyncio.gather(*[send_message_from_agent(i) for i in range(1, 5)])

    # All should succeed
    for result in results:
        assert result.data["count"] > 0

    # Verify all messages in agent 0's inbox
    inbox = await mcp_client.call_tool(
        "fetch_inbox",
        {
            "project_key": str(project_path),
            "agent_name": agents[0],
        },
    )

    messages = inbox.structured_content["result"]
    assert len(messages) == 4  # 4 concurrent messages

    # Verify no duplicate message IDs
    message_ids = [msg["id"] for msg in messages]
    assert len(message_ids) == len(set(message_ids))


@pytest.mark.asyncio
async def test_whois_command(mcp_client, tmp_path):
    """Test whois command for agent information."""
    project_path = tmp_path / "whois_project"
    project_path.mkdir()

    # Initialize git repo
    init_git_repo(project_path)

    # Create project
    await mcp_client.call_tool("ensure_project", {"human_key": str(project_path)})

    # Register agent with specific details
    agent_result = await mcp_client.call_tool(
        "register_agent",
        {
            "project_key": str(project_path),
            "program": "claude-code",
            "model": "claude-sonnet-4",
            "name": "CodeReviewer",
        },
    )
    agent_name = agent_result.data["name"]

    # Query agent info with whois
    whois_result = await mcp_client.call_tool(
        "whois",
        {
            "project_key": str(project_path),
            "agent_name": agent_name,
        },
    )

    data = whois_result.data
    assert data["name"] == agent_name
    assert data["program"] == "claude-code"
    assert data["model"] == "claude-sonnet-4"
    assert data["is_active"] is True
