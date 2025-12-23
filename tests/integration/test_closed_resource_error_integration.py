"""Integration test for ClosedResourceError handling with real server.

This test starts a real HTTP server and triggers the ClosedResourceError
by disconnecting clients mid-stream, simulating what happens when Codex
or other MCP clients disconnect during message routing.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import socket
import sys
import time
from pathlib import Path

import httpx
import pytest


def _find_free_port() -> int:
    """Find a free port to use for the test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_server(port: int, db_path: str, log_path: str) -> None:
    """Run the MCP server in a separate process."""
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["HTTP_HOST"] = "127.0.0.1"
    os.environ["HTTP_PORT"] = str(port)
    os.environ["HTTP_PATH"] = "/mcp"
    os.environ["APP_ENVIRONMENT"] = "test"

    # Redirect stdout/stderr to log file
    with Path(log_path).open("w") as log_file:
        sys.stdout = log_file
        sys.stderr = log_file

        import uvicorn

        from mcp_agent_mail.app import build_mcp_server
        from mcp_agent_mail.config import clear_settings_cache, get_settings
        from mcp_agent_mail.http import build_http_app

        clear_settings_cache()
        settings = get_settings()
        server = build_mcp_server()
        app = build_http_app(settings, server)

        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


def _wait_for_server(port: int, timeout: float = 10.0) -> bool:
    """Wait for the server to start accepting connections."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    return False


@pytest.fixture
def real_server(tmp_path):
    """Start a real MCP server for integration testing."""
    port = _find_free_port()
    db_path = str(tmp_path / "test.sqlite3")
    log_path = str(tmp_path / "server.log")

    # Start server in separate process
    proc = multiprocessing.Process(
        target=_run_server,
        args=(port, db_path, log_path),
        daemon=True,
    )
    proc.start()

    # Wait for server to be ready
    if not _wait_for_server(port):
        proc.terminate()
        proc.join(timeout=2)
        pytest.fail("Server failed to start")

    yield {"port": port, "log_path": log_path, "base_url": f"http://127.0.0.1:{port}"}

    # Cleanup
    proc.terminate()
    proc.join(timeout=2)
    if proc.is_alive():
        proc.kill()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_server_handles_disconnect_gracefully(real_server):
    """Test that server handles client disconnect gracefully without crashing.

    This test triggers a client disconnect mid-stream and verifies the server
    continues to function. The ClosedResourceError may or may not be visible
    in logs depending on log level configuration.
    """
    base_url = real_server["base_url"]

    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        # Make a streaming request and abort mid-stream
        try:
            async with client.stream(
                "POST",
                "/mcp/",
                json={
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "tools/list",
                    "params": {},
                },
                headers={"Accept": "text/event-stream"},
            ) as response:
                # Read first chunk then abort
                async for _ in response.aiter_bytes():
                    break  # Abort after first chunk
        except Exception:
            # Exceptions are expected here due to client disconnect; ignore to allow test to proceed.
            pass

        # Give server time to process
        await asyncio.sleep(0.3)

        # Verify server is still responsive after the disconnect
        response = await client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": "2",
                "method": "tools/call",
                "params": {"name": "health_check", "arguments": {}},
            },
        )
        assert response.status_code == 200, "Server should still respond after client disconnect"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_server_continues_after_disconnect(real_server):
    """Test that server continues to work after client disconnects."""
    base_url = real_server["base_url"]

    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        # First: trigger a disconnect
        try:
            async with client.stream(
                "POST",
                "/mcp/",
                json={"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}},
                headers={"Accept": "text/event-stream"},
            ) as response:
                async for _ in response.aiter_bytes():
                    break
        except Exception:
            # Exceptions are expected here due to client disconnect; ignore to allow test to proceed.
            pass

        # Give server time to process the error
        await asyncio.sleep(0.3)

        # Second: make a normal request - server should still work
        response = await client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": "2",
                "method": "tools/call",
                "params": {"name": "health_check", "arguments": {}},
            },
        )

        # Server should respond normally
        assert response.status_code == 200, f"Server should still work. Got: {response.status_code}"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_multiple_disconnects_dont_crash_server(real_server):
    """Test that multiple rapid disconnects don't crash the server."""
    base_url = real_server["base_url"]

    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        # Trigger multiple disconnects
        for i in range(5):
            try:
                async with client.stream(
                    "POST",
                    "/mcp/",
                    json={"jsonrpc": "2.0", "id": str(i), "method": "tools/list", "params": {}},
                    headers={"Accept": "text/event-stream"},
                ) as response:
                    async for _ in response.aiter_bytes():
                        break
            except Exception:
                # Ignore exceptions caused by intentional client disconnects.
                pass
            await asyncio.sleep(0.1)

        # Server should still respond
        response = await client.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": "final",
                "method": "tools/call",
                "params": {"name": "health_check", "arguments": {}},
            },
        )
        assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.slow
async def test_no_asgi_exception_in_logs(real_server):
    """Test that ASGI application exception is NOT logged after fix.

    The original bug caused 'Exception in ASGI application' to be logged
    along with ExceptionGroup traceback. After fix, this should not appear.
    """
    base_url = real_server["base_url"]
    log_path = real_server["log_path"]

    # Clear log
    Path(log_path).write_text("")

    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        # Trigger disconnects
        for i in range(3):
            try:
                async with client.stream(
                    "POST",
                    "/mcp/",
                    json={"jsonrpc": "2.0", "id": str(i), "method": "tools/list", "params": {}},
                    headers={"Accept": "text/event-stream"},
                ) as response:
                    async for _ in response.aiter_bytes():
                        break
            except Exception:
                # Ignore exceptions caused by intentional client disconnects.
                pass

    await asyncio.sleep(0.5)

    log_content = Path(log_path).read_text()

    # After fix: Should NOT see "Exception in ASGI application"
    # This is the key assertion - the fix should prevent this error
    assert "Exception in ASGI application" not in log_content, (
        f"ASGI application exception should not be logged after fix.\nLog:\n{log_content}"
    )

    # ExceptionGroup should also not propagate
    assert "ExceptionGroup" not in log_content and "BaseExceptionGroup" not in log_content, (
        f"ExceptionGroup should not propagate after fix.\nLog:\n{log_content}"
    )
