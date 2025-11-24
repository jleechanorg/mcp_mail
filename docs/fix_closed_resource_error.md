# Fix: ClosedResourceError Crash When Client Disconnects

## Issue

When MCP clients (like Codex) connect to the server and disconnect during message routing, the server crashes with:

```text
ERROR:mcp.server.streamable_http:Error in message router
Traceback (most recent call last):
  File ".../mcp/server/streamable_http.py", line 831, in message_router
    async for session_message in write_stream_reader:
  File ".../anyio/abc/_streams.py", line 41, in __anext__
    return await self.receive()
  File ".../anyio/streams/memory.py", line 111, in receive
    return self.receive_nowait()
  File ".../anyio/streams/memory.py", line 93, in receive_nowait
    raise ClosedResourceError
anyio.ClosedResourceError

ERROR:    Exception in ASGI application
  + Exception Group Traceback (most recent call last):
  ...
```

## Root Cause

In `StatelessMCPASGIApp.__call__()`, when a client disconnects:
1. The `http_transport.connect()` context manager exits
2. This closes the streams
3. The `server_task` (running `mcp_server.run()`) is still trying to read from those streams
4. `anyio.ClosedResourceError` is raised in the message router
5. The exception propagates through the ASGI middleware stack

## Local Reproduction

### 1. Started Real MCP Server

```bash
export DATABASE_URL="sqlite+aiosqlite:////tmp/mcp_test_db/test.sqlite3"
export HTTP_HOST="127.0.0.1"
export HTTP_PORT="18765"
uv run python -m mcp_agent_mail.http --host 127.0.0.1 --port 18765
```

### 2. Triggered ClosedResourceError

```python
import asyncio
import httpx

async def trigger_streaming_disconnect():
    async with httpx.AsyncClient(base_url='http://127.0.0.1:18765', timeout=2.0) as client:
        # Make streaming request and abort mid-stream
        async with client.stream('POST', '/mcp', json={
            'jsonrpc': '2.0',
            'id': '1',
            'method': 'tools/list',
            'params': {}
        }, headers={'Accept': 'text/event-stream'}) as response:
            async for chunk in response.aiter_bytes():
                break  # Abort after first chunk

asyncio.run(trigger_streaming_disconnect())
```

### 3. Server Logs Showed Exact Error

```text
ERROR:mcp.server.streamable_http:Error in message router
Traceback (most recent call last):
  File "/home/user/mcp_mail/.venv/lib/python3.11/site-packages/mcp/server/streamable_http.py", line 831, in message_router
    async for session_message in write_stream_reader:
  File "/home/user/mcp_mail/.venv/lib/python3.11/site-packages/anyio/abc/_streams.py", line 41, in __anext__
    return await self.receive()
  File "/home/user/mcp_mail/.venv/lib/python3.11/site-packages/anyio/streams/memory.py", line 111, in receive
    return self.receive_nowait()
  File "/home/user/mcp_mail/.venv/lib/python3.11/site-packages/anyio/streams/memory.py", line 93, in receive_nowait
    raise ClosedResourceError
anyio.ClosedResourceError
INFO:     127.0.0.1:44676 - "POST /mcp HTTP/1.1" 200 OK
```

## Fix Applied

**File:** `src/mcp_agent_mail/http.py` (lines 935-977)

```python
try:
    async with http_transport.connect() as streams:
        read_stream, write_stream = streams
        server_task = asyncio.create_task(
            self._server._mcp_server.run(
                read_stream,
                write_stream,
                self._server._mcp_server.create_initialization_options(),
                stateless=True,
            )
        )
        try:
            await http_transport.handle_request(new_scope, receive, send)
        finally:
            server_task.cancel()
            await asyncio.wait({server_task}, timeout=0.1)
            try:
                await http_transport.terminate()
            except anyio.ClosedResourceError:
                pass  # Expected on client disconnect
            except Exception:
                structlog.get_logger().error(
                    "Unexpected error during http_transport.terminate()",
                    exc_info=True,
                )
            with contextlib.suppress(asyncio.CancelledError):
                await server_task
except anyio.ClosedResourceError:
    pass
except (ExceptionGroup, BaseExceptionGroup) as eg:
    non_closed = [e for e in eg.exceptions if not isinstance(e, anyio.ClosedResourceError)]
    if non_closed:
        message = eg.message if hasattr(eg, "message") else eg.args[0] if eg.args else str(eg)
        derived = eg.derive(non_closed) if hasattr(eg, "derive") else type(eg)(message, non_closed)
        raise derived from eg
```

## Test Results

### Unit Tests (5 tests)
**File:** `tests/test_http_closed_resource_error.py`

```text
tests/test_http_closed_resource_error.py::test_closed_resource_error_handled_gracefully PASSED
tests/test_http_closed_resource_error.py::test_closed_resource_error_in_connect_suppressed PASSED
tests/test_http_closed_resource_error.py::test_handle_request_closed_resource_error_suppressed PASSED
tests/test_http_closed_resource_error.py::test_exception_group_with_closed_resource_error PASSED
tests/test_http_closed_resource_error.py::test_server_recovers_after_closed_resource_error PASSED
```

### Integration Tests (4 tests) - Real Server
**File:** `tests/integration/test_closed_resource_error_integration.py`

```text
tests/integration/test_closed_resource_error_integration.py::test_server_handles_disconnect_gracefully PASSED
tests/integration/test_closed_resource_error_integration.py::test_server_continues_after_disconnect PASSED
tests/integration/test_closed_resource_error_integration.py::test_multiple_disconnects_dont_crash_server PASSED
tests/integration/test_closed_resource_error_integration.py::test_no_asgi_exception_in_logs PASSED
```

### Existing HTTP Tests (10 tests)
```text
tests/test_http_transport.py: 5 passed
tests/test_http_unit.py: 2 passed
tests/test_http_logging_and_errors.py: 3 passed
```

## Verification

After applying the fix and running the same reproduction steps:
1. Server no longer crashes when clients disconnect mid-stream
2. Server continues to respond to subsequent requests
3. No "Exception in ASGI application" errors in logs
4. Multiple rapid disconnects don't cause server instability

## Commit

```text
4f52383 Fix ClosedResourceError crash when client disconnects during MCP request
69cb601 Fix ruff linting errors in test files
bcd4ddd Address review feedback (from PR #70)
```

Branch: `claude/fix-mail-crash-01ALo4EddmAe7DM4TsyRYXsN`
