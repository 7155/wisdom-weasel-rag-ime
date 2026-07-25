from __future__ import annotations

from collections.abc import Mapping, Sequence


class AcceptanceAliasError(ValueError):
    """A model-facing acceptance alias cannot be resolved safely."""


def acceptance_alias_map(
    acceptance_criterion_ids: Sequence[object],
) -> dict[str, str]:
    """Map one Task's frozen criterion order to compact model-facing aliases."""

    result: dict[str, str] = {}
    seen: set[str] = set()
    for raw_value in acceptance_criterion_ids:
        criterion_id = str(raw_value or "").strip()
        if not criterion_id or criterion_id in seen:
            continue
        seen.add(criterion_id)
        result[f"AC-{len(result) + 1}"] = criterion_id
    return result


def acceptance_cards(
    acceptance_criterion_ids: Sequence[object],
    requirement_context: Mapping[str, object] | None,
    *,
    accepted_evidence_by_criterion: Mapping[
        str, Sequence[object]
    ] | None = None,
) -> list[dict[str, object]]:
    """Return bounded aliases, statements, and authoritative proof state."""

    aliases = acceptance_alias_map(acceptance_criterion_ids)
    catalog = (
        requirement_context.get("catalog")
        if isinstance(requirement_context, Mapping)
        else None
    )
    raw_criteria = (
        catalog.get("acceptanceCriteria")
        if isinstance(catalog, Mapping)
        else None
    )
    criteria_by_id = {
        str(item.get("criterionId") or ""): item
        for item in raw_criteria or []
        if isinstance(item, Mapping)
    }
    cards: list[dict[str, object]] = []
    for alias, criterion_id in aliases.items():
        criterion = criteria_by_id.get(criterion_id, {})
        raw_proofs = criterion.get("proofs")
        proofs = [
            proof
            for proof in raw_proofs or []
            if isinstance(proof, Mapping)
        ]
        verified_refs = [
            str(proof.get("receiptId") or "").strip()
            for proof in proofs
            if int(proof.get("exitStatus") or 0) == 0
            and str(proof.get("receiptId") or "").strip()
        ]
        for raw_ref in (
            accepted_evidence_by_criterion or {}
        ).get(criterion_id, ()):
            evidence_ref = str(raw_ref or "").strip()
            if evidence_ref and evidence_ref not in verified_refs:
                verified_refs.append(evidence_ref)
        cards.append(
            {
                "acceptance": alias,
                "statement": str(
                    criterion.get("statement") or criterion_id
                ).strip(),
                "verified": bool(verified_refs),
                "evidenceRefs": verified_refs,
            }
        )
    return cards


def resolve_acceptance_aliases(
    aliases: Sequence[object],
    alias_map: Mapping[str, str],
    *,
    field_name: str = "acceptance",
) -> list[str]:
    """Resolve unique AC-n aliases without exposing database identifiers."""

    resolved: list[str] = []
    seen: set[str] = set()
    for raw_value in aliases:
        alias = str(raw_value or "").strip().upper()
        if not alias:
            raise AcceptanceAliasError(f"{field_name} contains an empty alias")
        criterion_id = alias_map.get(alias)
        if criterion_id is None:
            raise AcceptanceAliasError(
                f"{field_name} contains an alias outside the current Task"
            )
        if criterion_id not in seen:
            seen.add(criterion_id)
            resolved.append(criterion_id)
    return resolved


def alias_for_criterion(
    criterion_id: object,
    alias_map: Mapping[str, str],
) -> str | None:
    target = str(criterion_id or "").strip()
    return next(
        (
            alias
            for alias, value in alias_map.items()
            if value == target
        ),
        None,
    )
