"""Evidence-binding contracts for the canonical RV30 documentation."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLAIMS_PATH = ROOT / "docs" / "canonical_claims_and_limitations.md"
CONCLUSION_PATH = ROOT / "docs" / "canonical_validation_conclusion.md"
MODEL_CARDS = (
    "gamma_glm_rv30.md",
    "har_rv_rv30.md",
    "ridge_rv30.md",
    "elastic_net_rv30.md",
    "lightgbm_rv30.md",
)
REQUIRED_CLAIM_COLUMNS = (
    "claim_id",
    "claim_text",
    "status",
    "evidence_path",
    "metric",
    "model_role",
    "block",
    "limitation",
    "allowed_presentation_context",
)


def _claim_rows() -> list[dict[str, str]]:
    """Parse the compact Markdown claim ledger without an external dependency."""

    lines = CLAIMS_PATH.read_text(encoding="utf-8").splitlines()
    header_index = next(
        index for index, line in enumerate(lines) if line.startswith("| claim_id |")
    )
    header = [cell.strip() for cell in lines[header_index].strip("|").split("|")]
    assert tuple(header) == REQUIRED_CLAIM_COLUMNS
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        assert len(cells) == len(header)
        rows.append(dict(zip(header, cells, strict=True)))
    return rows


def test_every_claim_has_machine_evidence_and_declared_status() -> None:
    """A numerical or qualitative conclusion cannot exist without an evidence path."""

    rows = _claim_rows()

    assert rows
    for row in rows:
        assert row["claim_id"]
        assert row["claim_text"]
        assert row["status"] in {"SUPPORTED", "CONDITIONAL", "NOT_SUPPORTED"}
        assert row["evidence_path"]
        assert (ROOT / row["evidence_path"]).is_file()
        assert row["metric"]
        assert row["model_role"]
        assert row["block"]
        assert row["limitation"]
        assert row["allowed_presentation_context"]


def test_post_read_extensions_are_not_presented_as_registered_evidence() -> None:
    """HAR/Ridge/Elastic-Net remain descriptive post-read extensions everywhere."""

    text = "\n".join(
        [
            CLAIMS_PATH.read_text(encoding="utf-8"),
            CONCLUSION_PATH.read_text(encoding="utf-8"),
            *[
                (ROOT / "docs" / "model_cards" / name).read_text(encoding="utf-8")
                for name in MODEL_CARDS
            ],
        ]
    ).lower()

    assert "post-read fixed extension" in text
    assert "fresh oos" not in text


def test_conclusion_retains_model_family_dependent_decision() -> None:
    """The documentation cannot relabel inconsistent registered models as global evidence."""

    text = CONCLUSION_PATH.read_text(encoding="utf-8")

    assert "MODEL_FAMILY_DEPENDENT" in text
    assert "GLOBAL_EDGE" not in text
