#!/usr/bin/env python3
"""Compatibility wrapper that keeps the historical path for the fixed manual tests."""

import asyncio

from .manual_scenarios_fixed import main as _run_manual_tests

if __name__ == "__main__":
    asyncio.run(_run_manual_tests())
