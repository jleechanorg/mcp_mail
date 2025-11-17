#!/usr/bin/env bash
# MCP Common Functions
# This file contains shared functions for MCP server installation and configuration

# ... (other functions would be here) ...

# Install beads MCP server
# This function sets up the beads-mcp server configuration
install_beads_mcp() {
    local BD_FOUND=0
    local BD_PATH=""
    
    # Check if bd CLI exists in PATH
    if command -v bd >/dev/null 2>&1; then
        BD_FOUND=1
        BD_PATH=$(command -v bd)
    # Check common installation location
    elif [[ -f "$HOME/go/bin/bd" ]]; then
        BD_FOUND=1
        BD_PATH="$HOME/go/bin/bd"
    fi
    
    # Only set BEADS_PATH if bd was actually found
    if [[ $BD_FOUND -eq 1 ]]; then
        export BEADS_PATH="$BD_PATH"
        echo "Found beads CLI at: $BEADS_PATH"
    else
        echo "Warning: beads CLI (bd) not found. Skipping BEADS_PATH configuration."
        return 1
    fi
    
    # ... rest of installation logic ...
}

