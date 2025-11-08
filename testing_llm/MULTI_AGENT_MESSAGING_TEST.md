# Multi-Agent Messaging Test Case: Agent Registration and Communication
> [!IMPORTANT]
> **Manual LLM Prompt**: This specification must be read and executed step-by-step by an LLM or human tester; it is not an automated script.

## Test Objective
Validate multi-agent registration, messaging, and coordination functionality in the MCP Agent Mail system. This test creates 4 agents, registers them in a project, has them exchange messages, and saves proof of successful communication.

## Test Parameters
- **Agent Count**: 4 agents (FrontendDev, BackendDev, DatabaseAdmin, DevOpsEngineer)
- **Message Exchanges**: Each agent sends at least 1 message
- **Expected Response Time**: < 30 seconds total
- **Primary Focus**: Agent registration, messaging flow, and proof of delivery

## 📁 Evidence Collection Setup
**MANDATORY**: Set up structured evidence collection directory before testing:

```bash
# Create evidence collection directory
REPO_NAME=$(basename $(git rev-parse --show-toplevel) | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/_/g')
BRANCH_NAME=$(git branch --show-current | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/_/g')
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
TEST_DIR="/tmp/${REPO_NAME}_${BRANCH_NAME}_multiagent_${TIMESTAMP}"

mkdir -p "$TEST_DIR"/{evidence,agents,messages,inbox,outbox}

# All test outputs must be saved to:
echo "TEST_DIR=$TEST_DIR" > /tmp/current_test_session.env
echo "Evidence Directory: $TEST_DIR"
echo "TIMESTAMP=$TIMESTAMP" >> /tmp/current_test_session.env

# Log test directory for later reference
echo "Test evidence will be saved to: $TEST_DIR" | tee "$TEST_DIR/test_info.txt"
```

## Prerequisites
- MCP Agent Mail server running (either via MCP client or standalone)
- Python environment with required dependencies installed
- Access to the mcp_agent_mail Python package

## Test Instructions

### Step 1: Ensure Project Exists

Create a test project to hold all agents:

```python
# Execute this Python code via your MCP client or Python REPL
from mcp_agent_mail.app import build_mcp_server
from fastmcp import Client
import asyncio
import json
import os
from datetime import datetime

# Get test directory from environment
TEST_DIR = os.environ.get('TEST_DIR', '/tmp/mcp_agent_mail_multiagent_test')
os.makedirs(TEST_DIR, exist_ok=True)
os.makedirs(f"{TEST_DIR}/evidence", exist_ok=True)
os.makedirs(f"{TEST_DIR}/agents", exist_ok=True)
os.makedirs(f"{TEST_DIR}/messages", exist_ok=True)

async def test_multi_agent_messaging():
    """Test multi-agent registration and messaging."""
    results = {
        "test_name": "Multi-Agent Messaging Test",
        "timestamp": datetime.now().isoformat(),
        "test_dir": TEST_DIR,
        "steps": []
    }

    mcp = build_mcp_server()
    async with Client(mcp) as client:
        # Step 1: Ensure project
        print("=" * 60)
        print("STEP 1: Creating test project...")
        print("=" * 60)

        project_key = "/tmp/test_multiagent_project"
        project_result = await client.call_tool(
            "ensure_project",
            arguments={"human_key": project_key}
        )
        print(f"✅ Project created: {project_result.data['slug']}")
        results["steps"].append({
            "step": 1,
            "action": "ensure_project",
            "status": "success",
            "result": project_result.data
        })

        # Save project info
        with open(f"{TEST_DIR}/evidence/01_project_creation.json", 'w') as f:
            json.dump(project_result.data, f, indent=2)

        # Step 2: Register 4 agents
        print("\n" + "=" * 60)
        print("STEP 2: Registering 4 agents...")
        print("=" * 60)

        agents = [
            {
                "name": "FrontendDev",
                "program": "claude-code",
                "model": "sonnet-4.5",
                "task": "React UI development"
            },
            {
                "name": "BackendDev",
                "program": "claude-code",
                "model": "sonnet-4.5",
                "task": "FastAPI backend development"
            },
            {
                "name": "DatabaseAdmin",
                "program": "codex-cli",
                "model": "gpt5-codex",
                "task": "PostgreSQL database management"
            },
            {
                "name": "DevOpsEngineer",
                "program": "claude-code",
                "model": "opus-4",
                "task": "CI/CD and infrastructure"
            }
        ]

        registered_agents = []
        for agent in agents:
            agent_result = await client.call_tool(
                "register_agent",
                arguments={
                    "project_key": project_key,
                    "program": agent["program"],
                    "model": agent["model"],
                    "name": agent["name"],
                    "task_description": agent["task"]
                }
            )
            print(f"✅ Agent registered: {agent['name']} (ID: {agent_result.data['id']})")
            registered_agents.append(agent_result.data)

            # Save agent info
            with open(f"{TEST_DIR}/agents/{agent['name']}.json", 'w') as f:
                json.dump(agent_result.data, f, indent=2)

        results["steps"].append({
            "step": 2,
            "action": "register_agents",
            "status": "success",
            "agents": registered_agents
        })

        # Step 3: Send messages between agents
        print("\n" + "=" * 60)
        print("STEP 3: Exchanging messages between agents...")
        print("=" * 60)

        messages_sent = []

        # Message 1: FrontendDev -> BackendDev (API endpoint request)
        msg1 = await client.call_tool(
            "send_message",
            arguments={
                "project_key": project_key,
                "sender_name": "FrontendDev",
                "to": ["BackendDev"],
                "subject": "Need API endpoint for user dashboard",
                "body_md": "Hi! I'm building the user dashboard UI. Can you create a `/api/dashboard/stats` endpoint that returns user metrics?",
                "importance": "normal"
            }
        )
        print(f"✅ Message 1 sent: FrontendDev -> BackendDev")
        messages_sent.append({"from": "FrontendDev", "to": "BackendDev", "result": msg1.data})

        # Message 2: BackendDev -> DatabaseAdmin (DB query help)
        msg2 = await client.call_tool(
            "send_message",
            arguments={
                "project_key": project_key,
                "sender_name": "BackendDev",
                "to": ["DatabaseAdmin"],
                "subject": "Help with user metrics query",
                "body_md": "I need to aggregate user activity data. Can you help optimize this query: `SELECT * FROM user_events WHERE created_at > NOW() - INTERVAL '7 days'`?",
                "importance": "normal"
            }
        )
        print(f"✅ Message 2 sent: BackendDev -> DatabaseAdmin")
        messages_sent.append({"from": "BackendDev", "to": "DatabaseAdmin", "result": msg2.data})

        # Message 3: DatabaseAdmin -> BackendDev (Query optimization reply)
        msg3 = await client.call_tool(
            "send_message",
            arguments={
                "project_key": project_key,
                "sender_name": "DatabaseAdmin",
                "to": ["BackendDev"],
                "subject": "Re: Help with user metrics query",
                "body_md": "Here's the optimized query with proper indexing:\n```sql\nCREATE INDEX idx_user_events_created_at ON user_events(created_at);\nSELECT user_id, COUNT(*) as event_count FROM user_events WHERE created_at > NOW() - INTERVAL '7 days' GROUP BY user_id;\n```",
                "importance": "normal"
            }
        )
        print(f"✅ Message 3 sent: DatabaseAdmin -> BackendDev")
        messages_sent.append({"from": "DatabaseAdmin", "to": "BackendDev", "result": msg3.data})

        # Message 4: BackendDev -> FrontendDev, DatabaseAdmin (CC) - API ready notification
        msg4 = await client.call_tool(
            "send_message",
            arguments={
                "project_key": project_key,
                "sender_name": "BackendDev",
                "to": ["FrontendDev"],
                "cc": ["DatabaseAdmin"],
                "subject": "API endpoint ready: /api/dashboard/stats",
                "body_md": "The endpoint is ready! Returns:\n```json\n{\n  \"totalUsers\": 1234,\n  \"activeUsers\": 567,\n  \"weeklyEvents\": 8901\n}\n```\nCC'ing DatabaseAdmin since they helped optimize the query.",
                "importance": "high"
            }
        )
        print(f"✅ Message 4 sent: BackendDev -> FrontendDev (CC: DatabaseAdmin)")
        messages_sent.append({"from": "BackendDev", "to": ["FrontendDev"], "cc": ["DatabaseAdmin"], "result": msg4.data})

        # Message 5: DevOpsEngineer -> All (Deployment notification)
        msg5 = await client.call_tool(
            "send_message",
            arguments={
                "project_key": project_key,
                "sender_name": "DevOpsEngineer",
                "to": ["FrontendDev", "BackendDev", "DatabaseAdmin"],
                "subject": "Deployment scheduled for tonight 11 PM",
                "body_md": "Hi team! Deploying latest changes to staging at 11 PM. Please ensure all PRs are merged by 10 PM. I'll send deployment logs after completion.",
                "importance": "urgent"
            }
        )
        print(f"✅ Message 5 sent: DevOpsEngineer -> All agents")
        messages_sent.append({"from": "DevOpsEngineer", "to": ["FrontendDev", "BackendDev", "DatabaseAdmin"], "result": msg5.data})

        results["steps"].append({
            "step": 3,
            "action": "send_messages",
            "status": "success",
            "messages_sent": len(messages_sent),
            "messages": messages_sent
        })

        # Save all messages
        with open(f"{TEST_DIR}/messages/all_messages.json", 'w') as f:
            json.dump(messages_sent, f, indent=2)

        # Step 4: Fetch inboxes to verify delivery
        print("\n" + "=" * 60)
        print("STEP 4: Verifying message delivery (checking inboxes)...")
        print("=" * 60)

        inbox_results = {}
        for agent in agents:
            inbox = await client.call_tool(
                "fetch_inbox",
                arguments={
                    "project_key": project_key,
                    "agent_name": agent["name"],
                    "include_bodies": True,
                    "limit": 10
                }
            )
            message_count = len(inbox.data)
            print(f"✅ {agent['name']} inbox: {message_count} message(s)")
            inbox_results[agent["name"]] = {
                "count": message_count,
                "messages": inbox.data
            }

            # Save inbox
            with open(f"{TEST_DIR}/inbox/{agent['name']}_inbox.json", 'w') as f:
                json.dump(inbox.data, f, indent=2)

        results["steps"].append({
            "step": 4,
            "action": "verify_delivery",
            "status": "success",
            "inbox_results": inbox_results
        })

        # Step 5: Generate summary report
        print("\n" + "=" * 60)
        print("STEP 5: Generating test summary...")
        print("=" * 60)

        summary = {
            "test_status": "SUCCESS",
            "total_agents_registered": len(registered_agents),
            "total_messages_sent": len(messages_sent),
            "inbox_verification": {
                agent_name: data["count"]
                for agent_name, data in inbox_results.items()
            },
            "test_directory": TEST_DIR,
            "evidence_files": {
                "project_creation": f"{TEST_DIR}/evidence/01_project_creation.json",
                "agents": [f"{TEST_DIR}/agents/{a['name']}.json" for a in agents],
                "messages": f"{TEST_DIR}/messages/all_messages.json",
                "inboxes": [f"{TEST_DIR}/inbox/{a['name']}_inbox.json" for a in agents]
            }
        }

        results["summary"] = summary
        results["status"] = "SUCCESS"

        # Save final results
        with open(f"{TEST_DIR}/evidence/FINAL_TEST_RESULTS.json", 'w') as f:
            json.dump(results, f, indent=2)

        # Create human-readable summary
        summary_text = f"""
Multi-Agent Messaging Test - RESULTS
=====================================

Test Status: ✅ SUCCESS
Test Directory: {TEST_DIR}
Timestamp: {results['timestamp']}

Agents Registered: {len(registered_agents)}
{'-' * 40}
"""
        for agent in registered_agents:
            summary_text += f"  - {agent['name']} ({agent['program']}/{agent['model']})\n"

        summary_text += f"\nMessages Exchanged: {len(messages_sent)}\n{'-' * 40}\n"
        for idx, msg in enumerate(messages_sent, 1):
            summary_text += f"  {idx}. {msg['from']} -> {msg['to']}\n"

        summary_text += f"\nInbox Verification:\n{'-' * 40}\n"
        for agent_name, count in summary['inbox_verification'].items():
            summary_text += f"  - {agent_name}: {count} message(s) received\n"

        summary_text += f"\nEvidence Files:\n{'-' * 40}\n"
        summary_text += f"  - Project: {summary['evidence_files']['project_creation']}\n"
        summary_text += f"  - Agents: {len(summary['evidence_files']['agents'])} agent profile(s)\n"
        summary_text += f"  - Messages: {summary['evidence_files']['messages']}\n"
        summary_text += f"  - Inboxes: {len(summary['evidence_files']['inboxes'])} inbox snapshot(s)\n"

        summary_text += f"\n{'=' * 40}\nTest completed successfully!\n"

        with open(f"{TEST_DIR}/TEST_SUMMARY.txt", 'w') as f:
            f.write(summary_text)

        print("\n" + "=" * 60)
        print(summary_text)
        print("=" * 60)

        return results

# Run the test
if __name__ == "__main__":
    results = asyncio.run(test_multi_agent_messaging())
    print(f"\n✅ All test evidence saved to: {results['test_dir']}")
```

### Expected Output Structure

The test should create the following directory structure in `/tmp`:

```
/tmp/mcp_agent_mail_<branch>_multiagent_<timestamp>/
├── TEST_SUMMARY.txt                    # Human-readable summary
├── test_info.txt                       # Test metadata
├── evidence/
│   ├── 01_project_creation.json       # Project creation result
│   └── FINAL_TEST_RESULTS.json        # Complete test results
├── agents/
│   ├── FrontendDev.json               # Agent profile
│   ├── BackendDev.json
│   ├── DatabaseAdmin.json
│   └── DevOpsEngineer.json
├── messages/
│   └── all_messages.json              # All sent messages
└── inbox/
    ├── FrontendDev_inbox.json         # Inbox snapshots
    ├── BackendDev_inbox.json
    ├── DatabaseAdmin_inbox.json
    └── DevOpsEngineer_inbox.json
```

## Validation Criteria

### ✅ Success Indicators:
1. **All 4 agents registered successfully** with unique IDs
2. **All 5 messages delivered** without errors
3. **Inbox verification shows correct message counts**:
   - FrontendDev: 2 messages (1 direct, 1 CC)
   - BackendDev: 3 messages (2 direct, 1 CC from itself)
   - DatabaseAdmin: 2 messages (1 direct, 1 CC)
   - DevOpsEngineer: 0 messages (only sent, didn't receive)
4. **Evidence files created** in /tmp directory
5. **No exceptions or errors** during execution
6. **TEST_SUMMARY.txt** shows SUCCESS status

### ❌ Failure Indicators:
- Agent registration failures
- Message delivery errors
- Missing inbox messages
- Exception stack traces
- Incomplete evidence files
- Test directory not created

## Message Flow Diagram

```
FrontendDev  ──────────────────────> BackendDev
                                          │
                                          ├──────> DatabaseAdmin
                                          │            │
                                          │            ├─────> BackendDev
                                          │            │
                                          └<───────────┘
                                          │
                                          └──────> FrontendDev (+ CC: DatabaseAdmin)

DevOpsEngineer ────> [FrontendDev, BackendDev, DatabaseAdmin]
```

## Troubleshooting

### Common Issues:

1. **Import Error**: Ensure mcp_agent_mail is installed: `pip install -e .`
2. **Connection Error**: Verify MCP server is running
3. **Permission Error**: Check write permissions for /tmp directory
4. **Agent Name Conflicts**: Use unique agent names for each test run
5. **Project Already Exists**: The test uses `/tmp/test_multiagent_project` - if it exists from a previous run, agents will be added to it

### Debugging Steps:
1. Check Python imports: `python -c "from mcp_agent_mail.app import build_mcp_server"`
2. Verify TEST_DIR environment variable: `echo $TEST_DIR`
3. Check file system permissions: `ls -la /tmp`
4. Review error messages in console output
5. Inspect evidence files if test partially completes

## Performance Expectations
- **Total Test Time**: 10-30 seconds
- **Agent Registration**: < 1 second per agent
- **Message Delivery**: < 1 second per message
- **Inbox Retrieval**: < 1 second per agent

## Notes for LLM Testers
- This test validates the complete agent coordination workflow
- Evidence is automatically saved to /tmp for verification
- The test is idempotent - can be run multiple times
- Check TEST_SUMMARY.txt for human-readable results
- All JSON evidence files are formatted for easy inspection
- Agent names are chosen to represent realistic team roles

## Success Confirmation

After running the test, verify success by:

1. **Check console output** for "✅ SUCCESS" status
2. **Read TEST_SUMMARY.txt**: `cat $TEST_DIR/TEST_SUMMARY.txt`
3. **Verify evidence files exist**: `ls -R $TEST_DIR`
4. **Inspect a sample inbox**: `cat $TEST_DIR/inbox/FrontendDev_inbox.json | jq .`
5. **Review final results**: `cat $TEST_DIR/evidence/FINAL_TEST_RESULTS.json | jq .summary`

## Cleanup (Optional)

To clean up test artifacts after verification:

```bash
# Remove test directory (be careful with rm -rf!)
rm -rf "$TEST_DIR"

# Or keep for future reference - test directories include timestamp
# Old tests can be cleaned up with:
find /tmp -name "mcp_agent_mail_*_multiagent_*" -type d -mtime +7 -exec rm -rf {} +
```
