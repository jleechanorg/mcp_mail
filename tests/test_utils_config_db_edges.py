from __future__ import annotations

import asyncio

from mcp_agent_mail.config import clear_settings_cache, get_settings
from mcp_agent_mail.db import ensure_schema, get_engine, reset_database_state
from mcp_agent_mail.utils import sanitize_agent_name, slugify


def test_slugify_and_sanitize_edges():
    assert slugify("  Hello World!!  ") == "hello-world"
    assert slugify("") == "project"
    assert sanitize_agent_name(" A!@#$ ") == "A"
    assert sanitize_agent_name("!!!") is None


def test_config_csv_and_bool_parsing(monkeypatch):
    monkeypatch.setenv("HTTP_RBAC_READER_ROLES", "reader, ro ,, read ")
    monkeypatch.setenv("HTTP_RATE_LIMIT_ENABLED", "true")
    clear_settings_cache()
    s = get_settings()
    assert {"reader", "ro", "read"}.issubset(set(s.http.rbac_reader_roles))
    assert s.http.rate_limit_enabled is True


def test_config_credentials_precedence_for_slack_settings(monkeypatch):
    import mcp_agent_mail.config as _config

    # Ensure env vars don't override credentials-derived values
    for key in (
        "SLACK_SYNC_CHANNELS",
        "SLACK_SYNC_THREAD_REPLIES",
        "SLACK_SYNC_REACTIONS",
        "SLACK_USE_BLOCKS",
        "SLACK_INCLUDE_ATTACHMENTS",
        "SLACK_WEBHOOK_URL",
        "SLACKBOX_CHANNELS",
        "SLACKBOX_SENDER_NAME",
        "SLACKBOX_SUBJECT_PREFIX",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(
        _config,
        "_user_credentials",
        {
            "SLACK_SYNC_CHANNELS": "C111, C222",
            "SLACK_SYNC_THREAD_REPLIES": "false",
            "SLACK_SYNC_REACTIONS": "false",
            "SLACK_USE_BLOCKS": "false",
            "SLACK_INCLUDE_ATTACHMENTS": "false",
            "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/test",
            "SLACKBOX_CHANNELS": "CHAN_A, CHAN_B",
            "SLACKBOX_SENDER_NAME": "SlackboxCreds",
            "SLACKBOX_SUBJECT_PREFIX": "[SlackboxCreds]",
        },
    )

    clear_settings_cache()
    s = get_settings()
    assert s.slack.sync_channels == ["C111", "C222"]
    assert s.slack.sync_thread_replies is False
    assert s.slack.sync_reactions is False
    assert s.slack.use_blocks is False
    assert s.slack.include_attachments is False
    assert s.slack.webhook_url == "https://hooks.slack.com/services/test"
    assert s.slack.slackbox_channels == ["CHAN_A", "CHAN_B"]
    assert s.slack.slackbox_sender_name == "SlackboxCreds"
    assert s.slack.slackbox_subject_prefix == "[SlackboxCreds]"


def test_db_engine_reset_and_reinit(isolated_env):
    # Reset and ensure engine can be re-initialized and schema ensured
    reset_database_state()
    # Access engine should lazy-init
    _ = get_engine()
    # Ensure schema executes without error
    asyncio.run(ensure_schema())
