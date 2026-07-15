from __future__ import annotations

import fnmatch
import hashlib
import heapq
import html
import json
import math
import re
import shutil
import subprocess
import tarfile
import tempfile
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence


SCHEMA_VERSION = "rag-ime.authorized-blog-corpus.v1"
WHITELIST_SCHEMA_VERSION = "rag-ime.authorized-blog-whitelist.v1"

ALLOWED_LICENSES = {
    "CC-BY-4.0",
    "CC0-1.0",
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "owned",
    "author-permission",
}
REVIEW_REQUIRED_LICENSES = {"CC-BY-SA-4.0"}
BLOCKED_LICENSE_MARKERS = ("-NC", "-ND", "unknown", "proprietary")

HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LATIN_OR_DIGIT_RE = re.compile(r"[A-Za-z0-9]")
EMAIL_RE = re.compile(r"(?i)(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![A-Z0-9.-])")
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
SECRET_RE = re.compile(r"(?i)\b(?:sk|api[_-]?key|secret)[_-]?[A-Za-z0-9]{16,}\b")
RAW_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
BASE64_IMAGE_RE = re.compile(r"data:image/[^;\s]+;base64,[A-Za-z0-9+/=\s]+", re.IGNORECASE)
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
INLINE_CODE_RE = re.compile(r"`([^`\n]{1,80})`")
MARKDOWN_DECORATION_RE = re.compile(r"(?:\*\*|__|~~)")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
LIQUID_RE = re.compile(r"(?:\{%.*?%\}|\{\{.*?\}\})", re.DOTALL)
FRONT_MATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*(?:\n|\Z)", re.DOTALL)
SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？!?；;])")
SPACE_RE = re.compile(r"[ \t\u3000]+")
BLANK_RE = re.compile(r"\n{3,}")

BOILERPLATE_PATTERNS = (
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"点击(?:关注|订阅|下载)",
        r"欢迎(?:点赞|收藏|转发|关注)",
        r"更多精彩内容",
        r"立即咨询",
        r"免责声明",
        r"本文将详细介绍",
        r"综上所述",
        r"未经授权.*转载",
        r"相关阅读",
    )
)


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    kind: str
    license_id: str
    license_evidence: str
    license_sha256: str
    attribution: str
    permission_basis: str
    allow_training: bool
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    checkout_patterns: tuple[str, ...] = ()
    drop_patterns: tuple[str, ...] = ()
    repo_url: str = ""
    commit: str = ""
    path: str = ""
    url: str = ""
    max_documents: int = 10_000


@dataclass(frozen=True)
class RawDocument:
    source_id: str
    record_id: str
    source_url: str
    title: str
    published_at: str
    text: str


@dataclass(frozen=True)
class CorpusDocument:
    doc_id: str
    source_id: str
    record_id: str
    source_url: str
    title: str
    published_at: str
    text: str
    content_sha256: str
    normalized_sha256: str
    han_ratio: float
    style_score: int
    transformations: tuple[str, ...]
    selection_hash: str


class _HTMLTextExtractor(HTMLParser):
    _BLOCK_TAGS = {
        "article",
        "blockquote",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "main",
        "p",
        "pre",
        "section",
    }
    _SKIP_TAGS = {"script", "style", "svg", "nav", "footer", "header", "aside", "form"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self.skip_depth += 1
        elif not self.skip_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


class _NearDeduper:
    def __init__(self, max_distance: int = 3) -> None:
        self.max_distance = max_distance
        self.bands: list[dict[int, list[int]]] = [defaultdict(list) for _ in range(4)]

    def is_duplicate(self, text: str) -> bool:
        fingerprint = simhash64(text)
        candidates: set[int] = set()
        for index, band in enumerate(self.bands):
            candidates.update(band.get((fingerprint >> (index * 16)) & 0xFFFF, ()))
        if any((fingerprint ^ previous).bit_count() <= self.max_distance for previous in candidates):
            return True
        for index, band in enumerate(self.bands):
            band[(fingerprint >> (index * 16)) & 0xFFFF].append(fingerprint)
        return False


def load_whitelist(path: str | Path) -> tuple[dict[str, object], list[SourceSpec]]:
    config_path = Path(path).expanduser().resolve()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("whitelist must contain a JSON object")
    if payload.get("schemaVersion") != WHITELIST_SCHEMA_VERSION:
        raise ValueError(f"whitelist schemaVersion must be {WHITELIST_SCHEMA_VERSION}")
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("whitelist must contain at least one source")

    sources: list[SourceSpec] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_sources):
        if not isinstance(item, dict):
            raise ValueError(f"sources[{index}] must be an object")
        source_id = str(item.get("id", "")).strip()
        if not source_id or source_id in seen_ids:
            raise ValueError(f"invalid or duplicate source id: {source_id!r}")
        seen_ids.add(source_id)
        source = SourceSpec(
            source_id=source_id,
            kind=str(item.get("kind", "")).strip(),
            license_id=str(item.get("license", "")).strip(),
            license_evidence=str(item.get("licenseEvidence", "")).strip(),
            license_sha256=str(item.get("licenseSha256", "")).strip(),
            attribution=str(item.get("attribution", "")).strip(),
            permission_basis=str(item.get("permissionBasis", "")).strip(),
            allow_training=bool(item.get("allowTraining", False)),
            include=_string_tuple(item.get("include", ())),
            exclude=_string_tuple(item.get("exclude", ())),
            checkout_patterns=_string_tuple(item.get("checkoutPatterns", ())),
            drop_patterns=_string_tuple(item.get("dropPatterns", ())),
            repo_url=str(item.get("repoUrl", "")).strip(),
            commit=str(item.get("commit", "")).strip(),
            path=str(item.get("path", "")).strip(),
            url=str(item.get("url", "")).strip(),
            max_documents=int(item.get("maxDocuments", 10_000)),
        )
        _validate_source(source, allow_share_alike=bool(payload.get("allowShareAlike", False)))
        sources.append(source)
    return payload, sources


def audit_whitelist(path: str | Path) -> dict[str, object]:
    payload, sources = load_whitelist(path)
    return {
        "ok": True,
        "schemaVersion": WHITELIST_SCHEMA_VERSION,
        "sourceCount": len(sources),
        "sourceIds": [source.source_id for source in sources],
        "licenses": dict(sorted(Counter(source.license_id for source in sources).items())),
        "allTrainingAllowed": all(source.allow_training for source in sources),
        "allPinned": all(source.kind != "git_markdown" or bool(re.fullmatch(r"[0-9a-f]{40}", source.commit)) for source in sources),
        "allLicenseHashesPinned": all(
            source.kind != "git_markdown" or bool(re.fullmatch(r"[0-9a-f]{64}", source.license_sha256))
            for source in sources
        ),
        "redistributionReviewRequired": any(source.license_id in REVIEW_REQUIRED_LICENSES for source in sources),
        "shareAlikeAccepted": bool(payload.get("allowShareAlike", False)),
        "corpusLicense": str(payload.get("corpusLicense", "unspecified")),
        "notes": list(payload.get("notes", [])) if isinstance(payload.get("notes"), list) else [],
    }


def sync_git_sources(
    whitelist_path: str | Path,
    cache_root: str | Path,
) -> dict[str, object]:
    _, sources = load_whitelist(whitelist_path)
    cache = Path(cache_root).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []

    for source in sources:
        if source.kind != "git_markdown":
            results.append({"sourceId": source.source_id, "status": "not_git"})
            continue
        destination = source_snapshot_path(cache, source)
        if destination.exists():
            head = _git_output(destination, "rev-parse", "HEAD")
            if head != source.commit:
                raise RuntimeError(f"cached source {source.source_id} has unexpected HEAD {head}")
            license_sha = _license_sha256(destination)
            if license_sha != source.license_sha256:
                raise RuntimeError(f"cached source {source.source_id} license hash does not match the whitelist")
            results.append(
                {
                    "sourceId": source.source_id,
                    "status": "cached",
                    "path": str(destination),
                    "commit": head,
                    "licenseSha256": license_sha,
                }
            )
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"{source.source_id}-", dir=destination.parent) as tmp:
            checkout = Path(tmp) / "checkout"
            checkout.mkdir()
            _run_git(checkout, "init", "-q")
            _run_git(checkout, "remote", "add", "origin", source.repo_url)
            _run_git(checkout, "sparse-checkout", "init", "--no-cone")
            patterns = source.checkout_patterns or source.include
            _run_git(checkout, "sparse-checkout", "set", "--no-cone", *patterns)
            _run_git(
                checkout,
                "fetch",
                "--quiet",
                "--depth",
                "1",
                "--filter=blob:none",
                "origin",
                source.commit,
            )
            _run_git(checkout, "checkout", "--quiet", "--detach", "FETCH_HEAD")
            if _git_output(checkout, "rev-parse", "HEAD") != source.commit:
                raise RuntimeError(f"failed to pin source {source.source_id} to {source.commit}")
            shutil.move(str(checkout), str(destination))
        results.append(
            {
                "sourceId": source.source_id,
                "status": "synced",
                "path": str(destination),
                "commit": source.commit,
                "licenseSha256": _verified_license_sha256(destination, source),
            }
        )

    return {"ok": True, "cacheRoot": str(cache), "sources": results}


def build_authorized_blog_corpus(
    whitelist_path: str | Path,
    cache_root: str | Path,
    output_root: str | Path,
    *,
    seed: str = "rag-ime-blog-v1",
    min_chars: int = 100,
    max_chars: int = 4_000,
    min_han_ratio: float = 0.65,
    max_source_share: float = 0.45,
    review_sample_size: int = 50,
    near_dedupe: bool = True,
) -> dict[str, object]:
    config, sources = load_whitelist(whitelist_path)
    cache = Path(cache_root).expanduser().resolve()
    output = Path(output_root).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    rejections: Counter[str] = Counter()
    rejected_samples: list[dict[str, object]] = []
    input_counts: Counter[str] = Counter()
    raw_candidates: list[CorpusDocument] = []
    source_specs = {source.source_id: source for source in sources}

    for source in sources:
        source_count = 0
        for raw in iter_source_documents(source, cache):
            input_counts[source.source_id] += 1
            source_count += 1
            if source_count > source.max_documents:
                rejections[f"{source.source_id}:source_document_cap"] += 1
                break
            cleaned = clean_blog_text(raw.text)
            cleaned = _drop_source_paragraphs(cleaned, source.drop_patterns)
            if not cleaned:
                _reject(rejections, rejected_samples, source.source_id, raw.record_id, "empty_after_clean", raw.text)
                continue
            for chunk_index, chunk in enumerate(split_blog_text(cleaned, min_chars=min_chars, max_chars=max_chars)):
                reason, metrics = assess_blog_text(chunk, min_chars=min_chars, max_chars=max_chars, min_han_ratio=min_han_ratio)
                record_id = f"{raw.record_id}#chunk={chunk_index}"
                if reason:
                    _reject(rejections, rejected_samples, source.source_id, record_id, reason, chunk)
                    continue
                normalized = normalize_for_dedupe(chunk)
                normalized_sha = _sha256_text(normalized)
                content_sha = _sha256_text(chunk)
                doc_id = f"blog:{normalized_sha[:24]}"
                raw_candidates.append(
                    CorpusDocument(
                        doc_id=doc_id,
                        source_id=source.source_id,
                        record_id=record_id,
                        source_url=raw.source_url,
                        title=raw.title,
                        published_at=raw.published_at,
                        text=chunk,
                        content_sha256=content_sha,
                        normalized_sha256=normalized_sha,
                        han_ratio=float(metrics["hanRatio"]),
                        style_score=int(metrics["styleScore"]),
                        transformations=(
                            "unicode_nfc",
                            "frontmatter_removed",
                            "code_blocks_removed",
                            "markdown_html_stripped",
                            "paragraph_chunked",
                            *(("source_specific_paragraphs_removed",) if source.drop_patterns else ()),
                        ),
                        selection_hash=_sha256_text(f"{seed}\0{source.source_id}\0{record_id}\0{content_sha}"),
                    )
                )

    deduper = _NearDeduper()
    exact_seen: set[str] = set()
    deduped: list[CorpusDocument] = []
    for document in sorted(raw_candidates, key=lambda item: item.selection_hash):
        if document.normalized_sha256 in exact_seen:
            rejections[f"{document.source_id}:exact_duplicate"] += 1
            continue
        exact_seen.add(document.normalized_sha256)
        if near_dedupe and deduper.is_duplicate(normalize_for_dedupe(document.text)):
            rejections[f"{document.source_id}:near_duplicate"] += 1
            continue
        deduped.append(document)

    selected, balance_report = balance_sources(deduped, max_source_share=max_source_share)
    for source_id, dropped in balance_report["droppedDocumentsBySource"].items():
        rejections[f"{source_id}:source_share_cap"] += int(dropped)

    split_documents: dict[str, list[CorpusDocument]] = {"train": [], "val": [], "test": []}
    for document in selected:
        split_documents[deterministic_split(document.normalized_sha256, seed)].append(document)
    _ensure_nonempty_eval_splits(split_documents)
    for documents in split_documents.values():
        documents.sort(key=lambda item: item.selection_hash)

    provenance_rows: list[dict[str, object]] = []
    split_fingerprints: dict[str, str] = {}
    for split, documents in split_documents.items():
        split_path = output / f"{split}.jsonl"
        with split_path.open("w", encoding="utf-8") as handle:
            for line_number, document in enumerate(documents, start=1):
                handle.write(json.dumps({"text": document.text}, ensure_ascii=False, separators=(",", ":")) + "\n")
                source = source_specs[document.source_id]
                provenance_rows.append(
                    {
                        "docId": document.doc_id,
                        "split": split,
                        "lineNumber": line_number,
                        "sourceId": document.source_id,
                        "recordId": document.record_id,
                        "sourceUrl": document.source_url,
                        "title": document.title,
                        "publishedAt": document.published_at,
                        "authorAttribution": source.attribution,
                        "license": source.license_id,
                        "licenseEvidence": source.license_evidence,
                        "licenseSha256": source.license_sha256,
                        "permissionBasis": source.permission_basis,
                        "contentSha256": document.content_sha256,
                        "normalizedSha256": document.normalized_sha256,
                        "characters": len(document.text),
                        "hanRatio": round(document.han_ratio, 6),
                        "styleScore": document.style_score,
                        "transformations": list(document.transformations),
                    }
                )
        split_fingerprints[split] = _sha256_file(split_path)

    provenance_rows.sort(key=lambda item: (str(item["split"]), int(item["lineNumber"])))
    _write_jsonl(output / "provenance.jsonl", provenance_rows)
    _write_jsonl(
        output / "deletion-index.jsonl",
        (
            {
                "docId": row["docId"],
                "sourceId": row["sourceId"],
                "recordId": row["recordId"],
                "split": row["split"],
                "lineNumber": row["lineNumber"],
            }
            for row in provenance_rows
        ),
    )
    _write_jsonl(output / "rejected-sample.jsonl", rejected_samples)

    review_documents = heapq.nsmallest(review_sample_size, selected, key=lambda item: _sha256_text(f"review\0{seed}\0{item.doc_id}"))
    _write_jsonl(
        output / "review-sample.jsonl",
        (
            {
                "docId": item.doc_id,
                "sourceId": item.source_id,
                "recordId": item.record_id,
                "sourceUrl": item.source_url,
                "text": item.text,
            }
            for item in review_documents
        ),
    )

    source_stats: dict[str, dict[str, object]] = {}
    total_characters = sum(len(document.text) for document in selected)
    for source in sources:
        documents = [document for document in selected if document.source_id == source.source_id]
        characters = sum(len(document.text) for document in documents)
        source_stats[source.source_id] = {
            "documents": len(documents),
            "characters": characters,
            "characterShare": round(characters / total_characters, 6) if total_characters else 0.0,
            "inputDocuments": input_counts[source.source_id],
            "license": source.license_id,
            "licenseEvidence": source.license_evidence,
            "licenseSha256": source.license_sha256,
            "permissionBasis": source.permission_basis,
            "attribution": source.attribution,
            "commit": source.commit,
        }

    split_stats = {
        split: {
            "documents": len(documents),
            "characters": sum(len(document.text) for document in documents),
            "sha256": split_fingerprints[split],
        }
        for split, documents in split_documents.items()
    }
    corpus_fingerprint = _sha256_text("\n".join(sorted(document.normalized_sha256 for document in selected)))
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "corpusFingerprint": corpus_fingerprint,
        "whitelistFingerprint": _sha256_file(Path(whitelist_path).expanduser().resolve()),
        "trainingContract": {"rowShape": {"text": "string"}, "chatFieldsAllowed": False},
        "selection": {
            "seed": seed,
            "minCharacters": min_chars,
            "maxCharacters": max_chars,
            "minHanRatio": min_han_ratio,
            "nearDeduplication": near_dedupe,
            "nearDuplicateHammingDistance": 3 if near_dedupe else None,
            "maxSourceCharacterShare": max_source_share,
        },
        "documents": len(selected),
        "characters": total_characters,
        "estimatedTokens": estimate_tokens(document.text for document in selected),
        "tokenEstimateMethod": "han_chars/1.5 + other_nonspace_chars/3.5; replace with the selected tokenizer before training",
        "sources": source_stats,
        "splits": split_stats,
        "rejections": dict(sorted(rejections.items())),
        "balance": balance_report,
        "redistributionStatus": "review-required-before-publishing",
        "corpusLicense": str(config.get("corpusLicense", "unspecified")),
        "modelWeightsLicenseStatus": "not-determined-by-this-tool",
        "notes": list(config.get("notes", [])) if isinstance(config.get("notes"), list) else [],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "ATTRIBUTION.md").write_text(render_attribution(sources, source_stats, corpus_fingerprint), encoding="utf-8")
    return {"ok": True, "output": str(output), **manifest}


def iter_source_documents(source: SourceSpec, cache_root: Path) -> Iterator[RawDocument]:
    if source.kind == "git_markdown":
        root = source_snapshot_path(cache_root, source)
        if not root.exists():
            raise FileNotFoundError(f"source {source.source_id} is not synced: {root}")
        yield from _iter_markdown_tree(source, root)
        return
    if source.kind == "markdown_dir":
        yield from _iter_markdown_tree(source, Path(source.path).expanduser().resolve())
        return
    if source.kind == "html_dir":
        yield from _iter_html_tree(source, Path(source.path).expanduser().resolve())
        return
    if source.kind == "wordpress_wxr":
        yield from _iter_wordpress(source, Path(source.path).expanduser().resolve())
        return
    if source.kind == "ghost_json":
        yield from _iter_ghost(source, Path(source.path).expanduser().resolve())
        return
    if source.kind == "rss_atom":
        yield from _iter_rss_atom(source)
        return
    raise ValueError(f"unsupported source kind: {source.kind}")


def clean_blog_text(value: str) -> str:
    text = unicodedata.normalize("NFC", value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(
        character
        for character in text
        if character in "\n\t" or unicodedata.category(character) not in {"Cc", "Cf"}
    )
    text = BASE64_IMAGE_RE.sub("", text)
    text = FRONT_MATTER_RE.sub("", text)
    text = HTML_COMMENT_RE.sub("", text)
    text = LIQUID_RE.sub("", text)
    lines: list[str] = []
    in_fence = False
    fence_marker = ""
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        if _looks_like_code_line(stripped):
            continue
        line = MARKDOWN_IMAGE_RE.sub("", raw_line)
        line = MARKDOWN_LINK_RE.sub(r"\1", line)
        line = INLINE_CODE_RE.sub(r"\1", line)
        line = MARKDOWN_DECORATION_RE.sub("", line)
        line = re.sub(r"^\s{0,3}(?:#{1,6}|[-*+]\s+|>\s*|\d+[.)]\s+)", "", line)
        line = re.sub(r"<iframe\b.*?</iframe>", "", line, flags=re.IGNORECASE | re.DOTALL)
        lines.append(line)
    extractor = _HTMLTextExtractor()
    extractor.feed("\n".join(lines))
    text = html.unescape(extractor.text())
    text = RAW_URL_RE.sub("", text)
    text = re.sub(r":[a-zA-Z0-9_+-]{2,40}:", "", text)
    normalized_lines: list[str] = []
    for line in text.splitlines():
        line = SPACE_RE.sub(" ", line).strip()
        if not line or _is_navigation_line(line):
            normalized_lines.append("")
            continue
        normalized_lines.append(line)
    return BLANK_RE.sub("\n\n", "\n".join(normalized_lines)).strip()


def split_blog_text(text: str, *, min_chars: int, max_chars: int) -> Iterator[str]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    buffer: list[str] = []
    buffer_length = 0
    for paragraph in paragraphs:
        pieces = _split_long_paragraph(paragraph, max_chars)
        for piece in pieces:
            separator = 2 if buffer else 0
            if buffer and buffer_length + separator + len(piece) > max_chars:
                chunk = "\n\n".join(buffer).strip()
                if len(chunk) >= min_chars:
                    yield chunk
                buffer = []
                buffer_length = 0
            buffer.append(piece)
            buffer_length += (2 if len(buffer) > 1 else 0) + len(piece)
    chunk = "\n\n".join(buffer).strip()
    if len(chunk) >= min_chars:
        yield chunk


def assess_blog_text(
    text: str,
    *,
    min_chars: int,
    max_chars: int,
    min_han_ratio: float,
) -> tuple[str, dict[str, float | int]]:
    length = len(text)
    han_count = len(HAN_RE.findall(text))
    latin_or_digits = len(LATIN_OR_DIGIT_RE.findall(text))
    denominator = han_count + latin_or_digits
    han_ratio = han_count / denominator if denominator else 0.0
    style_score = blog_style_score(text)
    metrics: dict[str, float | int] = {"characters": length, "hanRatio": han_ratio, "styleScore": style_score}
    if length < min_chars:
        return "too_short", metrics
    if length > max_chars:
        return "too_long", metrics
    if han_ratio < min_han_ratio:
        return "low_han_ratio", metrics
    if EMAIL_RE.search(text):
        return "email", metrics
    if PHONE_RE.search(text):
        return "phone", metrics
    if SECRET_RE.search(text):
        return "possible_secret", metrics
    boilerplate_hits = sum(len(pattern.findall(text)) for pattern in BOILERPLATE_PATTERNS)
    if boilerplate_hits >= 3:
        return "template_or_marketing", metrics
    if _internal_repetition_ratio(text) > 0.35:
        return "internal_repetition", metrics
    if text.count("。") + text.count("！") + text.count("？") < 1:
        return "no_sentence_boundary", metrics
    return "", metrics


def normalize_for_dedupe(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    return "".join(character for character in normalized if character.isalnum() or HAN_RE.fullmatch(character))


def simhash64(text: str) -> int:
    normalized = normalize_for_dedupe(text)
    if not normalized:
        return 0
    width = 5 if len(normalized) >= 5 else max(1, len(normalized))
    shingles = {normalized[index : index + width] for index in range(0, max(1, len(normalized) - width + 1), 2)}
    weights = [0] * 64
    for shingle in shingles:
        value = int.from_bytes(hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest(), "big")
        for bit in range(64):
            weights[bit] += 1 if value & (1 << bit) else -1
    fingerprint = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            fingerprint |= 1 << bit
    return fingerprint


def blog_style_score(text: str) -> int:
    positive = sum(text.count(marker) for marker in ("我", "我们", "今天", "昨天", "后来", "当时", "这次", "最近", "发现", "感觉", "准备", "结果"))
    negative = sum(text.count(marker) for marker in ("本报记者", "中新网", "新华社", "题主", "答主", "法律规定", "点击购买", "责任编辑"))
    return min(12, positive) - min(12, negative * 2)


def balance_sources(
    documents: Sequence[CorpusDocument],
    *,
    max_source_share: float,
) -> tuple[list[CorpusDocument], dict[str, object]]:
    if not documents:
        return [], {"applied": False, "reason": "no_documents", "droppedDocumentsBySource": {}}
    by_source: dict[str, list[CorpusDocument]] = defaultdict(list)
    for document in documents:
        by_source[document.source_id].append(document)
    if not 0 < max_source_share <= 1:
        raise ValueError("max_source_share must be in (0, 1]")
    if len(by_source) * max_source_share < 1:
        raise ValueError("max_source_share is impossible for the number of nonempty sources")

    character_totals = {source_id: sum(len(item.text) for item in items) for source_id, items in by_source.items()}
    total_available = sum(character_totals.values())
    if all(value <= total_available * max_source_share for value in character_totals.values()):
        return list(documents), {
            "applied": False,
            "maxSourceCharacterShare": max_source_share,
            "droppedDocumentsBySource": {source_id: 0 for source_id in sorted(by_source)},
        }

    low = 0.0
    high = float(total_available)
    for _ in range(80):
        midpoint = (low + high) / 2
        capacity = sum(min(value, max_source_share * midpoint) for value in character_totals.values())
        if capacity >= midpoint:
            low = midpoint
        else:
            high = midpoint
    per_source_cap = max_source_share * low
    selected: list[CorpusDocument] = []
    dropped: dict[str, int] = {}
    for source_id, items in by_source.items():
        used = 0
        kept: list[CorpusDocument] = []
        for item in sorted(items, key=lambda candidate: candidate.selection_hash):
            if used + len(item.text) <= per_source_cap or not kept:
                kept.append(item)
                used += len(item.text)
        selected.extend(kept)
        dropped[source_id] = len(items) - len(kept)
    final_trims: Counter[str] = Counter()
    while selected:
        final_total = sum(len(item.text) for item in selected)
        final_by_source = Counter()
        for item in selected:
            final_by_source[item.source_id] += len(item.text)
        dominant_source, dominant_characters = max(final_by_source.items(), key=lambda pair: (pair[1], pair[0]))
        if dominant_characters / final_total <= max_source_share + 1e-12:
            break
        dominant_items = [item for item in selected if item.source_id == dominant_source]
        if len(dominant_items) <= 1:
            raise ValueError("cannot satisfy max_source_share with whole-document selection")
        removed = max(dominant_items, key=lambda item: item.selection_hash)
        selected.remove(removed)
        dropped[dominant_source] += 1
        final_trims[dominant_source] += 1
    return selected, {
        "applied": True,
        "maxSourceCharacterShare": max_source_share,
        "computedPerSourceCharacterCap": math.floor(per_source_cap),
        "droppedDocumentsBySource": dict(sorted(dropped.items())),
        "finalWholeDocumentTrimsBySource": dict(sorted(final_trims.items())),
    }


def deterministic_split(normalized_sha256: str, seed: str) -> str:
    bucket = int(_sha256_text(f"split\0{seed}\0{normalized_sha256}")[:8], 16) % 10_000
    if bucket < 9_800:
        return "train"
    if bucket < 9_900:
        return "val"
    return "test"


def estimate_tokens(texts: Iterable[str]) -> int:
    estimate = 0.0
    for text in texts:
        han = len(HAN_RE.findall(text))
        other = sum(1 for character in text if not character.isspace()) - han
        estimate += han / 1.5 + max(0, other) / 3.5
    return round(estimate)


def render_attribution(
    sources: Sequence[SourceSpec],
    source_stats: Mapping[str, Mapping[str, object]],
    corpus_fingerprint: str,
) -> str:
    lines = [
        "# Corpus Attribution",
        "",
        f"Corpus fingerprint: `{corpus_fingerprint}`",
        "",
        "This local research corpus contains transformed excerpts from the pinned sources below. "
        "The collector removed markup and code, filtered text, split long posts, and deduplicated chunks. "
        "Publishing the corpus or model artifacts still requires a separate license review.",
        "",
    ]
    for source in sources:
        stats = source_stats[source.source_id]
        lines.extend(
            [
                f"## {source.source_id}",
                "",
                f"- Attribution: {source.attribution}",
                f"- License: `{source.license_id}`",
                f"- License evidence: {source.license_evidence}",
                f"- License SHA-256: `{source.license_sha256 or 'not-applicable'}`",
                f"- Permission basis: `{source.permission_basis}`",
                f"- Pinned commit: `{source.commit or 'not-applicable'}`",
                f"- Included documents: {stats['documents']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def package_authorized_blog_corpus(
    whitelist_path: str | Path,
    cache_root: str | Path,
    corpus_root: str | Path,
    package_root: str | Path,
    *,
    package_name: str,
    downloaded_audit_path: str | Path | None = None,
) -> dict[str, object]:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", package_name):
        raise ValueError("package_name may contain only ASCII letters, digits, dot, underscore, and hyphen")
    _, sources = load_whitelist(whitelist_path)
    cache = Path(cache_root).expanduser().resolve()
    corpus = Path(corpus_root).expanduser().resolve()
    destination_root = Path(package_root).expanduser().resolve()
    destination = destination_root / package_name
    if destination.exists():
        raise FileExistsError(f"package directory already exists: {destination}")
    required = {
        "training": ("train.jsonl", "val.jsonl", "test.jsonl"),
        "provenance": ("provenance.jsonl", "deletion-index.jsonl", "ATTRIBUTION.md"),
        "review": ("review-sample.jsonl", "rejected-sample.jsonl"),
        "reports": ("manifest.json",),
    }
    for filenames in required.values():
        for filename in filenames:
            if not (corpus / filename).is_file():
                raise FileNotFoundError(corpus / filename)

    destination_root.mkdir(parents=True, exist_ok=True)
    for directory, filenames in required.items():
        target = destination / directory
        target.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            shutil.copy2(corpus / filename, target / filename)

    whitelist_target = destination / "provenance" / "authorized_blog_whitelist.v1.json"
    shutil.copy2(Path(whitelist_path).expanduser().resolve(), whitelist_target)
    license_root = destination / "provenance" / "licenses"
    license_root.mkdir()
    for source in sources:
        if source.kind == "git_markdown":
            snapshot = source_snapshot_path(cache, source)
            license_file = _find_license_file(snapshot)
            shutil.copy2(license_file, license_root / f"{source.source_id}-{license_file.name}")
        else:
            (license_root / f"{source.source_id}-PERMISSION.txt").write_text(
                f"Attribution: {source.attribution}\n"
                f"License: {source.license_id}\n"
                f"License evidence: {source.license_evidence}\n"
                f"Permission basis: {source.permission_basis}\n",
                encoding="utf-8",
            )

    if downloaded_audit_path:
        audit = Path(downloaded_audit_path).expanduser().resolve()
        if audit.is_file():
            shutil.copy2(audit, destination / "reports" / audit.name)

    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    (destination / "README.md").write_text(_render_package_readme(manifest, package_name), encoding="utf-8")
    checksums = _write_package_checksums(destination)

    archive_path = destination_root / f"{package_name}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(destination, arcname=package_name, recursive=True)
    archive_sha = _sha256_file(archive_path)
    (destination_root / f"{package_name}.tar.gz.sha256").write_text(
        f"{archive_sha}  {archive_path.name}\n", encoding="utf-8"
    )
    return {
        "ok": True,
        "packageDirectory": str(destination),
        "archive": str(archive_path),
        "archiveSha256": archive_sha,
        "packagedFiles": checksums,
        "documents": manifest.get("documents", 0),
        "estimatedTokens": manifest.get("estimatedTokens", 0),
        "corpusFingerprint": manifest.get("corpusFingerprint", ""),
    }


def source_snapshot_path(cache_root: Path, source: SourceSpec) -> Path:
    suffix = source.commit[:12] if source.commit else "local"
    return cache_root / f"{source.source_id}-{suffix}"


def _iter_markdown_tree(source: SourceSpec, root: Path) -> Iterator[RawDocument]:
    if not root.exists():
        raise FileNotFoundError(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        explicitly_included = any(
            relative == pattern and not any(character in pattern for character in "*?[")
            for pattern in source.include
        )
        if path.suffix.lower() not in {".md", ".markdown", ".mdx"} and not explicitly_included:
            continue
        if source.include and not any(fnmatch.fnmatchcase(relative, pattern) for pattern in source.include):
            continue
        if any(fnmatch.fnmatchcase(relative, pattern) for pattern in source.exclude):
            continue
        value = path.read_text(encoding="utf-8", errors="replace")
        metadata = _markdown_metadata(value)
        if source.repo_url:
            repo_http = source.repo_url.removesuffix(".git")
            source_url = f"{repo_http}/blob/{source.commit}/{urllib.parse.quote(relative, safe='/') }"
        else:
            source_url = f"local-export:{relative}"
        yield RawDocument(
            source_id=source.source_id,
            record_id=relative,
            source_url=source_url,
            title=metadata.get("title", path.stem),
            published_at=metadata.get("date", ""),
            text=value,
        )


def _iter_wordpress(source: SourceSpec, path: Path) -> Iterator[RawDocument]:
    content_tag = "{http://purl.org/rss/1.0/modules/content/}encoded"
    post_type_tag = "{http://wordpress.org/export/1.2/}post_type"
    status_tag = "{http://wordpress.org/export/1.2/}status"
    post_id_tag = "{http://wordpress.org/export/1.2/}post_id"
    post_date_tag = "{http://wordpress.org/export/1.2/}post_date"
    for _, element in ET.iterparse(path, events=("end",)):
        if _local_name(element.tag) != "item":
            continue
        post_type = _find_text(element, post_type_tag) or "post"
        status = _find_text(element, status_tag) or "publish"
        if post_type == "post" and status == "publish":
            record_id = _find_text(element, post_id_tag) or _find_text(element, "guid") or _find_text(element, "link")
            yield RawDocument(
                source_id=source.source_id,
                record_id=record_id,
                source_url=_find_text(element, "link"),
                title=_find_text(element, "title"),
                published_at=_find_text(element, post_date_tag),
                text=_find_text(element, content_tag) or _find_text(element, "description"),
            )
        element.clear()


def _iter_html_tree(source: SourceSpec, root: Path) -> Iterator[RawDocument]:
    if not root.exists():
        raise FileNotFoundError(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".html", ".htm"}:
            continue
        relative = path.relative_to(root).as_posix()
        if source.include and not any(fnmatch.fnmatchcase(relative, pattern) for pattern in source.include):
            continue
        if any(fnmatch.fnmatchcase(relative, pattern) for pattern in source.exclude):
            continue
        value = path.read_text(encoding="utf-8", errors="replace")
        title_match = re.search(r"<title\b[^>]*>(.*?)</title>", value, flags=re.IGNORECASE | re.DOTALL)
        title = clean_blog_text(title_match.group(1)) if title_match else path.stem
        yield RawDocument(
            source_id=source.source_id,
            record_id=relative,
            source_url=f"local-export:{relative}",
            title=title,
            published_at="",
            text=value,
        )


def _iter_ghost(source: SourceSpec, path: Path) -> Iterator[RawDocument]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    posts: object = payload
    if isinstance(payload, dict) and isinstance(payload.get("db"), list) and payload["db"]:
        posts = payload["db"][0].get("data", {}).get("posts", [])
    elif isinstance(payload, dict):
        posts = payload.get("posts", [])
    if not isinstance(posts, list):
        raise ValueError("Ghost export does not contain a posts list")
    for index, post in enumerate(posts):
        if not isinstance(post, dict) or post.get("status", "published") != "published":
            continue
        body = post.get("html") or post.get("plaintext") or ""
        yield RawDocument(
            source_id=source.source_id,
            record_id=str(post.get("id", index)),
            source_url=str(post.get("url", "")),
            title=str(post.get("title", "")),
            published_at=str(post.get("published_at", post.get("created_at", ""))),
            text=str(body),
        )


def _iter_rss_atom(source: SourceSpec) -> Iterator[RawDocument]:
    if source.path:
        payload = Path(source.path).expanduser().read_bytes()
    else:
        parsed = urllib.parse.urlparse(source.url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("remote RSS/Atom sources must use an explicit HTTPS URL")
        request = urllib.request.Request(source.url, headers={"User-Agent": "RAG-IME-authorized-blog-collector/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read(20 * 1024 * 1024 + 1)
        if len(payload) > 20 * 1024 * 1024:
            raise ValueError("RSS/Atom feed exceeds 20 MiB")
    root = ET.fromstring(payload)
    entries = [element for element in root.iter() if _local_name(element.tag) in {"item", "entry"}]
    for index, entry in enumerate(entries):
        link = ""
        for child in entry:
            if _local_name(child.tag) == "link":
                link = child.attrib.get("href", "") or (child.text or "")
                if link:
                    break
        body = ""
        for preferred in ("encoded", "content", "description", "summary"):
            for child in entry:
                if _local_name(child.tag) == preferred and (child.text or "").strip():
                    body = child.text or ""
                    break
            if body:
                break
        yield RawDocument(
            source_id=source.source_id,
            record_id=_child_text(entry, "id") or _child_text(entry, "guid") or link or str(index),
            source_url=link,
            title=_child_text(entry, "title"),
            published_at=_child_text(entry, "published") or _child_text(entry, "pubDate") or _child_text(entry, "updated"),
            text=body,
        )


def _validate_source(source: SourceSpec, *, allow_share_alike: bool = False) -> None:
    if source.kind not in {"git_markdown", "markdown_dir", "html_dir", "wordpress_wxr", "ghost_json", "rss_atom"}:
        raise ValueError(f"unsupported source kind for {source.source_id}: {source.kind}")
    if not source.allow_training:
        raise ValueError(f"source {source.source_id} does not explicitly allow training")
    if not source.license_id or not source.license_evidence or not source.attribution or not source.permission_basis:
        raise ValueError(f"source {source.source_id} is missing license/provenance fields")
    lowered = source.license_id.lower()
    if any(marker.lower() in lowered for marker in BLOCKED_LICENSE_MARKERS):
        raise ValueError(f"source {source.source_id} uses a blocked license: {source.license_id}")
    if source.license_id not in ALLOWED_LICENSES and source.license_id not in REVIEW_REQUIRED_LICENSES:
        raise ValueError(f"source {source.source_id} uses an unrecognized license: {source.license_id}")
    if source.license_id in REVIEW_REQUIRED_LICENSES and not allow_share_alike:
        raise ValueError(f"source {source.source_id} requires policy review before inclusion: {source.license_id}")
    if source.max_documents <= 0:
        raise ValueError(f"source {source.source_id} maxDocuments must be positive")
    if source.kind == "git_markdown":
        if not source.repo_url.startswith("https://github.com/") or not re.fullmatch(r"[0-9a-f]{40}", source.commit):
            raise ValueError(f"git source {source.source_id} must use a pinned GitHub HTTPS commit")
        if not source.include or not (source.checkout_patterns or source.include):
            raise ValueError(f"git source {source.source_id} needs include and checkout patterns")
        if not re.fullmatch(r"[0-9a-f]{64}", source.license_sha256):
            raise ValueError(f"git source {source.source_id} needs a pinned licenseSha256")
    elif source.kind in {"markdown_dir", "html_dir", "wordpress_wxr", "ghost_json"} and not source.path:
        raise ValueError(f"source {source.source_id} needs path")
    elif source.kind == "rss_atom" and not (source.path or source.url):
        raise ValueError(f"source {source.source_id} needs path or url")


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item for item in value):
        return ()
    return tuple(value)


def _run_git(cwd: Path, *args: str) -> None:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")


def _git_output(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _license_sha256(root: Path) -> str:
    return _sha256_file(_find_license_file(root))


def _find_license_file(root: Path) -> Path:
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
        path = root / name
        if path.exists():
            return path
    raise FileNotFoundError(f"synced source has no license file: {root}")


def _verified_license_sha256(root: Path, source: SourceSpec) -> str:
    actual = _license_sha256(root)
    if actual != source.license_sha256:
        raise RuntimeError(f"source {source.source_id} license hash does not match the whitelist")
    return actual


def _markdown_metadata(text: str) -> dict[str, str]:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return {}
    metadata: dict[str, str] = {}
    for line in match.group(0).splitlines()[1:-1]:
        key, separator, value = line.partition(":")
        if separator and key.strip() in {"title", "date", "published"}:
            metadata["date" if key.strip() == "published" else key.strip()] = value.strip().strip("'\"")
    return metadata


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    sentences = [sentence.strip() for sentence in SENTENCE_BOUNDARY_RE.split(paragraph) if sentence.strip()]
    pieces: list[str] = []
    buffer = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if buffer:
                pieces.append(buffer)
                buffer = ""
            pieces.extend(sentence[index : index + max_chars] for index in range(0, len(sentence), max_chars))
        elif buffer and len(buffer) + len(sentence) > max_chars:
            pieces.append(buffer)
            buffer = sentence
        else:
            buffer += sentence
    if buffer:
        pieces.append(buffer)
    return pieces


def _looks_like_code_line(line: str) -> bool:
    if not line:
        return False
    if "$$" in line or "\\begin{" in line or "\\end{" in line:
        return True
    if re.match(r"^(?:import|from|class|def|func|package|const|let|var|SELECT|INSERT|UPDATE|DELETE)\b", line):
        return True
    symbols = sum(character in "{}[]();=<>|&$" for character in line)
    han = len(HAN_RE.findall(line))
    return len(line) >= 24 and symbols >= 5 and han / len(line) < 0.1


def _is_navigation_line(line: str) -> bool:
    lowered = line.lower()
    return (
        lowered in {"目录", "返回首页", "上一篇", "下一篇", "table of contents"}
        or lowered.startswith(("tags:", "categories:", "permalink:"))
        or line.startswith(":::")
        or bool(re.fullmatch(r"原文(?:地址|链接)?[:：]?", line))
        or ("微博 | 知乎 | github" in lowered)
        or (line.startswith("李成熙，") and "专注于" in line)
        or bool(re.search(r"QQ群\s*[:：]?\s*\d{5,}", line, re.IGNORECASE))
        or bool(re.search(r"(?:关注|扫码).*公众号", line))
        or lowered in {"我的微博", "我的github", "我的 github"}
        or lowered.startswith("可以关注我的微博")
        or (line.count("|") >= 3 and len(HAN_RE.findall(line)) < 10)
    )


def _internal_repetition_ratio(text: str) -> float:
    paragraphs = [normalize_for_dedupe(item) for item in re.split(r"\n+", text) if len(normalize_for_dedupe(item)) >= 12]
    if not paragraphs:
        return 0.0
    counts = Counter(paragraphs)
    repeated = sum(len(value) * (count - 1) for value, count in counts.items() if count > 1)
    total = sum(len(value) * count for value, count in counts.items())
    return repeated / total if total else 0.0


def _drop_source_paragraphs(text: str, patterns: Sequence[str]) -> str:
    if not patterns:
        return text
    paragraphs = [
        paragraph
        for paragraph in re.split(r"\n\s*\n", text)
        if paragraph.strip() and not any(pattern in paragraph for pattern in patterns)
    ]
    return "\n\n".join(paragraphs).strip()


def _reject(
    rejections: Counter[str],
    samples: list[dict[str, object]],
    source_id: str,
    record_id: str,
    reason: str,
    text: str,
) -> None:
    rejections[f"{source_id}:{reason}"] += 1
    if len(samples) < 200:
        samples.append(
            {
                "sourceId": source_id,
                "recordId": record_id,
                "reason": reason,
                "preview": SPACE_RE.sub(" ", text[:500]).strip(),
            }
        )


def _ensure_nonempty_eval_splits(split_documents: dict[str, list[CorpusDocument]]) -> None:
    if len(split_documents["train"]) < 3:
        return
    for split in ("val", "test"):
        if not split_documents[split]:
            split_documents[split].append(split_documents["train"].pop())


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")) + "\n")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_package_checksums(root: Path) -> int:
    rows: list[str] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "SHA256SUMS"):
        rows.append(f"{_sha256_file(path)}  {path.relative_to(root).as_posix()}")
    (root / "SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return len(rows) + 1


def _render_package_readme(manifest: Mapping[str, object], package_name: str) -> str:
    sources = manifest.get("sources", {})
    source_lines: list[str] = []
    if isinstance(sources, dict):
        for source_id, stats in sorted(sources.items()):
            if not isinstance(stats, dict):
                continue
            source_lines.append(
                f"- `{source_id}`: {stats.get('documents', 0)} 个片段，"
                f"{stats.get('characters', 0)} 字符，许可 `{stats.get('license', '')}`。"
            )
    return f"""# {package_name}

这是已经整理好的中文授权博客训练语料，不是原始网页打包。

## 可直接训练

`training/train.jsonl`、`val.jsonl`、`test.jsonl` 每行严格只有一个 `text` 字段：

```json
{{"text":"连续的中文博客正文片段"}}
```

没有 prompt、system、user、assistant 或 chat template。该数据用于 causal pretraining；后续
`prefix -> completion` 特化仍使用独立数据和只计算 completion token 的 loss。

## 本次规模

- 文档片段：{manifest.get('documents', 0)}
- 字符：{manifest.get('characters', 0)}
- 估算 token：{manifest.get('estimatedTokens', 0)}（训练前必须用最终 tokenizer 重算）
- Corpus fingerprint：`{manifest.get('corpusFingerprint', '')}`

## 来源

{chr(10).join(source_lines)}

完整 URL、作者、固定 commit、许可、文本哈希和变换记录在 `provenance/provenance.jsonl`；
`provenance/deletion-index.jsonl` 可以按来源撤回数据。实际许可证文本在
`provenance/licenses/`，署名说明在 `provenance/ATTRIBUTION.md`。

## 人工复核

先看 `review/review-sample.jsonl`，不要只看统计数字。被过滤样本示例及原因在
`review/rejected-sample.jsonl`。当前包是高质量风格种子，不得宣称已经达到 1 亿 token。

## 传输与校验

远程机器解包后，在本目录运行：

```bash
shasum -a 256 -c SHA256SUMS
```

外层 `.tar.gz.sha256` 用于传输后先验证整个压缩包。发布语料或模型权重前仍需单独做许可复核。
"""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, local_name: str) -> str:
    for child in element:
        if _local_name(child.tag) == local_name:
            return (child.text or "").strip()
    return ""


def _find_text(element: ET.Element, tag: str) -> str:
    if tag.startswith("{"):
        child = element.find(tag)
        return (child.text or "").strip() if child is not None else ""
    return _child_text(element, tag)
