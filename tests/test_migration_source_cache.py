from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from rag_ime.db.migration_runner import (
    clear_migration_source_cache,
    load_migrations,
)


class MigrationSourceCacheTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_migration_source_cache()

    def test_default_migration_sources_are_read_once_per_process_generation(self) -> None:
        clear_migration_source_cache()
        original_read_text = Path.read_text
        reads: list[Path] = []

        def counted_read_text(path: Path, *args: object, **kwargs: object) -> str:
            reads.append(path)
            return original_read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", autospec=True, side_effect=counted_read_text):
            first = load_migrations()
            reads_after_first = len(reads)
            second = load_migrations()

        self.assertGreater(reads_after_first, 0)
        self.assertIs(first, second)
        self.assertEqual(len(reads), reads_after_first)

        clear_migration_source_cache()
        with patch.object(Path, "read_text", autospec=True, side_effect=counted_read_text):
            third = load_migrations()

        self.assertEqual(third, first)
        self.assertEqual(len(reads), reads_after_first * 2)


if __name__ == "__main__":
    unittest.main()
