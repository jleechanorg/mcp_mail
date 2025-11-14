#!/usr/bin/env python3
"""Compatibility wrapper that keeps the historical path for the fixed manual tests."""

import asyncio

try:
    from tests.manual.manual_scenarios_fixed import main as _run_manual_tests
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from manual_scenarios_fixed import main as _run_manual_tests  # type: ignore[no-redef]

if __name__ == "__main__":
    asyncio.run(_run_manual_tests())
