"""Top-level package for the MCP Agent Mail server."""

from __future__ import annotations

import importlib
import warnings
from typing import Any, cast

# Suppress the DeprecationWarning from FastMCP's use of asyncio.iscoroutinefunction
# on Python 3.12+. Scoped to this specific warning rather than monkey-patching asyncio.
warnings.filterwarnings(
    "ignore",
    message=r".*asyncio\.iscoroutinefunction.*",
    category=DeprecationWarning,
)

_app_module = cast(Any, importlib.import_module(".app", __name__))
build_mcp_server = _app_module.build_mcp_server

__all__ = ["build_mcp_server"]
