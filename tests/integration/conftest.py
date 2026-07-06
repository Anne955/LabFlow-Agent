from __future__ import annotations

import os
from pathlib import Path

import pytest

# Load .env from the repo root so integration tests pick up provider credentials
# without requiring them to be exported into the shell environment.
from pico.config import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2])


def pytest_collection_modifyitems(config, items):
    if os.environ.get("PICO_RUN_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="set PICO_RUN_INTEGRATION=1 (and provider credentials) to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def openai_env():
    key = os.environ.get("PICO_OPENAI_API_KEY")
    base = os.environ.get("PICO_OPENAI_API_BASE", "https://api.openai.com")
    pytest.importorskip("urllib.request")
    if not key:
        pytest.skip("PICO_OPENAI_API_KEY not set")
    return {
        "base_url": base,
        "api_key": key,
        "model": os.environ.get("PICO_OPENAI_MODEL", "gpt-4.1"),
    }
