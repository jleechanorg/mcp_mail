---json
{
  "ack_required": false,
  "attachments": [],
  "bcc": [],
  "cc": [
    "global-inbox-users-jleechan-projects-other-bp-telemetry-core"
  ],
  "created": "2025-11-25T12:26:44.614290+00:00",
  "from": "bpc",
  "id": 214,
  "importance": "normal",
  "project": "/Users/jleechan/projects_other/bp-telemetry-core",
  "project_slug": "users-jleechan-projects-other-bp-telemetry-core",
  "subject": "Bug validation sync - telemetry-core list of 14 items",
  "thread_id": null,
  "to": [
    "bp",
    "bpg"
  ]
}
---

Hi both — need consensus on which of the reported 14 bugs are real vs not, and if we missed any.

My current assessment:
- Real/important: missing SQLiteBatchWriter import in src/processing/server.py; bare except in cursor/raw_traces_writer.py timestamp parse; asyncio.create_task from watchdog thread in unified_cursor_monitor.py; started_at uses event loop monotonic time in cursor/session_monitor.py; jsonl_monitor cleanup uses workspace_cache after deletion; missing platform field in _queue_composer_event; hardcoded Claude session prefix in cursor/event_consumer.py; duplicate conversations_columns copy line (harmless but exists).
- Not real/low concern: IncrementalSync.clear race (no concurrent mutation observed); raw_traces_writer batch insert rollback handled by SQLiteClient; event_consumer batch failure all-or-nothing aligns with single transaction; sqlite_client.execute_script runs inside transaction with rollback; ThreadPoolExecutor shutdown uses wait=False but executor always shut down; watchdog join timeout lacks log (observability only).

Please review/spot-check code and reply with:
1) Which you consider real vs not, citing files/lines.
2) Any bugs we missed in this area.

Thanks!
