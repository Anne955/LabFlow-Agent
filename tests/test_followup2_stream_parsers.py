from __future__ import annotations

import unittest

from pico.providers.clients import (
    parse_anthropic_stream_line,
    parse_ollama_stream_line,
    parse_openai_stream_line,
)

# Each fixture is a (line, expected) tuple. ``None`` expected means the parser
# must skip the line (return None) without raising.


class OllamaParserTests(unittest.TestCase):
    """NDJSON: each line is a JSON object; yield ``obj["response"]``."""

    def test_cases(self):
        cases = [
            # normal delta
            ('{"response":"hel"}', "hel"),
            ('{"response":" world"}', " world"),
            # empty / whitespace lines
            ("", None),
            ("   ", None),
            ("\t", None),
            # malformed / non-JSON
            ("not json", None),
            ('{"response":', None),
            ("{bad", None),
            # parser-specific edges
            ('{"response":""}', None),  # empty delta -> None
            ('{"done":true}', None),  # no response key -> None
            ('{"response":"hel","done":true}', "hel"),  # delta + done flag
        ]
        for line, expected in cases:
            with self.subTest(line=line):
                self.assertEqual(parse_ollama_stream_line(line), expected)


class OpenAIParserTests(unittest.TestCase):
    """SSE: ``data:`` lines; ``[DONE]`` sentinel; yield ``choices[0].delta.content``."""

    def test_cases(self):
        cases = [
            # normal delta
            ('data: {"choices":[{"delta":{"content":"hi"}}]}', "hi"),
            ('data: {"choices":[{"delta":{"content":" there"}}]}', " there"),
            # empty / whitespace lines
            ("", None),
            ("   ", None),
            ("\t\n", None),
            # malformed data payload (after ``data:``)
            ("data: {bad json", None),
            ("data: ", None),  # data: with empty payload -> JSONDecodeError -> None
            # parser-specific edges
            ("data: [DONE]", None),  # sentinel
            ("data: {}", None),  # no choices
            ('data: {"choices":[]}', None),  # empty choices list
            # lines NOT starting with ``data:``
            (": comment", None),
            ("event: ping", None),
            ("retry: 5000", None),
        ]
        for line, expected in cases:
            with self.subTest(line=line):
                self.assertEqual(parse_openai_stream_line(line), expected)


class AnthropicParserTests(unittest.TestCase):
    """SSE: ``data:`` lines; only ``type == content_block_delta`` yields ``delta.text``."""

    def test_cases(self):
        cases = [
            # normal delta
            ('data: {"type":"content_block_delta","delta":{"text":"x"}}', "x"),
            ('data: {"type":"content_block_delta","delta":{"text":"y"}}', "y"),
            # empty / whitespace lines
            ("", None),
            ("   ", None),
            ("\t", None),
            # malformed data payload
            ("data: {bad json", None),
            ("data: ", None),
            # parser-specific edges
            ('data: {"type":"message_start"}', None),  # non-delta event
            ('data: {"type":"message_stop"}', None),
            ('data: {"type":"content_block_start"}', None),
            # delta event but no ``text`` key (e.g. tool-use input_json_delta)
            (
                'data: {"type":"content_block_delta","delta":{"type":"input_json_delta"}}',
                None,
            ),
            # empty text -> None
            ('data: {"type":"content_block_delta","delta":{"text":""}}', None),
            # non-data line
            ("event: ping", None),
            (": comment", None),
        ]
        for line, expected in cases:
            with self.subTest(line=line):
                self.assertEqual(parse_anthropic_stream_line(line), expected)


if __name__ == "__main__":
    unittest.main()
