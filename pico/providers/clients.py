from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..errors import (
    ModelProviderError,  # noqa: F401  re-exported via pico.providers
    ProviderAuthError,  # noqa: F401  re-exported for provider HTTP-status mapping (Phase 2 Task 2)
    ProviderConnectionError,  # noqa: F401  re-exported for provider HTTP-status mapping (Phase 2 Task 2)
    ProviderRateLimitError,  # noqa: F401  re-exported for provider HTTP-status mapping (Phase 2 Task 2)
    ProviderResponseError,  # noqa: F401  re-exported for provider HTTP-status mapping (Phase 2 Task 2)
)
from .retry import RetryConfig, with_retry


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

    def complete_stream(self, request: ModelRequest): ...


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
        self.last_metadata = {
            "provider": self.provider,
            "model": self.model,
            "fake_call": len(self.calls),
        }
        return ModelResponse(
            text=text, raw={"text": text}, provider=self.provider, model=self.model
        )

    def complete_stream(self, request: ModelRequest):
        self.calls.append(request)
        text = self.script.pop(0) if self.script else "<final>No more scripted responses.</final>"
        self.last_metadata = {
            "provider": self.provider,
            "model": self.model,
            "fake_call": len(self.calls),
        }
        yield from text


class JsonHttpClient:
    provider = "http"
    supports_prompt_cache = False

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        timeout: int = 60,
        retry_config: RetryConfig | None = None,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.retry_config = retry_config or RetryConfig()
        self.retry_events: list[dict] = []
        self.last_metadata: dict[str, Any] = {}

    def _post_json(
        self, path: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
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
            if exc.code == 429:
                raise ProviderRateLimitError(f"HTTP 429 from {url}: {detail}") from exc
            if exc.code in (401, 403):
                raise ProviderAuthError(f"HTTP {exc.code} from {url}: {detail}") from exc
            if 500 <= exc.code < 600:
                raise ProviderConnectionError(f"HTTP {exc.code} from {url}: {detail}") from exc
            raise ProviderResponseError(f"HTTP {exc.code} from {url}: {detail}") from exc
        except (OSError, TimeoutError) as exc:
            raise ProviderConnectionError(f"request failed for {url}: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(f"non-JSON response from {url}: {raw[:500]}") from exc

    def _stream_post(
        self,
        path: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        line_parser,
    ):
        """POST with stream:true and yield parsed text deltas via line_parser(line)->str|None."""
        import urllib.request

        url = self.base_url + path
        payload = dict(payload)
        payload["stream"] = True
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("content-type", "application/json")
        for key, value in headers.items():
            request.add_header(key, value)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                delta = line_parser(line)
                if delta:
                    yield delta


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
        raw = with_retry(
            lambda: self._post_json("/api/generate", payload, {}),
            self.retry_config,
            on_retry=lambda attempt, exc: self.retry_events.append(
                {"attempt": attempt, "error": str(exc)}
            ),
        )
        text = str(raw.get("response", ""))
        usage = {
            "input_tokens": raw.get("prompt_eval_count", 0),
            "output_tokens": raw.get("eval_count", 0),
            "total_duration": raw.get("total_duration", 0),
        }
        self.last_metadata = {"provider": self.provider, "model": self.model, **usage}
        return ModelResponse(
            text=text, raw=raw, usage=usage, provider=self.provider, model=self.model
        )

    def complete_stream(self, request: ModelRequest):
        payload = {
            "model": self.model,
            "prompt": request.prompt,
            "stream": True,
            "raw": False,
            "options": {"num_predict": request.max_tokens},
        }

        def parse(line):
            if not line:
                return None
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                return None
            return str(obj.get("response", "")) or None

        yield from self._stream_post("/api/generate", payload, {}, parse)


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
        raw = with_retry(
            lambda: self._post_json("/v1/chat/completions", payload, headers),
            self.retry_config,
            on_retry=lambda attempt, exc: self.retry_events.append(
                {"attempt": attempt, "error": str(exc)}
            ),
        )
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
        return ModelResponse(
            text=text, raw=raw, usage=usage, provider=self.provider, model=self.model
        )

    def complete_stream(self, request: ModelRequest):
        headers = {}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "max_tokens": request.max_tokens,
            "stream": True,
        }

        def parse(line):
            if not line.startswith("data:"):
                return None
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                return None
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                return None
            choices = obj.get("choices") or []
            if not choices:
                return None
            delta = choices[0].get("delta") or {}
            return str(delta.get("content") or "") or None

        yield from self._stream_post("/v1/chat/completions", payload, headers, parse)


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
        raw = with_retry(
            lambda: self._post_json("/v1/messages", payload, headers),
            self.retry_config,
            on_retry=lambda attempt, exc: self.retry_events.append(
                {"attempt": attempt, "error": str(exc)}
            ),
        )
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
        return ModelResponse(
            text=text, raw=raw, usage=usage, cache=cache, provider=self.provider, model=self.model
        )

    def complete_stream(self, request: ModelRequest):
        headers = {"anthropic-version": "2023-06-01"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        payload = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
            "stream": True,
        }

        def parse(line):
            if not line.startswith("data:"):
                return None
            data = line[len("data:") :].strip()
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                return None
            if obj.get("type") != "content_block_delta":
                return None
            delta = obj.get("delta") or {}
            return str(delta.get("text") or "") or None

        yield from self._stream_post("/v1/messages", payload, headers, parse)
