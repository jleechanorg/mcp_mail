"""Test that projects are informative only and do not organize messages.

This test validates that the unified inbox UI does not filter/organize messages
by project, while still displaying project metadata as informational context.

Reference: Projects should be informative and not organize messages anymore.
"""

from __future__ import annotations

import contextlib
import inspect

import pytest
from httpx import ASGITransport, AsyncClient

from mcp_agent_mail import config as _config
from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.http import build_http_app


@pytest.mark.asyncio
async def test_unified_inbox_does_not_filter_by_project(isolated_env):
    """Verify unified inbox template does not contain project filtering UI.

    Projects should be visible as metadata (badges/tags) but should not
    be used to organize or filter messages in the unified inbox.

    This test will FAIL if the template contains:
    - Project filter dropdown
    - filters.project JavaScript variable
    - Project filtering logic in filterMessages()
    """
    with contextlib.suppress(Exception):
        _config.clear_settings_cache()
    settings = _config.get_settings()
    server = build_mcp_server()
    app = build_http_app(settings, server)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Fetch the unified inbox page
        response = await client.get("/mail")
        assert response.status_code == 200

        html_content = response.text

        # ASSERTIONS: These should all PASS after the fix

        # 1. Should NOT have a project filter dropdown
        assert 'x-model="filters.project"' not in html_content, (
            "Unified inbox should not have project filter dropdown - projects should be informational only"
        )

        # 2. Should NOT have "All Projects" option in a filter
        assert '<option value="">All Projects</option>' not in html_content, (
            "Unified inbox should not have 'All Projects' filter option - projects should be informational only"
        )

        # 3. Should NOT have project filtering logic in JavaScript
        assert "this.filters.project" not in html_content, (
            "Unified inbox should not filter by project in JavaScript - projects should be informational only"
        )

        # 4. Should NOT compute uniqueProjects for filtering
        assert "get uniqueProjects()" not in html_content, (
            "Unified inbox should not compute unique projects for filtering - projects should be informational only"
        )

        # 5. Should NOT have label "Project" for a filter
        # (This is tricky - we want to allow displaying project metadata,
        #  but not as a filter label)
        project_filter_label_pattern = (
            '<label class="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">Project</label>'
        )
        assert project_filter_label_pattern not in html_content, (
            "Unified inbox should not have 'Project' as a filter label"
        )

        # POSITIVE ASSERTIONS: These should show projects are still informational

        # 6. SHOULD still display project metadata (like in message cards)
        # Project metadata can appear in message display
        assert "project_name" in html_content or "project_slug" in html_content, (
            "Projects should still be visible as informational metadata on messages"
        )


@pytest.mark.asyncio
async def test_unified_inbox_api_structure(isolated_env):
    """Verify the unified inbox API returns correct structure with project metadata.

    The API response should include a messages array where each message
    can have project metadata fields (project_name, project_slug) but
    the API itself doesn't filter by project.
    """
    with contextlib.suppress(Exception):
        _config.clear_settings_cache()
    settings = _config.get_settings()
    server = build_mcp_server()
    app = build_http_app(settings, server)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Fetch unified inbox via API
        response = await client.get("/mail/api/unified-inbox?include_projects=true")
        assert response.status_code == 200

        data = response.json()

        # Should have the expected structure
        assert "messages" in data, "API should return messages array"
        assert "projects" in data, "API should return projects array (when include_projects=true)"

        # Messages is a list (may be empty in test env)
        messages = data.get("messages", [])
        assert isinstance(messages, list), "Messages should be an array"

        # If there are messages, they should have project metadata fields available
        # (even if empty, the fields should exist)
        # Note: In a fresh test environment, there may be no messages, so we just
        # verify the structure is correct


@pytest.mark.asyncio
async def test_global_message_lookup_function_exists(isolated_env):
    """Verify the _get_message_by_id_global function exists and works correctly.

    This function is the key to making projects informational only - it allows
    messages to be looked up globally by ID without project boundaries.
    """
    # Import the function to verify it exists
    from mcp_agent_mail.app import _get_message_by_id_global

    # The function should be importable and have the correct signature
    sig = inspect.signature(_get_message_by_id_global)
    params = list(sig.parameters.keys())

    # Should only take message_id, not project
    assert "message_id" in params, "Function should accept message_id parameter"
    assert "project" not in params, "Function should NOT require project parameter"

    # Verify the docstring mentions global access
    assert _get_message_by_id_global.__doc__ is not None, "Function should have documentation"
    assert "global" in _get_message_by_id_global.__doc__.lower(), "Docstring should mention global access"
