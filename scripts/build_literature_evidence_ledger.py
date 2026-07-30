"""Build a conservative evidence ledger from the verified literature matrix.

The ledger intentionally downgrades claims when only an abstract or publisher
record was available. It never upgrades a DOI lookup into full-text evidence.
"""

# The evidence strings retain source coordinates and audit qualifications verbatim.
# ruff: noqa: E501

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "literature_matrix.csv"
OUTPUT = ROOT / "docs" / "literature_evidence_ledger.csv"

EVIDENCE = {
    "LIT-001": {
        "full_text_status": "VERIFIED_FULL_TEXT",
        "claim_strength_allowed": "STRONG_FULL_TEXT",
        "evidence_location": "arXiv HTML full text",
        "page": "HTML lines 227-253; 254-260; 345-347",
        "section": "5 Does forecast reconciliation help in RV forecasting; 6 Robustness",
        "table_or_figure": "Table 4; Tables 5-7; Figures 5-6",
        "verification_notes": "The HTML exposes the benchmark HAR comparison, QLIKE/MSE results, MCS block bootstrap and the 23/27 and 96.3%-100% counts. Do not transfer its daily target to RV30.",
    },
    "LIT-002": {
        "full_text_status": "VERIFIED_FULL_TEXT",
        "claim_strength_allowed": "STRONG_FULL_TEXT",
        "evidence_location": "Author-provided full-text PDF with Wiley publisher preview via ResearchGate; Wiley DOI record",
        "page": "PDF p. 10 (retrieved text lines 1448-1454 and 1559-1570); pp. 11-12 for robustness tables",
        "section": "3.2 Forecasting results; 3.3 feature-importance and Diebold-Mariano robustness",
        "table_or_figure": "Table 3; Tables 5, 7 and 8; Figure 5",
        "verification_notes": "The corresponding author uploaded the full text and the retrieval exposes Table 3, the train/test procedure, the 13-model comparison, jump-feature ablations and multi-step robustness tables. Its five-minute RV setting supports a candidate comparison, not transfer of its result to MDS650 RV30.",
    },
    "LIT-003": {
        "full_text_status": "VERIFIED_FULL_TEXT",
        "claim_strength_allowed": "STRONG_FULL_TEXT",
        "evidence_location": "Taylor & Francis full-article HTML/search extract",
        "page": "HTML (pagination not exposed by retrieval)",
        "section": "Methods; empirical forecast comparison",
        "table_or_figure": "not recorded by retrieval",
        "verification_notes": "The full-article extract supports option-surface and activity features, HAR comparison, rolling origin construction and named LASSO/Elastic Net/XGBoost/Heston/Bates specifications. Numeric superiority claims remain bounded to the article text.",
    },
    "LIT-004": {
        "full_text_status": "VERIFIED_PUBLISHER_METADATA_ONLY",
        "claim_strength_allowed": "METADATA_ONLY",
        "evidence_location": "Elsevier/Crossref publisher metadata and abstract index",
        "page": "not_available",
        "section": "abstract",
        "table_or_figure": "not_available",
        "verification_notes": "The abstract supports the short-horizon versus long-horizon ML/HAR conclusion; exact model-by-model tables are not treated as verified text.",
    },
    "LIT-005": {
        "full_text_status": "VERIFIED_PUBLISHER_METADATA_ONLY",
        "claim_strength_allowed": "METADATA_ONLY",
        "evidence_location": "INFORMS publisher abstract record",
        "page": "not_available",
        "section": "abstract",
        "table_or_figure": "not_available",
        "verification_notes": "Publisher metadata confirms more than 100 features, five ML algorithms, S&P 100 stocks and out-of-sample comparison; detailed feature/result coordinates are not available in this audit.",
    },
    "LIT-006": {
        "full_text_status": "VERIFIED_FULL_TEXT",
        "claim_strength_allowed": "STRONG_FULL_TEXT",
        "evidence_location": "Federal Reserve FEDS PDF",
        "page": "PDF pp. 1-2",
        "section": "Abstract; empirical design and results sections",
        "table_or_figure": "result tables in the PDF (exact table number pending line-level extraction)",
        "verification_notes": "The PDF states ARFIMA, HAR, THAR, STHAR, MSHAR, XGBoost, deep feed-forward NN, BRNN, LSTM, LSTM-A and GRU, rolling forecasts from 2006 and the regime-switching result. It is explicitly preliminary working-paper evidence.",
    },
    "LIT-007": {
        "full_text_status": "VERIFIED_ABSTRACT_ONLY",
        "claim_strength_allowed": "LIMITED_ABSTRACT",
        "evidence_location": "RePEc/publisher abstract record",
        "page": "not_available",
        "section": "abstract",
        "table_or_figure": "not_available",
        "verification_notes": "The abstract supports shrinkage HAR, LASSO/Elastic Net, cross-market predictors and daily/weekly/monthly horizons; market-specific result tables require full text.",
    },
    "LIT-008": {
        "full_text_status": "VERIFIED_FULL_TEXT",
        "claim_strength_allowed": "STRONG_FULL_TEXT",
        "evidence_location": "Wiley open-access full-article HTML",
        "page": "HTML abstract; Sections 1 and 3.1-3.3 (volume 45, issue 4, pp. 1714-1729)",
        "section": "Abstract; 3.1 Competing Forecasting Models and Evaluation Procedures; 3.3 empirical forecasting exercise",
        "table_or_figure": "Method/evaluation text; exact numerical result-table counts not independently retained",
        "verification_notes": "The open-access article confirms qlikeHAR versus mseHAR and qlikeSHAR versus mseSHAR, 1- and 5-minute RV sampling, 250-2,000-day rolling windows, QLIKE/MSE, and individual/panel DMW tests with Newey-West variance estimation. Exact 99/87-percent counts remain excluded because their result table was not independently retained in the evidence ledger.",
    },
    "LIT-009": {
        "full_text_status": "VERIFIED_PUBLISHER_METADATA_ONLY",
        "claim_strength_allowed": "METADATA_ONLY",
        "evidence_location": "ScienceDirect publisher abstract record",
        "page": "not_available",
        "section": "abstract; introduction extract",
        "table_or_figure": "not_available",
        "verification_notes": "The publisher record supports the delta/vega informed-trading decomposition and Volmageddon association. It is not an RV forecast benchmark and sample/identification details remain unresolved.",
    },
    "LIT-010": {
        "full_text_status": "VERIFIED_FULL_TEXT",
        "claim_strength_allowed": "STRONG_FULL_TEXT",
        "evidence_location": "Wiley full-article HTML",
        "page": "HTML (volume 45, issue 4; printed pp. 1633-1651)",
        "section": "2.5 Artificial Neural Network; 3 Evaluation; 4.1 Data Description; 5.1 Short-Term Forecasts",
        "table_or_figure": "Table 1; Table 2; Table 3; Appendix Tables A.1-A.5",
        "verification_notes": "The article text supports five-minute WTI data, HAR/OLS benchmark, regularization/tree/RF/NN methods, MSFE/DM/MCS evaluation and the reported RF ranking. It is a commodity study, not evidence for equity options.",
    },
}


def main() -> None:
    """Merge matrix metadata with conservative source-text evidence status."""
    with MATRIX.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    fields = [
        "study_id",
        "category",
        "apa7_reference",
        "authors",
        "year",
        "title",
        "venue_or_status",
        "doi_or_stable_url",
        "full_text_status",
        "claim_strength_allowed",
        "evidence_location",
        "page",
        "section",
        "table_or_figure",
        "exact_claim_supported",
        "verification_notes",
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            evidence = EVIDENCE[row["study_id"]]
            writer.writerow(
                {
                    **{field: row.get(field, "") for field in fields if field in row},
                    **evidence,
                    "exact_claim_supported": row["result"],
                }
            )
    print(
        {
            "status": "PASS",
            "rows": len(rows),
            "unresolved_full_text": sum(
                value["full_text_status"] != "VERIFIED_FULL_TEXT" for value in EVIDENCE.values()
            ),
        }
    )


if __name__ == "__main__":
    main()
