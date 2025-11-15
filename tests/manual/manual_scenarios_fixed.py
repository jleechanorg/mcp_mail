#!/usr/bin/env python3
"""
Fixed Manual Test Scenarios for MCP Agent Mail

This script contains corrected test implementations:
- Test 1.2: Updated expectations for agent_filter (sender OR recipient)
- Test 2.1: Fixed timing for since_ts (capture T0 between batches)

IMPORTANT: Uses unique project key per run to avoid test pollution from previous runs.

FIX (mcp_agent_mail-7rj): Agent names are normalized via sanitize_agent_name().
The test intentionally uses underscores to exercise the sanitizer, then captures
the returned canonical name for subsequent operations.
"""

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.db import reset_database_state

# Generate unique project key per run to avoid test pollution
PROJECT_KEY = f"test_manual_{uuid.uuid4().hex[:8]}"

# Test timing constants
MESSAGE_PROCESSING_DELAY = 0.5  # Allow time for message processing
TIMESTAMP_SEPARATION_DELAY = 1.0  # Ensure clear timestamp separation between batches


class TestResults:
    """Track test results."""

    def __init__(self):
        self.tests = []
        self.start_time = datetime.now(timezone.utc)

    def add_result(self, test_id, name, status, details=None, error=None):
        self.tests.append(
            {
                "test_id": test_id,
                "name": name,
                "status": status,
                "details": details,
                "error": str(error) if error else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        emoji = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⏭️"
        print(f"\n{emoji} {test_id}: {name} - {status}")
        if details:
            print(f"   Details: {details}")
        if error:
            print(f"   Error: {error}")

    def get_summary(self):
        total = len(self.tests)
        passed = sum(1 for t in self.tests if t["status"] == "PASS")
        failed = sum(1 for t in self.tests if t["status"] == "FAIL")
        return {"total": total, "passed": passed, "failed": failed}


async def test_1_2_agent_filter_FIXED(client, results):
    """Test 1.2: Agent Filter in Search (FIXED EXPECTATIONS)"""
    test_id = "Test-1.2-FIXED"
    test_name = "Agent Filter in Search (sender OR recipient)"

    try:
        print(f"\n{'=' * 70}")
        print(f"Executing {test_id}: {test_name}")
        print(f"Project: {PROJECT_KEY}")
        print(f"{'=' * 70}")

        # Register two agents with unique names per run
        # NOTE: Agent names are normalized via sanitize_agent_name() (src/mcp_agent_mail/utils.py)
        # Non-alphanumeric characters (including underscores) are stripped.
        # We intentionally use underscores here to exercise the sanitizer, then capture
        # the returned canonical name for use in subsequent operations.
        alice_result = await client.call_tool(
            "register_agent",
            {
                "project_key": PROJECT_KEY,
                "program": "test-cli",
                "model": "test-model",
                "name": f"Alice_{uuid.uuid4().hex[:6]}",  # Will be sanitized to "Aliceabc123"
            },
        )
        # CRITICAL: Use the returned name (sanitized), not the input name
        alice_name = alice_result.data.get("name") if hasattr(alice_result, "data") else alice_result.get("name")

        bob_result = await client.call_tool(
            "register_agent",
            {
                "project_key": PROJECT_KEY,
                "program": "test-cli",
                "model": "test-model",
                "name": f"Bob_{uuid.uuid4().hex[:6]}",  # Will be sanitized to "Bobdef456"
            },
        )
        # CRITICAL: Use the returned name (sanitized), not the input name
        bob_name = bob_result.data.get("name") if hasattr(bob_result, "data") else bob_result.get("name")

        print(f"Registered agents: {alice_name}, {bob_name}")

        # Alice sends 3 messages to Bob
        for i in range(3):
            await client.call_tool(
                "send_message",
                {
                    "project_key": PROJECT_KEY,
                    "sender_name": alice_name,  # Use returned (sanitized) name
                    "to": [bob_name],  # Use returned (sanitized) name
                    "subject": f"Alice testing message {i + 1}",
                    "body_md": f"Testing content from Alice {i + 1}",
                },
            )

        # Bob sends 2 messages to Alice
        for i in range(2):
            await client.call_tool(
                "send_message",
                {
                    "project_key": PROJECT_KEY,
                    "sender_name": bob_name,  # Use returned (sanitized) name
                    "to": [alice_name],  # Use returned (sanitized) name
                    "subject": f"Bob testing message {i + 1}",
                    "body_md": f"Testing content from Bob {i + 1}",
                },
            )

        await asyncio.sleep(MESSAGE_PROCESSING_DELAY)

        # Search with Alice filter
        # CORRECTED EXPECTATION: Alice is involved in 5 messages:
        # - 3 messages she sent (Alice is sender)
        # - 2 messages she received (Alice is recipient)
        result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": PROJECT_KEY,
                "query": "testing",
                "agent_filter": alice_name,  # Use returned (sanitized) name
                "limit": 10,
            },
        )

        if hasattr(result, "structured_content") and result.structured_content:
            alice_results = result.structured_content.get("result", [])
        elif hasattr(result, "data"):
            alice_results = result.data if isinstance(result.data, list) else []
        else:
            alice_results = []

        alice_count = len(alice_results)

        # Search with Bob filter
        # CORRECTED EXPECTATION: Bob is involved in 5 messages:
        # - 2 messages he sent (Bob is sender)
        # - 3 messages he received (Bob is recipient)
        result = await client.call_tool(
            "search_mailbox",
            {
                "project_key": PROJECT_KEY,
                "query": "testing",
                "agent_filter": bob_name,  # Use returned (sanitized) name
                "limit": 10,
            },
        )

        if hasattr(result, "structured_content") and result.structured_content:
            bob_results = result.structured_content.get("result", [])
        elif hasattr(result, "data"):
            bob_results = result.data if isinstance(result.data, list) else []
        else:
            bob_results = []

        bob_count = len(bob_results)

        # CORRECTED VALIDATION: Both should have 5 messages (sender OR recipient)
        if alice_count == 5 and bob_count == 5:
            results.add_result(
                test_id,
                test_name,
                "PASS",
                (
                    f"Agent filtering works correctly (Alice: {alice_count}, Bob: {bob_count}) - "
                    f"returns messages where agent is sender OR recipient"
                ),
            )
        else:
            results.add_result(
                test_id,
                test_name,
                "FAIL",
                f"Expected 5 for both Alice and Bob, got Alice: {alice_count}, Bob: {bob_count}",
            )

    except Exception as e:
        results.add_result(test_id, test_name, "FAIL", error=e)


async def test_2_1_since_ts_FIXED(client, results):
    """Test 2.1: fetch_inbox with since_ts (FIXED TIMING)"""
    test_id = "Test-2.1-FIXED"
    test_name = "fetch_inbox with since_ts Filter (corrected timing)"

    try:
        print(f"\n{'=' * 70}")
        print(f"Executing {test_id}: {test_name}")
        print(f"Project: {PROJECT_KEY}")
        print(f"{'=' * 70}")

        # Register agent with unique name
        # NOTE: Agent names are normalized via sanitize_agent_name() (src/mcp_agent_mail/utils.py)
        # We intentionally use underscores to exercise the sanitizer.
        tester_result = await client.call_tool(
            "register_agent",
            {
                "project_key": PROJECT_KEY,
                "program": "test-cli",
                "model": "test-model",
                "name": f"InboxTester_{uuid.uuid4().hex[:6]}",  # Will be sanitized to "InboxTesterghi789"
            },
        )
        # CRITICAL: Use the returned name (sanitized), not the input name
        tester_name = tester_result.data.get("name") if hasattr(tester_result, "data") else tester_result.get("name")
        print(f"Registered agent: {tester_name}")

        # FIXED: Send first batch BEFORE capturing T0
        print("Sending first batch (10 messages)...")
        for i in range(10):
            await client.call_tool(
                "send_message",
                {
                    "project_key": PROJECT_KEY,
                    "sender_name": tester_name,  # Use returned (sanitized) name
                    "to": [tester_name],  # Use returned (sanitized) name
                    "subject": f"T0 Message {i + 1}",
                    "body_md": f"Content at T0 - message {i + 1}",
                },
            )

        # FIXED: Capture T0 AFTER first batch
        await asyncio.sleep(TIMESTAMP_SEPARATION_DELAY)
        t0 = datetime.now(timezone.utc)
        print(f"Captured T0: {t0.isoformat()}")
        await asyncio.sleep(TIMESTAMP_SEPARATION_DELAY)

        # Send second batch AFTER T0
        print("Sending second batch (5 messages)...")
        for i in range(5):
            await client.call_tool(
                "send_message",
                {
                    "project_key": PROJECT_KEY,
                    "sender_name": tester_name,  # Use returned (sanitized) name
                    "to": [tester_name],  # Use returned (sanitized) name
                    "subject": f"T1 Message {i + 1}",
                    "body_md": f"Content at T1 - message {i + 1}",
                },
            )

        # Test 1: Fetch without since_ts, limit 8
        result = await client.call_tool(
            "fetch_inbox",
            {
                "project_key": PROJECT_KEY,
                "agent_name": tester_name,  # Use returned (sanitized) name
                "limit": 8,
                "include_bodies": False,
            },
        )

        inbox_no_filter = result.data if (hasattr(result, "data") and isinstance(result.data, list)) else []
        print(f"Without filter: {len(inbox_no_filter)} messages")

        if len(inbox_no_filter) != 8:
            results.add_result(
                test_id, test_name, "FAIL", f"Expected 8 messages without filter, got {len(inbox_no_filter)}"
            )
            return

        # Test 2: Fetch with since_ts=T0, limit 8
        # Should get only the 5 messages from second batch (created after T0)
        result = await client.call_tool(
            "fetch_inbox",
            {
                "project_key": PROJECT_KEY,
                "agent_name": tester_name,  # Use returned (sanitized) name
                "since_ts": t0.isoformat(),
                "limit": 8,
                "include_bodies": False,
            },
        )

        inbox_after_t0 = result.data if (hasattr(result, "data") and isinstance(result.data, list)) else []
        print(f"After T0: {len(inbox_after_t0)} messages")

        if len(inbox_after_t0) == 5:
            results.add_result(
                test_id,
                test_name,
                "PASS",
                (
                    f"since_ts filter works correctly (verifies limit applied AFTER filter): "
                    f"Got {len(inbox_after_t0)} messages from second batch"
                ),
            )
        else:
            results.add_result(
                test_id,
                test_name,
                "FAIL",
                f"Expected 5 messages after T0 (verifies limit applied AFTER filter), got {len(inbox_after_t0)}",
            )

    except Exception as e:
        results.add_result(test_id, test_name, "FAIL", error=e)


async def main():
    """Run fixed manual tests."""
    print("\n" + "=" * 70)
    print("MCP AGENT MAIL - FIXED MANUAL TEST EXECUTION")
    print(f"Using unique project key: {PROJECT_KEY}")
    print("=" * 70)

    # CRITICAL FIX (mcp_agent_mail-7rj): Reset database state to clear cached sessions
    # This ensures that session factory is recreated and agents registered in one
    # tool call are immediately visible in subsequent tool calls
    print("Resetting database state for clean session...")
    reset_database_state()

    results = TestResults()

    mcp = build_mcp_server()
    async with Client(mcp) as client:
        await test_1_2_agent_filter_FIXED(client, results)
        await test_2_1_since_ts_FIXED(client, results)

    summary = results.get_summary()
    print(f"\n{'=' * 70}")
    print("RESULTS")
    print(f"{'=' * 70}")
    print(f"Project: {PROJECT_KEY} (unique per run)")
    print(f"Total:   {summary['total']}")
    print(f"Passed:  {summary['passed']} ✅")
    print(f"Failed:  {summary['failed']} ❌")
    print(f"Success: {summary['passed']}/{summary['total']} = {(summary['passed'] / summary['total'] * 100):.1f}%")
    print(f"{'=' * 70}\n")

    sys.exit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
