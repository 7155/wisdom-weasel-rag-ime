from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from rag_ime.authorized_blog_corpus import (
    WHITELIST_SCHEMA_VERSION,
    assess_blog_text,
    audit_whitelist,
    build_authorized_blog_corpus,
    clean_blog_text,
    iter_source_documents,
    load_whitelist,
    normalize_for_dedupe,
    package_authorized_blog_corpus,
    simhash64,
)


class AuthorizedBlogCorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="authorized-blog-corpus-")
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_whitelist_requires_explicit_permission_and_blocks_nc_or_sharealike(self) -> None:
        path = self.root / "whitelist.json"
        path.write_text(
            json.dumps(
                {
                    "schemaVersion": WHITELIST_SCHEMA_VERSION,
                    "sources": [
                        {
                            "id": "blocked",
                            "kind": "markdown_dir",
                            "path": str(self.root),
                            "license": "CC-BY-NC-SA-4.0",
                            "licenseEvidence": "https://example.test/license",
                            "attribution": "Example",
                            "permissionBasis": "repository-license",
                            "allowTraining": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "blocked license"):
            load_whitelist(path)

        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["sources"][0]["license"] = "CC-BY-SA-4.0"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "requires policy review"):
            load_whitelist(path)

        payload["allowShareAlike"] = True
        payload["corpusLicense"] = "CC-BY-SA-4.0"
        path.write_text(json.dumps(payload), encoding="utf-8")
        _, accepted = load_whitelist(path)
        self.assertEqual(accepted[0].license_id, "CC-BY-SA-4.0")

    def test_cleaning_removes_frontmatter_code_markup_urls_and_base64(self) -> None:
        value = """---
title: 一次真实复盘
date: 2026-07-11
---
# 一次真实复盘

今天我准备把训练数据重新整理一遍，先确认来源，再检查每一段文字是否自然。

```python
api_key = "sk-not-a-real-key"
print(api_key)
```

<script>bad()</script><p>后来发现，保留完整段落比随机拼句子更适合连续输入。</p>

![payload](data:image/png;base64,AAAAAA) [项目地址](https://example.test/path)
"""

        cleaned = clean_blog_text(value)

        self.assertNotIn("title:", cleaned)
        self.assertNotIn("api_key", cleaned)
        self.assertNotIn("bad()", cleaned)
        self.assertNotIn("base64", cleaned)
        self.assertNotIn("https://", cleaned)
        self.assertIn("今天我准备把训练数据重新整理一遍", cleaned)
        self.assertIn("后来发现", cleaned)

    def test_export_and_feed_importers_preserve_record_provenance(self) -> None:
        wordpress = self.root / "wordpress.xml"
        wordpress.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:wp="http://wordpress.org/export/1.2/">
  <channel><item><title>周末记录</title><link>https://blog.example/post</link>
  <wp:post_id>7</wp:post_id><wp:post_type>post</wp:post_type><wp:status>publish</wp:status>
  <wp:post_date>2026-07-11</wp:post_date><content:encoded><![CDATA[<p>今天把事情做完了，后面再检查结果。</p>]]></content:encoded>
  </item></channel>
</rss>""",
            encoding="utf-8",
        )
        ghost = self.root / "ghost.json"
        ghost.write_text(
            json.dumps(
                {
                    "db": [
                        {
                            "data": {
                                "posts": [
                                    {
                                        "id": "post-8",
                                        "status": "published",
                                        "title": "工作记录",
                                        "html": "<p>今天先处理数据，明天再跑训练。</p>",
                                        "published_at": "2026-07-11",
                                    }
                                ]
                            }
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        rss = self.root / "feed.xml"
        rss.write_text(
            """<rss><channel><item><guid>post-9</guid><title>晚间记录</title>
<link>https://blog.example/post-9</link><description><![CDATA[<p>晚上把日志看完，再补一条说明。</p>]]></description>
</item></channel></rss>""",
            encoding="utf-8",
        )
        html_directory = self.root / "html-export"
        html_directory.mkdir()
        (html_directory / "post-10.html").write_text(
            "<html><head><title>公众号导出</title></head><body><article><p>今天把导出的文章整理好了。</p></article></body></html>",
            encoding="utf-8",
        )
        config = self._write_whitelist(
            [
                self._source("wp", "wordpress_wxr", wordpress),
                self._source("ghost", "ghost_json", ghost),
                self._source("rss", "rss_atom", rss),
                self._source("html", "html_dir", html_directory, include=["*.html"]),
            ]
        )
        _, sources = load_whitelist(config)

        rows = [row for source in sources for row in iter_source_documents(source, self.root / "cache")]

        self.assertEqual({row.record_id for row in rows}, {"7", "post-8", "post-9", "post-10.html"})
        self.assertEqual({row.title for row in rows}, {"周末记录", "工作记录", "晚间记录", "公众号导出"})
        self.assertTrue(all(row.text for row in rows))

    def test_build_outputs_text_only_splits_and_separate_provenance(self) -> None:
        sources = []
        for source_index in range(3):
            directory = self.root / f"source-{source_index}"
            directory.mkdir()
            for document_index in range(8):
                text = self._article(source_index, document_index)
                (directory / f"post-{document_index}.md").write_text(text, encoding="utf-8")
            sources.append(self._source(f"source-{source_index}", "markdown_dir", directory, include=["*.md"]))
        whitelist = self._write_whitelist(sources)
        output = self.root / "output"

        report = build_authorized_blog_corpus(
            whitelist,
            self.root / "cache",
            output,
            seed="fixed-seed",
            min_chars=80,
            max_chars=1000,
            min_han_ratio=0.7,
            max_source_share=0.45,
            review_sample_size=5,
        )

        self.assertTrue(report["ok"], report)
        self.assertGreater(report["documents"], 10)
        self.assertTrue((output / "ATTRIBUTION.md").exists())
        all_rows = []
        for split in ("train", "val", "test"):
            rows = [json.loads(line) for line in (output / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(rows, split)
            self.assertTrue(all(set(row) == {"text"} and row["text"] for row in rows))
            all_rows.extend(rows)
        normalized = [normalize_for_dedupe(row["text"]) for row in all_rows]
        self.assertEqual(len(normalized), len(set(normalized)))

        provenance = [json.loads(line) for line in (output / "provenance.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(provenance), len(all_rows))
        self.assertTrue(all(row["license"] == "owned" for row in provenance))
        self.assertTrue(all(row["sourceUrl"].startswith("local-export:") for row in provenance))
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["trainingContract"]["rowShape"], {"text": "string"})
        self.assertFalse(manifest["trainingContract"]["chatFieldsAllowed"])
        self.assertIn("replace with the selected tokenizer", manifest["tokenEstimateMethod"])
        self.assertTrue(all(source["characterShare"] <= 0.45 for source in manifest["sources"].values()))

    def test_build_is_deterministic_for_same_seed_and_inputs(self) -> None:
        sources = []
        for source_index in range(3):
            directory = self.root / f"det-source-{source_index}"
            directory.mkdir()
            for document_index in range(6):
                (directory / f"post-{document_index}.md").write_text(
                    self._article(source_index, document_index), encoding="utf-8"
                )
            sources.append(self._source(f"det-{source_index}", "markdown_dir", directory, include=["*.md"]))
        whitelist = self._write_whitelist(sources, name="det-whitelist.json")
        outputs = [self.root / "out-a", self.root / "out-b"]

        reports = [
            build_authorized_blog_corpus(
                whitelist,
                self.root / "cache",
                output,
                seed="same-seed",
                min_chars=80,
                max_chars=1000,
                min_han_ratio=0.7,
                max_source_share=0.45,
            )
            for output in outputs
        ]

        self.assertEqual(reports[0]["corpusFingerprint"], reports[1]["corpusFingerprint"])
        for name in ("train.jsonl", "val.jsonl", "test.jsonl", "provenance.jsonl", "review-sample.jsonl"):
            self.assertEqual((outputs[0] / name).read_bytes(), (outputs[1] / name).read_bytes(), name)

    def test_package_is_remote_transfer_ready_with_checksums_and_licenses(self) -> None:
        sources = []
        for source_index in range(3):
            directory = self.root / f"package-source-{source_index}"
            directory.mkdir()
            for document_index in range(5):
                (directory / f"post-{document_index}.md").write_text(
                    self._article(source_index, document_index), encoding="utf-8"
                )
            sources.append(self._source(f"package-{source_index}", "markdown_dir", directory, include=["*.md"]))
        whitelist = self._write_whitelist(sources, name="package-whitelist.json")
        corpus = self.root / "package-corpus"
        build_authorized_blog_corpus(
            whitelist,
            self.root / "cache",
            corpus,
            min_chars=80,
            max_chars=1000,
            min_han_ratio=0.7,
            max_source_share=0.45,
        )

        report = package_authorized_blog_corpus(
            whitelist,
            self.root / "cache",
            corpus,
            self.root / "packages",
            package_name="blog-corpus-test",
        )

        package = Path(report["packageDirectory"])
        archive = Path(report["archive"])
        self.assertTrue((package / "training" / "train.jsonl").is_file())
        self.assertTrue((package / "provenance" / "deletion-index.jsonl").is_file())
        self.assertTrue((package / "review" / "review-sample.jsonl").is_file())
        self.assertTrue((package / "SHA256SUMS").is_file())
        self.assertEqual(len(list((package / "provenance" / "licenses").glob("*-PERMISSION.txt"))), 3)
        self.assertTrue(archive.is_file())
        self.assertTrue(Path(str(archive) + ".sha256").is_file())
        with tarfile.open(archive, "r:gz") as handle:
            names = handle.getnames()
        self.assertIn("blog-corpus-test/training/train.jsonl", names)

    def test_near_duplicate_fingerprint_and_quality_gate(self) -> None:
        original = "今天我把博客语料整理完成，然后检查来源记录和许可信息，最后再随机抽样复核自然度。"
        variation = "今天我把博客语料整理完成，然后检查来源记录和许可信息，最后再随机抽样复核自然度！"
        unrelated = "周末和朋友见面以后，我们先吃饭，再讨论下周要处理的工作。"

        self.assertLessEqual((simhash64(original) ^ simhash64(variation)).bit_count(), 3)
        self.assertGreater((simhash64(original) ^ simhash64(unrelated)).bit_count(), 3)
        reason, metrics = assess_blog_text(
            original * 3,
            min_chars=50,
            max_chars=1000,
            min_han_ratio=0.7,
        )
        self.assertEqual(reason, "")
        self.assertGreater(metrics["hanRatio"], 0.9)

        reason, _ = assess_blog_text(
            "这是一段自然中文说明，比如我自己的i@example.cn，但邮箱不能进入公开训练语料。" * 3,
            min_chars=50,
            max_chars=1000,
            min_han_ratio=0.6,
        )
        self.assertEqual(reason, "email")

    def test_public_whitelist_is_pinned_and_auditable(self) -> None:
        public = Path(__file__).resolve().parents[1] / "dataset" / "authorized_blog_whitelist.v1.json"
        audit = audit_whitelist(public)

        self.assertTrue(audit["ok"])
        self.assertGreaterEqual(audit["sourceCount"], 12)
        self.assertEqual(sum(audit["licenses"].values()), audit["sourceCount"])
        self.assertTrue(set(audit["licenses"]).issubset({"CC-BY-4.0", "CC-BY-SA-4.0"}))
        self.assertTrue(audit["allPinned"])
        self.assertTrue(audit["allLicenseHashesPinned"])
        self.assertTrue(audit["redistributionReviewRequired"])
        self.assertTrue(audit["shareAlikeAccepted"])
        self.assertEqual(audit["corpusLicense"], "CC-BY-SA-4.0")

    def _source(
        self,
        source_id: str,
        kind: str,
        path: Path,
        *,
        include: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "id": source_id,
            "kind": kind,
            "path": str(path),
            "include": include or [],
            "exclude": [],
            "license": "owned",
            "licenseEvidence": f"local-permission:{source_id}",
            "attribution": f"Owner {source_id}",
            "permissionBasis": "owner-export",
            "allowTraining": True,
            "maxDocuments": 100,
        }

    def _write_whitelist(self, sources: list[dict[str, object]], *, name: str = "whitelist.json") -> Path:
        path = self.root / name
        path.write_text(
            json.dumps({"schemaVersion": WHITELIST_SCHEMA_VERSION, "sources": sources}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _article(source_index: int, document_index: int) -> str:
        return (
            "---\n"
            f"title: 第{source_index}-{document_index}篇记录\n"
            "---\n"
            f"今天我整理第{source_index}组资料里的第{document_index}篇记录，先确认原始来源和授权信息。"
            "后来检查正文时，我把代码块、导航和广告都去掉，只保留连续自然的中文段落。"
            "最后再做去重和随机抽样，确认这些内容适合中文输入法继续预训练，而不是聊天问答。"
        )


if __name__ == "__main__":
    unittest.main()
