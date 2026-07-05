from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.providers import FakeModelClient, ModelRequest
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.workspace import WorkspaceContext


class StreamingTests(unittest.TestCase):
    def test_fake_client_streams_chars(self):
        client = FakeModelClient(script=["<final>hello</final>"])
        tokens = list(client.complete_stream(ModelRequest(prompt="hi")))
        self.assertEqual("".join(tokens), "<final>hello</final>")
        self.assertGreater(len(tokens), 1)

    def test_ask_with_stream_callback_invokes_on_final(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "data").mkdir()
            client = FakeModelClient(script=["<final>streamed answer</final>"])
            pico = Pico(
                workspace=WorkspaceContext.build(root),
                model_client=client,
                session_store=SessionStore(root),
                run_store=RunStore(root),
                max_steps=1,
            )
            received = []
            pico.ask("hi", stream_callback=received.append)
            self.assertIn("streamed answer", "".join(received))


if __name__ == "__main__":
    unittest.main()
