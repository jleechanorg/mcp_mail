---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-tmp-test-multiagent-sqlite-20251118-224643"
  ],
  "created": "2025-11-19T14:46:44.047754+00:00",
  "from": "DatabaseAdmin",
  "id": 21,
  "importance": "normal",
  "project": "/tmp/test_multiagent_sqlite_20251118_224643",
  "project_slug": "tmp-test-multiagent-sqlite-20251118-224643",
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
