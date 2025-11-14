#!/usr/bin/env python3
"""
Unit tests for agent name sanitization behavior.

This test suite verifies that:
1. Agent name sanitization removes non-alphanumeric characters (including underscores)
2. Agent registration returns the sanitized name
3. Tests should use the returned name for subsequent operations
"""

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp_agent_mail.utils import sanitize_agent_name


class TestAgentNameSanitization:
    """Test agent name sanitization rules."""

    def test_sanitize_removes_underscores(self):
        """Underscores should be removed from agent names."""
        assert sanitize_agent_name("Alice_123abc") == "Alice123abc"
        assert sanitize_agent_name("Bob_xyz789") == "Bobxyz789"
        assert sanitize_agent_name("Test_Agent_Name") == "TestAgentName"

    def test_sanitize_removes_hyphens(self):
        """Hyphens should be removed from agent names."""
        assert sanitize_agent_name("Alice-123") == "Alice123"
        assert sanitize_agent_name("Bob-Test") == "BobTest"

    def test_sanitize_removes_spaces(self):
        """Spaces should be removed from agent names."""
        assert sanitize_agent_name("Alice 123") == "Alice123"
        assert sanitize_agent_name("Bob Test") == "BobTest"

    def test_sanitize_preserves_alphanumeric(self):
        """Alphanumeric characters should be preserved."""
        assert sanitize_agent_name("Alice123abc") == "Alice123abc"
        assert sanitize_agent_name("BOB789XYZ") == "BOB789XYZ"
        assert sanitize_agent_name("GreenLake") == "GreenLake"

    def test_sanitize_mixed_case(self):
        """Mixed case should be preserved."""
        assert sanitize_agent_name("TestAgent") == "TestAgent"
        assert sanitize_agent_name("UPPERCASE") == "UPPERCASE"
        assert sanitize_agent_name("lowercase") == "lowercase"

    def test_sanitize_returns_none_for_empty(self):
        """Empty strings or strings with only special chars should return None."""
        assert sanitize_agent_name("") is None
        assert sanitize_agent_name("   ") is None
        assert sanitize_agent_name("___") is None
        assert sanitize_agent_name("---") is None
        assert sanitize_agent_name("@#$%") is None

    def test_sanitize_strips_whitespace(self):
        """Leading/trailing whitespace should be removed."""
        assert sanitize_agent_name("  Alice123  ") == "Alice123"
        assert sanitize_agent_name("\tBob456\n") == "Bob456"

    def test_sanitize_enforces_max_length(self):
        """Names should be truncated to 128 characters."""
        long_name = "A" * 200
        result = sanitize_agent_name(long_name)
        assert result is not None
        assert len(result) == 128

    @pytest.mark.parametrize(
        "input_name,expected",
        [
            ("Alice_abc123", "Aliceabc123"),
            ("Bob-xyz789", "Bobxyz789"),
            ("Test Agent 456", "TestAgent456"),
            ("user@domain.com", "userdomaincom"),
            ("CamelCase123", "CamelCase123"),
        ],
    )
    def test_sanitize_examples(self, input_name, expected):
        """Parametrized tests for various input patterns."""
        assert sanitize_agent_name(input_name) == expected


@pytest.mark.asyncio
class TestAgentRegistrationIntegration:
    """Integration tests for agent name handling in register_agent."""

    async def test_register_agent_returns_sanitized_name(self, isolated_env):
        """register_agent should return the sanitized version of the provided name."""
        from fastmcp import Client

        from mcp_agent_mail.app import build_mcp_server

        mcp = build_mcp_server()
        async with Client(mcp) as client:
            # Register with underscore in name
            result = await client.call_tool(
                "register_agent",
                {
                    "project_key": "test_project",
                    "program": "test-cli",
                    "model": "test-model",
                    "name": "Alice_abc123",  # Has underscore
                },
            )

            # Should return sanitized name without underscore
            agent_data = result.data if hasattr(result, "data") else result
            assert agent_data["name"] == "Aliceabc123"  # No underscore!

    async def test_use_returned_agent_name(self, isolated_env):
        """Tests should use the returned agent name for subsequent operations."""
        from fastmcp import Client

        from mcp_agent_mail.app import build_mcp_server

        mcp = build_mcp_server()
        async with Client(mcp) as client:
            # Register agent
            result = await client.call_tool(
                "register_agent",
                {
                    "project_key": "test_project",
                    "program": "test-cli",
                    "model": "test-model",
                    "name": "Alice_abc123",  # Has underscore
                },
            )

            # Extract the RETURNED (sanitized) name
            agent_data = result.data if hasattr(result, "data") else result
            sanitized_name = agent_data["name"]  # "Aliceabc123" (no underscore)

            # Use sanitized name for send_message - should work!
            result = await client.call_tool(
                "send_message",
                {
                    "project_key": "test_project",
                    "sender_name": sanitized_name,  # Use returned name, not original
                    "to": [sanitized_name],
                    "subject": "Test",
                    "body_md": "Should work now",
                },
            )

            # Should succeed without error
            assert result is not None
