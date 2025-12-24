"""Regression test for HTTP path handling (no slash vs trailing slash)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_mcp_path_no_slash_works():
    """Test that POST /mcp (no trailing slash) works correctly.

    This is a regression test for the ASGI handler signature mismatch bug
    where add_route() was used instead of mount() for the no-slash path.
    """
    from mcp_agent_mail.http import create_app

    app = create_app()

    async with AsyncClient(app=app, base_url="http://test") as client:
        # Test POST to /mcp (no trailing slash)
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": "test", "method": "initialize", "params": {"capabilities": {}}},
            headers={"Content-Type": "application/json"},
        )

        # Should not get TypeError from signature mismatch
        assert response.status_code in [200, 400, 401]  # Any valid HTTP response, not 500

        # Test POST to /mcp/ (with trailing slash)
        response = await client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": "test", "method": "initialize", "params": {"capabilities": {}}},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code in [200, 400, 401]


@pytest.mark.asyncio
async def test_mail_ui_not_shadowed():
    """Test that /mail UI is not shadowed when HTTP_PATH is configured.

    This is a regression test to ensure that mounting at "/" doesn't break
    other routes like /mail.
    """
    from mcp_agent_mail.http import create_app

    app = create_app()

    async with AsyncClient(app=app, base_url="http://test") as client:
        # Test that /mail is still accessible
        response = await client.get("/mail")

        # Should get 200 or redirect, not 404
        assert response.status_code in [200, 301, 302, 307, 308]
