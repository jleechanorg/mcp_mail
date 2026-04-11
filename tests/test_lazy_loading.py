"""Tests for lazy loading meta-tools."""

from __future__ import annotations

import pytest
from fastmcp import Client

from mcp_agent_mail.app import _EXTENDED_TOOL_REGISTRY, CORE_TOOLS, EXTENDED_TOOLS, PRODUCT_TOOLS, build_mcp_server


@pytest.mark.asyncio
async def test_list_extended_tools(isolated_env):
    """Test list_extended_tools returns correct metadata."""
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        result = await client.call_tool("list_extended_tools", arguments={})
        result = result.data  # Extract dict from CallToolResult

        # Check structure
        assert "total" in result
        assert "by_category" in result
        assert "tools" in result

        # Check correct count (keep in sync with EXTENDED_TOOLS)
        assert result["total"] == len(EXTENDED_TOOLS)

        # Check all tools have valid metadata
        assert len(result["tools"]) == len(EXTENDED_TOOLS)
        for tool in result["tools"]:
            assert "name" in tool
            assert "category" in tool
            assert "description" in tool
            assert tool["name"] in EXTENDED_TOOLS

        # Check by_category structure
        assert isinstance(result["by_category"], dict)
        # Flatten all categories to verify all tools are included
        all_categorized_tools = []
        for tools_list in result["by_category"].values():
            all_categorized_tools.extend(tools_list)
        # All extended tools should be categorized
        # (contact-related tools were removed from EXTENDED_TOOLS entirely)
        assert len(all_categorized_tools) == len(EXTENDED_TOOLS)


@pytest.mark.asyncio
async def test_call_extended_tool_valid(isolated_env):
    """Test calling a valid extended tool."""
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # First setup: create a project and agent for the test
        await client.call_tool("ensure_project", arguments={"human_key": "/tmp/test_project"})
        await client.call_tool(
            "register_agent",
            arguments={
                "project_key": "/tmp/test_project",
                "program": "test_program",
                "model": "test_model",
                "name": "test_agent",
            },
        )

        # Test calling an extended tool via the meta-tool
        # Use search_messages as it's a simple read-only tool
        result = await client.call_tool(
            "call_extended_tool",
            arguments={
                "tool_name": "search_messages",
                "arguments": {"project_key": "/tmp/test_project", "query": "test"},
            },
        )
        result = result.data  # Extract from CallToolResult

        # Should succeed and return a dict with result key
        assert isinstance(result, dict)
        assert "result" in result
        assert isinstance(result["result"], list)


@pytest.mark.asyncio
async def test_call_extended_tool_invalid(isolated_env):
    """Test calling invalid tool raises ValueError."""
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Try to call a non-existent tool
        with pytest.raises(Exception) as exc_info:
            await client.call_tool(
                "call_extended_tool", arguments={"tool_name": "fake_tool_does_not_exist", "arguments": {}}
            )

        # Should raise ToolError (wrapped ValueError)
        # Error message is wrapped in generic MCP error
        assert "Error calling tool" in str(exc_info.value) or "Unknown extended tool" in str(exc_info.value)


@pytest.mark.asyncio
async def test_call_extended_tool_invalid_arguments(isolated_env):
    """Test calling with invalid arguments raises ValueError."""
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Try to call a valid tool but with wrong arguments
        with pytest.raises(Exception) as exc_info:
            await client.call_tool(
                "call_extended_tool", arguments={"tool_name": "search_messages", "arguments": {"wrong_arg": "value"}}
            )

        # Should raise error about invalid arguments (may be wrapped in generic error)
        error_msg = str(exc_info.value).lower()
        assert "invalid arguments" in error_msg or "required" in error_msg or "error calling tool" in error_msg


def test_extended_tool_registry_populated():
    """Test all extended tools are in registry."""
    # Build the server to trigger registry population
    build_mcp_server()

    # Check registry has correct count
    assert len(_EXTENDED_TOOL_REGISTRY) == len(EXTENDED_TOOLS)

    # Check all extended tools are registered
    for tool_name in EXTENDED_TOOLS:
        assert tool_name in _EXTENDED_TOOL_REGISTRY, f"Tool {tool_name} not in registry"
        tool = _EXTENDED_TOOL_REGISTRY[tool_name]
        # Tools are FunctionTool objects from FastMCP
        assert hasattr(tool, "fn"), f"Tool {tool_name} does not have fn attribute"
        assert callable(tool.fn), f"Tool {tool_name}.fn is not callable"


def test_core_and_extended_tools_disjoint():
    """Test that core and extended tools don't overlap."""
    overlap = CORE_TOOLS & EXTENDED_TOOLS
    assert len(overlap) == 0, f"Core and extended tools should not overlap, but found: {overlap}"


def test_tool_sets_all_disjoint():
    """Test that CORE_TOOLS, EXTENDED_TOOLS, and PRODUCT_TOOLS are mutually disjoint."""
    assert len(CORE_TOOLS & EXTENDED_TOOLS) == 0
    assert len(CORE_TOOLS & PRODUCT_TOOLS) == 0
    assert len(EXTENDED_TOOLS & PRODUCT_TOOLS) == 0


def test_extended_tools_count():
    """Test that we have exactly 22 extended tools (includes build-slot and Slack tools)."""
    assert len(EXTENDED_TOOLS) == 22, f"Expected 22 extended tools, but found {len(EXTENDED_TOOLS)}"


def test_core_tools_count():
    """Test that we have exactly 9 core tools."""
    assert len(CORE_TOOLS) == 9, f"Expected 9 core tools, but found {len(CORE_TOOLS)}"


def test_product_tools_count():
    """Test that we have exactly 5 product bus tools."""
    assert len(PRODUCT_TOOLS) == 5, f"Expected 5 product tools, but found {len(PRODUCT_TOOLS)}"
    expected = {
        "ensure_product",
        "products_link",
        "search_messages_product",
        "fetch_inbox_product",
        "summarize_thread_product",
    }
    assert expected == PRODUCT_TOOLS, f"PRODUCT_TOOLS mismatch: {PRODUCT_TOOLS}"


@pytest.mark.asyncio
async def test_core_mode_hides_product_tools(isolated_env, monkeypatch):
    """Test that core mode removes product tools from MCP exposure."""
    monkeypatch.setenv("MCP_TOOLS_MODE", "core")
    mcp = build_mcp_server()
    async with Client(mcp) as client:
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        for tool_name in PRODUCT_TOOLS:
            assert tool_name not in tool_names, f"Product tool {tool_name!r} should be hidden in core mode"
        for tool_name in CORE_TOOLS:
            assert tool_name in tool_names, f"Core tool {tool_name!r} should be exposed in core mode"
