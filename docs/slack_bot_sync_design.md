# Slack Bot Bidirectional Sync Design

This document describes the standard Slack **bot-based** integration that provides full bidirectional communication between Slack and MCP Agent Mail without relying on legacy outgoing webhooks.

## Goals
- **Inbound:** Turn Slack channel messages into MCP inbox messages with thread continuity.
- **Outbound:** Post MCP messages back to Slack in the originating channel/thread when possible.
- **Deduplication:** Avoid duplicate ingestion when Slack retries events.
- **Security:** Enforce Slack signing-secret verification for Events API requests.

## Architecture
- Slack sends Events API payloads to `/slack/events` (validated with `SLACK_SIGNING_SECRET`).
- The server normalizes events via `handle_slack_message_event`, deriving the MCP `thread_id` from the Slack channel + thread/message timestamp.
- `_ingest_slack_bridge_message` creates the MCP message, writes the archive entry, and records dedupe keys.
- When a Slack client is available (bot token connected), the ingestion step maps the MCP `thread_id` to the Slack channel/timestamp so future MCP replies post into the same Slack thread.
- Outbound Slack notifications (`notify_slack_message` / `notify_slack_ack`) use the thread mapping to reply inline; otherwise they fall back to the configured default channel.

## Configuration (env)
```bash
SLACK_ENABLED=true
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_SYNC_ENABLED=true
SLACK_SYNC_CHANNELS=C1234567890,C2345678901    # optional allowlist
SLACK_SYNC_PROJECT_NAME=slack-sync
SLACK_SYNC_THREAD_REPLIES=true
SLACK_NOTIFY_ON_MESSAGE=true
SLACK_DEFAULT_CHANNEL=C1234567890
```

## Setup Steps
1. Create a Slack app with a bot user; add scopes `chat:write`, `chat:write.public`, `channels:history`, `channels:read`, and (optionally) `groups:history` if syncing private channels.
2. Enable **Event Subscriptions**; set the Request URL to `<server>/slack/events` and subscribe to `message.channels` (and `message.groups` if needed).
3. Install the app to the workspace, copy the bot token and signing secret, and place them in `.env` using the variables above.
4. Restart the MCP Agent Mail server so the Slack client initializes with the bot token.

## Runtime Behavior
- A message in a synced channel becomes an MCP message with sender `SlackBridge` and subject `[Slack] <first line>`. The `thread_id` uses `slack_<channel>_<ts>` so threaded replies stay together.
- If the Slack bot is available, the ingestion step maps that `thread_id` to the Slack channel/timestamp; when an agent replies from MCP, the Slack notification uses the mapping to reply in-thread instead of creating a new top-level post.
- Deduplication uses `(channel, ts)` keys to drop Slack retry deliveries.

## Notes
- Slackbox (legacy outgoing webhook) remains available but is not required for bot-based bidirectional sync.
- Thread mappings are in-memory; if you need persistence across restarts, extend `SlackClient.map_thread` to store mappings in the database.
