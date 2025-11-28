---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-tmp-test-multiagent-project"
  ],
  "created": "2025-11-19T03:17:23.786631+00:00",
  "from": "DatabaseAdmin",
  "id": 53,
  "importance": "normal",
  "project": "/tmp/test_multiagent_project",
  "project_slug": "tmp-test-multiagent-project",
  "subject": "Re: Help with user metrics query",
  "thread_id": null,
  "to": [
    "BackendDev"
  ]
}
---

Here's the optimized query with proper indexing:
```sql
CREATE INDEX idx_user_events_created_at ON user_events(created_at);
SELECT user_id, COUNT(*) as event_count FROM user_events WHERE created_at > NOW() - INTERVAL '7 days' GROUP BY user_id;
```
