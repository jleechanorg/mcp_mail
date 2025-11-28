---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "DatabaseAdmin",
    "global-inbox-tmp-test-multiagent-sqlite-20251118-222255"
  ],
  "created": "2025-11-19T14:22:57.473159+00:00",
  "from": "BackendDev",
  "id": 12,
  "importance": "high",
  "project": "/tmp/test_multiagent_sqlite_20251118_222255",
  "project_slug": "tmp-test-multiagent-sqlite-20251118-222255",
  "subject": "API endpoint ready: /api/dashboard/stats",
  "thread_id": null,
  "to": [
    "FrontendDev"
  ]
}
---

The endpoint is ready! Returns:
```json
{
  "totalUsers": 1234,
  "activeUsers": 567,
  "weeklyEvents": 8901
}
```
CC'ing DatabaseAdmin since they helped optimize the query.
