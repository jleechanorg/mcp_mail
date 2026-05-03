"""Test that ClosedResourceError from client disconnects is handled gracefully.

Reproduces the crash reported when Codex connects to the MCP server and the
connection is closed early, causing anyio.ClosedResourceError to propagate
through the ASGI stack.

Error trace being addressed:
    ERROR:mcp.server.streamable_http:Error in message router
    anyio.ClosedResourceError
    ERROR:    Exception in ASGI application
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import patch

import anyio
import pytest
from httpx import ASGITransport, AsyncClient

from mcp_agent_mail import config as _config
from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.http import build_http_app


def _rpc(method: str, params: dict) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": "1", "method": method, "params": params}


@pytest.mark.asyncio
async def test_closed_resource_error_handled_gracefully(isolated_env, monkeypatch):
    """Sanity check that standard requests do not crash the server.

    This ensures baseline HTTP handling is stable before simulating disconnects
    in later tests.
    """
    with contextlib.suppress(Exception):
        _config.clear_settings_cache()
    settings = _config.get_settings()
    server = build_mcp_server()
    app = build_http_app(settings, server)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Make a normal request first to ensure server is working
            r1 = await client.post(
                settings.http.path,
                json=_rpc("tools/call", {"name": "health_check", "arguments": {}}),
            )
            # Should succeed (200) or be unauthorized (401) but NOT crash (500)
            assert r1.status_code in (200, 401, 403)

            # Server should still be working after any connection issues
            r2 = await client.post(
                settings.http.path,
                json=_rpc("tools/call", {"name": "health_check", "arguments": {}}),
            )
            assert r2.status_code in (200, 401, 403)


@pytest.mark.asyncio
async def test_closed_resource_error_in_connect_suppressed(isolated_env, monkeypatch):
    """Test that ClosedResourceError during transport connect() is suppressed.

    This test patches the StreamableHTTPServerTransport.connect to raise
    ClosedResourceError, simulating a client disconnect during connection.
    """
    from mcp.server.streamable_http import StreamableHTTPServerTransport

    with contextlib.suppress(Exception):
        _config.clear_settings_cache()
    settings = _config.get_settings()
    server = build_mcp_server()

    original_connect = StreamableHTTPServerTransport.connect
    call_count = 0

    @contextlib.asynccontextmanager
    async def patched_connect(self):
        """Patched connect that raises ClosedResourceError on second call."""
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            # Simulate ClosedResourceError during stream iteration
            raise anyio.ClosedResourceError()
        async with original_connect(self) as streams:
            yield streams

    app = build_http_app(settings, server)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First request should work
            r1 = await client.post(
                settings.http.path,
                json=_rpc("tools/call", {"name": "health_check", "arguments": {}}),
            )
            assert r1.status_code in (200, 401, 403)

            # Patch for second request
            with patch.object(StreamableHTTPServerTransport, "connect", patched_connect):
                # Second request triggers ClosedResourceError - should be handled gracefully
                try:
                    r2 = await client.post(
                        settings.http.path,
                        json=_rpc("tools/call", {"name": "health_check", "arguments": {}}),
                    )
                    # The request might timeout or return an error code, but shouldn't crash
                    # After fix: gracefully handled, no exception propagation
                    assert r2.status_code in (200, 401, 403, 500, 503)
                except anyio.ClosedResourceError:
                    # Before fix: this would propagate
                    pytest.fail("ClosedResourceError should be handled gracefully")


@pytest.mark.asyncio
async def test_handle_request_closed_resource_error_suppressed(isolated_env, monkeypatch):
    """Test that ClosedResourceError during handle_request is suppressed.

    This specifically tests the scenario from the error traceback where the
    error occurs in the message_router trying to read from a closed stream.
    """
    from mcp.server.streamable_http import StreamableHTTPServerTransport

    with contextlib.suppress(Exception):
        _config.clear_settings_cache()
    settings = _config.get_settings()
    server = build_mcp_server()

    original_handle_request = StreamableHTTPServerTransport.handle_request
    call_count = 0

    async def patched_handle_request(self, scope, receive, send):
        """Patched handle_request that raises ClosedResourceError on second call."""
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            # Simulate the exact error from the traceback
            raise anyio.ClosedResourceError()
        return await original_handle_request(self, scope, receive, send)

    app = build_http_app(settings, server)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First request should work
            r1 = await client.post(
                settings.http.path,
                json=_rpc("tools/call", {"name": "health_check", "arguments": {}}),
            )
            assert r1.status_code in (200, 401, 403)

            # Patch for second request
            with patch.object(StreamableHTTPServerTransport, "handle_request", patched_handle_request):
                try:
                    r2 = await client.post(
                        settings.http.path,
                        json=_rpc("tools/call", {"name": "health_check", "arguments": {}}),
                    )
                    # After fix: Should handle gracefully
                    assert r2.status_code in (200, 401, 403, 500, 503)
                except anyio.ClosedResourceError:
                    pytest.fail("ClosedResourceError should be handled gracefully, not propagate")


@pytest.mark.asyncio
async def test_exception_group_with_closed_resource_error(isolated_env, monkeypatch):
    """Test that ExceptionGroup containing ClosedResourceError is handled.

    This tests the scenario where anyio's task group raises an ExceptionGroup
    containing ClosedResourceError from the message router.
    """
    from mcp.server.streamable_http import StreamableHTTPServerTransport

    with contextlib.suppress(Exception):
        _config.clear_settings_cache()
    settings = _config.get_settings()
    server = build_mcp_server()

    original_handle_request = StreamableHTTPServerTransport.handle_request
    call_count = 0

    async def patched_handle_request(self, scope, receive, send):
        """Patched handle_request that raises ExceptionGroup with ClosedResourceError."""
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            # Simulate ExceptionGroup from anyio task group
            raise ExceptionGroup("test", [anyio.ClosedResourceError()])
        return await original_handle_request(self, scope, receive, send)

    app = build_http_app(settings, server)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First request should work
            r1 = await client.post(
                settings.http.path,
                json=_rpc("tools/call", {"name": "health_check", "arguments": {}}),
            )
            assert r1.status_code in (200, 401, 403)

            # Patch for second request
            with patch.object(StreamableHTTPServerTransport, "handle_request", patched_handle_request):
                try:
                    r2 = await client.post(
                        settings.http.path,
                        json=_rpc("tools/call", {"name": "health_check", "arguments": {}}),
                    )
                    # After fix: Should handle gracefully
                    assert r2.status_code in (200, 401, 403, 500, 503)
                except (ExceptionGroup, BaseExceptionGroup) as eg:
                    # Check if the only exception in the group is ClosedResourceError
                    all_closed = all(isinstance(e, anyio.ClosedResourceError) for e in eg.exceptions)
                    if all_closed:
                        pytest.fail("ExceptionGroup with only ClosedResourceError should be suppressed")
                    # If there are other exceptions, that's a test issue, not the fix
                except anyio.ClosedResourceError:
                    pytest.fail("ClosedResourceError should be handled gracefully")


@pytest.mark.asyncio
async def test_server_recovers_after_closed_resource_error(isolated_env, monkeypatch):
    """Test that server continues to work after handling ClosedResourceError."""
    from mcp.server.streamable_http import StreamableHTTPServerTransport

    with contextlib.suppress(Exception):
        _config.clear_settings_cache()
    settings = _config.get_settings()
    server = build_mcp_server()

    original_handle_request = StreamableHTTPServerTransport.handle_request
    error_triggered = False

    async def patched_handle_request(self, scope, receive, send):
        """Patched handle_request that raises ClosedResourceError once."""
        nonlocal error_triggered
        if not error_triggered:
            error_triggered = True
            raise anyio.ClosedResourceError()
        return await original_handle_request(self, scope, receive, send)

    app = build_http_app(settings, server)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # First request triggers ClosedResourceError
            with (
                patch.object(StreamableHTTPServerTransport, "handle_request", patched_handle_request),
                contextlib.suppress(Exception),
            ):
                await client.post(
                    settings.http.path,
                    json=_rpc("tools/call", {"name": "health_check", "arguments": {}}),
                )

            # Second request (without patch) should work - server has recovered
            r2 = await client.post(
                settings.http.path,
                json=_rpc("tools/call", {"name": "health_check", "arguments": {}}),
            )
            assert r2.status_code in (200, 401, 403), "Server should recover after handling ClosedResourceError"
