---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "DatabaseAdmin",
    "global-inbox-tmp-test-multiagent-project"
  ],
  "created": "2025-11-18T06:26:24.461189+00:00",
  "from": "BackendDev",
  "id": 4,
  "importance": "high",
  "project": "/tmp/test_multiagent_project",
  "project_slug": "tmp-test-multiagent-project",
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
