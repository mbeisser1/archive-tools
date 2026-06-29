"""Tests for EXIF-based rename naming."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from lib.exif_rename import next_available_name


class ExifRenameTests(unittest.TestCase):
    def test_second_59_retries_into_next_minute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dt = datetime(2025, 3, 22, 14, 37, 59)
            taken = root / "2025-03-22__14-37-59-imessage.jpg"
            taken.write_bytes(b"taken")
            claimed: set[str] = set()
            claimed_slots: set[str] = set()
            name = next_available_name(
                "imessage",
                dt,
                "jpg",
                root,
                use_prefix=False,
                claimed=claimed,
                claimed_slots=claimed_slots,
            )
            self.assertEqual(name, "2025-03-22__14-38-00-imessage.jpg")


if __name__ == "__main__":
    unittest.main()
