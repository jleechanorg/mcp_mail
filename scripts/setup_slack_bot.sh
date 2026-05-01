#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# MCP Agent Mail - Slack Bot Setup Script
# =============================================================================
# This script guides you through setting up Slack bidirectional sync.
# Manual steps are required in the Slack UI - the script will prompt you.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

print_step() {
    echo -e "${YELLOW}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "  $1"
}

# =============================================================================
# Step 1: Check Prerequisites
# =============================================================================
print_header "Step 1: Checking Prerequisites"

# Check for required tools
for cmd in curl jq; do
    if ! command -v "$cmd" &> /dev/null; then
        print_error "$cmd is required but not installed"
        exit 1
    fi
done
print_success "Required tools (curl, jq) are available"

# Check if .env exists
ENV_FILE="$PROJECT_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    print_info "Creating .env file..."
    touch "$ENV_FILE"
fi
print_success ".env file exists at $ENV_FILE"

# =============================================================================
# Step 2: Manual Slack App Setup Instructions
# =============================================================================
print_header "Step 2: Create Slack App (One-Click Setup)"

echo -e "${GREEN}We can auto-generate a URL that creates the app with all settings pre-configured!${NC}"
echo ""

# Ask for server URL
read -p "Enter your server's public URL (e.g., https://mcp.example.com): " SERVER_URL

if [[ -n "$SERVER_URL" ]]; then
    # Generate the manifest URL
    MANIFEST_URL=$(python3 "$SCRIPT_DIR/generate_slack_app_url.py" --server-url "$SERVER_URL" 2>/dev/null | grep "^https://api.slack.com" || true)

    if [[ -n "$MANIFEST_URL" ]]; then
        echo ""
        echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
        echo -e "${GREEN}  CLICK THIS URL TO CREATE YOUR SLACK APP:${NC}"
        echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
        echo ""
        echo "$MANIFEST_URL"
        echo ""
        echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
        echo ""
        echo "This URL pre-configures:"
        echo "  ✓ All required bot scopes"
        echo "  ✓ Event subscriptions for message.channels"
        echo "  ✓ Request URL pointing to $SERVER_URL/slack/events"
        echo ""
        echo "After clicking:"
        echo "  1. Select your workspace → Click 'Create'"
        echo "  2. Go to 'Install App' → 'Install to Workspace'"
        echo "  3. Copy 'Bot User OAuth Token' (xoxb-...)"
        echo "  4. Go to 'Basic Information' → Copy 'Signing Secret'"
        echo ""
    else
        echo -e "${YELLOW}Could not generate manifest URL. Using manual setup...${NC}"
    fi
else
    echo -e "${YELLOW}No server URL provided. Using manual setup...${NC}"
fi

echo ""
echo -e "${YELLOW}Manual setup instructions (if needed):${NC}"
echo ""
echo "  1. Go to: https://api.slack.com/apps"
echo "  2. Click 'Create New App' → 'From manifest'"
echo "  3. Select workspace, paste manifest from: $PROJECT_ROOT/examples/slack_app_manifest.json"
echo "  4. Update the request_url to your server's /slack/events endpoint"
echo "  5. Create and install the app"
echo "  6. Copy Bot Token and Signing Secret"
echo ""

read -p "Press Enter when you've completed the Slack App setup..."

# =============================================================================
# Step 3: Configure Credentials
# =============================================================================
print_header "Step 3: Configure Credentials"

# Create ~/.mcp_mail directory if it doesn't exist
CREDS_DIR="$HOME/.mcp_mail"
CREDS_FILE="$CREDS_DIR/credentials.json"
mkdir -p "$CREDS_DIR"
chmod 700 "$CREDS_DIR"

# Initialize credentials file if it doesn't exist
if [[ ! -f "$CREDS_FILE" ]]; then
    echo '{}' > "$CREDS_FILE"
    chmod 600 "$CREDS_FILE"
fi

print_info "Credentials will be saved to: $CREDS_FILE"
echo ""

# Function to get current value from credentials.json
get_cred() {
    local key="$1"
    python3 -c "import json; d=json.load(open('$CREDS_FILE')); print(d.get('$key', ''))" 2>/dev/null || echo ""
}

# Function to set value in credentials.json
set_cred() {
    local key="$1"
    local value="$2"
    python3 -c "
import json
with open('$CREDS_FILE', 'r') as f:
    d = json.load(f)
d['$key'] = '$value'
with open('$CREDS_FILE', 'w') as f:
    json.dump(d, f, indent=2)
"
}

# Function to prompt for credential
configure_cred() {
    local var_name="$1"
    local description="$2"
    local default_value="${3:-}"
    local is_secret="${4:-false}"

    # Check if already set
    current_value=$(get_cred "$var_name")

    if [[ -n "$current_value" ]]; then
        if [[ "$is_secret" == "true" ]]; then
            print_info "$var_name is already set (****hidden****)"
        else
            print_info "$var_name is already set: $current_value"
        fi
        read -p "  Keep existing value? [Y/n]: " keep
        if [[ "${keep:-Y}" =~ ^[Yy]?$ ]]; then
            return
        fi
    fi

    # Prompt for value
    if [[ "$is_secret" == "true" ]]; then
        read -sp "  Enter $var_name ($description): " value
        echo ""
    else
        if [[ -n "$default_value" ]]; then
            read -p "  Enter $var_name ($description) [$default_value]: " value
            value="${value:-$default_value}"
        else
            read -p "  Enter $var_name ($description): " value
        fi
    fi

    # Save to credentials file
    set_cred "$var_name" "$value"
    print_success "$var_name configured"
}

print_step "Configuring Slack credentials..."
echo ""

configure_cred "SLACK_ENABLED" "Enable Slack integration" "true"
configure_cred "SLACK_BOT_TOKEN" "Bot OAuth Token (xoxb-...)" "" "true"
configure_cred "SLACK_SIGNING_SECRET" "Signing Secret" "" "true"
configure_cred "SLACK_SYNC_ENABLED" "Enable bidirectional sync" "true"
configure_cred "SLACK_DEFAULT_CHANNEL" "Default channel ID (e.g., C1234567890)"
configure_cred "SLACK_SYNC_PROJECT_NAME" "MCP project for Slack messages" "slack-sync"
configure_cred "SLACK_NOTIFY_ON_MESSAGE" "Notify Slack on new MCP messages" "true"

echo ""
print_success "Credentials saved to $CREDS_FILE"
print_info "This file is user-local and not part of any git repo."

# =============================================================================
# Step 4: Validate Configuration
# =============================================================================
print_header "Step 4: Validating Configuration"

# Check required vars from credentials file
REQUIRED_VARS=(
    "SLACK_ENABLED"
    "SLACK_BOT_TOKEN"
    "SLACK_SIGNING_SECRET"
    "SLACK_DEFAULT_CHANNEL"
)

all_valid=true
for var in "${REQUIRED_VARS[@]}"; do
    value=$(get_cred "$var")
    if [[ -z "$value" ]]; then
        print_error "$var is not set"
        all_valid=false
    else
        print_success "$var is configured"
    fi
done

if [[ "$all_valid" != "true" ]]; then
    print_error "Some required variables are missing. Please run this script again."
    exit 1
fi

# Export for testing
SLACK_BOT_TOKEN=$(get_cred "SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET=$(get_cred "SLACK_SIGNING_SECRET")
SLACK_DEFAULT_CHANNEL=$(get_cred "SLACK_DEFAULT_CHANNEL")

# =============================================================================
# Step 5: Test Slack Connection
# =============================================================================
print_header "Step 5: Testing Slack Connection"

print_step "Testing bot token with auth.test API..."

AUTH_RESPONSE=$(curl -s -X POST "https://slack.com/api/auth.test" \
    -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
    -H "Content-Type: application/json")

if echo "$AUTH_RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    TEAM_NAME=$(echo "$AUTH_RESPONSE" | jq -r '.team')
    BOT_USER=$(echo "$AUTH_RESPONSE" | jq -r '.user')
    print_success "Connected to Slack workspace: $TEAM_NAME"
    print_success "Bot user: $BOT_USER"
else
    ERROR=$(echo "$AUTH_RESPONSE" | jq -r '.error // "unknown error"')
    print_error "Failed to connect to Slack: $ERROR"
    echo ""
    echo "Common issues:"
    echo "  • Invalid bot token - check OAuth & Permissions in Slack App settings"
    echo "  • Token not installed - reinstall the app to your workspace"
    exit 1
fi

# Test channel access
print_step "Testing channel access for $SLACK_DEFAULT_CHANNEL..."

CHANNEL_RESPONSE=$(curl -s -X GET "https://slack.com/api/conversations.info?channel=$SLACK_DEFAULT_CHANNEL" \
    -H "Authorization: Bearer $SLACK_BOT_TOKEN")

if echo "$CHANNEL_RESPONSE" | jq -e '.ok == true' > /dev/null 2>&1; then
    CHANNEL_NAME=$(echo "$CHANNEL_RESPONSE" | jq -r '.channel.name')
    print_success "Channel accessible: #$CHANNEL_NAME"
else
    ERROR=$(echo "$CHANNEL_RESPONSE" | jq -r '.error // "unknown error"')
    print_error "Cannot access channel: $ERROR"
    echo ""
    echo "Common issues:"
    echo "  • Bot not in channel - invite the bot with /invite @MCP Agent Mail"
    echo "  • Invalid channel ID - use the channel ID (C...), not the name"
    echo "  • Missing channels:read scope"
fi

# =============================================================================
# Step 6: Summary & Next Steps
# =============================================================================
print_header "Setup Complete!"

echo "Your Slack integration is configured. Here's what to do next:"
echo ""
echo "  ${GREEN}1. Start/restart the MCP Agent Mail server:${NC}"
echo "     cd $PROJECT_ROOT"
echo "     ./scripts/run_server_with_token.sh"
echo ""
echo "  ${GREEN}2. Verify Event Subscriptions URL:${NC}"
echo "     Make sure your server is accessible at the URL you configured"
echo "     in Slack Event Subscriptions. Slack will verify the endpoint."
echo ""
echo "  ${GREEN}3. Test the integration:${NC}"
echo "     • Post a message in the configured Slack channel"
echo "     • Check the MCP Agent Mail server logs for the incoming event"
echo "     • Use the MCP tools to reply and see it appear in Slack"
echo ""
echo "  ${YELLOW}Credentials file:${NC} $CREDS_FILE"
echo "  ${YELLOW}Documentation:${NC} $PROJECT_ROOT/docs/slack_bot_sync_design.md"
echo ""
echo "  ${BLUE}Credentials configured:${NC}"
python3 -c "
import json
with open('$CREDS_FILE') as f:
    d = json.load(f)
for k, v in d.items():
    if 'TOKEN' in k or 'SECRET' in k:
        print(f'    {k}=****hidden****')
    else:
        print(f'    {k}={v}')
" 2>/dev/null || echo "    (unable to read credentials file)"
echo ""
