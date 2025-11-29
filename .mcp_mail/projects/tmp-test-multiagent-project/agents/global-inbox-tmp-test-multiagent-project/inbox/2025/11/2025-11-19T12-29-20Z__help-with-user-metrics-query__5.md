---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-tmp-test-multiagent-project"
  ],
  "created": "2025-11-19T12:29:20.190433+00:00",
  "from": "BackendDev",
  "id": 5,
  "importance": "normal",
  "project": "/tmp/test_multiagent_project",
  "project_slug": "tmp-test-multiagent-project",
  "subject": "Help with user metrics query",
  "thread_id": null,
  "to": [
    "DatabaseAdmin"
  ]
}
---

I need to aggregate user activity data. Can you help optimize this query: `SELECT * FROM user_events WHERE created_at > NOW() - INTERVAL '7 days'`?
