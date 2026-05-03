from __future__ import annotations

from mcp_agent_mail.slack_integration import format_mcp_message_for_slack, mirror_message_to_slack


def test_mirror_message_to_slack_posts_when_enabled(monkeypatch):
    captured = {}

    def fake_post(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return "ok"

    monkeypatch.setenv("SLACK_MCP_MAIL_WEBHOOK_URL", "https://hooks.slack.com/services/test")
    monkeypatch.setenv("SLACK_MIRROR_ENABLED", "1")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "")
    monkeypatch.setenv("SLACK_LIVE_TEST", "0")

    monkeypatch.setattr("mcp_agent_mail.slack_integration._post_webhook", fake_post)

    frontmatter = {
        "project": "proj",
        "subject": "subj",
        "thread_id": "tid",
        "from": "SenderAgent",
        "to": ["RecipientAgent"],
        "cc": ["CCAgent"],
        "bcc": ["BCCAgent"],
    }
    body = "hello body"
    resp = mirror_message_to_slack(frontmatter, body)

    assert resp == "ok"
    assert captured["url"] == "https://hooks.slack.com/services/test"
    text = captured["payload"]["text"]
    assert "proj" in text
    assert "subj" in text
    assert "tid" in text
    assert "hello body" in text
    assert "*From:* SenderAgent" in text
    assert "*To:* RecipientAgent, CCAgent, BCCAgent" in text


def test_mirror_message_to_slack_handles_missing_names(monkeypatch):
    captured = {}

    def fake_post(url, payload):
        captured["payload"] = payload
        return "ok"

    monkeypatch.setenv("SLACK_MCP_MAIL_WEBHOOK_URL", "https://hooks.slack.com/services/test")
    monkeypatch.setenv("SLACK_MIRROR_ENABLED", "1")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "")

    monkeypatch.setattr("mcp_agent_mail.slack_integration._post_webhook", fake_post)

    frontmatter = {"project": "proj", "subject": "subj"}
    body = "hello body"

    resp = mirror_message_to_slack(frontmatter, body)

    assert resp == "ok"
    text = captured["payload"]["text"]
    assert "proj" in text
    assert "subj" in text
    assert "*From:*" not in text
    assert "*To:*" not in text


def test_mirror_message_to_slack_skips_when_disabled(monkeypatch):
    monkeypatch.delenv("SLACK_MCP_MAIL_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("SLACK_MIRROR_ENABLED", "0")

    frontmatter = {"project": "proj", "subject": "subj"}
    body = "hello body"
    resp = mirror_message_to_slack(frontmatter, body)

    assert resp is None


def test_format_mcp_message_for_slack_includes_full_agent_details():
    recipients = [f"Agent {i}" for i in range(1, 8)]

    text, blocks = format_mcp_message_for_slack(
        subject="Demo Subject",
        body_md="Body content",
        sender_name="Primary Sender",
        recipients=recipients,
        message_id="1234567890abcdef",
        importance="high",
    )

    assert "Primary Sender" in text
    assert "+2 more" in text  # fallback text reflects truncated recipients

    assert blocks is not None
    fields = {field["text"] for field in blocks[1]["fields"]}

    sender_field = next(text for text in fields if text.startswith("*From:*"))
    recipient_field = next(text for text in fields if text.startswith("*To:*"))

    assert "*Primary Sender*" in sender_field
    # Should include displayed recipients and a "+N more" indicator
    assert all(name in recipient_field for name in recipients[:5])
    assert "+2 more" in recipient_field
    assert recipient_field.count("•") == 6  # 5 recipients + "+2 more"
