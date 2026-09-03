"""Deterministic, evidence-bound API cost estimates for Agent Lab.

Pricing is caller data, not a model catalog.  The helper performs no Provider
call, persistence, comparison, or savings calculation.  A provider bill, when
available, remains a separate receipt from the computed estimate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from urllib.parse import urlsplit

from .contracts.json_schema import ContractValidationError, validate_contract


_REQUEST_CONTRACT = "agent-lab-cost-request.v1.json"
_RECEIPT_CONTRACT = "agent-lab-cost-receipt.v1.json"
_TOKENS_PER_MILLION = Decimal(1_000_000)


class AgentLabCostError(ValueError):
    """The caller did not provide a complete, valid cost evidence request."""


def build_agent_lab_cost_receipt(request: Mapping[str, object]) -> dict[str, object]:
    """Return a deterministic USD estimate without treating it as a bill."""

    payload = dict(request)
    try:
        validate_contract(payload, _REQUEST_CONTRACT)
    except (ContractValidationError, ValueError) as exc:
        raise AgentLabCostError(f"invalid Agent Lab cost request: {exc}") from exc

    pricing = _mapping(payload["pricingIdentity"], label="pricingIdentity")
    usage = _mapping(payload["usage"], label="usage")
    rates = _mapping(pricing["rates"], label="pricingIdentity.rates")
    _validate_published_date(str(pricing["publishedDate"]))
    _validate_source_url(str(pricing["sourceUrl"]))

    counts = {
        "uncachedInput": _token_count(
            usage["uncachedInputTokens"], label="usage.uncachedInputTokens"
        ),
        "cachedInput": _token_count(
            usage["cachedInputTokens"], label="usage.cachedInputTokens"
        ),
        "output": _token_count(usage["outputTokens"], label="usage.outputTokens"),
    }
    if not sum(counts.values()):
        raise AgentLabCostError("usage must contain at least one reported token")

    with localcontext() as context:
        context.prec = 96
        uncached_cost = _cost(
            counts["uncachedInput"],
            _decimal(rates["uncachedInputUsd"], label="uncached input rate"),
        )
        cached_cost = _cost(
            counts["cachedInput"],
            _decimal(rates["cachedInputUsd"], label="cached input rate"),
        )
        output_cost = _cost(
            counts["output"],
            _decimal(rates["outputUsd"], label="output rate"),
        )
        total_cost = uncached_cost + cached_cost + output_cost

    billed = payload.get("billedReceipt")
    if billed is None:
        billing: dict[str, object] = {"status": "not_provided"}
        billing_boundary = (
            "No billed receipt was supplied; billing status remains not_provided."
        )
    else:
        billed_receipt = _mapping(billed, label="billedReceipt")
        billing = {
            "status": "provided",
            "currency": "USD",
            "totalUsd": _decimal_text(
                _decimal(billed_receipt["totalUsd"], label="billed total")
            ),
            "receiptRef": str(billed_receipt["receiptRef"]),
            "receiptSha256": str(billed_receipt["receiptSha256"]),
        }
        billing_boundary = (
            "The billed receipt is preserved separately and is not reconciled or "
            "replaced by the estimate."
        )

    receipt: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-lab-cost-receipt.v1",
        "authority": "pricing_estimate",
        "pricingIdentity": {
            "pricingId": str(pricing["pricingId"]),
            "provider": str(pricing["provider"]),
            "model": str(pricing["model"]),
            "currency": "USD",
            "unit": "per_million_tokens",
            "rates": {
                "uncachedInputUsd": str(rates["uncachedInputUsd"]),
                "cachedInputUsd": str(rates["cachedInputUsd"]),
                "outputUsd": str(rates["outputUsd"]),
            },
            "publishedDate": str(pricing["publishedDate"]),
            "sourceUrl": str(pricing["sourceUrl"]),
            "sourceSha256": str(pricing["sourceSha256"]),
        },
        "usage": {
            "available": True,
            "uncachedInputTokens": counts["uncachedInput"],
            "cachedInputTokens": counts["cachedInput"],
            "outputTokens": counts["output"],
            "sourceRef": str(usage["sourceRef"]),
            "sourceSha256": str(usage["sourceSha256"]),
        },
        "estimate": {
            "uncachedInputCostUsd": _decimal_text(uncached_cost),
            "cachedInputCostUsd": _decimal_text(cached_cost),
            "outputCostUsd": _decimal_text(output_cost),
            "totalCostUsd": _decimal_text(total_cost),
        },
        "billing": billing,
        "boundaries": [
            "This is a deterministic estimate from caller-supplied pricing and "
            "reported usage, not a provider bill.",
            billing_boundary,
            "No savings amount is inferred by this receipt.",
        ],
    }
    receipt["receiptSha256"] = hashlib.sha256(
        _canonical_json(receipt).encode("utf-8")
    ).hexdigest()
    try:
        validate_contract(receipt, _RECEIPT_CONTRACT)
    except ContractValidationError as exc:  # pragma: no cover - internal invariant
        raise RuntimeError(f"Agent Lab cost receipt violated its contract: {exc}") from exc
    return receipt


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise AgentLabCostError(f"{label} must be an object")
    return dict(value)


def _token_count(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AgentLabCostError(f"{label} must be a non-negative integer")
    return value


def _decimal(value: object, *, label: str) -> Decimal:
    if not isinstance(value, str):
        raise AgentLabCostError(f"{label} must be an exact decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise AgentLabCostError(f"{label} is not a decimal amount") from exc
    if not amount.is_finite() or amount < 0:
        raise AgentLabCostError(f"{label} must be finite and non-negative")
    return amount


def _cost(tokens: int, rate_per_million: Decimal) -> Decimal:
    return Decimal(tokens) * rate_per_million / _TOKENS_PER_MILLION


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    # ``Decimal.normalize()`` uses the ambient context and can silently round a
    # value computed under the wider calculation context.  Fixed-point
    # formatting preserves every coefficient digit; trimming only removes
    # insignificant trailing zeroes.
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _validate_published_date(value: str) -> None:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise AgentLabCostError("pricing publishedDate is not a real ISO date") from exc
    if parsed.isoformat() != value:
        raise AgentLabCostError("pricing publishedDate must be canonical YYYY-MM-DD")


def _validate_source_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise AgentLabCostError("pricing sourceUrl must be a credential-free HTTPS URL")


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
