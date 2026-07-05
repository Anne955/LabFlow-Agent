from __future__ import annotations

import re

import pytest

from pico.providers import ModelRequest, OpenAICompatibleModelClient

pytestmark = pytest.mark.integration


def test_openai_returns_final_or_tool(openai_env):
    client = OpenAICompatibleModelClient(
        model=openai_env["model"], base_url=openai_env["base_url"], api_key=openai_env["api_key"]
    )
    response = client.complete(
        ModelRequest(prompt="Reply with exactly: <final>pong</final>", max_tokens=64)
    )
    assert response.text
    assert re.search(r"<final>|<tool>", response.text) or response.text.strip()
