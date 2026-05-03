#!/usr/bin/env python3
"""Generate a Slack App creation URL with pre-filled manifest.

This creates a URL that opens Slack's app creation page with all
scopes, event subscriptions, and settings pre-configured. The user
just needs to:
1. Click the URL
2. Select their workspace
3. Click "Create"
4. Click "Install to Workspace"
5. Copy the Bot Token and Signing Secret

Usage:
    python scripts/generate_slack_app_url.py [--server-url URL]

    If --server-url is provided, it replaces YOUR_SERVER_URL in the manifest.
"""

import argparse
import json
import sys
import urllib.parse

MANIFEST = {
    "display_information": {
        "name": "MCP Agent Mail",
        "description": "Bidirectional sync between Slack and MCP Agent Mail for AI agent coordination",
        "background_color": "#4A154B",
    },
    "features": {
        "bot_user": {
            "display_name": "MCP Agent Mail",
            "always_online": True,
        },
        "app_home": {
            "home_tab_enabled": False,
            "messages_tab_enabled": True,
            "messages_tab_read_only_enabled": False,
        },
    },
    "oauth_config": {
        "scopes": {
            "bot": [
                "chat:write",
                "chat:write.public",
                "channels:history",
                "channels:read",
                "groups:history",
                "groups:read",
                "im:history",
                "im:read",
                "mpim:history",
                "mpim:read",
                "users:read",
            ]
        }
    },
    "settings": {
        "event_subscriptions": {
            "request_url": "https://YOUR_SERVER_URL/slack/events",
            "bot_events": [
                "message.channels",
                "message.groups",
                "message.im",
                "message.mpim",
            ],
        },
        "interactivity": {"is_enabled": False},
        "org_deploy_enabled": False,
        "socket_mode_enabled": False,
        "token_rotation_enabled": False,
    },
}


def generate_slack_app_url(server_url: str | None = None) -> str:
    """Generate Slack app creation URL with manifest.

    Args:
        server_url: Optional server URL to replace YOUR_SERVER_URL placeholder.
                   If not provided, user must update it manually in Slack.

    Returns:
        URL that opens Slack app creation with pre-filled manifest.
    """
    manifest = MANIFEST.copy()

    if server_url:
        # Deep copy and update the request URL
        manifest = json.loads(json.dumps(MANIFEST))
        manifest["settings"]["event_subscriptions"]["request_url"] = f"{server_url.rstrip('/')}/slack/events"

    # URL-encode the manifest JSON
    manifest_json = json.dumps(manifest, separators=(",", ":"))
    encoded_manifest = urllib.parse.quote(manifest_json)

    return f"https://api.slack.com/apps?new_app=1&manifest_json={encoded_manifest}"


def main():
    parser = argparse.ArgumentParser(description="Generate Slack App creation URL with pre-filled manifest")
    parser.add_argument(
        "--server-url",
        help="Your MCP Agent Mail server URL (e.g., https://mcp.example.com)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the URL in the default browser",
    )
    args = parser.parse_args()

    url = generate_slack_app_url(args.server_url)

    print("\n" + "=" * 70)
    print("  SLACK APP CREATION URL")
    print("=" * 70)
    print()

    if not args.server_url:
        print("⚠️  No --server-url provided.")
        print("   After creating the app, update the Event Subscriptions URL in Slack.")
        print()

    print("Click this URL to create your Slack app with all settings pre-configured:")
    print()
    print(url)
    print()
    print("=" * 70)
    print()
    print("After clicking the URL:")
    print("  1. Select your Slack workspace")
    print("  2. Click 'Create'")
    print("  3. Go to 'Install App' → 'Install to Workspace'")
    print("  4. Copy the 'Bot User OAuth Token' (xoxb-...)")
    print("  5. Go to 'Basic Information' → copy 'Signing Secret'")
    print("  6. Add both to your .env file:")
    print("     SLACK_BOT_TOKEN=xoxb-...")
    print("     SLACK_SIGNING_SECRET=...")
    print()

    if args.open:
        import webbrowser

        webbrowser.open(url)
        print("✓ Opened URL in browser")

    return 0


if __name__ == "__main__":
    sys.exit(main())
