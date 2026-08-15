#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path


ROOT_DOCUMENT_BUDGETS = {
    "AGENTS.md": 1_250,
    "PROJECT.md": 900,
    "OUTCOMES.md": 1_300,
    "DECISIONS.md": 1_200,
    "CONTEXT.md": 900,
}

CORE_SKILLS = (
    "alignment-and-decision",
    "implementation-planning",
    "systematic-debugging",
    "test-driven-implementation",
    "orchestrate-session",
    "facilitate-room",
    "independent-review",
    "organize-work-documents",
)

RETIRED_FLOW_NAMES = (
    "implementation-execution",
    "quality-gate",
    "review-feedback-resolution",
    "structured-handoff",
    "work-document-archive",
    "room_define",
    "room_commit",
    "room_collaborate",
)

CURRENT_CONTRACT_DOCS = (
    "AGENTS.md",
    "PROJECT.md",
    "OUTCOMES.md",
    "DECISIONS.md",
    "CONTEXT.md",
    "README.md",
    "ARCHITECTURE.md",
)

LOCAL_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _word_count(text: str) -> int:
    return len(text.split())


def _read_documents(root: Path, errors: list[str]) -> dict[str, str]:
    documents: dict[str, str] = {}
    for relative, budget in ROOT_DOCUMENT_BUDGETS.items():
        path = root / relative
        if not path.is_file():
            errors.append(f"missing root harness document: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        documents[relative] = text
        count = _word_count(text)
        if count > budget:
            errors.append(
                f"{relative} exceeds its bounded context budget: {count} > {budget} words"
            )
    return documents


def _validate_local_links(root: Path, relative: str, text: str, errors: list[str]) -> None:
    source_dir = (root / relative).parent
    for target in LOCAL_LINK_RE.findall(text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        local_target = target.split("#", 1)[0]
        if not local_target:
            continue
        if not (source_dir / local_target).exists():
            errors.append(f"{relative} has a missing local link: {target}")


def validate_project_harness(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    documents = _read_documents(root, errors)

    agents = documents.get("AGENTS.md", "")
    for relative in ("PROJECT.md", "OUTCOMES.md", "CONTEXT.md", "DECISIONS.md"):
        if f"]({relative})" not in agents:
            errors.append(f"AGENTS.md must route progressively to {relative}")

    for skill in CORE_SKILLS:
        if f"`{skill}`" not in agents:
            errors.append(f"AGENTS.md does not route the core Skill: {skill}")
        if not (root / "integrations" / "pi" / "skills" / skill / "SKILL.md").is_file():
            errors.append(f"missing core Skill body: {skill}")

    for relative in CURRENT_CONTRACT_DOCS:
        path = root / relative
        if not path.is_file():
            if relative not in ROOT_DOCUMENT_BUDGETS:
                errors.append(f"missing current contract document: {relative}")
            continue
        text = documents.get(relative)
        if text is None:
            text = path.read_text(encoding="utf-8")
        for retired in RETIRED_FLOW_NAMES:
            if retired in text:
                errors.append(f"{relative} still references retired flow name: {retired}")

    for relative, text in documents.items():
        _validate_local_links(root, relative, text, errors)

    outcomes = documents.get("OUTCOMES.md", "")
    if "release/product-status.json" not in outcomes:
        errors.append("OUTCOMES.md must name the machine-readable release evidence")

    context = documents.get("CONTEXT.md", "")
    for implementation_marker in ("rag_ime/", "control-center-web/", "scripts/", ".py"):
        if implementation_marker in context:
            errors.append(
                f"CONTEXT.md must remain a glossary, found implementation marker: "
                f"{implementation_marker}"
            )

    gitignore = root / ".gitignore"
    if not gitignore.is_file() or "/docs/" not in gitignore.read_text(encoding="utf-8"):
        errors.append("ignored local docs/ history boundary is missing from .gitignore")

    for retired in RETIRED_FLOW_NAMES[:5]:
        if (root / "integrations" / "pi" / "skills" / retired).exists():
            errors.append(f"retired fixed-pipeline Skill directory still exists: {retired}")

    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = validate_project_harness(root)
    if errors:
        print("FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "OK: bounded root context, progressive Skill routing, "
        "and retired-flow cleanup are consistent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
