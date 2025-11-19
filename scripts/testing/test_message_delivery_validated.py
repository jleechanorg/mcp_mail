#!/usr/bin/env python3
"""Comprehensive Message Delivery Validation Test - With SQLite Proof"""

import asyncio
import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from anyio import Path as AsyncPath
from fastmcp import Client

from mcp_agent_mail.app import build_mcp_server

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
# Test directory (cross-platform)
TEST_DIR = Path(tempfile.gettempdir()) / f"mcp_mail_validation_{TIMESTAMP}"


class ValidationResult(TypedDict):
    agent: str
    validation: str
    passed: bool
    expected: int
    actual: int


class TestResults(TypedDict, total=False):
    test_name: str
    timestamp: str
    test_dir: str
    validations: list[ValidationResult]
    content_validations: list[dict[str, Any]]
    status: str
    sqlite_proof: dict[str, Any]
    summary: dict[str, Any]


async def write_json_async(path: Path, payload: dict) -> None:
    """Persist JSON payload using non-blocking I/O."""
    async_path = AsyncPath(path)
    await async_path.parent.mkdir(parents=True, exist_ok=True)
    await async_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


async def write_text_async(path: Path, content: str) -> None:
    """Persist plain text using non-blocking I/O."""
    async_path = AsyncPath(path)
    await async_path.parent.mkdir(parents=True, exist_ok=True)
    await async_path.write_text(content, encoding="utf-8")


def setup_test_dir():
    """Create test evidence directory."""
    evidence_dir = TEST_DIR / "evidence"
    sqlite_dir = TEST_DIR / "sqlite_verification"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    sqlite_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Test directory: {TEST_DIR}")
    return TEST_DIR


def verify_via_sqlite(project_slug: str, agent_names: list[str]) -> dict:
    """Verify message content directly via SQLite database."""
    db_path = Path(".mcp_mail/storage.sqlite3")

    if not db_path.exists():
        return {"error": "Database not found"}

    try:
        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.cursor()

            # Get all messages
            cursor.execute(
                """
                SELECT m.id, a.name as sender, m.subject, m.body_md, m.importance
                FROM messages m
                JOIN agents a ON m.sender_id = a.id
                JOIN projects p ON m.project_id = p.id
                WHERE p.slug = ?
                ORDER BY m.id
            """,
                (project_slug,),
            )
            messages = cursor.fetchall()

            # Get all recipients for each message
            cursor.execute(
                """
                SELECT m.id, a.name as recipient, mr.kind
                FROM message_recipients mr
                JOIN messages m ON mr.message_id = m.id
                JOIN projects p ON m.project_id = p.id
                JOIN agents a ON mr.agent_id = a.id
                WHERE p.slug = ?
                ORDER BY m.id, mr.kind, a.name
            """,
                (project_slug,),
            )
            recipients = cursor.fetchall()

            # Organize results
            message_details = []
            for msg_id, sender, subject, body, importance in messages:
                msg_recipients = [{"name": name, "kind": kind} for mid, name, kind in recipients if mid == msg_id]

                message_details.append(
                    {
                        "id": msg_id,
                        "sender": sender,
                        "subject": subject,
                        "body": body,
                        "importance": importance,
                        "recipients": msg_recipients,
                    }
                )

            # Get inbox counts for each agent
            inbox_counts = {}
            for agent_name in agent_names:
                cursor.execute(
                    """
                    SELECT COUNT(DISTINCT mr.message_id)
                    FROM message_recipients mr
                    JOIN messages m ON mr.message_id = m.id
                    JOIN projects p ON m.project_id = p.id
                    JOIN agents a ON mr.agent_id = a.id
                    WHERE p.slug = ?
                      AND a.name = ?
                      AND mr.kind IN ('to', 'cc')
                """,
                    (project_slug, agent_name),
                )

                row = cursor.fetchone()
                count = int(row[0]) if row else 0
                inbox_counts[agent_name] = count

    except Exception as exc:  # pragma: no cover - defensive guard
        return {"error": f"SQLite verification failed: {exc}"}

    return {"messages": message_details, "inbox_counts": inbox_counts, "total_messages": len(message_details)}


async def test_message_delivery_validation():
    """Test message delivery with SQLite-based proof."""
    setup_test_dir()

    results: TestResults = {
        "test_name": "Message Delivery Validation Test (with SQLite Proof)",
        "timestamp": datetime.now().isoformat(),
        "test_dir": str(TEST_DIR),
        "validations": [],
    }

    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Step 1: Create project
        print("\n" + "=" * 60)
        print("STEP 1: Creating clean test project")
        print("=" * 60)

        project_key = str(Path(tempfile.gettempdir()) / f"test_validation_{TIMESTAMP}")
        project_result = await client.call_tool("ensure_project", arguments={"human_key": project_key})
        project_data = getattr(project_result, "data", {}) or {}
        project_slug = project_data.get("slug")
        if not project_slug:
            raise RuntimeError(f"Failed to create project: {project_result}")
        print(f"✅ Project: {project_slug}")

        # Step 2: Register agents
        print("\n" + "=" * 60)
        print("STEP 2: Registering agents")
        print("=" * 60)

        agents = ["Alice", "Bob", "Charlie"]
        for agent_name in agents:
            await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": project_key,
                    "program": "test",
                    "model": "test-model",
                    "name": agent_name,
                    "task_description": f"Test agent {agent_name}",
                },
            )
            print(f"✅ Registered: {agent_name}")

        # Step 3: Send specific test messages
        print("\n" + "=" * 60)
        print("STEP 3: Sending test messages")
        print("=" * 60)

        test_messages = [
            {
                "sender": "Alice",
                "to": ["Bob"],
                "subject": "Test Message 1: Alice to Bob",
                "body": "This is a direct message from Alice to Bob.",
            },
            {
                "sender": "Bob",
                "to": ["Charlie"],
                "subject": "Test Message 2: Bob to Charlie",
                "body": "This is a direct message from Bob to Charlie.",
            },
            {
                "sender": "Alice",
                "to": ["Bob"],
                "cc": ["Charlie"],
                "subject": "Test Message 3: Alice to Bob (CC Charlie)",
                "body": "This message should reach Bob directly and Charlie via CC.",
            },
        ]

        sent_messages = []
        for idx, msg_def in enumerate(test_messages, 1):
            msg_result = await client.call_tool(
                "send_message",
                arguments={
                    "project_key": project_key,
                    "sender_name": msg_def["sender"],
                    "to": msg_def["to"],
                    "cc": msg_def.get("cc"),
                    "subject": msg_def["subject"],
                    "body_md": msg_def["body"],
                    "importance": "normal",
                },
            )

            # Extract message ID from delivery
            msg_data = getattr(msg_result, "data", {}) or {}
            deliveries = msg_data.get("deliveries") or []
            if (
                not isinstance(deliveries, list)
                or not deliveries
                or not isinstance(deliveries[0], dict)
                or "payload" not in deliveries[0]
                or not isinstance(deliveries[0]["payload"], dict)
                or "id" not in deliveries[0]["payload"]
            ):
                raise RuntimeError(f"Failed to send message {idx}: {msg_result}")

            msg_id = deliveries[0]["payload"]["id"]
            msg_def["message_id"] = msg_id
            sent_messages.append(msg_def)

            print(f"✅ Message {idx} sent (ID: {msg_id}): {msg_def['sender']} → {msg_def['to']}")

        # Step 4: Verify via SQLite (ground truth)
        print("\n" + "=" * 60)
        print("STEP 4: Verifying via SQLite database")
        print("=" * 60)

        sqlite_proof = verify_via_sqlite(project_slug, agents)
        if "error" in sqlite_proof:
            raise RuntimeError(f"SQLite verification failed: {sqlite_proof['error']}")

        # Save SQLite proof
        sqlite_proof_path = TEST_DIR / "sqlite_verification" / "database_proof.json"
        await write_json_async(sqlite_proof_path, sqlite_proof)

        print(f"✅ Found {sqlite_proof['total_messages']} messages in database")
        print(f"✅ Inbox counts: {sqlite_proof['inbox_counts']}")

        # Step 5: Validate expected delivery
        print("\n" + "=" * 60)
        print("STEP 5: Validating message delivery")
        print("=" * 60)

        expected_deliveries = {
            "Alice": 0,  # Only sent messages
            "Bob": 2,  # Msg 1 (direct) + Msg 3 (direct)
            "Charlie": 2,  # Msg 2 (direct) + Msg 3 (CC)
        }

        all_validations_passed = True

        for agent_name in agents:
            actual_count = sqlite_proof["inbox_counts"][agent_name]
            expected_count = expected_deliveries[agent_name]

            count_valid = actual_count == expected_count
            status = "✅" if count_valid else "❌"
            print(f"{status} {agent_name}: {actual_count} messages (expected {expected_count})")

            if not count_valid:
                all_validations_passed = False

            results["validations"].append(
                {
                    "agent": agent_name,
                    "validation": "message_count",
                    "passed": count_valid,
                    "expected": expected_count,
                    "actual": actual_count,
                }
            )

        # Step 6: Validate message content
        print("\n" + "=" * 60)
        print("STEP 6: Validating message content")
        print("=" * 60)

        content_validations = []
        for idx, sent_msg in enumerate(sent_messages, 1):
            # Find corresponding message in SQLite proof
            db_msg = None
            for msg in sqlite_proof["messages"]:
                if msg["subject"] == sent_msg["subject"]:
                    db_msg = msg
                    break

            if db_msg:
                subject_match = db_msg["subject"] == sent_msg["subject"]
                body_match = db_msg["body"] == sent_msg["body"]
                sender_match = db_msg["sender"] == sent_msg["sender"]

                validation = {
                    "message_id": idx,
                    "subject_match": subject_match,
                    "body_match": body_match,
                    "sender_match": sender_match,
                    "all_match": subject_match and body_match and sender_match,
                }
                content_validations.append(validation)

                status = "✅" if validation["all_match"] else "❌"
                print(f"{status} Message {idx}: Content validation {'PASSED' if validation['all_match'] else 'FAILED'}")

                if not validation["all_match"]:
                    all_validations_passed = False
            else:
                print(f"❌ Message {idx}: NOT FOUND in database")
                all_validations_passed = False

        results["content_validations"] = content_validations

        # Step 7: Generate validation report
        print("\n" + "=" * 60)
        print("STEP 7: Validation Report")
        print("=" * 60)

        results["status"] = "SUCCESS" if all_validations_passed else "FAILED"
        results["sqlite_proof"] = sqlite_proof
        results["summary"] = {
            "total_messages_sent": len(sent_messages),
            "total_validations": len(results["validations"]),
            "validations_passed": sum(1 for v in results["validations"] if v["passed"]),
            "content_validations": len(content_validations),
            "content_validations_passed": sum(1 for v in content_validations if v.get("all_match")),
            "all_validations_passed": all_validations_passed,
        }

        # Save results
        validation_results_path = TEST_DIR / "evidence" / "VALIDATION_RESULTS.json"
        await write_json_async(validation_results_path, results)

        # Create summary
        summary_text = f"""
Message Delivery Validation Test - RESULTS
=========================================

Test Status: {"✅ SUCCESS" if all_validations_passed else "❌ FAILED"}
Test Directory: {TEST_DIR}
Timestamp: {results["timestamp"]}

Messages Sent: {len(sent_messages)}
----------------------------------------
"""
        for idx, msg in enumerate(sent_messages, 1):
            cc_info = f" (CC: {msg.get('cc')})" if msg.get("cc") else ""
            summary_text += f"  {idx}. {msg['sender']} → {msg['to']}{cc_info}\n"
            summary_text += f"     Subject: {msg['subject']}\n"
            summary_text += f"     Message ID: {msg['message_id']}\n"

        summary_text += f"\nSQLite Database Proof:\n{'-' * 40}\n"
        for msg in sqlite_proof["messages"]:
            summary_text += (
                f"  ID {msg['id']}: {msg['sender']} → [{', '.join([r['name'] for r in msg['recipients']])}]\n"
            )
            summary_text += f"    Subject: {msg['subject']}\n"
            summary_text += f"    Body: {msg['body'][:50]}...\n"

        summary_text += f"\nInbox Validation:\n{'-' * 40}\n"
        for validation in results["validations"]:
            status = "✅" if validation["passed"] else "❌"
            agent = validation["agent"]
            expected = validation["expected"]
            actual = validation["actual"]
            summary_text += f"  {status} {agent}: {actual}/{expected} messages\n"

        summary_text += f"\nContent Validation:\n{'-' * 40}\n"
        for idx, val in enumerate(content_validations, 1):
            status = "✅" if val["all_match"] else "❌"
            summary_text += f"  {status} Message {idx}: "
            if val["all_match"]:
                summary_text += "All fields match\n"
            else:
                summary_text += (
                    f"Subject:{val['subject_match']} Body:{val['body_match']} Sender:{val['sender_match']}\n"
                )

        summary_text += f"\n{'=' * 40}\n"
        summary_text += f"{'✅ All validations PASSED!' if all_validations_passed else '❌ Some validations FAILED!'}\n"
        summary_text += "\n📊 Summary:\n"
        summary_text += f"  - Messages sent: {results['summary']['total_messages_sent']}\n"
        summary_text += f"  - Delivery validations: {results['summary']['validations_passed']}/{results['summary']['total_validations']}\n"
        summary_text += f"  - Content validations: {results['summary']['content_validations_passed']}/{results['summary']['content_validations']}\n"

        summary_path = TEST_DIR / "VALIDATION_SUMMARY.txt"
        await write_text_async(summary_path, summary_text)

        print(summary_text)

        return results


# Run the test
if __name__ == "__main__":
    try:
        results = asyncio.run(test_message_delivery_validation())
        print(f"\n📁 All evidence saved to: {results['test_dir']}")
        exit(0 if results["status"] == "SUCCESS" else 1)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        exit(1)
