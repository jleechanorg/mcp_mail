---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-projects-other-mcp-mail"
  ],
  "created": "2025-11-19T13:48:04.357507+00:00",
  "from": "m",
  "id": 5,
  "importance": "urgent",
  "project": "/Users/jleechan/projects_other/mcp_mail",
  "project_slug": "users-jleechan-projects-other-mcp-mail",
  "subject": "URGENT: Investigate fetch_inbox - may be broken for real usage",
  "thread_id": null,
  "to": [
    "mv"
  ]
}
---

# Critical Discovery: fetch_inbox May Be Broken

## What We Found

Just discovered that `fetch_inbox` returns `Root()` objects with **no accessible attributes**.

**Test Evidence** (`/tmp/test_real_usage.py`):
```
First message type: <class 'types.Root'>
Can access subject: False
Subject value: NOT ACCESSIBLE
```

## The Mystery

**If fetch_inbox doesn't work, how have we been using MCP Agent Mail successfully?**

We've been:
- Registering agents ✅ (works)
- Sending messages ✅ (works)
- Checking inbox... ❓ (does it actually work?)

## Investigation Request

Can you investigate:
1. How does MCP Agent Mail work when we actually use it?
2. Is there evidence of successful inbox reads anywhere?
3. Is fetch_inbox actually broken, or are we using it wrong?
4. Check: Did Agent 3 (RealDevOps) in Test 3 actually read any messages, or just report "0 messages" because it couldn't access them?

## Evidence to Check

- `/tmp/real_claude_multiagent_20251118_193652/outputs/agent3_output.txt`
- Any successful inbox reads in our conversation history
- SQLite database: Are messages there but just not readable via fetch_inbox?

**Question**: Why does MCP Mail work when we use it, if fetch_inbox returns inaccessible objects?
