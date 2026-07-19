"""Fixtures for Lidl Weekly Offers tests."""

import sys
import types

import pytest
import pytest_socket

# Mock fcntl module for Windows compatibility during Home Assistant test initialization
if sys.platform == "win32":
    fcntl = types.ModuleType("fcntl")
    fcntl.fcntl = lambda *args, **kwargs: 0  # type: ignore[attr-defined]
    fcntl.ioctl = lambda *args, **kwargs: 0  # type: ignore[attr-defined]
    sys.modules["fcntl"] = fcntl

# Bypass pytest-socket unconditionally to allow loopback sockets/socketpairs on all platforms
pytest_socket.disable_socket = lambda *args, **kwargs: None
pytest_socket.enable_socket()


@pytest.fixture(autouse=True)
async def enable_custom_integrations(hass):
    """Enable custom integrations to be loaded in tests."""
    hass.data.pop("custom_components", None)
