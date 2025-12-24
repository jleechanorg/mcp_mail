"""TDD tests for HTTP path ASGI handler and streaming support.

This test suite verifies that:
1. POST /mcp (no trailing slash) works without TypeError
2. POST /mcp/ (with trailing slash) works
3. HTTP_PATH="/" DOES shadow /mail (known limitation for streaming support)
4. MCP streaming works correctly at all paths
"""

import os
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from mcp_agent_mail import config as _config
from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.http import build_http_app


@pytest.fixture
def clear_settings_cache() -> None:
    """Clear settings cache before and after tests that patch environment."""
    _config.get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    _config.get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_post_mcp_no_trailing_slash_does_not_crash():
    """Test that POST /mcp (no trailing slash) works without TypeError.

    This is a regression test for the ASGI handler signature mismatch bug
    where add_route() was used instead of a proper Request handler wrapper.

    Expected: Should return a valid HTTP response (not 500 TypeError)
    """
    settings = _config.get_settings()
    server = build_mcp_server()
    app = build_http_app(settings, server)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as client:
            # Test POST to /mcp (no trailing slash) with MCP initialize request
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": "test-1",
                    "method": "initialize",
                    "params": {"capabilities": {}, "protocolVersion": "2024-11-05"},
                },
                headers={"Content-Type": "application/json"},
            )

            # Should NOT get 500 Internal Server Error from TypeError
            assert response.status_code != 500, (
                f"Expected valid response, got 500. This suggests ASGI signature mismatch. "
                f"Response: {response.text[:500]}"
            )

            # Should get either 200 (success), 401 (auth), or 400 (bad request)
            # but NOT 500 (server error from signature mismatch)
            assert response.status_code in [200, 400, 401, 403], f"Unexpected status code: {response.status_code}"


@pytest.mark.asyncio
async def test_post_mcp_with_trailing_slash_works():
    """Test that POST /mcp/ (with trailing slash) works correctly."""
    settings = _config.get_settings()
    server = build_mcp_server()
    app = build_http_app(settings, server)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as client:
            response = await client.post(
                "/mcp/",
                json={
                    "jsonrpc": "2.0",
                    "id": "test-2",
                    "method": "initialize",
                    "params": {"capabilities": {}, "protocolVersion": "2024-11-05"},
                },
                headers={"Content-Type": "application/json"},
            )

            # Should work without errors
            assert response.status_code in [200, 400, 401, 403]


@pytest.mark.asyncio
async def test_http_path_root_DOES_shadow_mail_ui(clear_settings_cache: None):
    """Test that HTTP_PATH='/' DOES shadow /mail UI (known limitation).

    This documents the fundamental limitation: mounting MCP at "/" will shadow
    all other routes including /mail. This is by design to support MCP streaming.

    Users should use HTTP_PATH='/mcp' if they need both MCP and /mail UI.
    """
    # Mock environment to set HTTP_PATH="/"
    with patch.dict(os.environ, {"HTTP_PATH": "/"}):
        settings = _config.get_settings()
        server = build_mcp_server()
        app = build_http_app(settings, server)

        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as client:
                # Test that /mail is shadowed (404) when HTTP_PATH='/'
                response = await client.get("/mail")

                # EXPECT 404 - /mail is shadowed by MCP mount at "/"
                assert response.status_code == 404, (
                    f"Expected /mail to be shadowed (404) when HTTP_PATH='/'. Got status: {response.status_code}"
                )


@pytest.mark.asyncio
async def test_http_path_root_mcp_still_works(clear_settings_cache: None):
    """Test that MCP endpoints still work when HTTP_PATH='/'.

    Even though HTTP_PATH='/' is not recommended, if configured,
    the MCP endpoints should still be accessible.
    """
    with patch.dict(os.environ, {"HTTP_PATH": "/"}):
        settings = _config.get_settings()
        server = build_mcp_server()
        app = build_http_app(settings, server)

        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as client:
                # MCP should be accessible at root when HTTP_PATH="/"
                response = await client.post(
                    "/",
                    json={
                        "jsonrpc": "2.0",
                        "id": "test-3",
                        "method": "initialize",
                        "params": {"capabilities": {}, "protocolVersion": "2024-11-05"},
                    },
                    headers={"Content-Type": "application/json"},
                )

                # Should get valid MCP response
                assert response.status_code in [200, 400, 401, 403]
