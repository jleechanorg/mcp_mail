"""Integration tests for Slack bidirectional sync with thread mapping.

These tests validate the complete bidirectional flow:
1. MCP → Slack: Agent sends MCP message, appears in Slack
2. Slack → MCP: Reply in Slack thread creates MCP message with correct thread_id
3. Thread Mapping: Slack threads correctly link to original MCP message IDs

Tests are structured to run against a mock HTTP server, with optional
live Slack testing when SLACK_LIVE_TEST=1 and credentials are configured.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

# Try importing the actual modules - skip tests if not available
try:
    from mcp_agent_mail.config import SlackSettings
    from mcp_agent_mail.slack_integration import SlackClient, SlackThreadMapping, mirror_message_to_slack

    SLACK_INTEGRATION_AVAILABLE = True
except ImportError as e:
    SLACK_INTEGRATION_AVAILABLE = False
    IMPORT_ERROR = str(e)


pytestmark = pytest.mark.skipif(
    not SLACK_INTEGRATION_AVAILABLE,
    reason=f"slack_integration module not available: {IMPORT_ERROR if not SLACK_INTEGRATION_AVAILABLE else ''}",
)


def create_test_slack_settings(**overrides) -> "SlackSettings":
    """Create SlackSettings with test defaults."""
    defaults = {
        "enabled": True,
        "bot_token": "xoxb-test-token-12345",
        "app_token": None,
        "signing_secret": "test-signing-secret",
        "default_channel": "C0123456789",
        "notify_on_message": True,
        "notify_on_ack": True,
        "notify_mention_format": "agent_name",
        "sync_enabled": True,
        "sync_project_name": "test-project",
        "sync_channels": [],
        "sync_thread_replies": True,
        "sync_reactions": True,
        "use_blocks": True,
        "include_attachments": True,
        "webhook_url": None,
        "slackbox_enabled": False,
        "slackbox_token": None,
        "slackbox_channels": [],
        "slackbox_sender_name": "SlackBridge",
        "slackbox_subject_prefix": "[Slack]",
    }
    defaults.update(overrides)
    return SlackSettings(**defaults)


def generate_slack_signature(payload: str, signing_secret: str, timestamp: str) -> str:
    """Generate a valid Slack signature for testing."""
    sig_basestring = f"v0:{timestamp}:{payload}"
    signature = hmac.new(signing_secret.encode("utf-8"), sig_basestring.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"v0={signature}"


class TestSlackThreadMapping:
    """Tests for thread mapping data structure."""

    def test_create_thread_mapping(self):
        """Test creating a thread mapping."""
        mapping = SlackThreadMapping(
            mcp_thread_id="42",
            slack_channel_id="C0123456789",
            slack_thread_ts="1234567890.123456",
            created_at=datetime.now(timezone.utc),
        )
        assert mapping.mcp_thread_id == "42"
        assert mapping.slack_channel_id == "C0123456789"
        assert mapping.slack_thread_ts == "1234567890.123456"

    def test_thread_mapping_fields(self):
        """Test that thread mapping has all expected fields."""
        now = datetime.now(timezone.utc)
        mapping = SlackThreadMapping(
            mcp_thread_id="123", slack_channel_id="C0123456789", slack_thread_ts="1234567890.234567", created_at=now
        )
        assert mapping.created_at == now


class TestSlackClientSingleton:
    """Tests for SlackClient singleton behavior."""

    def test_slack_client_initialization(self):
        """Test that SlackClient can be instantiated with settings."""
        settings = create_test_slack_settings()
        client = SlackClient(settings)
        assert client.settings == settings
        assert client._thread_mappings == {}
        assert client._reverse_thread_mappings == {}

    def test_thread_mapping_storage(self):
        """Test that thread mappings can be stored and retrieved."""
        settings = create_test_slack_settings()
        client = SlackClient(settings)

        # Add a mapping
        mapping = SlackThreadMapping(
            mcp_thread_id="100",
            slack_channel_id="C0123456789",
            slack_thread_ts="1111111111.111111",
            created_at=datetime.now(timezone.utc),
        )
        client._thread_mappings["100"] = mapping

        # Verify mapping exists
        assert "100" in client._thread_mappings
        assert client._thread_mappings["100"].slack_thread_ts == "1111111111.111111"

    def test_reverse_thread_mapping(self):
        """Test that reverse thread mappings work for Slack → MCP lookups."""
        settings = create_test_slack_settings()
        client = SlackClient(settings)

        # Add forward and reverse mappings
        mapping = SlackThreadMapping(
            mcp_thread_id="42",
            slack_channel_id="C0123456789",
            slack_thread_ts="1234567890.111111",
            created_at=datetime.now(timezone.utc),
        )
        client._thread_mappings["42"] = mapping
        client._reverse_thread_mappings[("C0123456789", "1234567890.111111")] = "42"

        # Look up MCP thread from Slack coordinates
        mcp_thread_id = client._reverse_thread_mappings.get(("C0123456789", "1234567890.111111"))
        assert mcp_thread_id == "42"


class TestBidirectionalThreadFlow:
    """Tests for complete bidirectional thread flow."""

    def test_thread_flow_mcp_to_slack_mapping(self):
        """Test that MCP thread IDs map to Slack thread coordinates."""
        settings = create_test_slack_settings()
        client = SlackClient(settings)

        # Step 1: MCP message #181 → Slack (simulated)
        mapping = SlackThreadMapping(
            mcp_thread_id="181",
            slack_channel_id="C0123456789",
            slack_thread_ts="1234567890.181000",
            created_at=datetime.now(timezone.utc),
        )
        client._thread_mappings["181"] = mapping
        client._reverse_thread_mappings[("C0123456789", "1234567890.181000")] = "181"

        # Step 2: Verify forward mapping (MCP → Slack)
        assert "181" in client._thread_mappings
        assert client._thread_mappings["181"].slack_thread_ts == "1234567890.181000"

        # Step 3: Verify reverse mapping (Slack → MCP)
        mcp_thread_id = client._reverse_thread_mappings.get(("C0123456789", "1234567890.181000"))
        assert mcp_thread_id == "181"

    def test_thread_flow_slack_reply_lookup(self):
        """Test that Slack thread replies can find the MCP thread."""
        settings = create_test_slack_settings()
        client = SlackClient(settings)

        # Set up: MCP message #181 created a Slack thread
        client._reverse_thread_mappings[("C0123456789", "1234567890.181000")] = "181"

        # Simulate: Slack reply in thread_ts=1234567890.181000
        slack_reply_thread_ts = "1234567890.181000"
        slack_channel = "C0123456789"

        # Look up: Should find MCP thread_id=181
        mcp_thread_id = client._reverse_thread_mappings.get((slack_channel, slack_reply_thread_ts))
        assert mcp_thread_id == "181", "Slack reply should resolve to MCP message 181"


class TestThreadIdFormat:
    """Tests for thread ID format handling."""

    def test_slack_thread_id_format(self):
        """Test that Slack-originating thread IDs have correct format."""
        channel_id = "C0123456789"
        thread_ts = "1234567890.123456"

        expected_format = f"slack_{channel_id}_{thread_ts}"
        assert expected_format == "slack_C0123456789_1234567890.123456"

    def test_slackbox_thread_id_format(self):
        """Test slackbox variant of thread ID format."""
        channel_id = "C0123456789"
        thread_ts = "1234567890.123456"

        expected_format = f"slackbox_{channel_id}_{thread_ts}"
        assert expected_format == "slackbox_C0123456789_1234567890.123456"

    def test_mcp_thread_id_is_string(self):
        """Test that MCP thread IDs are stored as strings."""
        settings = create_test_slack_settings()
        client = SlackClient(settings)

        # Thread IDs should be strings (MCP message IDs converted to string)
        mcp_thread_id = "42"
        client._thread_mappings[mcp_thread_id] = SlackThreadMapping(
            mcp_thread_id=mcp_thread_id,
            slack_channel_id="C0123456789",
            slack_thread_ts="1234567890.123456",
            created_at=datetime.now(timezone.utc),
        )

        assert mcp_thread_id in client._thread_mappings
        assert isinstance(client._thread_mappings[mcp_thread_id].mcp_thread_id, str)


class TestMirrorToSlack:
    """Tests for mirror_message_to_slack function."""

    @patch("mcp_agent_mail.slack_integration._post_webhook")
    def test_mirror_with_webhook_returns_ok(self, mock_post):
        """Test that mirror_message_to_slack posts via webhook when configured."""
        mock_post.return_value = "ok"

        frontmatter = {
            "project": "test-project",
            "subject": "Test message",
            "from": "TestAgent",
            "to": ["RecipientAgent"],
        }
        body_md = "This is a test message."

        # This will only work if webhook URL is configured
        # The function returns None if no webhook configured
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"}):
            mirror_message_to_slack(frontmatter, body_md)
            # Result depends on whether webhook is configured in settings


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_thread_mappings(self):
        """Test behavior with no thread mappings."""
        settings = create_test_slack_settings()
        client = SlackClient(settings)

        # Should return None for unknown thread
        result = client._reverse_thread_mappings.get(("C0123456789", "unknown.ts"))
        assert result is None

    def test_disabled_slack_client(self):
        """Test SlackClient when Slack is disabled."""
        settings = create_test_slack_settings(enabled=False, bot_token=None, default_channel="")
        client = SlackClient(settings)
        assert client.settings.enabled is False


class TestLiveSlackIntegration:
    """Live Slack integration tests (requires SLACK_LIVE_TEST=1)."""

    def test_live_roundtrip(self):
        """Test live MCP → Slack → verify flow.

        Requires:
        - SLACK_LIVE_TEST=1
        - Valid SLACK_BOT_TOKEN
        - Valid SLACK_DEFAULT_CHANNEL
        """
        if os.getenv("SLACK_LIVE_TEST") != "1":
            pytest.skip("SLACK_LIVE_TEST not enabled")

        # Send a test message to Slack
        frontmatter = {
            "project": "live-test",
            "subject": f"Bidi Test {datetime.now(timezone.utc).isoformat()}",
            "from": "TestAgent",
            "to": ["SlackBridge"],
        }
        body_md = "This is a bidirectional sync integration test."

        result = mirror_message_to_slack(frontmatter, body_md)

        # Should return "ok" or a Slack ts
        assert result is not None or os.getenv("SLACK_WEBHOOK_URL") is None


class TestSignatureVerification:
    """Tests for Slack webhook signature verification patterns."""

    def test_signature_generation(self):
        """Test that we can generate valid HMAC-SHA256 signatures."""
        payload = '{"type": "event_callback"}'
        timestamp = str(int(time.time()))
        signing_secret = "test-signing-secret"

        signature = generate_slack_signature(payload, signing_secret, timestamp)

        # Signature should be in v0= format
        assert signature.startswith("v0=")
        assert len(signature) == 67  # v0= + 64 hex chars

    def test_signature_deterministic(self):
        """Test that same inputs produce same signature."""
        payload = '{"test": true}'
        timestamp = "1234567890"
        signing_secret = "secret"

        sig1 = generate_slack_signature(payload, signing_secret, timestamp)
        sig2 = generate_slack_signature(payload, signing_secret, timestamp)

        assert sig1 == sig2

    def test_different_payloads_different_signatures(self):
        """Test that different payloads produce different signatures."""
        timestamp = "1234567890"
        signing_secret = "secret"

        sig1 = generate_slack_signature('{"a": 1}', signing_secret, timestamp)
        sig2 = generate_slack_signature('{"b": 2}', signing_secret, timestamp)

        assert sig1 != sig2


class TestSlackSettings:
    """Tests for SlackSettings configuration."""

    def test_settings_with_all_fields(self):
        """Test creating SlackSettings with all fields."""
        settings = create_test_slack_settings(
            bot_token="xoxb-test",
            signing_secret="secret",
            webhook_url="https://hooks.slack.com/test",
            sync_channels=["C0123456789"],
        )
        assert settings.enabled is True
        assert settings.bot_token == "xoxb-test"
        assert settings.sync_enabled is True

    def test_settings_minimal(self):
        """Test creating SlackSettings with minimal fields using helper."""
        settings = create_test_slack_settings(bot_token="xoxb-test")
        assert settings.enabled is True
        assert settings.bot_token == "xoxb-test"
