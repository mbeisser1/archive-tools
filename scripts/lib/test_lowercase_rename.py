"""Tests for lowercase basename renaming."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lib.lowercase_rename import (
    rename_to_lowercase_file,
    resolve_lowercase_dest,
)


class LowercaseRenameTests(unittest.TestCase):
    def test_already_lowercase_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "photo.jpg"
            path.write_bytes(b"x")
            self.assertIsNone(resolve_lowercase_dest(path))
            status, dest, _msg = rename_to_lowercase_file(path, dry_run=False)
            self.assertEqual(status, "unchanged")
            self.assertIsNone(dest)

    def test_simple_lowercase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "Photo.JPG"
            path.write_bytes(b"x")
            dest = resolve_lowercase_dest(path)
            self.assertIsNotNone(dest)
            assert dest is not None
            self.assertEqual(dest.name, "photo.jpg")
            status, renamed, _msg = rename_to_lowercase_file(path, dry_run=False)
            self.assertEqual(status, "renamed")
            assert renamed is not None
            self.assertTrue(renamed.is_file())
            self.assertFalse(path.exists())

    def test_case_conflict_uses_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lower = root / "4324.jpg"
            upper = root / "4324.JPG"
            lower.write_bytes(b"lower")
            upper.write_bytes(b"upper")
            claimed: set[str] = set()
            dest = resolve_lowercase_dest(upper, claimed=claimed)
            self.assertIsNotNone(dest)
            assert dest is not None
            self.assertEqual(dest.name, "4324_1.jpg")
            status, renamed, _msg = rename_to_lowercase_file(
                upper, dry_run=False, claimed=claimed
            )
            self.assertEqual(status, "renamed")
            assert renamed is not None
            self.assertEqual(renamed.name, "4324_1.jpg")
            self.assertTrue(lower.is_file())

    def test_three_case_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "photo.jpg").write_bytes(b"a")
            photo_jpg = root / "Photo.JPG"
            photo_jpg.write_bytes(b"b")
            photo_upper = root / "PHOTO.JPG"
            photo_upper.write_bytes(b"c")
            claimed: set[str] = set()
            dest1 = resolve_lowercase_dest(photo_jpg, claimed=claimed)
            assert dest1 is not None
            self.assertEqual(dest1.name, "photo_1.jpg")
            claimed.add(dest1.name)
            dest2 = resolve_lowercase_dest(photo_upper, claimed=claimed)
            assert dest2 is not None
            self.assertEqual(dest2.name, "photo_2.jpg")


if __name__ == "__main__":
    unittest.main()
