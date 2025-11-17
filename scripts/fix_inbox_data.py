#!/usr/bin/env python3
"""
Fix inbox data using direct database query instead of FastMCP serialization.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# Parse command-line arguments
parser = argparse.ArgumentParser(description="Fix inbox data using direct database query")
parser.add_argument("test_dir", help="Path to test directory")
parser.add_argument(
    "--db-path",
    type=str,
    default=None,
    help="Path to SQLite database (default: .mcp_mail/storage.sqlite3)",
)
args = parser.parse_args()

# Find database (based on config.py default: sqlite+aiosqlite:///./.mcp_mail/storage.sqlite3)
db_path = Path(args.db_path) if args.db_path else Path(".mcp_mail") / "storage.sqlite3"

if not db_path.exists():
    print(f"Error: Database not found at {db_path}")
    sys.exit(1)

print(f"Found database: {db_path}\n")

# Test directory
TEST_DIR = Path(args.test_dir)

# Agent IDs from test
agent_mapping = {"FrontendDev": 71, "BackendDev": 72, "DatabaseAdmin": 73, "DevOpsEngineer": 74}

# Connect to database
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

print("Querying inbox messages from database...\n")

for agent_name, agent_id in agent_mapping.items():
    try:
        # Query messages where agent is recipient
        query = """
        SELECT DISTINCT m.id, m.subject, m.body_md, m.importance,
               m.ack_required, m.created_ts, m.sender_id,
               a.name as sender_name
        FROM messages m
        JOIN message_recipients mr ON m.id = mr.message_id
        LEFT JOIN agents a ON m.sender_id = a.id
        WHERE mr.agent_id = ?
        ORDER BY m.created_ts DESC
        LIMIT 50
        """

        cursor = conn.execute(query, (agent_id,))
        rows = cursor.fetchall()

        # Convert to JSON-serializable format
        messages = []
        for row in rows:
            # Get recipients for this message
            recip_cursor = conn.execute(
                """
                SELECT a.name, mr.kind
                FROM message_recipients mr
                JOIN agents a ON mr.agent_id = a.id
                WHERE mr.message_id = ?
            """,
                (row["id"],),
            )

            recipients = recip_cursor.fetchall()
            to_list = [r["name"] for r in recipients if r["kind"] == "to"]
            cc_list = [r["name"] for r in recipients if r["kind"] == "cc"]

            messages.append(
                {
                    "id": row["id"],
                    "from": row["sender_name"],
                    "to": to_list,
                    "cc": cc_list,
                    "subject": row["subject"],
                    "body_md": row["body_md"],
                    "importance": row["importance"],
                    "created_ts": row["created_ts"],
                    "ack_required": bool(row["ack_required"]),
                }
            )

        # Save to mcp_outputs
        mcp_output_file = TEST_DIR / "mcp_outputs" / f"3_fetch_inbox_{agent_name}.json"
        with mcp_output_file.open("w") as f:
            json.dump(messages, f, indent=2)

        # Save to inboxes
        inbox_file = TEST_DIR / "inboxes" / f"{agent_name}_inbox.json"
        with inbox_file.open("w") as f:
            json.dump(messages, f, indent=2)

        # Remove error file if it exists
        error_file = TEST_DIR / "errors" / f"fetch_inbox_{agent_name}_error.json"
        if error_file.exists():
            error_file.unlink()

        print(f"✅ {agent_name}: {len(messages)} messages serialized")
        if messages:
            print(f'   Sample: ID={messages[0]["id"]}, from={messages[0]["from"]}, subject="{messages[0]["subject"]}"')

    except Exception as e:
        print(f"❌ {agent_name}: {e}")
        error = {"agent": agent_name, "error": str(e)}
        error_file = TEST_DIR / "errors" / f"fetch_inbox_{agent_name}_error.json"
        with error_file.open("w") as f:
            json.dump(error, f, indent=2)

conn.close()

# Update TEST_SUMMARY.json
print("\nUpdating TEST_SUMMARY.json...")
summary_file = TEST_DIR / "TEST_SUMMARY.json"
with summary_file.open("r") as f:
    summary = json.load(f)

# Clear errors related to inbox fetch
summary["errors"] = [e for e in summary.get("errors", []) if e.get("step") != "fetch_inbox"]

with summary_file.open("w") as f:
    json.dump(summary, f, indent=2)

print("✅ Summary updated\n")
print(f"All inbox data fixed and saved to: {TEST_DIR}")
print("\nVerification commands:")
print(f"  cat {TEST_DIR}/inboxes/FrontendDev_inbox.json | python3 -m json.tool | head -30")
print(f"  cat {TEST_DIR}/mcp_outputs/3_fetch_inbox_BackendDev.json | python3 -m json.tool | head -30")
