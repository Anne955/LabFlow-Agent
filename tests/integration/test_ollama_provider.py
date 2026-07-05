from __future__ import annotations

import os

import pytest

from pico.providers import ModelRequest, OllamaModelClient

pytestmark = pytest.mark.integration


def test_ollama_returns_text():
    host = os.environ.get("PICO_OLLAMA_HOST")
    if not host:
        pytest.skip("PICO_OLLAMA_HOST not set")
    model = os.environ.get("PICO_OLLAMA_MODEL", "qwen2.5-coder")
    client = OllamaModelClient(model=model, base_url=host)
    response = client.complete(
        ModelRequest(prompt="Reply with exactly: <final>pong</final>", max_tokens=64)
    )
    assert response.text.strip()
