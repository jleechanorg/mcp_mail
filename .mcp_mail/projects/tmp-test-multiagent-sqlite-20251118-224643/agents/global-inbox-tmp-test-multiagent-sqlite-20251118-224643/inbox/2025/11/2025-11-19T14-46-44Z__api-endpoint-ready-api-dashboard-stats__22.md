---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "DatabaseAdmin",
    "global-inbox-tmp-test-multiagent-sqlite-20251118-224643"
  ],
  "created": "2025-11-19T14:46:44.167499+00:00",
  "from": "BackendDev",
  "id": 22,
  "importance": "high",
  "project": "/tmp/test_multiagent_sqlite_20251118_224643",
  "project_slug": "tmp-test-multiagent-sqlite-20251118-224643",
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
