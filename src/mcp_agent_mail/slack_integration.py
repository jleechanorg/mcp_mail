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
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from .config import Settings, SlackSettings

logger = logging.getLogger(__name__)


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
            logger.info("Slack client closed")

    def _check_client(self) -> None:
        """Ensure client is connected."""
        if not self._http_client:
            raise SlackIntegrationError("Slack client not connected. Call connect() first.")

    async def _call_api(self, method: str, **kwargs: Any) -> dict[str, Any]:
        """Call Slack Web API method.

        Args:
            method: API method name (e.g., "chat.postMessage")
            **kwargs: Method parameters

        Returns:
            API response as dict

        Raises:
            SlackIntegrationError: If API call fails
        """
        self._check_client()
        assert self._http_client is not None  # for mypy

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
        """Post a message to a Slack channel.

        Args:
            channel: Channel ID or name
            text: Message text (fallback for notifications)
            blocks: Optional Block Kit blocks for rich formatting
            thread_ts: Optional thread timestamp to reply in thread
            mrkdwn: Whether to enable markdown formatting

        Returns:
            Slack API response with message details

        Example:
            >>> await client.post_message(
            ...     channel="C1234567890",
            ...     text="New message from Agent",
            ...     blocks=[{
            ...         "type": "section",
            ...         "text": {"type": "mrkdwn", "text": "*New message*"}
            ...     }]
            ... )
        """
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
        """Upload a file to Slack channels.

        Args:
            channels: List of channel IDs
            file_path: Path to file to upload
            title: Optional file title
            initial_comment: Optional comment to add with file
            thread_ts: Optional thread timestamp

        Returns:
            Slack API response

        Note:
            Currently uses synchronous file I/O which may block the event loop
            for large files. Consider using aiofiles or asyncio.to_thread() for
            async file operations in future improvements.
        """
        self._check_client()
        assert self._http_client is not None

        # Read file into bytes before async request
        # TODO: Consider using aiofiles for non-blocking file I/O
        with file_path.open("rb") as f:
            file_bytes = f.read()

        files = {"file": (file_path.name, file_bytes, "application/octet-stream")}
        data: dict[str, Any] = {"channels": ",".join(channels)}

        if title:
            data["title"] = title
        if initial_comment:
            data["initial_comment"] = initial_comment
        if thread_ts:
            data["thread_ts"] = thread_ts

        # Note: files.upload requires multipart/form-data, not JSON
        # httpx will automatically set the correct Content-Type with boundary
        response = await self._http_client.post(
            "files.upload",
            data=data,
            files=files,
        )
        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            error = result.get("error", "unknown_error")
            raise SlackIntegrationError(f"File upload error: {error}")

        return result

    async def add_reaction(self, channel: str, timestamp: str, name: str) -> dict[str, Any]:
        """Add a reaction emoji to a message.

        Args:
            channel: Channel ID
            timestamp: Message timestamp
            name: Emoji name (without colons, e.g., "thumbsup")

        Returns:
            Slack API response
        """
        return await self._call_api(
            "reactions.add",
            channel=channel,
            timestamp=timestamp,
            name=name,
        )

    async def list_channels(self, *, exclude_archived: bool = True) -> list[dict[str, Any]]:
        """List all channels the bot can access.

        Args:
            exclude_archived: Whether to exclude archived channels

        Returns:
            List of channel objects
        """
        channels = []
        cursor = None

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
        """Get information about a channel.

        Args:
            channel: Channel ID

        Returns:
            Channel information
        """
        result = await self._call_api("conversations.info", channel=channel)
        return result.get("channel", {})

    async def get_permalink(self, channel: str, message_ts: str) -> str:
        """Get permanent link to a message.

        Args:
            channel: Channel ID
            message_ts: Message timestamp

        Returns:
            Permalink URL
        """
        result = await self._call_api(
            "chat.getPermalink",
            channel=channel,
            message_ts=message_ts,
        )
        return result.get("permalink", "")

    async def map_thread(
        self,
        mcp_thread_id: str,
        slack_channel_id: str,
        slack_thread_ts: str,
    ) -> None:
        """Map an MCP thread ID to a Slack thread.

        Note:
            Mapping is stored in-memory only and will be lost on restart.

        Args:
            mcp_thread_id: MCP message thread ID
            slack_channel_id: Slack channel ID
            slack_thread_ts: Slack thread timestamp
        """
        mapping = SlackThreadMapping(
            mcp_thread_id=mcp_thread_id,
            slack_channel_id=slack_channel_id,
            slack_thread_ts=slack_thread_ts,
            created_at=datetime.now(timezone.utc),
        )
        async with self._mappings_lock:
            self._thread_mappings[mcp_thread_id] = mapping
            self._reverse_thread_mappings[(slack_channel_id, slack_thread_ts)] = mcp_thread_id
        logger.debug(
            f"Mapped thread: MCP={mcp_thread_id} -> Slack={slack_channel_id}/{slack_thread_ts}"
        )

    async def get_slack_thread(self, mcp_thread_id: str) -> Optional[SlackThreadMapping]:
        """Get Slack thread mapping for an MCP thread ID.

        Args:
            mcp_thread_id: MCP thread ID

        Returns:
            SlackThreadMapping if found, None otherwise
        """
        async with self._mappings_lock:
            return self._thread_mappings.get(mcp_thread_id)

    async def get_mcp_thread_id(self, slack_channel_id: str, slack_thread_ts: str) -> Optional[str]:
        """Get MCP thread ID for a Slack thread.

        Args:
            slack_channel_id: Slack channel ID
            slack_thread_ts: Slack thread timestamp

        Returns:
            MCP thread ID if found, None otherwise
        """
        async with self._mappings_lock:
            return self._reverse_thread_mappings.get((slack_channel_id, slack_thread_ts))

    @staticmethod
    def verify_signature(
        signing_secret: Optional[str],
        timestamp: str,
        signature: str,
        body: bytes,
    ) -> bool:
        """Verify Slack request signature for webhook security.

        Args:
            signing_secret: Slack signing secret
            timestamp: Request timestamp from X-Slack-Request-Timestamp header
            signature: Signature from X-Slack-Signature header
            body: Raw request body bytes

        Returns:
            True if signature is valid, False otherwise

        Reference:
            https://api.slack.com/authentication/verifying-requests-from-slack
        """
        if not signing_secret:
            logger.warning("SLACK_SIGNING_SECRET not set, skipping signature verification")
            return True

        try:
            # Reject old timestamps to prevent replay attacks
            request_time = int(timestamp)
            current_time = int(time.time())
            if abs(current_time - request_time) > 60 * 5:  # 5 minutes
                logger.warning("Slack request timestamp too old")
                return False

            # Compute signature
            sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
            expected_signature = "v0=" + hmac.new(
                signing_secret.encode(),
                sig_basestring.encode(),
                hashlib.sha256,
            ).hexdigest()

            return hmac.compare_digest(expected_signature, signature)
        except (ValueError, UnicodeDecodeError) as e:
            logger.warning(f"Invalid Slack request: {e}")
            return False


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

    # Fallback text for notifications with importance indicator
    text = f"{importance_emoji} *{subject}* from {sender_name}"

    if not use_blocks:
        return (text, None)

    # Build Block Kit blocks for rich formatting
    blocks: list[dict[str, Any]] = []

    # Header with importance indicator and subject
    header_text = f"{importance_emoji} {subject}"
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": header_text[:150],  # Slack header limit
            "emoji": True,
        },
    })

    # Metadata section
    metadata_fields = [
        {"type": "mrkdwn", "text": f"*From:*\n{sender_name}"},
        {"type": "mrkdwn", "text": f"*To:*\n{', '.join(recipients[:5])}"},
    ]

    if message_id:
        metadata_fields.append({"type": "mrkdwn", "text": f"*Message ID:*\n`{message_id[:8]}`"})

    blocks.append({
        "type": "section",
        "fields": metadata_fields,
    })

    blocks.append({"type": "divider"})

    # Message body (limit to 3000 chars for Slack)
    body_text = body_md[:3000]
    if len(body_md) > 3000:
        body_text += "\n\n_...message truncated..._"

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": body_text,
        },
    })

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

        # Check for existing thread mapping
        slack_thread_ts: Optional[str] = None
        if thread_id:
            thread_mapping = await client.get_slack_thread(thread_id)
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
        if thread_id and not slack_thread_ts:
            msg_ts = response.get("ts")
            channel_id = response.get("channel")
            if msg_ts and channel_id:
                await client.map_thread(thread_id, channel_id, msg_ts)

        logger.info(
            f"Sent Slack notification for message {message_id[:8]} to channel {channel}"
        )
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
        on failure. Acknowledgment notifications are non-critical; errors are
        logged but do not propagate to prevent disrupting the ack workflow.

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
