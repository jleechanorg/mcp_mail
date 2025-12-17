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
print_header "Step 2: Create Slack App (Manual Steps Required)"

echo -e "${YELLOW}You need to create a Slack App manually. Follow these steps:${NC}"
echo ""
echo "  1. Go to: https://api.slack.com/apps"
echo ""
echo "  2. Click 'Create New App' → 'From scratch'"
echo "     - App Name: MCP Agent Mail"
echo "     - Workspace: Select your workspace"
echo ""
echo "  3. Go to 'OAuth & Permissions' → 'Scopes' → 'Bot Token Scopes'"
echo "     Add these scopes:"
echo "     ${GREEN}• chat:write${NC}          - Post messages"
echo "     ${GREEN}• chat:write.public${NC}   - Post to public channels"
echo "     ${GREEN}• channels:history${NC}    - Read message history"
echo "     ${GREEN}• channels:read${NC}       - List channels"
echo "     ${GREEN}• groups:history${NC}      - Read private channel history (optional)"
echo ""
echo "  4. Go to 'Event Subscriptions'"
echo "     - Enable Events: ON"
echo "     - Request URL: ${BLUE}https://YOUR_SERVER/slack/events${NC}"
echo "       (Server must be running and publicly accessible)"
echo "     - Subscribe to bot events:"
echo "       ${GREEN}• message.channels${NC}  - Messages in public channels"
echo "       ${GREEN}• message.groups${NC}    - Messages in private channels (optional)"
echo ""
echo "  5. Install the app to your workspace:"
echo "     Go to 'Install App' → 'Install to Workspace'"
echo ""
echo "  6. Copy these values:"
echo "     - Bot Token (xoxb-...): OAuth & Permissions → Bot User OAuth Token"
echo "     - Signing Secret: Basic Information → Signing Secret"
echo ""

read -p "Press Enter when you've completed the Slack App setup..."

# =============================================================================
# Step 3: Configure Environment Variables
# =============================================================================
print_header "Step 3: Configure Environment Variables"

# Function to prompt for env var
configure_env() {
    local var_name="$1"
    local description="$2"
    local default_value="${3:-}"
    local is_secret="${4:-false}"

    # Check if already set
    current_value=$(grep "^${var_name}=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || echo "")

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

    # Update .env file
    if grep -q "^${var_name}=" "$ENV_FILE" 2>/dev/null; then
        # Update existing
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s|^${var_name}=.*|${var_name}=${value}|" "$ENV_FILE"
        else
            sed -i "s|^${var_name}=.*|${var_name}=${value}|" "$ENV_FILE"
        fi
    else
        # Add new
        echo "${var_name}=${value}" >> "$ENV_FILE"
    fi

    print_success "$var_name configured"
}

print_step "Configuring Slack settings..."
echo ""

configure_env "SLACK_ENABLED" "Enable Slack integration" "true"
configure_env "SLACK_BOT_TOKEN" "Bot OAuth Token (xoxb-...)" "" "true"
configure_env "SLACK_SIGNING_SECRET" "Signing Secret" "" "true"
configure_env "SLACK_SYNC_ENABLED" "Enable bidirectional sync" "true"
configure_env "SLACK_DEFAULT_CHANNEL" "Default channel ID (e.g., C1234567890)"
configure_env "SLACK_SYNC_PROJECT_NAME" "MCP project for Slack messages" "slack-sync"
configure_env "SLACK_NOTIFY_ON_MESSAGE" "Notify Slack on new MCP messages" "true"

echo ""
print_success "Environment variables configured in $ENV_FILE"

# =============================================================================
# Step 4: Validate Configuration
# =============================================================================
print_header "Step 4: Validating Configuration"

# Load env file
set -a
source "$ENV_FILE"
set +a

# Check required vars
REQUIRED_VARS=(
    "SLACK_ENABLED"
    "SLACK_BOT_TOKEN"
    "SLACK_SIGNING_SECRET"
    "SLACK_DEFAULT_CHANNEL"
)

all_valid=true
for var in "${REQUIRED_VARS[@]}"; do
    if [[ -z "${!var:-}" ]]; then
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
echo "  ${YELLOW}Configuration file:${NC} $ENV_FILE"
echo "  ${YELLOW}Documentation:${NC} $PROJECT_ROOT/docs/slack_bot_sync_design.md"
echo ""
echo "  ${BLUE}Environment variables configured:${NC}"
grep "^SLACK_" "$ENV_FILE" | while read -r line; do
    var_name=$(echo "$line" | cut -d'=' -f1)
    if [[ "$var_name" == "SLACK_BOT_TOKEN" ]] || [[ "$var_name" == "SLACK_SIGNING_SECRET" ]]; then
        echo "    $var_name=****hidden****"
    else
        echo "    $line"
    fi
done
echo ""
