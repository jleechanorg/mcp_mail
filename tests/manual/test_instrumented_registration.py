#!/usr/bin/env python3
"""
Instrumented Test for Agent Registration Bug (mcp_agent_mail-7rj)

This test enables SQL query logging and adds detailed instrumentation to
trace the exact behavior of register_agent and send_message to identify
why agents are not found immediately after registration.

Key features:
- SQLAlchemy echo mode enabled to see all SQL queries
- Detailed timestamps for each operation
- Logging of agent IDs and names
- Transaction state tracking
"""

import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# CRITICAL: Set environment variables BEFORE importing any MCP code
# This ensures DATABASE_ECHO is read when Settings are first loaded
os.environ["DATABASE_ECHO"] = "true"
os.environ["APP_ENVIRONMENT"] = "test"

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server
from mcp_agent_mail.config import clear_settings_cache
from mcp_agent_mail.db import reset_database_state

# Enable detailed Python logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Generate unique project key
PROJECT_KEY = f"test_instrumented_{uuid.uuid4().hex[:8]}"


def log(msg: str):
    """Log with high-precision timestamp."""
    timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    print(f"\n{'=' * 80}")
    print(f"[{timestamp}] {msg}")
    print(f"{'=' * 80}\n")


async def test_agent_registration_bug():
    """Instrumented test to trace agent registration bug."""

    log("TEST START - Tracing agent registration bug")
    log(f"Project key: {PROJECT_KEY}")

    # Clear settings cache and reset database state
    log("Clearing settings cache and resetting database state...")
    clear_settings_cache()
    reset_database_state()

    # Build MCP server
    log("Building MCP server...")
    mcp = build_mcp_server()

    async with Client(mcp) as client:
        # Generate unique agent name
        agent_name = f"TestAgent_{uuid.uuid4().hex[:6]}"
        log(f"Test agent name: {agent_name}")

        # Step 1: Register agent
        log("STEP 1: Calling register_agent...")
        t0 = datetime.now(timezone.utc)

        try:
            result = await client.call_tool(
                "register_agent",
                {"project_key": PROJECT_KEY, "program": "test-cli", "model": "test-model", "name": agent_name},
            )

            t1 = datetime.now(timezone.utc)
            elapsed = (t1 - t0).total_seconds() * 1000

            log(f"register_agent SUCCEEDED in {elapsed:.2f}ms")

            # Extract agent details from result
            if hasattr(result, "data"):
                agent_data = result.data
            elif hasattr(result, "structured_content"):
                agent_data = result.structured_content
            else:
                agent_data = result

            agent_id = agent_data.get("id", "UNKNOWN")
            agent_name_returned = agent_data.get("name", "UNKNOWN")

            log(f"Agent created: ID={agent_id}, Name={agent_name_returned}")
            log(f"Full agent data: {agent_data}")

        except Exception as e:
            log(f"register_agent FAILED: {e}")
            return

        # Small delay to ensure transaction completes
        # Allow the transaction commit to settle before verifying state
        await asyncio.sleep(0.1)

        # Step 2: Try to send message using the registered agent
        log("STEP 2: Calling send_message with the registered agent...")
        t2 = datetime.now(timezone.utc)
        time_since_registration = (t2 - t1).total_seconds() * 1000
        log(f"Time since registration: {time_since_registration:.2f}ms")

        try:
            result = await client.call_tool(
                "send_message",
                {
                    "project_key": PROJECT_KEY,
                    "sender_name": agent_name,
                    "to": [agent_name],
                    "subject": "Test message",
                    "body_md": "Testing if agent can be found",
                },
            )

            t3 = datetime.now(timezone.utc)
            elapsed = (t3 - t2).total_seconds() * 1000

            log(f"send_message SUCCEEDED in {elapsed:.2f}ms")
            log("✅ BUG NOT REPRODUCED - Agent was found successfully!")

        except Exception as e:
            t3 = datetime.now(timezone.utc)
            elapsed = (t3 - t2).total_seconds() * 1000

            log(f"send_message FAILED in {elapsed:.2f}ms")
            log(f"❌ BUG REPRODUCED - Error: {e}")
            log(
                f"Agent '{agent_name}' (ID={agent_id}) was not found {time_since_registration:.2f}ms after registration"
            )

            # Try again after a longer delay
            log("Waiting 1 second and retrying...")
            # Longer pause to observe whether eventual consistency resolves the issue
            await asyncio.sleep(1.0)

            try:
                result = await client.call_tool(
                    "send_message",
                    {
                        "project_key": PROJECT_KEY,
                        "sender_name": agent_name,
                        "to": [agent_name],
                        "subject": "Test message (retry)",
                        "body_md": "Testing if agent can be found after delay",
                    },
                )
                log("✅ RETRY SUCCEEDED - Agent found after 1 second delay")
                log("This suggests a timing/transaction issue, not a permanent bug")
            except Exception as e2:
                log(f"❌ RETRY FAILED - Error: {e2}")
                log("Agent still not found even after 1 second - deeper issue")

    log("TEST COMPLETE")


async def main():
    """Run the instrumented test."""
    print("\n" + "=" * 80)
    print("INSTRUMENTED TEST FOR AGENT REGISTRATION BUG (mcp_agent_mail-7rj)")
    print("=" * 80)
    print("\nThis test will show:")
    print("- All SQL queries executed by SQLAlchemy (via DATABASE_ECHO=true)")
    print("- Precise timestamps for each operation")
    print("- Agent IDs and names")
    print("- Transaction timing")
    print("\n" + "=" * 80 + "\n")

    try:
        await test_agent_registration_bug()
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
