from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class RimeCandidateIndexTests(unittest.TestCase):
    def test_index_builder_includes_wanxiang_english_candidates(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-index-builder-") as tmp:
            tmp_path = Path(tmp)
            dict_dir = tmp_path / "rime"
            (dict_dir / "dicts").mkdir(parents=True)
            (dict_dir / "wanxiang.dict.yaml").write_text(
                textwrap.dedent(
                    """\
                    # Rime dictionary
                    ---
                    name: wanxiang
                    import_tables:
                      - dicts/base
                    ...
                    """
                ),
                encoding="utf-8",
            )
            (dict_dir / "dicts" / "base.dict.yaml").write_text(
                textwrap.dedent(
                    """\
                    # encoding: utf-8
                    ---
                    name: base
                    ...
                    你\tni\t2000
                    世界\tshi jie\t1500
                    设计\tshe ji\t1300
                    """
                ),
                encoding="utf-8",
            )
            (dict_dir / "wanxiang_english.dict.yaml").write_text(
                textwrap.dedent(
                    """\
                    # Rime dictionary
                    ---
                    name: wanxiang_english
                    import_tables:
                      - dicts/en
                    ...
                    """
                ),
                encoding="utf-8",
            )
            (dict_dir / "dicts" / "en.dict.yaml").write_text(
                textwrap.dedent(
                    """\
                    # encoding: utf-8
                    ---
                    name: en
                    ...
                    hello\thello
                    python\tpython
                    """
                ),
                encoding="utf-8",
            )
            output = tmp_path / "rime-candidate-index.tsv"

            subprocess.run(
                [
                    "python3",
                    str(root / "scripts/build_rime_candidate_index.py"),
                    "--dict-dir",
                    str(dict_dir),
                    "--output",
                    str(output),
                    "--cap",
                    "8",
                    "--max-prefix-len",
                    "8",
                    "--max-text-len",
                    "8",
                    "--max-entries",
                    "20",
                    "--max-english-entries",
                    "20",
                    "--max-english-prefix-len",
                    "12",
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            rows = output.read_text(encoding="utf-8").splitlines()

        self.assertIn("ni\t你\twanxiang\t0", rows)
        self.assertIn("sj\t世界\twanxiang\t1", rows)
        self.assertIn("sj\t设计\twanxiang\t2", rows)
        self.assertIn("hello\thello\twanxiang_english\t3", rows)
        self.assertIn("python\tpython\twanxiang_english\t4", rows)
        self.assertTrue(any(row.startswith("rag\trag\twanxiang_english\t") for row in rows))
        self.assertFalse(any(row.startswith("h\thello\t") for row in rows))


if __name__ == "__main__":
    unittest.main()
