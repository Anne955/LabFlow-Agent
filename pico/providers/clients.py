from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..errors import (
    ModelProviderError,
    ProviderAuthError,  # noqa: F401  re-exported for provider HTTP-status mapping (Phase 2 Task 2)
    ProviderConnectionError,  # noqa: F401  re-exported for provider HTTP-status mapping (Phase 2 Task 2)
    ProviderRateLimitError,  # noqa: F401  re-exported for provider HTTP-status mapping (Phase 2 Task 2)
    ProviderResponseError,  # noqa: F401  re-exported for provider HTTP-status mapping (Phase 2 Task 2)
)


@dataclass
class ModelRequest:
    prompt: str
    max_tokens: int = 4096
    prompt_cache_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResponse:
    text: str
    raw: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    cache: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    model: str = ""


class ModelClient(Protocol):
    provider: str
    model: str
    supports_prompt_cache: bool
    last_metadata: dict[str, Any]

    def complete(self, request: ModelRequest) -> ModelResponse: ...


class FakeModelClient:
    provider = "fake"
    supports_prompt_cache = False

    def __init__(self, script: list[str] | None = None, model: str = "fake-scripted"):
        self.script = list(script or ["<final>Fake response.</final>"])
        self.model = model
        self.calls: list[ModelRequest] = []
        self.last_metadata: dict[str, Any] = {}

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        text = self.script.pop(0) if self.script else "<final>No more scripted responses.</final>"
        self.last_metadata = {"provider": self.provider, "model": self.model, "fake_call": len(self.calls)}
        return ModelResponse(text=text, raw={"text": text}, provider=self.provider, model=self.model)


class JsonHttpClient:
    provider = "http"
    supports_prompt_cache = False

    def __init__(self, model: str, base_url: str, api_key: str | None = None, timeout: int = 60):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.last_metadata: dict[str, Any] = {}

    def _post_json(self, path: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        url = self.base_url + path
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("content-type", "application/json")
        for key, value in headers.items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ModelProviderError(f"HTTP {exc.code} from {url}: {detail}") from exc
        except OSError as exc:
            raise ModelProviderError(f"request failed for {url}: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelProviderError(f"non-JSON response from {url}: {raw[:500]}") from exc


class OllamaModelClient(JsonHttpClient):
    provider = "ollama"

    def complete(self, request: ModelRequest) -> ModelResponse:
        payload = {
            "model": self.model,
            "prompt": request.prompt,
            "stream": False,
            "raw": False,
            "options": {"num_predict": request.max_tokens},
        }
        raw = self._post_json("/api/generate", payload, {})
        text = str(raw.get("response", ""))
        usage = {
            "input_tokens": raw.get("prompt_eval_count", 0),
            "output_tokens": raw.get("eval_count", 0),
            "total_duration": raw.get("total_duration", 0),
        }
        self.last_metadata = {"provider": self.provider, "model": self.model, **usage}
        return ModelResponse(text=text, raw=raw, usage=usage, provider=self.provider, model=self.model)


class OpenAICompatibleModelClient(JsonHttpClient):
    provider = "openai-compatible"

    def complete(self, request: ModelRequest) -> ModelResponse:
        headers = {}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "max_tokens": request.max_tokens,
        }
        raw = self._post_json("/v1/chat/completions", payload, headers)
        choices = raw.get("choices") or []
        text = ""
        if choices:
            message = choices[0].get("message") or {}
            text = str(message.get("content") or "")
        raw_usage = raw.get("usage") or {}
        usage = {
            "input_tokens": raw_usage.get("prompt_tokens", 0),
            "output_tokens": raw_usage.get("completion_tokens", 0),
            "total_tokens": raw_usage.get("total_tokens", 0),
        }
        self.last_metadata = {"provider": self.provider, "model": self.model, **usage}
        return ModelResponse(text=text, raw=raw, usage=usage, provider=self.provider, model=self.model)


class AnthropicCompatibleModelClient(JsonHttpClient):
    provider = "anthropic-compatible"

    def complete(self, request: ModelRequest) -> ModelResponse:
        headers = {"anthropic-version": "2023-06-01"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        payload = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        raw = self._post_json("/v1/messages", payload, headers)
        text_parts = []
        for block in raw.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
        text = "".join(text_parts)
        raw_usage = raw.get("usage") or {}
        usage = {
            "input_tokens": raw_usage.get("input_tokens", 0),
            "output_tokens": raw_usage.get("output_tokens", 0),
            "cache_creation_input_tokens": raw_usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": raw_usage.get("cache_read_input_tokens", 0),
        }
        cache = {
            "cache_creation_tokens": usage["cache_creation_input_tokens"],
            "cache_read_tokens": usage["cache_read_input_tokens"],
            "cache_hit": bool(usage["cache_read_input_tokens"]),
        }
        self.last_metadata = {"provider": self.provider, "model": self.model, **usage, **cache}
        return ModelResponse(text=text, raw=raw, usage=usage, cache=cache, provider=self.provider, model=self.model)
