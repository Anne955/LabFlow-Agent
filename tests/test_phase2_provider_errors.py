from __future__ import annotations

import unittest

from pico.errors import (
    ModelProviderError,
    ProviderAuthError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderResponseError,
)


class ProviderErrorHierarchyTests(unittest.TestCase):
    def test_all_subclass_model_provider_error(self):
        subclasses = (
            ProviderConnectionError,
            ProviderRateLimitError,
            ProviderAuthError,
            ProviderResponseError,
        )
        for cls in subclasses:
            self.assertTrue(issubclass(cls, ModelProviderError))

    def test_auth_is_not_connection(self):
        self.assertFalse(issubclass(ProviderAuthError, ProviderConnectionError))


if __name__ == "__main__":
    unittest.main()
