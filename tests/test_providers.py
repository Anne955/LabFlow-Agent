from __future__ import annotations

import unittest

from pico.providers import (
    AnthropicCompatibleModelClient,
    FakeModelClient,
    ModelRequest,
    OllamaModelClient,
    OpenAICompatibleModelClient,
)


class ProviderTests(unittest.TestCase):
    def test_fake_model_client_returns_scripted_responses(self):
        client = FakeModelClient(["<final>a</final>", "<final>b</final>"])
        self.assertEqual(client.complete(ModelRequest("one")).text, "<final>a</final>")
        self.assertEqual(client.complete(ModelRequest("two")).text, "<final>b</final>")
        self.assertEqual(len(client.calls), 2)

    def test_ollama_response_parsing(self):
        client = OllamaModelClient("m", "http://host")
        client._post_json = lambda path, payload, headers: {  # type: ignore[method-assign]
            "response": "hello",
            "prompt_eval_count": 2,
            "eval_count": 3,
        }
        response = client.complete(ModelRequest("prompt"))
        self.assertEqual(response.text, "hello")
        self.assertEqual(response.usage["input_tokens"], 2)
        self.assertEqual(response.usage["output_tokens"], 3)

    def test_openai_compatible_response_parsing(self):
        client = OpenAICompatibleModelClient("m", "http://host", "key")
        client._post_json = lambda path, payload, headers: {  # type: ignore[method-assign]
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        }
        response = client.complete(ModelRequest("prompt"))
        self.assertEqual(response.text, "hello")
        self.assertEqual(response.usage["total_tokens"], 5)

    def test_anthropic_compatible_response_parsing(self):
        client = AnthropicCompatibleModelClient("claude-opus-4-8", "http://host", "key")
        client._post_json = lambda path, payload, headers: {  # type: ignore[method-assign]
            "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "hello"}],
            "usage": {"input_tokens": 2, "output_tokens": 3, "cache_read_input_tokens": 4},
        }
        response = client.complete(ModelRequest("prompt"))
        self.assertEqual(response.text, "hello")
        self.assertTrue(response.cache["cache_hit"])
        self.assertEqual(response.usage["input_tokens"], 2)


if __name__ == "__main__":
    unittest.main()
