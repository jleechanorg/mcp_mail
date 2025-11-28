---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-tmp-test-multiagent-sqlite-20251118-222453"
  ],
  "created": "2025-11-19T14:24:55.006440+00:00",
  "from": "BackendDev",
  "id": 15,
  "importance": "normal",
  "project": "/tmp/test_multiagent_sqlite_20251118_222453",
  "project_slug": "tmp-test-multiagent-sqlite-20251118-222453",
  "subject": "Help with user metrics query",
  "thread_id": null,
  "to": [
    "DatabaseAdmin"
  ]
}
---

I need to aggregate user activity data. Can you help optimize this query: `SELECT * FROM user_events WHERE created_at > NOW() - INTERVAL '7 days'`?
