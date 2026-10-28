"""
conftest.py — shared pytest fixtures and asyncio event-loop configuration.
"""
import pytest
import asyncio


# ── Use pytest-asyncio in auto mode so every async test works without decoration ──
# Requires: pip install pytest-asyncio
pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(scope="session")
def event_loop():
    """Single event loop shared across the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
