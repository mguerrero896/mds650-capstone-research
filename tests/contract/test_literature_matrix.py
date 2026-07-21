"""Contract tests for the verified recent-literature matrix."""

from __future__ import annotations

import csv
from pathlib import Path

MATRIX = Path(__file__).parents[2] / "docs" / "literature_matrix.csv"
REQUIRED_COLUMNS = {
    "study_id",
    "category",
    "apa7_reference",
    "authors",
    "year",
    "title",
    "venue_or_status",
    "doi_or_stable_url",
    "market_and_sample",
    "data_frequency",
    "research_question",
    "predictors",
    "target",
    "exact_models",
    "exact_benchmark",
    "temporal_validation",
    "leakage_controls",
    "metrics",
    "result",
    "limitation",
    "project_implication",
    "verification_status",
}
ALLOWED_CATEGORIES = {
    "ordinary_option_state",
    "unusual_options_flow",
    "intraday_realized_volatility",
    "benchmark_comparison",
}
REQUIRED_MODEL_TOKENS = {
    "HAR": "HAR",
    "HARQ": "HARQ",
    "OLS": "OLS",
    "LASSO": "LASSO",
    "Elastic Net": "Elastic Net",
    "Random Forest": "Random Forest",
    "XGBoost": "XGBoost",
    "LightGBM": "LightGBM",
    "MLP": "MLP",
    "LSTM": "LSTM",
}


def _rows() -> list[dict[str, str]]:
    with MATRIX.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_matrix_has_exactly_ten_recent_empirical_rows() -> None:
    rows = _rows()
    assert len(rows) == 10
    assert {row["study_id"] for row in rows} == {f"LIT-{index:03d}" for index in range(1, 11)}


def test_matrix_schema_and_verification_fields_are_nonempty() -> None:
    with MATRIX.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert set(reader.fieldnames or []) == REQUIRED_COLUMNS
    for row in _rows():
        assert row["category"] in ALLOWED_CATEGORIES
        assert 2023 <= int(row["year"]) <= 2026
        assert row["doi_or_stable_url"].startswith(("https://doi.org/", "https://"))
        for field in REQUIRED_COLUMNS:
            assert row[field].strip(), f"empty {field} for {row['study_id']}"


def test_matrix_has_unique_stable_identifiers_and_no_generic_superiority_claim() -> None:
    rows = _rows()
    assert len({row["doi_or_stable_url"] for row in rows}) == len(rows)
    text = MATRIX.read_text(encoding="utf-8").lower()
    assert "los modelos lineales siguen siendo difíciles de superar" not in text
    assert "hard to beat" not in text


def test_matrix_collectively_names_required_models() -> None:
    text = MATRIX.read_text(encoding="utf-8")
    for label, token in REQUIRED_MODEL_TOKENS.items():
        assert token in text, f"missing exact model token: {label}"
