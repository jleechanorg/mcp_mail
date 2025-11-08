# PyPI Package Cleanup

## Deprecated Packages

Two legacy artifacts still appear on PyPI and should be cleaned up to avoid confusion:

- `mcp-agent-mail` (original package name)
- `ai-universe-mail` version `0.1.0` (intermediate rename)

### To Remove the Old Package (mcp-agent-mail)

PyPI doesn't provide a public API for deleting or yanking packages. You must use the web interface:

#### Option 1: Delete Project (Recommended for complete removal)

1. Log in to <https://pypi.org>
2. Navigate to <https://pypi.org/project/mcp-agent-mail/>
3. Click "Manage" in the sidebar
4. Click "Settings"
5. Scroll to the bottom and click "Delete project"
6. Confirm by typing the project name: `mcp-agent-mail`

**Note**: Deletion is only available if the package has minimal downloads and no dependents.

#### Option 2: Yank Release (If deletion unavailable)

1. Log in to <https://pypi.org>
2. Navigate to <https://pypi.org/project/mcp-agent-mail/>
3. Click on version "0.1.0"
4. Click "Options" dropdown
5. Select "Yank version 0.1.0"
6. Add yank reason: "Package superseded by mcp_mail"

**Effect**: Prevents new installations but keeps the package visible with a warning.

---

### To Yank ai-universe-mail 0.1.0

Version 0.1.0 was an intermediate release before the project settled on the `mcp_mail` name. Yank it so new installations move to the canonical package:

1. Log in to <https://pypi.org>
2. Navigate to <https://pypi.org/project/ai-universe-mail/>
3. Click on version "0.1.0"
4. Click "Options" dropdown
5. Select "Yank version 0.1.0"
6. Add yank reason: "Package superseded by mcp_mail"

**Important**: Do NOT yank newer versions that might exist under `ai-universe-mail` if they are still in use—only version 0.1.0 needs to be removed.

---

## Current Package: mcp_mail (Python 3.11+)

**Install**: `uv pip install mcp_mail`

**PyPI URL**: <https://pypi.org/project/mcp-mail/>

The server is tested on Python 3.11, 3.12, and 3.13 and should be installed via uv (per project policy).
