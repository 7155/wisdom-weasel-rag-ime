from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class MacOSDictionaryProviderTests(unittest.TestCase):
    def test_wanxiang_import_tables_and_tone_marks_are_supported(self) -> None:
        swiftc = shutil.which("swiftc")
        if swiftc is None:
            self.skipTest("swiftc is not available")

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-wanxiang-provider-") as tmp:
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
                    你\tnǐ\t2000
                    呢\tne\t900
                    世界\tshì jiè\t1500
                    设计\tshè jì\t1300
                    """
                ),
                encoding="utf-8",
            )
            wrapper = tmp_path / "main.swift"
            wrapper.write_text(
                textwrap.dedent(
                    """\
                    import Foundation

                    let dictDir = CommandLine.arguments[1]
                    let provider = RimeDictionaryCandidateProvider(environment: [
                        "RAG_IME_RIME_DICT_DIR": dictDir
                    ])
                    let payload = provider.diagnosticPayload(for: [
                        "ni",
                        "shijie",
                        "sj",
                        "git status",
                        "/Volumes/undo"
                    ])
                    let data = try JSONSerialization.data(
                        withJSONObject: payload,
                        options: [.sortedKeys]
                    )
                    FileHandle.standardOutput.write(data)
                    """
                ),
                encoding="utf-8",
            )
            executable = tmp_path / "provider_probe"
            subprocess.run(
                [
                    swiftc,
                    str(root / "macos/RagImeMac/Sources/RagModels.swift"),
                    str(root / "macos/RagImeMac/Sources/RimeSidecarModels.swift"),
                    str(root / "macos/RagImeMac/Sources/RagBridgeClient.swift"),
                    str(root / "macos/RagImeMac/Sources/RimeDictionaryCandidateProvider.swift"),
                    str(wrapper),
                    "-o",
                    str(executable),
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            result = subprocess.run(
                [str(executable), str(dict_dir)],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["ni"][0]["text"], "你")
        self.assertEqual(payload["ni"][0]["comment"], "wanxiang")
        self.assertEqual(payload["shijie"][0]["text"], "世界")
        self.assertIn("世界", [candidate["text"] for candidate in payload["sj"]])
        self.assertIn("设计", [candidate["text"] for candidate in payload["sj"]])
        self.assertEqual(payload["git status"], [])
        self.assertEqual(payload["/Volumes/undo"], [])

    def test_prebuilt_index_supports_cached_live_lookup(self) -> None:
        swiftc = shutil.which("swiftc")
        if swiftc is None:
            self.skipTest("swiftc is not available")

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="rag-ime-rime-index-") as tmp:
            tmp_path = Path(tmp)
            index_path = tmp_path / "rime-candidate-index.tsv"
            index_path.write_text(
                textwrap.dedent(
                    """\
                    # rag-ime-rime-index-v1\tprefix\ttext\tcomment\tindex
                    ni\t你\twanxiang\t10
                    ni\t呢\twanxiang\t11
                    wx\t我想\twanxiang\t12
                    """
                ),
                encoding="utf-8",
            )
            wrapper = tmp_path / "main.swift"
            wrapper.write_text(
                textwrap.dedent(
                    """\
                    import Foundation

                    let indexPath = CommandLine.arguments[1]
                    let provider = RimeDictionaryCandidateProvider(environment: [
                        "RAG_IME_RIME_INDEX_PATH": indexPath,
                        "RAG_IME_RIME_DICT_DIR": "/tmp/rag-ime-missing-rime-dir"
                    ])
                    _ = provider.candidates(for: "ni", maxCount: 2, allowColdLoad: true)
                    let payload: [String: Any] = [
                        "readyAfterColdLoad": provider.isReady,
                        "ni": provider.candidates(for: "ni", maxCount: 2, allowColdLoad: false).map { $0.text },
                        "wx": provider.candidates(for: "wx", maxCount: 1, allowColdLoad: false).map { $0.text },
                        "missing": provider.candidates(for: "zzzz", maxCount: 1, allowColdLoad: false).map { $0.text }
                    ]
                    let data = try JSONSerialization.data(
                        withJSONObject: payload,
                        options: [.sortedKeys]
                    )
                    FileHandle.standardOutput.write(data)
                    """
                ),
                encoding="utf-8",
            )
            executable = tmp_path / "provider_index_probe"
            subprocess.run(
                [
                    swiftc,
                    str(root / "macos/RagImeMac/Sources/RagModels.swift"),
                    str(root / "macos/RagImeMac/Sources/RimeSidecarModels.swift"),
                    str(root / "macos/RagImeMac/Sources/RagBridgeClient.swift"),
                    str(root / "macos/RagImeMac/Sources/RimeDictionaryCandidateProvider.swift"),
                    str(wrapper),
                    "-o",
                    str(executable),
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            result = subprocess.run(
                [str(executable), str(index_path)],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

        payload = json.loads(result.stdout)
        self.assertTrue(payload["readyAfterColdLoad"])
        self.assertEqual(payload["ni"], ["你", "呢"])
        self.assertEqual(payload["wx"], ["我想"])
        self.assertEqual(payload["missing"], [])


if __name__ == "__main__":
    unittest.main()
