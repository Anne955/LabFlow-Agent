from __future__ import annotations

import os

import pytest

from pico.providers import AnthropicCompatibleModelClient, ModelRequest

pytestmark = pytest.mark.integration


def test_anthropic_returns_text():
    key = os.environ.get("PICO_ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("PICO_ANTHROPIC_API_KEY not set")
    base = os.environ.get("PICO_ANTHROPIC_API_BASE", "https://api.anthropic.com")
    model = os.environ.get("PICO_ANTHROPIC_MODEL", "claude-opus-4-8")
    client = AnthropicCompatibleModelClient(model=model, base_url=base, api_key=key)
    response = client.complete(
        ModelRequest(prompt="Reply with exactly: <final>pong</final>", max_tokens=64)
    )
    assert response.text.strip()
