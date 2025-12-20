"""Integration tests for message delivery latency investigation.

This test suite investigates why messages sometimes aren't found immediately
after being sent, despite SQLite's local storage which should be fast.

Potential causes:
1. Archive write lock contention
2. Connection pool isolation issues
3. WAL mode checkpoint delays
4. Git archive write blocking
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

import pytest
from fastmcp import Client
from rich import print as rich_print

from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.db import reset_database_state

MAX_RETRY_ATTEMPTS = 20
RETRY_DELAY_SECONDS = 0.1
NUM_RAPID_CYCLES = 10
NUM_FETCH_MEASUREMENTS = 20
MAX_FETCH_LATENCY_SECONDS = 0.5
NUM_FRESH_SESSION_TESTS = 5
MAX_WAIT_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.1
NUM_STRESS_SENDERS = 5
MESSAGES_PER_SENDER = 5


def extract_inbox(inbox_result) -> list[dict[str, Any]]:
    """Extract inbox messages from various result formats."""
    # Handle different response formats from fastmcp
    if hasattr(inbox_result, "structured_content") and inbox_result.structured_content:
        content = inbox_result.structured_content
        if hasattr(content, "root"):
            return content.root if isinstance(content.root, list) else []
        if isinstance(content, dict):
            return content.get("result", content.get("messages", []))
        if isinstance(content, list):
            return content
    if hasattr(inbox_result, "data"):
        data = inbox_result.data
        if hasattr(data, "root"):
            return data.root if isinstance(data.root, list) else []
        if isinstance(data, dict):
            return data.get("result", data.get("messages", []))
        if isinstance(data, list):
            return data
    return []


def extract_send_data(send_result) -> dict[str, Any]:
    """Extract send message data from various result formats."""
    if hasattr(send_result, "data"):
        data = send_result.data
        if hasattr(data, "root"):
            return data.root if isinstance(data.root, dict) else {}
        if isinstance(data, dict):
            return data
    return {}


@pytest.mark.asyncio
async def test_immediate_message_visibility_single_client(isolated_env):
    """
    Test that a message is immediately visible after send using a single client.

    This establishes the baseline behavior.
    """
    server = build_mcp_server()
    async with Client(server) as client:
        # Setup
        await client.call_tool(
            "register_agent",
            {"project_key": "/latency/test", "program": "sender", "model": "test", "name": "Sender"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "/latency/test", "program": "receiver", "model": "test", "name": "Receiver"},
        )

        # Send and immediately fetch
        send_start = time.perf_counter()
        send_result = await client.call_tool(
            "send_message",
            {
                "project_key": "/latency/test",
                "sender_name": "Sender",
                "to": ["Receiver"],
                "subject": "Latency Test",
                "body_md": "Testing immediate visibility",
            },
        )
        send_elapsed = time.perf_counter() - send_start

        send_data = extract_send_data(send_result)
        message_id = send_data["deliveries"][0]["payload"]["id"]

        # Immediate fetch (no delay)
        fetch_start = time.perf_counter()
        inbox_result = await client.call_tool(
            "fetch_inbox",
            {"project_key": "/latency/test", "agent_name": "Receiver", "include_bodies": True},
        )
        fetch_elapsed = time.perf_counter() - fetch_start

        inbox = extract_inbox(inbox_result)

        # Should find message immediately
        matching = [m for m in inbox if m["id"] == message_id]
        assert matching, (
            f"Message {message_id} not found. Send took {send_elapsed:.3f}s, fetch took {fetch_elapsed:.3f}s"
        )

        rich_print(f"\n[TIMING] Single client - Send: {send_elapsed:.3f}s, Fetch: {fetch_elapsed:.3f}s")


@pytest.mark.asyncio
async def test_immediate_message_visibility_separate_clients(isolated_env):
    """
    Test message visibility using separate MCP client instances.

    This tests for potential session isolation issues where different
    connections might not see each other's commits immediately.
    """
    server = build_mcp_server()

    # Use first client for setup and sending
    async with Client(server) as sender_client:
        await sender_client.call_tool(
            "register_agent",
            {"project_key": "/latency/test2", "program": "sender", "model": "test", "name": "Sender2"},
        )
        await sender_client.call_tool(
            "register_agent",
            {"project_key": "/latency/test2", "program": "receiver", "model": "test", "name": "Receiver2"},
        )

        send_start = time.perf_counter()
        send_result = await sender_client.call_tool(
            "send_message",
            {
                "project_key": "/latency/test2",
                "sender_name": "Sender2",
                "to": ["Receiver2"],
                "subject": "Separate Client Test",
                "body_md": "Testing visibility across clients",
            },
        )
        send_elapsed = time.perf_counter() - send_start
        send_data = extract_send_data(send_result)
        message_id = send_data["deliveries"][0]["payload"]["id"]

    # Use a completely new client instance for fetching
    async with Client(server) as receiver_client:
        fetch_start = time.perf_counter()
        inbox_result = await receiver_client.call_tool(
            "fetch_inbox",
            {"project_key": "/latency/test2", "agent_name": "Receiver2", "include_bodies": True},
        )
        fetch_elapsed = time.perf_counter() - fetch_start

        inbox = extract_inbox(inbox_result)

        matching = [m for m in inbox if m["id"] == message_id]
        assert matching, (
            f"Message {message_id} not found with separate client. Send: {send_elapsed:.3f}s, Fetch: {fetch_elapsed:.3f}s"
        )

        rich_print(f"\n[TIMING] Separate clients - Send: {send_elapsed:.3f}s, Fetch: {fetch_elapsed:.3f}s")


@pytest.mark.asyncio
async def test_concurrent_send_and_fetch(isolated_env):
    """
    Test message visibility when send and fetch happen nearly simultaneously.

    This tests for race conditions where a fetch might start before
    the DB transaction commits.
    """
    server = build_mcp_server()

    async with Client(server) as client:
        # Setup
        await client.call_tool(
            "register_agent",
            {"project_key": "/latency/concurrent", "program": "sender", "model": "test", "name": "ConcurrentSender"},
        )
        await client.call_tool(
            "register_agent",
            {
                "project_key": "/latency/concurrent",
                "program": "receiver",
                "model": "test",
                "name": "ConcurrentReceiver",
            },
        )

        results: dict[str, Any] = {"message_id": None, "found": False, "attempts": 0}

        async def send_message():
            result = await client.call_tool(
                "send_message",
                {
                    "project_key": "/latency/concurrent",
                    "sender_name": "ConcurrentSender",
                    "to": ["ConcurrentReceiver"],
                    "subject": "Concurrent Test",
                    "body_md": "Testing concurrent access",
                },
            )
            send_data = extract_send_data(result)
            results["message_id"] = send_data["deliveries"][0]["payload"]["id"]
            return result

        async def fetch_with_retry(
            max_retries: int = MAX_RETRY_ATTEMPTS, delay: float = RETRY_DELAY_SECONDS
        ) -> tuple[int, list[dict[str, Any]]]:
            """Fetch inbox with retry to measure how long until message appears."""
            for attempt in range(max_retries):
                results["attempts"] = attempt + 1
                inbox_result = await client.call_tool(
                    "fetch_inbox",
                    {"project_key": "/latency/concurrent", "agent_name": "ConcurrentReceiver"},
                )
                inbox = extract_inbox(inbox_result)

                if results["message_id"] and any(m["id"] == results["message_id"] for m in inbox):
                    results["found"] = True
                    return attempt, inbox

                await asyncio.sleep(delay)

            return max_retries, []

        # Run send and fetch concurrently
        start = time.perf_counter()
        send_task = asyncio.create_task(send_message())

        # Wait a tiny bit to ensure send starts first
        await asyncio.sleep(0.001)

        fetch_task = asyncio.create_task(fetch_with_retry())

        await send_task
        attempts, _ = await fetch_task
        elapsed = time.perf_counter() - start

        assert results["found"], f"Message not found after {attempts} attempts ({elapsed:.3f}s total)"
        rich_print(f"\n[TIMING] Concurrent - Found after {attempts} attempts, {elapsed:.3f}s total")


@pytest.mark.asyncio
async def test_rapid_send_fetch_cycles(isolated_env):
    """
    Test multiple rapid send-fetch cycles to catch intermittent latency issues.

    Sometimes latency issues are intermittent and only appear under certain conditions.
    """
    server = build_mcp_server()

    async with Client(server) as client:
        await client.call_tool(
            "register_agent",
            {"project_key": "/latency/rapid", "program": "sender", "model": "test", "name": "RapidSender"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "/latency/rapid", "program": "receiver", "model": "test", "name": "RapidReceiver"},
        )

        timings: list[dict[str, float]] = []
        failures: list[int] = []

        for i in range(NUM_RAPID_CYCLES):
            send_start = time.perf_counter()
            send_result = await client.call_tool(
                "send_message",
                {
                    "project_key": "/latency/rapid",
                    "sender_name": "RapidSender",
                    "to": ["RapidReceiver"],
                    "subject": f"Rapid Test {i}",
                    "body_md": f"Message {i}",
                },
            )
            send_elapsed = time.perf_counter() - send_start
            send_data = extract_send_data(send_result)
            message_id = send_data["deliveries"][0]["payload"]["id"]

            fetch_start = time.perf_counter()
            inbox_result = await client.call_tool(
                "fetch_inbox",
                {"project_key": "/latency/rapid", "agent_name": "RapidReceiver"},
            )
            fetch_elapsed = time.perf_counter() - fetch_start

            inbox = extract_inbox(inbox_result)
            found = any(m["id"] == message_id for m in inbox)

            timings.append(
                {
                    "cycle": i,
                    "send": send_elapsed,
                    "fetch": fetch_elapsed,
                    "total": send_elapsed + fetch_elapsed,
                    "found": found,
                }
            )

            if not found:
                failures.append(i)

        # Report timing statistics
        send_times = [t["send"] for t in timings]
        fetch_times = [t["fetch"] for t in timings]
        total_times = [t["total"] for t in timings]

        rich_print(f"\n[TIMING] Rapid cycles (n={NUM_RAPID_CYCLES}):")
        rich_print(
            f"  Send  - min: {min(send_times):.3f}s, max: {max(send_times):.3f}s, avg: {sum(send_times) / len(send_times):.3f}s"
        )
        rich_print(
            f"  Fetch - min: {min(fetch_times):.3f}s, max: {max(fetch_times):.3f}s, avg: {sum(fetch_times) / len(fetch_times):.3f}s"
        )
        rich_print(
            f"  Total - min: {min(total_times):.3f}s, max: {max(total_times):.3f}s, avg: {sum(total_times) / len(total_times):.3f}s"
        )

        if failures:
            rich_print(f"  FAILURES at cycles: {failures}")

        assert not failures, f"Message not immediately visible at cycles: {failures}"


@pytest.mark.asyncio
async def test_message_visibility_with_db_session_reset(isolated_env):
    """
    Test that explicitly resetting DB state between operations doesn't affect visibility.

    This tests if there's caching at the session factory level.
    """
    server = build_mcp_server()

    async with Client(server) as client:
        await client.call_tool(
            "register_agent",
            {"project_key": "/latency/reset", "program": "sender", "model": "test", "name": "ResetSender"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "/latency/reset", "program": "receiver", "model": "test", "name": "ResetReceiver"},
        )

        send_result = await client.call_tool(
            "send_message",
            {
                "project_key": "/latency/reset",
                "sender_name": "ResetSender",
                "to": ["ResetReceiver"],
                "subject": "Reset Test",
                "body_md": "Testing after state reset",
            },
        )
        send_data = extract_send_data(send_result)
        message_id = send_data["deliveries"][0]["payload"]["id"]

        # Reset DB state to force new connections
        reset_database_state()

        # Fetch with fresh session
        inbox_result = await client.call_tool(
            "fetch_inbox",
            {"project_key": "/latency/reset", "agent_name": "ResetReceiver"},
        )

        inbox = extract_inbox(inbox_result)
        matching = [m for m in inbox if m["id"] == message_id]

        assert matching, f"Message {message_id} not found after DB state reset"


@pytest.mark.asyncio
async def test_parallel_sends_then_fetch(isolated_env):
    """
    Test visibility when multiple messages are sent in parallel before fetching.

    Archive lock contention could cause delays when multiple agents send simultaneously.
    """
    server = build_mcp_server()

    async with Client(server) as client:
        # Setup multiple senders
        senders = ["ParallelA", "ParallelB", "ParallelC"]
        for name in senders:
            await client.call_tool(
                "register_agent",
                {"project_key": "/latency/parallel", "program": "sender", "model": "test", "name": name},
            )

        await client.call_tool(
            "register_agent",
            {"project_key": "/latency/parallel", "program": "receiver", "model": "test", "name": "ParallelReceiver"},
        )

        async def send_from(sender_name: str):
            start = time.perf_counter()
            result = await client.call_tool(
                "send_message",
                {
                    "project_key": "/latency/parallel",
                    "sender_name": sender_name,
                    "to": ["ParallelReceiver"],
                    "subject": f"From {sender_name}",
                    "body_md": f"Parallel message from {sender_name}",
                },
            )
            elapsed = time.perf_counter() - start
            send_data = extract_send_data(result)
            return sender_name, send_data["deliveries"][0]["payload"]["id"], elapsed

        # Send from all senders in parallel
        start = time.perf_counter()
        results = await asyncio.gather(*[send_from(s) for s in senders])
        parallel_send_elapsed = time.perf_counter() - start

        message_ids = {r[1] for r in results}
        timings = {r[0]: r[2] for r in results}

        # Immediately fetch
        fetch_start = time.perf_counter()
        inbox_result = await client.call_tool(
            "fetch_inbox",
            {"project_key": "/latency/parallel", "agent_name": "ParallelReceiver"},
        )
        fetch_elapsed = time.perf_counter() - fetch_start

        inbox = extract_inbox(inbox_result)
        found_ids = {m["id"] for m in inbox}

        missing = message_ids - found_ids

        rich_print("\n[TIMING] Parallel sends:")
        rich_print(f"  Total parallel send time: {parallel_send_elapsed:.3f}s")
        for sender, elapsed in timings.items():
            rich_print(f"  {sender}: {elapsed:.3f}s")
        rich_print(f"  Fetch: {fetch_elapsed:.3f}s")

        assert not missing, f"Missing messages after parallel send: {missing}"


@pytest.mark.asyncio
async def test_fetch_latency_measurement(isolated_env):
    """
    Measure fetch latency over multiple calls to identify if fetches themselves are slow.
    """
    server = build_mcp_server()

    async with Client(server) as client:
        await client.call_tool(
            "register_agent",
            {"project_key": "/latency/measure", "program": "agent", "model": "test", "name": "MeasureAgent"},
        )

        # Warm up
        await client.call_tool(
            "fetch_inbox",
            {"project_key": "/latency/measure", "agent_name": "MeasureAgent"},
        )

        # Measure fetch latency
        fetch_times: list[float] = []
        for _ in range(NUM_FETCH_MEASUREMENTS):
            start = time.perf_counter()
            await client.call_tool(
                "fetch_inbox",
                {"project_key": "/latency/measure", "agent_name": "MeasureAgent"},
            )
            fetch_times.append(time.perf_counter() - start)

        avg = sum(fetch_times) / len(fetch_times)
        rich_print(f"\n[TIMING] Fetch latency (n={NUM_FETCH_MEASUREMENTS}):")
        rich_print(f"  min: {min(fetch_times) * 1000:.1f}ms")
        rich_print(f"  max: {max(fetch_times) * 1000:.1f}ms")
        rich_print(f"  avg: {avg * 1000:.1f}ms")

        # Fetch should be fast for empty inbox
        assert avg < MAX_FETCH_LATENCY_SECONDS, (
            f"Average fetch latency {avg:.3f}s exceeds {MAX_FETCH_LATENCY_SECONDS * 1000:.0f}ms threshold"
        )


@pytest.mark.asyncio
async def test_message_visibility_with_fresh_db_sessions(isolated_env):
    """
    Test message visibility when forcing fresh database sessions.

    This simulates what might happen in production where different
    processes/workers each create their own database connections.
    """
    server = build_mcp_server()

    async with Client(server) as client:
        await client.call_tool(
            "register_agent",
            {"project_key": "/latency/fresh", "program": "sender", "model": "test", "name": "FreshSender"},
        )
        await client.call_tool(
            "register_agent",
            {"project_key": "/latency/fresh", "program": "receiver", "model": "test", "name": "FreshReceiver"},
        )

        latencies: list[tuple[int, float]] = []  # (attempt, time_to_find)

        for i in range(NUM_FRESH_SESSION_TESTS):
            # Send message
            send_result = await client.call_tool(
                "send_message",
                {
                    "project_key": "/latency/fresh",
                    "sender_name": "FreshSender",
                    "to": ["FreshReceiver"],
                    "subject": f"Fresh Session Test {i}",
                    "body_md": f"Message {i} testing fresh session visibility",
                },
            )
            send_data = extract_send_data(send_result)
            message_id = send_data["deliveries"][0]["payload"]["id"]

            # Force fresh connections
            reset_database_state()

            # Try to fetch with timing
            start = time.perf_counter()
            found = False
            attempts = 0
            max_attempts = max(1, math.ceil(MAX_WAIT_SECONDS / POLL_INTERVAL_SECONDS))

            while not found and attempts < max_attempts:
                attempts += 1
                inbox_result = await client.call_tool(
                    "fetch_inbox",
                    {"project_key": "/latency/fresh", "agent_name": "FreshReceiver"},
                )
                inbox = extract_inbox(inbox_result)
                if any(m["id"] == message_id for m in inbox):
                    found = True
                else:
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)

            elapsed = time.perf_counter() - start
            latencies.append((attempts, elapsed))

            assert found, f"Message {i} not found after {attempts} attempts"

        rich_print("\n[TIMING] Fresh DB session tests:")
        for i, (attempts, elapsed) in enumerate(latencies):
            rich_print(f"  Message {i}: found after {attempts} attempts ({elapsed:.3f}s)")

        avg_attempts = sum(a for a, _ in latencies) / len(latencies)
        avg_time = sum(t for _, t in latencies) / len(latencies)
        rich_print(f"  Average: {avg_attempts:.1f} attempts, {avg_time:.3f}s")

        # Should be found in first attempt
        assert avg_attempts < 2, f"Average attempts {avg_attempts} > 1, indicating visibility delay"


@pytest.mark.asyncio
async def test_stress_many_concurrent_messages(isolated_env):
    """
    Stress test: Send many messages concurrently and verify all are visible.

    High concurrency might expose lock contention or connection pool issues.
    """
    server = build_mcp_server()

    async with Client(server) as client:
        # Setup: 5 senders, 1 receiver
        senders = [f"StressSender{i}" for i in range(NUM_STRESS_SENDERS)]
        for name in senders:
            await client.call_tool(
                "register_agent",
                {"project_key": "/latency/stress", "program": "sender", "model": "test", "name": name},
            )

        await client.call_tool(
            "register_agent",
            {"project_key": "/latency/stress", "program": "receiver", "model": "test", "name": "StressReceiver"},
        )

        # Each sender sends messages for a combined total across senders
        async def send_messages(sender: str, count: int):
            results = []
            for i in range(count):
                result = await client.call_tool(
                    "send_message",
                    {
                        "project_key": "/latency/stress",
                        "sender_name": sender,
                        "to": ["StressReceiver"],
                        "subject": f"Stress {sender} msg {i}",
                        "body_md": f"Stress test message {i} from {sender}",
                    },
                )
                send_data = extract_send_data(result)
                results.append(send_data["deliveries"][0]["payload"]["id"])
            return results

        # Send from all senders in parallel
        start = time.perf_counter()
        all_results = await asyncio.gather(*[send_messages(s, MESSAGES_PER_SENDER) for s in senders])
        send_elapsed = time.perf_counter() - start

        all_message_ids = set()
        for sender_results in all_results:
            all_message_ids.update(sender_results)

        expected_total = NUM_STRESS_SENDERS * MESSAGES_PER_SENDER
        assert len(all_message_ids) == expected_total, (
            f"Expected {expected_total} message IDs, got {len(all_message_ids)}"
        )

        # Now fetch inbox and check all messages are visible
        fetch_start = time.perf_counter()
        inbox_result = await client.call_tool(
            "fetch_inbox",
            {"project_key": "/latency/stress", "agent_name": "StressReceiver", "limit": 100},
        )
        fetch_elapsed = time.perf_counter() - fetch_start

        inbox = extract_inbox(inbox_result)
        found_ids = {m["id"] for m in inbox}

        missing = all_message_ids - found_ids

        rich_print(f"\n[TIMING] Stress test ({expected_total} messages from {NUM_STRESS_SENDERS} senders):")
        rich_print(f"  Total send time: {send_elapsed:.3f}s")
        rich_print(f"  Fetch time: {fetch_elapsed:.3f}s")
        rich_print(f"  Messages found: {len(found_ids)}/{expected_total}")

        if missing:
            rich_print(f"  MISSING: {len(missing)} messages")

        assert not missing, f"Missing {len(missing)} messages after stress test: {missing}"
