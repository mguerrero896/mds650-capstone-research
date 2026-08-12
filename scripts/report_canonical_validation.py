"""Report hash-verified canonical RV30 evidence without provider calls.

The runner reads only completed canonical prediction blocks from ``MDS650_DATA_ROOT`` and
compact repository summaries. It recalculates paired QLIKE inference, descriptive calibration,
drift and feature redundancy; it never refits a model or accesses a provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from mds650.canonical_validation import (
    evaluate_canonical_predictions,
    summarize_b2_redundancy,
)

_BLOCKS = ("phase6", "independent_replication")


def _sha256(path: Path) -> str:
    """Return a SHA-256 digest for one evidence file."""

    if not path.is_file():
        raise RuntimeError("CANONICAL_REPORT_INPUT_UNAVAILABLE")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object or raise a sanitized evidence error."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("CANONICAL_REPORT_JSON_UNAVAILABLE") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("CANONICAL_REPORT_JSON_INVALID")
    return payload


def load_hash_verified_predictions(
    *, data_root: Path, output_root: Path, block: str
) -> pl.DataFrame:
    """Load one canonical prediction block only if all recorded hashes agree.

    Parameters
    ----------
    data_root
        Samsung-backed root containing the derived canonical prediction Parquet.
    output_root
        Repository-local root holding compact summary artifacts.
    block
        ``phase6`` or ``independent_replication``.

    Returns
    -------
    polars.DataFrame
        Verified forecast rows with the stable ``block`` label appended.

    Raises
    ------
    RuntimeError
        If the block name, manifest/summary status or any recorded SHA-256 differs.

    Notes
    -----
    The function does not read provider data, does not fit a model and does not trust a file name
    as provenance. Both the data-root manifest and repository summary must agree on the bytes.

    Examples
    --------
    Hash-rejection behavior is covered by
    ``tests/contract/test_canonical_reporting_runner.py``.
    """

    if block not in _BLOCKS:
        raise RuntimeError("CANONICAL_REPORT_BLOCK_INVALID")
    data_block = data_root / "canonical_validation_v1" / block
    repository_block = output_root / block
    prediction_path = data_block / "predictions.parquet"
    manifest = _read_json(data_block / "manifest.json")
    summary = _read_json(repository_block / "summary.json")
    observed = _sha256(prediction_path)
    expected = manifest.get("output_hashes")
    if (
        manifest.get("status") != "PASS_CANONICAL_VALIDATION"
        or summary.get("status") != "PASS_CANONICAL_VALIDATION"
        or not isinstance(expected, Mapping)
        or expected.get("predictions.parquet") != observed
        or summary.get("prediction_sha256") != observed
    ):
        raise RuntimeError("CANONICAL_REPORT_INPUT_HASH_MISMATCH")
    return pl.read_parquet(prediction_path).with_columns(pl.lit(block).alias("block"))


def _positive_float_mapping(payload: object, error_code: str) -> dict[str, float]:
    """Parse a strict mapping of positive finite floats."""

    if not isinstance(payload, Mapping):
        raise RuntimeError(error_code)
    output: dict[str, float] = {}
    for key, value in payload.items():
        if (
            isinstance(value, bool)
            or not isinstance(key, str)
            or not isinstance(value, (int, float))
        ):
            raise RuntimeError(error_code)
        parsed = float(value)
        if not np.isfinite(parsed) or parsed <= 0:
            raise RuntimeError(error_code)
        output[key] = parsed
    return output


def load_frozen_mde(evidence_root: Path) -> tuple[dict[str, float], str]:
    """Load the Phase 6 training-only frozen MDE values and their source hash.

    Parameters
    ----------
    evidence_root
        Read-only root containing the historical Phase 6 method freeze.

    Returns
    -------
    tuple[dict[str, float], str]
        ``delta_b1v2``/``delta_b2v2`` MDE values and SHA-256 of the freeze source.

    Raises
    ------
    RuntimeError
        If the method freeze is unavailable or lacks exactly the two positive frozen MDE values.
    """

    path = evidence_root / "artifacts" / "phase6" / "method_freeze.json"
    freeze = _read_json(path)
    mde = _positive_float_mapping(freeze.get("training_mde"), "CANONICAL_MDE_INVALID")
    if set(mde) != {"delta_b1v2", "delta_b2v2"}:
        raise RuntimeError("CANONICAL_MDE_INVALID")
    return mde, _sha256(path)


def _verify_independent_mde(evidence_root: Path, mde: Mapping[str, float]) -> str:
    """Require the independent result ledger to retain the same frozen thresholds."""

    path = evidence_root / "artifacts" / "independent_replication" / "independent_results.json"
    payload = _read_json(path)
    comparison = payload.get("mde_comparison")
    if not isinstance(comparison, Mapping):
        raise RuntimeError("CANONICAL_INDEPENDENT_MDE_INVALID")
    observed: set[tuple[str, float]] = set()
    for role in ("gamma_glm_confirmatory", "lightgbm_robustness"):
        role_rows = comparison.get(role)
        if not isinstance(role_rows, Mapping):
            raise RuntimeError("CANONICAL_INDEPENDENT_MDE_INVALID")
        for contrast in ("delta_b1v2", "delta_b2v2"):
            row = role_rows.get(contrast)
            if not isinstance(row, Mapping):
                raise RuntimeError("CANONICAL_INDEPENDENT_MDE_INVALID")
            value = _positive_float_mapping(
                {contrast: row.get("mde")}, "CANONICAL_INDEPENDENT_MDE_INVALID"
            )
            observed.add((contrast, value[contrast]))
    expected = {(contrast, value) for contrast, value in mde.items()}
    if observed != expected:
        raise RuntimeError("CANONICAL_INDEPENDENT_MDE_INVALID")
    return _sha256(path)


def _verified_redundancy_panel(
    *, block: str, evidence_root: Path, data_root: Path
) -> tuple[pl.DataFrame, str]:
    """Load one target-blind B2 panel after checking its recorded source hash."""

    if block == "phase6":
        source = evidence_root / "artifacts" / "phase6"
        freeze = _read_json(source / "method_freeze.json")
        hashes = freeze.get("input_hashes")
        panel_path = source / "common_panel.parquet"
        expected = hashes.get("common_panel.parquet") if isinstance(hashes, Mapping) else None
        panel = pl.read_parquet(panel_path)
    elif block == "independent_replication":
        source = evidence_root / "artifacts" / "independent_replication"
        results = _read_json(source / "independent_results.json")
        hashes = results.get("hashes")
        panel_path = (
            data_root / "independent_replication_30" / "derived" / "common_panel_90d.parquet"
        )
        expected = hashes.get("panel") if isinstance(hashes, Mapping) else None
        panel = pl.read_parquet(panel_path)
        if "role" in panel.columns:
            panel = panel.filter(pl.col("role") == "target")
    else:
        raise RuntimeError("CANONICAL_REPORT_BLOCK_INVALID")
    if not isinstance(expected, str) or _sha256(panel_path) != expected:
        raise RuntimeError("CANONICAL_REPORT_PANEL_HASH_MISMATCH")
    if "common_complete" in panel.columns:
        panel = panel.filter(pl.col("common_complete"))
    return panel, _sha256(panel_path)


def _write_bytes_if_equal(path: Path, data: bytes) -> str:
    """Atomically persist deterministic compact evidence or reject a collision."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError("CANONICAL_REPORT_OUTPUT_CONFLICT")
        return _sha256(path)
    temporary = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(data)
    temporary.rename(path)
    return _sha256(path)


def _write_json_if_equal(path: Path, payload: Mapping[str, object]) -> str:
    """Serialize a JSON payload deterministically and return its SHA-256."""

    return _write_bytes_if_equal(
        path, json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )


def _write_parquet_if_equal(path: Path, frame: pl.DataFrame) -> str:
    """Write a compact Parquet table atomically or retain byte-identical evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    frame.write_parquet(temporary, compression="zstd")
    if path.exists():
        if _sha256(path) != _sha256(temporary):
            temporary.unlink()
            raise RuntimeError("CANONICAL_REPORT_OUTPUT_CONFLICT")
        temporary.unlink()
        return _sha256(path)
    temporary.rename(path)
    return _sha256(path)


def report_canonical_validation(
    *, evidence_root: Path, data_root: Path, output_root: Path
) -> dict[str, object]:
    """Generate the canonical RV30 metrics, inference and feature-only diagnostics.

    Parameters
    ----------
    evidence_root
        Read-only root containing prior Phase 6 and independent-replication manifests.
    data_root
        Samsung-backed root containing the hash-verified canonical prediction Parquet files.
    output_root
        Repository-local root for compact, sanitized report artifacts.

    Returns
    -------
    dict[str, object]
        Status, claim eligibility, artifact hashes and input provenance suitable for a handoff.

    Raises
    ------
    RuntimeError
        If input hashes, frozen MDE, report output idempotence or evidence roots are invalid.
    ValueError
        If paired metrics or canonical inference contracts fail.

    Notes
    -----
    The only models represented are hash-reused registered Gamma/LightGBM forecasts and fixed
    post-read HAR/Ridge/Elastic-Net extensions. This routine never trains, tunes or reads a
    provider response.

    Examples
    --------
    ``uv run python scripts/report_canonical_validation.py --input
    artifacts/canonical_validation_v1`` produces compact evidence only after both blocks pass.
    """

    if output_root.resolve().is_relative_to(evidence_root.resolve()):
        raise RuntimeError("CANONICAL_REPORT_OUTPUT_ROOT_INVALID")
    if not evidence_root.is_dir() or not data_root.is_dir():
        raise RuntimeError("CANONICAL_REPORT_INPUT_UNAVAILABLE")
    prediction_frames = [
        load_hash_verified_predictions(data_root=data_root, output_root=output_root, block=block)
        for block in _BLOCKS
    ]
    predictions = pl.concat(prediction_frames).sort(
        ["block", "fold", "model_role", "information_set", "origin_id"]
    )
    mde, mde_source_hash = load_frozen_mde(evidence_root)
    _verify_independent_mde(evidence_root, mde)
    results = evaluate_canonical_predictions(
        predictions,
        bootstrap_seed=650,
        draws=10_000,
        mde_by_contrast=mde,
    )
    contrast_integrity = results.get("contrast_integrity")
    stability_rows = results.get("stability")
    if (
        not isinstance(contrast_integrity, Mapping)
        or not isinstance(stability_rows, list)
        or not all(isinstance(row, Mapping) for row in stability_rows)
    ):
        raise RuntimeError("CANONICAL_REPORT_RESULT_INVALID")
    redundancy: list[dict[str, object]] = []
    panel_hashes: dict[str, str] = {}
    for block in _BLOCKS:
        panel, panel_hash = _verified_redundancy_panel(
            block=block, evidence_root=evidence_root, data_root=data_root
        )
        redundancy.extend(summarize_b2_redundancy(panel, block=block))
        panel_hashes[block] = panel_hash
    metrics_hash = _write_json_if_equal(
        output_root / "metrics.json",
        {
            "schema_version": "1.0",
            "status": "PASS",
            "bootstrap": results["bootstrap"],
            "metrics": results["metrics"],
            "drift": results["drift"],
            "all_signs_retained": results["all_signs_retained"],
            "personal_paths_emitted": False,
            "secret_values_emitted": False,
        },
    )
    contrasts_hash = _write_json_if_equal(
        output_root / "contrasts.json",
        {
            "schema_version": "1.0",
            "status": contrast_integrity.get("status"),
            "contrast_integrity": dict(contrast_integrity),
            "mde_by_contrast": mde,
            "claim_eligibility": results["claim_eligibility"],
            "contrasts": results["contrasts"],
            "all_signs_retained": results["all_signs_retained"],
            "personal_paths_emitted": False,
            "secret_values_emitted": False,
        },
    )
    calibration_hash = _write_json_if_equal(
        output_root / "calibration.json",
        {
            "schema_version": "1.0",
            "status": "PASS",
            "calibration": results["calibration"],
            "registered_models_only_for_claims": True,
            "personal_paths_emitted": False,
            "secret_values_emitted": False,
        },
    )
    redundancy_hash = _write_json_if_equal(
        output_root / "redundancy.json",
        {
            "schema_version": "1.0",
            "status": "PASS",
            "rows": redundancy,
            "target_read": False,
            "personal_paths_emitted": False,
            "secret_values_emitted": False,
        },
    )
    stability_hash = _write_parquet_if_equal(
        output_root / "stability.parquet",
        pl.from_dicts([dict(row) for row in stability_rows]),
    )
    report = {
        "schema_version": "1.0",
        "status": "PASS_CANONICAL_REPORT",
        "claim_eligibility": results["claim_eligibility"],
        "prediction_row_count": predictions.height,
        "input_hashes": {
            "phase6_predictions": _sha256(
                data_root / "canonical_validation_v1" / "phase6" / "predictions.parquet"
            ),
            "independent_predictions": _sha256(
                data_root
                / "canonical_validation_v1"
                / "independent_replication"
                / "predictions.parquet"
            ),
            "phase6_method_freeze": mde_source_hash,
            "phase6_redundancy_panel": panel_hashes["phase6"],
            "independent_redundancy_panel": panel_hashes["independent_replication"],
        },
        "output_hashes": {
            "metrics.json": metrics_hash,
            "contrasts.json": contrasts_hash,
            "calibration.json": calibration_hash,
            "redundancy.json": redundancy_hash,
            "stability.parquet": stability_hash,
        },
        "logical_prediction_paths": [
            "MDS650_DATA_ROOT/canonical_validation_v1/phase6/predictions.parquet",
            "MDS650_DATA_ROOT/canonical_validation_v1/independent_replication/predictions.parquet",
        ],
        "personal_paths_emitted": False,
        "secret_values_emitted": False,
    }
    _write_json_if_equal(output_root / "report_manifest.json", report)
    return report


def _parse_args() -> argparse.Namespace:
    """Parse offline reporting arguments without accepting provider credentials."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path(os.environ["MDS650_EVIDENCE_ROOT"])
        if "MDS650_EVIDENCE_ROOT" in os.environ
        else None,
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(os.environ.get("MDS650_DATA_ROOT", r"D:\\MDS650")),
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("artifacts/canonical_validation_v1"),
    )
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    """Execute the offline canonical reporting pass and print sanitized JSON."""

    args = _parse_args()
    if args.evidence_root is None:
        raise SystemExit("MDS650_EVIDENCE_ROOT_REQUIRED")
    output = args.output if args.output is not None else args.input
    result = report_canonical_validation(
        evidence_root=args.evidence_root,
        data_root=args.data_root,
        output_root=output,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
