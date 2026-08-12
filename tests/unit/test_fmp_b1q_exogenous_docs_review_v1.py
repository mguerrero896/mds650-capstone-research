"""Tests for the target-blind FMP B1Q documentation boundary."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

import pytest

MODULE_NAME = "mds650.fmp_b1q_exogenous_docs_review_v1"


class _FmpB1qDocsReview(Protocol):
    """Public surface used by this focused contract test."""

    def build_fmp_b1q_exogenous_docs_review_v1(self) -> dict[str, object]:
        """Return the fixed, documentation-only B1Q evidence review."""

    def validate_fmp_b1q_exogenous_docs_review_v1(self, review: Mapping[str, object]) -> None:
        """Reject a changed self-hash or any attempted gate upgrade."""

    def write_fmp_b1q_exogenous_docs_review_v1(self, output_path: Path) -> Path:
        """Write an immutable review or preserve a byte-identical replay."""


def _module() -> _FmpB1qDocsReview:
    """Load the production module after explicitly proving it exists."""
    assert importlib.util.find_spec(MODULE_NAME) is not None, (
        "FMP B1Q exogenous documentation review v1 is required"
    )
    return cast(_FmpB1qDocsReview, importlib.import_module(MODULE_NAME))


def _canonical_sha256(document: Mapping[str, object]) -> str:
    """Calculate a semantic hash independently of production code."""
    rendered = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def test_docs_review_records_endpoint_facts_but_keeps_b1q_unresolved() -> None:
    """Endpoint/cycle documentation must never be mistaken for PIT provenance."""
    review = _module().build_fmp_b1q_exogenous_docs_review_v1()

    assert review["status"] == "DOCUMENTED_ENDPOINTS_INSUFFICIENT_FOR_B1Q_PIT"
    assert review["treasury_endpoint_status"] == "DOCUMENTED_HISTORICAL_ENDPOINT"
    assert review["treasury_cycle_time_status"] == "DOCUMENTED_TWO_HOURS"
    assert review["dividend_endpoint_status"] == "DOCUMENTED_DECLARATION_DATE_FIELD"
    assert review["dividend_cycle_time_status"] == "DOCUMENTED_ONE_TO_TWO_HOURS"
    assert review["b1q_exogenous_input_provenance_status"] == "UNRESOLVED"
    assert review["safe_to_build_b1q"] is False
    assert review["safe_to_reconcile_existing_results"] == "NO"
    assert review["safe_to_open_or_evaluate_oos"] == "NO"
    assert review["provider_market_data_requests_performed"] is False
    assert review["required_support_claim_ids"] == [
        "FMP_TREASURY_OBSERVATION_DATE_SEMANTICS",
        "FMP_TREASURY_HISTORICAL_AVAILABILITY_OR_REVISION_SEMANTICS",
        "FMP_DIVIDEND_DECLARATION_DATE_SEMANTICS",
        "FMP_DIVIDEND_HISTORICAL_AVAILABILITY_OR_REVISION_SEMANTICS",
    ]
    assert review["semantic_self_hash"] == _canonical_sha256(
        {key: value for key, value in review.items() if key != "semantic_self_hash"}
    )


def test_validator_rejects_rehashed_attempt_to_upgrade_endpoint_docs_into_b1q() -> None:
    """A valid hash cannot turn documentation scope into a source-coverage pass."""
    module = _module()
    review = module.build_fmp_b1q_exogenous_docs_review_v1()
    review["permitted_conclusion"] = (
        "The endpoint documentation proves B1Q point-in-time provenance."
    )
    review["semantic_self_hash"] = _canonical_sha256(
        {key: value for key, value in review.items() if key != "semantic_self_hash"}
    )

    with pytest.raises(ValueError, match="FMP_B1Q_DOCS_REVIEW_POLICY_INVALID"):
        module.validate_fmp_b1q_exogenous_docs_review_v1(review)


def test_validator_rejects_rehashed_secret_like_conclusion() -> None:
    """Sanitization still applies after a caller recomputes a valid self-hash."""
    module = _module()
    review = module.build_fmp_b1q_exogenous_docs_review_v1()
    review["permitted_conclusion"] = "The review has api_key: forbidden and remains unsafe."
    review["semantic_self_hash"] = _canonical_sha256(
        {key: value for key, value in review.items() if key != "semantic_self_hash"}
    )

    with pytest.raises(ValueError, match="FMP_B1Q_DOCS_REVIEW_UNSAFE_CONTENT"):
        module.validate_fmp_b1q_exogenous_docs_review_v1(review)


def test_writer_is_idempotent_and_rejects_divergent_existing_review(tmp_path: Path) -> None:
    """The evidence record must be immutable after its first deterministic write."""
    module = _module()
    output_path = tmp_path / "fmp_b1q_exogenous_docs_review_v1.json"

    assert module.write_fmp_b1q_exogenous_docs_review_v1(output_path) == output_path
    expected = output_path.read_bytes()
    assert module.write_fmp_b1q_exogenous_docs_review_v1(output_path) == output_path
    assert output_path.read_bytes() == expected

    output_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="FMP_B1Q_DOCS_REVIEW_OUTPUT_CONFLICT"):
        module.write_fmp_b1q_exogenous_docs_review_v1(output_path)
