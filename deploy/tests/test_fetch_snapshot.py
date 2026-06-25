"""Tests du fetch de snapshot GitHub Release (sans réseau)."""
from __future__ import annotations

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from deploy import fetch_snapshot


def _make_tar_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class TestFindAssetId(unittest.TestCase):
    def test_picks_matching_asset(self):
        release = {"assets": [
            {"id": 11, "name": "other.txt"},
            {"id": 42, "name": "data-snapshot.tar.gz"},
        ]}
        self.assertEqual(
            fetch_snapshot.find_asset_id(release, "data-snapshot.tar.gz"), 42
        )

    def test_returns_none_when_absent(self):
        self.assertIsNone(
            fetch_snapshot.find_asset_id({"assets": []}, "data-snapshot.tar.gz")
        )


class TestExtractTar(unittest.TestCase):
    def test_extracts_sqlite_files(self):
        data = _make_tar_bytes({"incidents.sqlite": b"abc", "scores.sqlite": b"xyz"})
        with tempfile.TemporaryDirectory() as d:
            fetch_snapshot.extract_tar_bytes(data, Path(d))
            self.assertEqual((Path(d) / "incidents.sqlite").read_bytes(), b"abc")
            self.assertEqual((Path(d) / "scores.sqlite").read_bytes(), b"xyz")

    def test_rejects_path_traversal(self):
        data = _make_tar_bytes({"../evil.sqlite": b"nope"})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                fetch_snapshot.extract_tar_bytes(data, Path(d))


if __name__ == "__main__":
    unittest.main()
