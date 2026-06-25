"""Verrouille la résolution du répertoire de données via EVERTRACK_DATA_DIR."""
from __future__ import annotations

import importlib
import os
import unittest
from pathlib import Path


class TestDataDirResolution(unittest.TestCase):
    def test_env_var_overrides_data_dir(self):
        os.environ["EVERTRACK_DATA_DIR"] = "/tmp/evertrack_test_data"
        try:
            from dashboard_reflex.services import data as data_mod
            importlib.reload(data_mod)
            self.assertEqual(data_mod.DATA_DIR, Path("/tmp/evertrack_test_data"))
            self.assertEqual(
                data_mod.INCIDENTS_DB, Path("/tmp/evertrack_test_data") / "incidents.sqlite"
            )
        finally:
            del os.environ["EVERTRACK_DATA_DIR"]

    def test_default_data_dir_when_unset(self):
        os.environ.pop("EVERTRACK_DATA_DIR", None)
        from dashboard_reflex.services import data as data_mod
        importlib.reload(data_mod)
        self.assertTrue(str(data_mod.DATA_DIR).replace("\\", "/").endswith("agents/data"))


if __name__ == "__main__":
    unittest.main()
