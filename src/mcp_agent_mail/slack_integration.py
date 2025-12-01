"""Slack integration for MCP Agent Mail.

This module provides bidirectional integration with Slack:
- Outbound: Send notifications to Slack when MCP messages are created/acknowledged
- Inbound: Sync Slack messages to MCP message system
- Thread mapping: Map Slack threads to MCP thread_id
- Reactions: Map Slack reactions to MCP acknowledgments

IMPORTANT: Thread Mapping Limitation
------------------------------------
Thread mappings between MCP threads and Slack threads are stored in-memory only
and will be lost on server restart. After a restart, messages in an existing MCP
thread will create new top-level Slack messages instead of replying to the existing
Slack thread.

For production deployments, consider implementing persistent storage for thread
mappings in the database to maintain thread continuity across server restarts.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from .config import Settings, SlackSettings

logger = logging.getLogger(__name__)

# Regex pattern for extracting Slack user mentions (e.g., <@U123|name>)
_SLACK_MENTION_PATTERN = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]+)?>")


@dataclass
class SlackThreadMapping:
    """Maps a Slack thread to an MCP message thread."""

    mcp_thread_id: str
    slack_channel_id: str
    slack_thread_ts: str
    created_at: datetime


class SlackIntegrationError(Exception):
    """Base exception for Slack integration errors."""

    pass


class SlackClient:
    """Async client for Slack Web API and Socket Mode.

    Provides methods for:
    - Posting messages to channels
    - Uploading files
    - Managing threads
    - Handling reactions
    - Socket Mode event streaming (for bidirectional sync)

    Thread Mapping Limitation:
        Thread mappings between MCP threads and Slack threads are stored in-memory
        and will be lost on server restart. After a restart, messages in an existing
        MCP thread will create new top-level Slack messages instead of replying to
        the existing Slack thread. For production use, persist mappings to database.
    """

    def __init__(self, settings: SlackSettings):
        """Initialize Slack client with settings.

        Args:
            settings: Slack configuration from Settings

        Note:
            Thread mappings are stored in-memory and will be lost on restart.
            TODO: Persist to database for production use.
        """
        self.settings = settings
        self._http_client: Optional[httpx.AsyncClient] = None
        # Note: In-memory thread mappings - lost on restart
        # TODO: Persist to database for production use
        self._thread_mappings: dict[str, SlackThreadMapping] = {}
        self._reverse_thread_mappings: dict[tuple[str, str], str] = {}
        self._mappings_lock = asyncio.Lock()

    async def __aenter__(self) -> SlackClient:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()

    async def connect(self) -> None:
        """Initialize HTTP client for Slack API."""
        if not self.settings.enabled:
            logger.debug("Slack integration is disabled")
            return

        if not self.settings.bot_token:
            raise SlackIntegrationError("SLACK_BOT_TOKEN is required when SLACK_ENABLED=true")

        self._http_client = httpx.AsyncClient(
            base_url="https://slack.com/api/",
            headers={
                "Authorization": f"Bearer {self.settings.bot_token}",
            },
            timeout=30.0,
        )
        logger.info("Slack client connected")

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def _check_client(self) -> None:
        """Ensure client is connected."""
        if not self._http_client:
            raise SlackIntegrationError("Slack client not connected. Call connect() first.")

    async def _call_api(self, method: str, **kwargs: Any) -> dict[str, Any]:
        """Call Slack Web API method."""
        self._check_client()
        assert self._http_client is not None

        try:
            response = await self._http_client.post(
                method,
                json=kwargs,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("ok"):
                error = data.get("error", "unknown_error")
                raise SlackIntegrationError(f"Slack API error: {error}")

            return data
        except httpx.HTTPError as e:
            logger.error(f"Slack API HTTP error: {e}")
            raise SlackIntegrationError(f"HTTP error calling {method}: {e}") from e

    async def post_message(
        self,
        channel: str,
        text: str,
        *,
        blocks: Optional[list[dict[str, Any]]] = None,
        thread_ts: Optional[str] = None,
        mrkdwn: bool = True,
    ) -> dict[str, Any]:
        """Post a message to a Slack channel."""
        kwargs: dict[str, Any] = {
            "channel": channel,
            "text": text,
            "mrkdwn": mrkdwn,
        }
        if blocks:
            kwargs["blocks"] = blocks
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        return await self._call_api("chat.postMessage", **kwargs)

    async def upload_file(
        self,
        channels: list[str],
        file_path: Path,
        *,
        title: Optional[str] = None,
        initial_comment: Optional[str] = None,
        thread_ts: Optional[str] = None,
    ) -> dict[str, Any]:
        """Upload a file to Slack channels."""
        self._check_client()
        assert self._http_client is not None

        file_bytes = await asyncio.to_thread(file_path.read_bytes)

        files = {"file": (file_path.name, file_bytes, "application/octet-stream")}
        data: dict[str, Any] = {"channels": ",".join(channels)}
        if title:
            data["title"] = title
        if initial_comment:
            data["initial_comment"] = initial_comment
        if thread_ts:
            data["thread_ts"] = thread_ts

        response = await self._http_client.post("files.upload", data=data, files=files)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            error = result.get("error", "unknown_error")
            raise SlackIntegrationError(f"File upload error: {error}")
        return result

    async def add_reaction(self, channel: str, timestamp: str, name: str) -> dict[str, Any]:
        """Add a reaction emoji to a message."""
        return await self._call_api("reactions.add", channel=channel, timestamp=timestamp, name=name)

    async def list_channels(self, *, exclude_archived: bool = True) -> list[dict[str, Any]]:
        """List all channels the bot can access."""
        channels: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            kwargs: dict[str, Any] = {
                "exclude_archived": exclude_archived,
                "types": "public_channel,private_channel",
            }
            if cursor:
                kwargs["cursor"] = cursor
            result = await self._call_api("conversations.list", **kwargs)
            channels.extend(result.get("channels", []))
            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        return channels

    async def get_channel_info(self, channel: str) -> dict[str, Any]:
        """Get information about a Slack channel."""
        result = await self._call_api("conversations.info", channel=channel)
        return result.get("channel", {})

    async def get_permalink(self, channel: str, message_ts: str) -> str:
        """Get permanent link to a message."""
        result = await self._call_api("chat.getPermalink", channel=channel, message_ts=message_ts)
        permalink = result.get("permalink")
        if not permalink:
            raise SlackIntegrationError("Failed to get permalink")
        return permalink

    async def map_thread(self, mcp_thread_id: str, slack_channel_id: str, slack_thread_ts: str) -> None:
        """Map an MCP thread ID to a Slack thread."""
        mapping = SlackThreadMapping(
            mcp_thread_id=mcp_thread_id,
            slack_channel_id=slack_channel_id,
            slack_thread_ts=slack_thread_ts,
            created_at=datetime.now(timezone.utc),
        )
        async with self._mappings_lock:
            self._thread_mappings[mcp_thread_id] = mapping
            self._reverse_thread_mappings[(slack_channel_id, slack_thread_ts)] = mcp_thread_id
        logger.debug(f"Mapped thread: MCP={mcp_thread_id} -> Slack={slack_channel_id}/{slack_thread_ts}")

    async def get_slack_thread(self, mcp_thread_id: str) -> Optional[SlackThreadMapping]:
        """Get Slack thread mapping for an MCP thread ID."""
        async with self._mappings_lock:
            return self._thread_mappings.get(mcp_thread_id)

    async def get_mcp_thread_id(self, slack_channel_id: str, slack_thread_ts: str) -> Optional[str]:
        """Get MCP thread ID for a Slack thread."""
        async with self._mappings_lock:
            return self._reverse_thread_mappings.get((slack_channel_id, slack_thread_ts))

    @staticmethod
    def verify_signature(*, signing_secret: Optional[str], timestamp: str, signature: str, body: bytes) -> bool:
        """Verify Slack request signature for webhook security."""
        if not signing_secret:
            logger.warning("SLACK_SIGNING_SECRET not set, rejecting request (signature verification required)")
            return False
        try:
            request_time = int(timestamp)
            current_time = int(time.time())
            if abs(current_time - request_time) > 60 * 5:
                logger.warning("Slack request timestamp too old")
                return False

            sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
            expected_signature = (
                "v0=" + hmac.new(signing_secret.encode(), sig_basestring.encode(), hashlib.sha256).hexdigest()
            )
            return hmac.compare_digest(expected_signature, signature)
        except (ValueError, UnicodeDecodeError) as e:
            logger.warning(f"Invalid Slack request: {e}")
            return False


# --- Simple webhook mirroring (outbound, optional) --------------------------------------------


def _post_webhook(url: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload).encode("utf-8")
    req = httpx.Request("POST", url, content=data, headers={"Content-Type": "application/json"})
    with httpx.Client(timeout=10.0) as client:
        resp = client.send(req)
        resp.raise_for_status()
        return resp.text


def mirror_message_to_slack(frontmatter: dict[str, Any], body_md: str) -> str | None:
    """Mirror an MCP message to Slack via incoming webhook when configured.

    Controlled by env vars:
    - SLACK_MCP_MAIL_WEBHOOK_URL (primary)
    - SLACK_WEBHOOK_URL (fallback)
    - SLACK_MIRROR_ENABLED (default: true). Set to '0'/'false' to disable.

    Returns the response body when sent, or None if skipped.
    """
    enabled_raw = os.getenv("SLACK_MIRROR_ENABLED", "true").strip().lower()
    enabled = enabled_raw not in {"0", "false", "no"}
    webhook = os.getenv("SLACK_MCP_MAIL_WEBHOOK_URL") or os.getenv("SLACK_WEBHOOK_URL")
    if not enabled or not webhook:
        return None

    project = frontmatter.get("project", "")
    subject = frontmatter.get("subject", "")
    sender_name = frontmatter.get("from", "")

    recipients: list[str] = []
    for key in ("to", "cc", "bcc"):
        value = frontmatter.get(key)
        if isinstance(value, str):
            recipients.append(value)
        elif isinstance(value, list):
            recipients.extend(value)
    thread = frontmatter.get("thread_id")
    title = f"{project} | {subject}".strip(" |")
    if thread:
        title = f"{title} (thread {thread})"

    lines = [f"*{title}*"]
    if sender_name:
        lines.append(f"*From:* {sender_name}")
    if recipients:
        lines.append(f"*To:* {', '.join(recipients)}")
    lines.append(body_md)

    text = "\n".join(lines)
    payload = {"text": text}
    return _post_webhook(webhook, payload)


def format_mcp_message_for_slack(
    subject: str,
    body_md: str,
    sender_name: str,
    recipients: list[str],
    *,
    message_id: Optional[str] = None,
    importance: str = "normal",
    use_blocks: bool = True,
) -> tuple[str, Optional[list[dict[str, Any]]]]:
    """Format an MCP message for posting to Slack.

    Args:
        subject: Message subject
        body_md: Message body in markdown
        sender_name: Sender's agent name
        recipients: List of recipient names
        message_id: Optional MCP message ID
        importance: Message importance level
        use_blocks: Whether to use Block Kit formatting

    Returns:
        Tuple of (text, blocks) where text is fallback and blocks is Block Kit layout
    """
    # Get importance indicator emoji
    importance_emoji = {
        "urgent": ":rotating_light:",
        "high": ":exclamation:",
        "normal": ":email:",
        "low": ":information_source:",
    }.get(importance, ":email:")

    # Fallback text for notifications with importance indicator and full routing info
    if recipients:
        recipient_list = ", ".join(recipients)
        text = f"{importance_emoji} *{subject}* from *{sender_name}* to {recipient_list}"
    else:
        text = f"{importance_emoji} *{subject}* from *{sender_name}*"

    if not use_blocks:
        return (text, None)

    # Build Block Kit blocks for rich formatting
    blocks: list[dict[str, Any]] = []

    # Header with importance indicator and subject
    header_text = f"{importance_emoji} {subject}"
    blocks.append(
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": header_text[:150],  # Slack header limit
                "emoji": True,
            },
        }
    )

    # Metadata section
    recipient_lines = "\n".join(f"• {name}" for name in recipients) if recipients else "—"

    metadata_fields = [
        {"type": "mrkdwn", "text": f"*From:*\n*{sender_name}*"},
        {"type": "mrkdwn", "text": f"*To:*\n{recipient_lines}"},
    ]

    if message_id:
        metadata_fields.append({"type": "mrkdwn", "text": f"*Message ID:*\n`{message_id[:8]}`"})

    blocks.append(
        {
            "type": "section",
            "fields": metadata_fields,
        }
    )

    blocks.append({"type": "divider"})

    # Message body (limit to 3000 chars for Slack)
    suffix = "\n\n_...message truncated..._"
    body_text = body_md[: 3000 - len(suffix)] + suffix if len(body_md) > 3000 else body_md

    blocks.append(
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": body_text,
            },
        }
    )

    return (text, blocks)


async def notify_slack_message(
    client: SlackClient,
    settings: Settings,
    *,
    message_id: str,
    subject: str,
    body_md: str,
    sender_name: str,
    recipients: list[str],
    importance: str = "normal",
    thread_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Send a notification to Slack when an MCP message is created.

    Args:
        client: Connected SlackClient instance
        settings: Application settings
        message_id: MCP message ID
        subject: Message subject
        body_md: Message body markdown
        sender_name: Sender agent name
        recipients: List of recipient names
        importance: Message importance
        thread_id: Optional MCP thread ID for threading

    Returns:
        Slack API response if sent, None if disabled

    Raises:
        SlackIntegrationError: If notification fails
    """
    if not settings.slack.enabled or not settings.slack.notify_on_message:
        return None

    try:
        # Format message for Slack
        text, blocks = format_mcp_message_for_slack(
            subject=subject,
            body_md=body_md,
            sender_name=sender_name,
            recipients=recipients,
            message_id=message_id,
            importance=importance,
            use_blocks=settings.slack.use_blocks,
        )

        # Determine channel
        channel = settings.slack.default_channel

        # Check for existing thread mapping (fallback to message_id for new threads)
        slack_thread_ts: Optional[str] = None
        thread_key = thread_id or message_id
        if thread_key:
            thread_mapping = await client.get_slack_thread(thread_key)
            if thread_mapping:
                slack_thread_ts = thread_mapping.slack_thread_ts
                channel = thread_mapping.slack_channel_id

        # Post to Slack
        response = await client.post_message(
            channel=channel,
            text=text,
            blocks=blocks,
            thread_ts=slack_thread_ts,
        )

        # If this is a new thread, create mapping
        if thread_key and not slack_thread_ts:
            msg_ts = response.get("ts")
            channel_id = response.get("channel")
            if msg_ts and channel_id:
                await client.map_thread(thread_key, channel_id, msg_ts)

        logger.info(f"Sent Slack notification for message {message_id[:8]} to channel {channel}")
        return response

    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")
        raise SlackIntegrationError(f"Failed to notify Slack: {e}") from e


async def notify_slack_ack(
    client: SlackClient,
    settings: Settings,
    *,
    message_id: str,
    agent_name: str,
    subject: str,
) -> Optional[dict[str, Any]]:
    """Send a notification to Slack when a message is acknowledged.

    Note:
        Unlike notify_slack_message, this function does not raise exceptions
        on failure. Acknowledgment notifications are intentionally treated as
        best-effort so that Slack outages do not disrupt the primary ack
        workflow. Errors are logged but do not propagate.

    Args:
        client: Connected SlackClient instance
        settings: Application settings
        message_id: MCP message ID
        agent_name: Agent who acknowledged
        subject: Original message subject

    Returns:
        Slack API response if sent, None if disabled or on error

    Raises:
        Does not raise exceptions; logs errors and returns None on failure
    """
    if not settings.slack.enabled or not settings.slack.notify_on_ack:
        return None

    try:
        text = f":white_check_mark: {agent_name} acknowledged: {subject}"
        response = await client.post_message(
            channel=settings.slack.default_channel,
            text=text,
        )

        logger.info(f"Sent Slack ack notification for message {message_id[:8]}")
        return response

    except Exception as e:
        logger.error(f"Failed to send Slack ack notification: {e}")
        # Don't raise - ack notifications are non-critical
        return None


async def handle_slack_message_event(
    event: dict[str, Any],
    settings: Settings,
) -> Optional[dict[str, Any]]:
    """Handle incoming Slack message event and create MCP message.

    This function implements Slack → MCP Mail sync. When a message is posted to
    a configured Slack channel, it creates a corresponding MCP message that agents
    can see and respond to.

    Args:
        event: Slack message event payload
        settings: Application settings

    Returns:
        Dict with created message info, or None if message should be ignored

    Message Routing Logic:
        - Messages from configured sync channels are broadcast to all agents
        - @mentions create targeted messages to specific agents
        - Thread replies are mapped to MCP thread_id for conversation continuity
        - Bot's own messages are ignored to prevent loops

    Example event:
        {
          "type": "message",
          "channel": "C1234567890",
          "user": "U1234567890",
          "text": "@BlueWhale can you review the deployment?",
          "ts": "1503435956.000247",
          "thread_ts": "1503435956.000100"  # If reply in thread
        }
    """
    # Ignore bot messages to prevent loops
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        logger.debug("Ignoring bot message to prevent loop")
        return None

    channel_id = event.get("channel")
    text = event.get("text", "")
    user_id = event.get("user")
    message_ts = event.get("ts")
    thread_ts = event.get("thread_ts")  # If reply in thread

    # Check if this channel is configured for sync
    if not settings.slack.sync_enabled:
        logger.debug("Slack sync is disabled")
        return None

    if settings.slack.sync_channels and channel_id not in settings.slack.sync_channels:
        logger.debug(f"Channel {channel_id} not in sync_channels list")
        return None

    # Extract @mentions for potential targeted delivery
    # Slack format: <@U1234567890|username> or <@U1234567890>
    mentioned_users = _SLACK_MENTION_PATTERN.findall(text)
    # TODO: Route messages to mentioned agents once agent/user mapping is available

    # Route all Slack traffic through the shared SlackBridge system agent
    sender_name = "SlackBridge"

    # Determine MCP thread_id from Slack thread
    # Use Slack thread_ts when present, otherwise top-level ts, so dedupe and replies work
    if settings.slack.sync_thread_replies:
        base_ts = thread_ts or message_ts
        mcp_thread_id = f"slack_{channel_id}_{base_ts}" if base_ts else None
    else:
        mcp_thread_id = None

    # Create subject from first line of text
    subject_parts = text.split("\n", 1)
    subject_raw = subject_parts[0].strip() if subject_parts else ""
    subject = subject_raw[:100] if subject_raw else "Empty message"

    # Clean up text (remove Slack mention formatting while preserving URLs)
    body_md = _SLACK_MENTION_PATTERN.sub(r"@\1", text)

    logger.info(f"Creating MCP message from Slack: channel={channel_id}, user={user_id}, thread={mcp_thread_id}")

    return {
        "sender_name": sender_name,
        "subject": f"[Slack] {subject}",
        "body_md": body_md,
        "thread_id": mcp_thread_id,
        "slack_channel": channel_id,
        "slack_ts": message_ts,
        "slack_thread_ts": thread_ts,
        "mentioned_users": mentioned_users,
    }


async def post_via_webhook(
    webhook_url: str,
    text: str,
    *,
    blocks: Optional[list[dict[str, Any]]] = None,
) -> bool:
    """Post message to Slack via webhook URL (fallback method).

    Webhook URLs are simpler but more limited than the Web API:
    - Can only post to one pre-configured channel
    - Cannot list channels, get permalinks, or read messages
    - Useful as a fallback when bot token isn't available

    Args:
        webhook_url: Incoming webhook URL
        text: Message text (required, used as fallback)
        blocks: Optional Block Kit blocks for rich formatting

    Returns:
        True if message posted successfully, False otherwise
    """
    payload: dict[str, Any] = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()

            if response.text == "ok":
                logger.info("Posted message via webhook")
                return True
            else:
                logger.warning(f"Unexpected webhook response: {response.text}")
                return False

    except Exception as e:
        logger.error(f"Failed to post via webhook: {e}")
        return False
