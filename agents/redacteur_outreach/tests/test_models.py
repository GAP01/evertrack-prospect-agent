"""Tests unitaires pour redacteur_outreach.models — constantes et version."""

from __future__ import annotations

import unittest

from redacteur_outreach.models import REDACTEUR_VERSION


class TestRedacteurVersion(unittest.TestCase):

    def test_redacteur_version_is_1_1(self) -> None:
        self.assertEqual(REDACTEUR_VERSION, "1.1")


if __name__ == "__main__":
    unittest.main()
