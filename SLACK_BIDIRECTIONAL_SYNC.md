# Slack Bidirectional Sync Setup Guide

This guide explains how to set up **full bidirectional synchronization** between Slack and MCP Agent Mail, enabling agents to communicate through Slack channels.

## Overview

With bidirectional sync enabled:
- **Slack → MCP**: Messages posted to configured Slack channels automatically create MCP messages that agents receive
- **MCP → Slack**: MCP messages automatically post to Slack (already configured via `SLACK_NOTIFY_ON_MESSAGE`)
- **Thread Mapping**: Slack threads map to MCP `thread_id` for conversation continuity
- **Agent Collaboration**: Agents can see and respond to Slack messages, enabling human-agent and agent-agent communication via Slack

## Architecture

```
┌─────────────┐                    ┌──────────────────┐                 ┌─────────────┐
│   Slack     │ ──── Events ────> │  MCP Mail Server │ ──── Inbox ──> │   Agents    │
│  Channel    │                    │  (HTTP Webhook)  │                 │             │
│             │ <─── Posts ─────── │                  │ <─── Send ───── │             │
└─────────────┘                    └──────────────────┘                 └─────────────┘
     ↑                                      ↓
     │                              SlackBridge Agent
     │                              (System agent for
     └──────────────────────────── Slack → MCP messages)
```

## Quick Start

### 1. Create Slack App

1. Go to https://api.slack.com/apps and click **"Create New App"**
2. Choose **"From scratch"**
3. Name: `MCP Agent Mail`
4. Select your workspace

### 2. Configure OAuth & Permissions

**Bot Token Scopes** (required):
- `chat:write` - Post messages
- `chat:write.public` - Post to public channels without joining
- `channels:read` - List channels
- `channels:history` - Read message history (for sync)
- `groups:history` - Read private channel history (if using private channels)

**Install App to Workspace**:
- Click "Install to Workspace"
- Copy the **Bot User OAuth Token** (starts with `xoxb-`)

### 3. Enable Event Subscriptions

1. Navigate to **Event Subscriptions** in your Slack app
2. Enable Events: **ON**
3. **Request URL**: `https://your-server.com/slack/events`
   - For local testing: Use Cloudflare Tunnel (recommended) or ngrok
   - See **Section 3.1** below for tunnel setup
4. **Subscribe to bot events**:
   - `message.channels` - Messages in public channels
   - `message.groups` - Messages in private channels (optional)
   - `reaction_added` - Reactions (for future acknowledgment support)

5. Save Changes

### 3.1 Exposing Local Server with Cloudflare Tunnel (Recommended)

For local development and testing, you need to expose your local MCP Mail server to receive Slack webhooks. **Cloudflare Tunnel (cloudflared)** is the recommended approach as it's free and doesn't require authentication.

#### Install cloudflared

```bash
# macOS
brew install cloudflared

# Linux
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/
```

#### Start the Tunnel

```bash
# Start MCP Mail server first (default port 8765)
./scripts/run_server_with_token.sh &

# Start Cloudflare tunnel pointing to local server
cloudflared tunnel --url http://localhost:8765 --ha-connections 1 2>&1 | tee /tmp/cloudflared.log &

# Wait for the tunnel URL
sleep 5
grep -o 'https://[^"]*\.trycloudflare\.com' /tmp/cloudflared.log
```

You'll get a URL like: `https://earl-bloomberg-partner-russell.trycloudflare.com`

#### Configure Slack with Tunnel URL

1. Go to your Slack app → **Event Subscriptions**
2. Set **Request URL** to: `https://your-tunnel-url.trycloudflare.com/slack/events`
3. Slack will verify the endpoint (should show "Verified ✓")
4. Save changes

**Important Notes:**
- The tunnel URL changes each time you restart cloudflared
- For production, use a permanent Cloudflare Tunnel with a custom domain
- The tunnel must be running whenever you want to receive Slack events

#### Alternative: ngrok (Requires Account)

```bash
# Requires ngrok account and authtoken
ngrok http 8765

# Use the https://xxx.ngrok.io URL for Slack Event Subscriptions
```

### 4. Configure Credentials

You have two options for configuration:

#### Option A: credentials.json (Recommended for PyPI installs)

Create or update `~/.mcp_mail/credentials.json`:

```json
{
  "slack": {
    "enabled": true,
    "bot_token": "xoxb-your-bot-token-here",
    "signing_secret": "your-signing-secret",
    "default_channel": "C0A0AG6EELB",
    "notify_on_message": true,
    "use_blocks": true,
    "sync_enabled": true,
    "sync_channels": ["C0A0AG6EELB"],
    "sync_thread_replies": true,
    "sync_reactions": true
  }
}
```

#### Option B: Environment Variables (.env file)

Update your `.env` file:

```bash
# Enable Slack integration
SLACK_ENABLED=true

# Bot token from OAuth & Permissions
SLACK_BOT_TOKEN=xoxb-your-bot-token-here

# Signing secret from Basic Information
SLACK_SIGNING_SECRET=your-signing-secret

# Default channel for MCP → Slack notifications
SLACK_DEFAULT_CHANNEL=general

# Notification settings
SLACK_NOTIFY_ON_MESSAGE=true
SLACK_USE_BLOCKS=true

# === BIDIRECTIONAL SYNC SETTINGS ===

# Enable Slack → MCP sync
SLACK_SYNC_ENABLED=true

# Channels to sync (comma-separated channel IDs or names)
# Leave empty to sync ALL channels the bot can access
SLACK_SYNC_CHANNELS=C1234567890,C0987654321

# Thread and reaction support
SLACK_SYNC_THREAD_REPLIES=true
SLACK_SYNC_REACTIONS=true

# Optional: Webhook URL for fallback posting (if bot token unavailable)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

**Note**: The `credentials.json` file takes precedence. If both are configured, values from `credentials.json` will be used.

### 5. Find Channel IDs

To get channel IDs for `SLACK_SYNC_CHANNELS`:

```bash
# Option 1: Use the slack_list_channels MCP tool
# (after starting server with SLACK_BOT_TOKEN configured)

# Option 2: In Slack, right-click channel → Copy Link
# URL format: https://workspace.slack.com/archives/C1234567890
#                                             ^^^^^^^^^^ = Channel ID
```

### 6. Restart Server

```bash
# Stop existing server
kill <PID>

# Start with new configuration
./scripts/run_server_with_token.sh
```

## How It Works

### Slack → MCP Message Flow

1. **User posts to Slack channel** (configured in `SLACK_SYNC_CHANNELS`)
2. Slack sends event to `/slack/events` webhook
3. Server validates signature (using `SLACK_SIGNING_SECRET`)
4. Creates MCP message with:
   - **Sender**: `SlackBridge` (auto-created system agent)
   - **Recipients**: All active agents (they can filter/ignore as needed)
   - **Subject**: `[Slack] <first line of message>`
   - **Thread ID**: `slack_<channel>_<thread_ts>` (if threaded reply)
   - **Body**: Slack message text (with @ mentions preserved)

5. Agents receive message in their inbox and can respond

### MCP → Slack Message Flow

1. **Agent sends MCP message** via `send_message()` tool
2. Server creates MCP message in database
3. Background task posts to Slack:
   - **Web API** (if `SLACK_BOT_TOKEN` configured) - full features
   - **Webhook** (if only `SLACK_WEBHOOK_URL` set) - basic posting
4. Message appears in configured `SLACK_DEFAULT_CHANNEL`
5. If `thread_id` matches a Slack thread, posts as reply

## Testing

### Test Webhook Reception

1. Post a message in configured Slack channel:
   ```
   Hello agents! Can anyone help with deployment?
   ```

2. Check server logs:
   ```bash
   tail -f /tmp/mcp_agent_mail_server.log | grep slack
   ```

   You should see:
   ```
   slack_event_received event_type=message channel=C1234567890
   Creating MCP message from Slack: channel=C1234567890, user=U1234567890
   Created MCP message from Slack to 3 agents: [Slack] Hello agents! Can anyone help...
   ```

3. Check agent inbox (via `fetch_inbox` tool):
   ```json
   {
     "messages": [
       {
         "sender": "SlackBridge",
         "subject": "[Slack] Hello agents! Can anyone help with deployment?",
         "thread_id": "slack_C1234567890_1234567890.123456"
       }
     ]
   }
   ```

### Test MCP → Slack Posting

```python
# Agent sends message
send_message(
    project_key="myproject",
    agent_name="DeployAgent",
    to=["SlackBridge"],  # Or any agents
    subject="Deployment status",
    body_md="Production deployment completed successfully! 🎉",
    importance="high"
)
```

Check Slack - you should see the message with:
- Header showing importance emoji (❗)
- Formatted with Block Kit
- Metadata (sender, recipients, message ID)

## Thread Mapping

Thread linking enables proper conversation continuity between Slack and MCP.

**Slack Thread → MCP Thread**:
- When you reply to an MCP agent's message in Slack, the reply gets the **original MCP message ID** as its `thread_id`
- Example: MCP message #181 → Slack thread reply → MCP message #182 with `thread_id=181`
- New Slack threads without an MCP origin get IDs like: `slack_C1234567890_1503435956.000247`

**MCP Thread → Slack Thread**:
- MCP messages with matching `thread_id` post as Slack thread replies
- Thread mappings use a **singleton pattern** ensuring consistency across all code paths

**Thread Flow Example**:
```text
#181 (Claude → Slack) "Hello from Claude!"
  └── #182 (Slack → MCP) "test reply" [thread_id=181] ✓
      └── #183 (Claude → Slack) "Got it!" [thread_id=181] ✓
```

**Technical Note**: The SlackClient singleton maintains forward/reverse thread mappings in memory. Mappings persist while the server is running but are lost on restart. For production with high availability, consider persisting mappings to the database.

## Agent Collaboration Examples

### Example 1: Human asks agent for help

**Slack:**
```text
@human: Can someone review the PR?
```

**Agent receives:**
```json
{
  "sender": "SlackBridge",
  "subject": "[Slack] Can someone review the PR?",
  "body_md": "Can someone review the PR?"
}
```

**Agent responds:**
```python
send_message(
    to=["SlackBridge"],
    subject="Re: Can someone review the PR?",
    body_md="I'll review it now. Link: ...",
    thread_id="slack_C1234567890_1234567890.123456"  # Same thread
)
```

**Slack shows:**
```
[Thread]
  @human: Can someone review the PR?
  [BOT] ReviewAgent: I'll review it now. Link: ...
```

### Example 2: Agents coordinate via Slack

**Agent 1 → Slack:**
```python
send_message(
    to=["BuildAgent", "TestAgent"],
    subject="Build #1234 ready",
    body_md="Build complete. Please run tests."
)
```

**Slack:**
```
[BOT] DeployAgent:
Build #1234 ready
From: DeployAgent
To: BuildAgent, TestAgent
```

**Agent 2 sees in Slack, replies in thread**:
```
Tests passing! ✅
```

**Agent 1 receives MCP message:**
```json
{
  "sender": "SlackBridge",
  "subject": "[Slack] Tests passing! ✅",
  "thread_id": "slack_C1234567890_1234567890.789012"
}
```

## Troubleshooting

### Webhook Not Receiving Events

1. **Check Request URL is accessible**:
   ```bash
   curl -X POST https://your-server.com/slack/events \
     -H "Content-Type: application/json" \
     -d '{"type":"url_verification","challenge":"test123"}'
   ```
   Should return: `{"challenge":"test123"}`

2. **Verify signing secret**:
   - Check `SLACK_SIGNING_SECRET` matches Slack app
   - Server logs should NOT show `slack_signing_secret_missing`

3. **Check event subscriptions**:
   - Slack app → Event Subscriptions → Subscribed Events
   - Must include `message.channels`

### Messages Not Creating in MCP

1. **Check sync is enabled**:
   ```bash
   grep SLACK_SYNC_ENABLED .env
   # Should be: SLACK_SYNC_ENABLED=true
   ```

2. **Check channel is configured**:
   - If `SLACK_SYNC_CHANNELS` is set, make sure channel ID is in the list
   - Or leave empty to sync ALL channels

3. **Check logs for errors**:
   ```bash
   tail -f /tmp/mcp_agent_mail_server.log | grep -i "slack\|error"
   ```

### SlackBridge Agent Missing

The SlackBridge agent is auto-created on first Slack message. If missing:

```python
# Manually create via register_agent tool
register_agent(
    project_key="slack-sync",  # Or your project
    agent_name="SlackBridge",
    program="system"
)
```

## Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SLACK_ENABLED` | Yes | `false` | Enable Slack integration |
| `SLACK_BOT_TOKEN` | Yes* | - | Bot OAuth token (xoxb-...) |
| `SLACK_WEBHOOK_URL` | No | - | Fallback webhook for posting |
| `SLACK_SIGNING_SECRET` | Recommended | - | Webhook signature verification |
| `SLACK_DEFAULT_CHANNEL` | Yes | `general` | Default channel for MCP→Slack |
| `SLACK_SYNC_ENABLED` | Yes** | `false` | Enable Slack→MCP sync |
| `SLACK_SYNC_CHANNELS` | No | (all) | Channel IDs to sync (comma-separated) |
| `SLACK_SYNC_THREAD_REPLIES` | No | `true` | Map threads to MCP thread_id |
| `SLACK_NOTIFY_ON_MESSAGE` | No | `true` | Post MCP messages to Slack |
| `SLACK_USE_BLOCKS` | No | `true` | Use Block Kit formatting |

\* Required for full features; webhook URL can be used for posting only
\** Required for bidirectional sync (Slack → MCP)

## Security Notes

1. **Always use HTTPS** for webhook endpoint (Slack requirement)
2. **Set `SLACK_SIGNING_SECRET`** to verify webhook authenticity
3. **Limit channel access**: Only sync channels with appropriate content
4. **Bot messages are ignored** to prevent infinite loops
5. **Webhook validates signatures** before processing events

## Future Enhancements

- [ ] Persist thread mappings to database (currently in-memory)
- [ ] Map Slack users to MCP agent names (user table)
- [ ] Use reactions for acknowledgments (`👍` → `acknowledge_message`)
- [ ] Support Slack slash commands (`/mcp send @agent message`)
- [ ] Rich message formatting (convert Slack blocks → Markdown)
- [ ] File attachment sync (Slack files → MCP attachments)

## Support

For issues or questions:
- GitHub: https://github.com/jleechanorg/mcp_agent_mail/issues
- Check server logs: `/tmp/mcp_agent_mail_server.log`
