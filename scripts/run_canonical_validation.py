"""Build hash-bound canonical RV30 comparison evidence without provider calls.

Historical Phase 6 and independent-replication inputs are read through explicit external roots.
The script reuses their registered Gamma/LightGBM predictions and fits only fixed post-read
HAR-RV, Ridge and Elastic Net extensions on the same causally separated rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from mds650.canonical_validation import (
    CANONICAL_MODEL_ROLES,
    assert_causal_audit,
    assert_identical_origin_sets,
    build_causal_audit,
    forecast_canonical_fold,
)
from mds650.phase6_evaluation import (
    add_training_volatility_regime,
    phase6_fold_definitions,
    validate_phase6_evaluation_panel,
)
from mds650.temporal_validation import FoldDefinition, split_expanding_fold

_PRIMARY_TIMING = "PRIMARY"
_HISTORICAL_ROLES = ("gamma_glm_confirmatory", "lightgbm_robustness")
_EXTENSION_ROLES = (
    "har_rv_fixed_extension",
    "ridge_fixed_extension",
    "elastic_net_fixed_extension",
)
_INFORMATION_SETS = ("B0v2", "B1v2a", "B2v2")
_OUTPUT_PREDICTION_COLUMNS = (
    "origin_id",
    "asset",
    "session_date",
    "forecast_origin_utc",
    "session_tercile",
    "volatility_regime",
    "rv30",
    "fold",
    "model_role",
    "information_set",
    "forecast",
    "qlike_loss",
    "absolute_error",
    "squared_error",
    "selected_parameters",
    "feature_schema_sha256",
    "timing_variant",
    "analysis_status",
)


@dataclass(frozen=True)
class BlockInputs:
    """Read-only inputs required for one canonical validation block."""

    block: str
    panel: pl.DataFrame
    existing_predictions: pl.DataFrame
    folds: tuple[FoldDefinition, ...]
    guard_minutes: int
    input_hashes: Mapping[str, str]


def _sha256(path: Path) -> str:
    """Return SHA-256 for a regular file.

    Parameters
    ----------
    path
        File to hash.

    Returns
    -------
    str
        Lower-case hexadecimal SHA-256 digest.

    Raises
    ------
    RuntimeError
        If the expected file does not exist.
    """

    if not path.is_file():
        raise RuntimeError("CANONICAL_EVIDENCE_FILE_UNAVAILABLE")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object or fail with a sanitized evidence error."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("CANONICAL_EVIDENCE_JSON_UNAVAILABLE") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("CANONICAL_EVIDENCE_JSON_INVALID")
    return payload


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    """Write a JSON file atomically without overwriting an existing artifact."""

    if path.exists():
        raise RuntimeError("CANONICAL_OUTPUT_ALREADY_EXISTS")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.rename(path)


def validate_roots(*, evidence_root: Path, data_root: Path, output_root: Path) -> None:
    """Validate explicit, non-overlapping external input and output roots.

    Parameters
    ----------
    evidence_root
        Read-only root holding untracked manifests and compact Phase 6 evidence.
    data_root
        Samsung-backed root holding derived Parquet inputs and canonical prediction outputs.
    output_root
        Repository-local root for compact sanitized summaries.

    Returns
    -------
    None
        The function returns only when the three roots are valid and non-overlapping.

    Raises
    ------
    RuntimeError
        If an input root is absent or an output could modify the evidence root.

    Notes
    -----
    Paths are never copied into generated artifacts; only environment-variable logical paths and
    SHA-256 values are recorded.
    """

    evidence = evidence_root.resolve()
    data = data_root.resolve()
    output = output_root.resolve()
    if output == evidence or output.is_relative_to(evidence):
        raise RuntimeError("CANONICAL_EVIDENCE_ROOT_INVALID")
    if not evidence.is_dir() or not data.is_dir():
        raise RuntimeError("CANONICAL_EVIDENCE_ROOT_INVALID")
    if output == data:
        raise RuntimeError("CANONICAL_OUTPUT_ROOT_INVALID")


def reuse_hash_verified_block(block_output: Path) -> dict[str, str] | None:
    """Reuse a completed canonical data block only after its hash matches.

    Parameters
    ----------
    block_output
        Data-root block directory containing a manifest and forecast Parquet.

    Returns
    -------
    dict[str, str] | None
        Reuse status and forecast hash when a complete block exists; otherwise ``None``.

    Raises
    ------
    RuntimeError
        If a completed manifest is malformed or any recorded output hash differs.
    """

    manifest_path = block_output / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = _read_json(manifest_path)
    hashes = manifest.get("output_hashes")
    if manifest.get("status") != "PASS_CANONICAL_VALIDATION" or not isinstance(hashes, dict):
        raise RuntimeError("CANONICAL_OUTPUT_MANIFEST_INVALID")
    for name, expected in hashes.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise RuntimeError("CANONICAL_OUTPUT_MANIFEST_INVALID")
        if _sha256(block_output / name) != expected:
            raise RuntimeError("CANONICAL_OUTPUT_HASH_MISMATCH")
    prediction_hash = hashes.get("predictions.parquet")
    if not isinstance(prediction_hash, str):
        raise RuntimeError("CANONICAL_OUTPUT_MANIFEST_INVALID")
    return {"status": "REUSED_HASH_VERIFIED", "predictions_sha256": prediction_hash}


def _require_hash(path: Path, expected: object) -> str:
    """Verify one pre-recorded input hash and return it."""

    observed = _sha256(path)
    if not isinstance(expected, str) or observed != expected:
        raise RuntimeError("CANONICAL_EVIDENCE_HASH_MISMATCH")
    return observed


def _phase6_inputs(evidence_root: Path) -> BlockInputs:
    """Load and verify immutable Phase 6 canonical inputs."""

    root = evidence_root / "artifacts" / "phase6"
    freeze = _read_json(root / "method_freeze.json")
    preregistration = _read_json(root / "preregistration.json")
    hashes = freeze.get("input_hashes")
    if not isinstance(hashes, dict):
        raise RuntimeError("CANONICAL_EVIDENCE_HASH_CONTRACT_INVALID")
    panel_path = root / "common_panel.parquet"
    prediction_path = root / "oos_predictions.parquet"
    panel_hash = _require_hash(panel_path, hashes.get("common_panel.parquet"))
    prediction_hash = _sha256(prediction_path)
    panel = validate_phase6_evaluation_panel(pl.read_parquet(panel_path), preregistration)
    predictions = pl.read_parquet(prediction_path).filter(
        pl.col("timing_variant") == _PRIMARY_TIMING
    )
    if set(predictions.get_column("model_role").unique().to_list()) != set(_HISTORICAL_ROLES):
        raise RuntimeError("CANONICAL_HISTORICAL_ROLE_CONTRACT_INVALID")
    if set(predictions.get_column("information_set").unique().to_list()) != set(_INFORMATION_SETS):
        raise RuntimeError("CANONICAL_HISTORICAL_INFORMATION_SET_INVALID")
    guard = preregistration.get("models", {}).get("purge_embargo_minutes")
    if not isinstance(guard, int) or guard < 0:
        raise RuntimeError("CANONICAL_TEMPORAL_GUARD_INVALID")
    return BlockInputs(
        block="phase6",
        panel=panel,
        existing_predictions=predictions,
        folds=phase6_fold_definitions(preregistration),
        guard_minutes=guard,
        input_hashes={
            "common_panel.parquet": panel_hash,
            "oos_predictions.parquet": prediction_hash,
            "method_freeze.json": _sha256(root / "method_freeze.json"),
            "preregistration.json": _sha256(root / "preregistration.json"),
        },
    )


def _independent_inputs(evidence_root: Path, data_root: Path) -> BlockInputs:
    """Load and verify immutable independent-replication canonical inputs."""

    evidence = evidence_root / "artifacts" / "independent_replication"
    results = _read_json(evidence / "independent_results.json")
    result_hashes = results.get("hashes")
    if not isinstance(result_hashes, dict):
        raise RuntimeError("CANONICAL_EVIDENCE_HASH_CONTRACT_INVALID")
    derived = data_root / "independent_replication_30" / "derived"
    panel_path = derived / "common_panel_90d.parquet"
    prediction_path = derived / "independent_predictions.parquet"
    panel_hash = _require_hash(panel_path, result_hashes.get("panel"))
    prediction_hash = _require_hash(prediction_path, result_hashes.get("predictions"))
    panel = pl.read_parquet(panel_path).filter(pl.col("common_complete"))
    if "role" not in panel.columns:
        raise RuntimeError("CANONICAL_INDEPENDENT_ROLE_COLUMN_MISSING")
    warmup = panel.filter(pl.col("role") == "warmup")
    target = panel.filter(pl.col("role") == "target")
    if warmup.is_empty() or target.is_empty():
        raise RuntimeError("CANONICAL_INDEPENDENT_PANEL_INVALID")
    train_end = max(warmup.get_column("session_date").cast(pl.String).to_list())
    test_start = min(target.get_column("session_date").cast(pl.String).to_list())
    test_end = max(target.get_column("session_date").cast(pl.String).to_list())
    fold = FoldDefinition(
        fold=1,
        train_end=date.fromisoformat(train_end),
        test_start=date.fromisoformat(test_start),
        test_end=date.fromisoformat(test_end),
    )
    predictions = pl.read_parquet(prediction_path).filter(
        pl.col("timing_variant") == _PRIMARY_TIMING
    )
    if set(predictions.get_column("model_role").unique().to_list()) != set(
        _HISTORICAL_ROLES
    ) or set(predictions.get_column("information_set").unique().to_list()) != set(
        _INFORMATION_SETS
    ):
        raise RuntimeError("CANONICAL_INDEPENDENT_PREDICTION_CONTRACT_INVALID")
    return BlockInputs(
        block="independent_replication",
        panel=panel,
        existing_predictions=predictions,
        folds=(fold,),
        guard_minutes=30,
        input_hashes={
            "common_panel_90d.parquet": panel_hash,
            "independent_predictions.parquet": prediction_hash,
            "independent_results.json": _sha256(evidence / "independent_results.json"),
            "method_freeze.json": _sha256(evidence / "method_freeze.json"),
        },
    )


def _historical_fold_predictions(
    inputs: BlockInputs, *, fold: int, expected_origins: Sequence[str]
) -> pl.DataFrame:
    """Return verified registered predictions for one fold."""

    rows = inputs.existing_predictions.filter(pl.col("fold") == fold)
    if rows.is_empty():
        raise RuntimeError("CANONICAL_HISTORICAL_FOLD_MISSING")
    expected = sorted(expected_origins)
    for role in _HISTORICAL_ROLES:
        information_frames = {
            information_set: rows.filter(
                (pl.col("model_role") == role) & (pl.col("information_set") == information_set)
            )
            for information_set in _INFORMATION_SETS
        }
        shared = assert_identical_origin_sets(information_frames)
        if shared != expected:
            raise RuntimeError("CANONICAL_EVALUATION_ORIGIN_MISMATCH")
    return rows.select(
        *(column for column in _OUTPUT_PREDICTION_COLUMNS if column in rows.columns)
    ).with_columns(pl.lit("HISTORICAL_REGISTERED_REFERENCE").alias("analysis_status"))


def _extension_fold_predictions(
    training: pl.DataFrame,
    testing: pl.DataFrame,
    *,
    fold: int,
    expected_origins: Sequence[str],
) -> tuple[pl.DataFrame, list[dict[str, object]]]:
    """Fit fixed extensions on one causal fold and verify shared origin keys."""

    parts: list[pl.DataFrame] = []
    ledger: list[dict[str, object]] = []
    expected = sorted(expected_origins)
    for role in _EXTENSION_ROLES:
        information_frames: dict[str, pl.DataFrame] = {}
        for information_set in _INFORMATION_SETS:
            part = forecast_canonical_fold(
                training,
                testing,
                role=role,
                information_set=information_set,
                phase6_frozen={},
                fold=fold,
            ).with_columns(
                pl.lit(_PRIMARY_TIMING).alias("timing_variant"),
                pl.lit("POST_READ_FIXED_EXTENSION").alias("analysis_status"),
            )
            information_frames[information_set] = part
            parts.append(part)
            ledger.append(
                {
                    "fold": fold,
                    "model_role": role,
                    "information_set": information_set,
                    "analysis_status": "POST_READ_FIXED_EXTENSION",
                    "selected_parameters": part.get_column("selected_parameters")[0],
                    "status": "RUN",
                }
            )
        if assert_identical_origin_sets(information_frames) != expected:
            raise RuntimeError("CANONICAL_EVALUATION_ORIGIN_MISMATCH")
    return pl.concat(parts).select(*_OUTPUT_PREDICTION_COLUMNS), ledger


def _build_predictions(
    inputs: BlockInputs,
) -> tuple[pl.DataFrame, pl.DataFrame, list[dict[str, object]], list[dict[str, object]]]:
    """Build one hashable canonical prediction table from immutable and extension roles."""

    causal_audit = build_causal_audit(
        inputs.panel,
        inputs.folds,
        model_roles=CANONICAL_MODEL_ROLES,
        target_horizon_minutes=30,
        embargo_minutes=inputs.guard_minutes,
        block=inputs.block,
    )
    assert_causal_audit(causal_audit)
    parts: list[pl.DataFrame] = []
    variant_ledger: list[dict[str, object]] = []
    origin_audit: list[dict[str, object]] = []
    for fold in inputs.folds:
        training, testing = split_expanding_fold(
            inputs.panel,
            fold,
            purge_minutes=inputs.guard_minutes,
            embargo_minutes=inputs.guard_minutes,
        )
        testing, regime_cutpoints = add_training_volatility_regime(training, testing)
        expected_origins = sorted(testing.get_column("origin_id").to_list())
        historical = _historical_fold_predictions(
            inputs, fold=fold.fold, expected_origins=expected_origins
        )
        extensions, extension_ledger = _extension_fold_predictions(
            training, testing, fold=fold.fold, expected_origins=expected_origins
        )
        parts.extend((historical, extensions))
        variant_ledger.extend(extension_ledger)
        for role in _HISTORICAL_ROLES:
            for information_set in _INFORMATION_SETS:
                parameters = (
                    historical.filter(
                        (pl.col("model_role") == role)
                        & (pl.col("information_set") == information_set)
                    )
                    .get_column("selected_parameters")
                    .unique()
                    .sort()
                    .to_list()
                )
                variant_ledger.append(
                    {
                        "fold": fold.fold,
                        "model_role": role,
                        "information_set": information_set,
                        "analysis_status": "HISTORICAL_REGISTERED_REFERENCE",
                        "selected_parameters": parameters,
                        "status": "REUSED_BY_HASH",
                    }
                )
        for role in CANONICAL_MODEL_ROLES:
            role_frames = {
                information_set: pl.concat((historical, extensions)).filter(
                    (pl.col("fold") == fold.fold)
                    & (pl.col("model_role") == role)
                    & (pl.col("information_set") == information_set)
                )
                for information_set in _INFORMATION_SETS
            }
            shared = assert_identical_origin_sets(role_frames)
            if shared != expected_origins:
                raise RuntimeError("CANONICAL_EVALUATION_ORIGIN_MISMATCH")
            origin_audit.append(
                {
                    "block": inputs.block,
                    "fold": fold.fold,
                    "model_role": role,
                    "expected_origin_count": len(expected_origins),
                    "shared_origin_count": len(shared),
                    "status": "PASS",
                    "volatility_regime_cutpoints": regime_cutpoints,
                }
            )
    predictions = (
        pl.concat(parts)
        .select(*_OUTPUT_PREDICTION_COLUMNS)
        .sort(["fold", "model_role", "information_set", "origin_id"])
    )
    key_count = predictions.select(
        pl.struct("fold", "model_role", "information_set", "origin_id").n_unique()
    ).item()
    if key_count != predictions.height:
        raise RuntimeError("CANONICAL_PREDICTION_DUPLICATE_KEY")
    return predictions, causal_audit, variant_ledger, origin_audit


def _write_data_block(
    *, data_root: Path, block: str, predictions: pl.DataFrame, input_hashes: Mapping[str, str]
) -> dict[str, str]:
    """Atomically write one canonical forecast parquet under the data root."""

    block_output = data_root / "canonical_validation_v1" / block
    existing = reuse_hash_verified_block(block_output)
    if existing is not None:
        return existing
    if block_output.exists():
        raise RuntimeError("CANONICAL_OUTPUT_ALREADY_EXISTS")
    temporary = block_output.with_name(block_output.name + f".tmp-{uuid.uuid4().hex}")
    temporary.mkdir(parents=True)
    prediction_path = temporary / "predictions.parquet"
    predictions.write_parquet(prediction_path, compression="zstd")
    output_hashes = {"predictions.parquet": _sha256(prediction_path)}
    manifest = {
        "schema_version": "1.0",
        "status": "PASS_CANONICAL_VALIDATION",
        "block": block,
        "logical_prediction_path": (
            f"MDS650_DATA_ROOT/canonical_validation_v1/{block}/predictions.parquet"
        ),
        "input_hashes": dict(sorted(input_hashes.items())),
        "output_hashes": output_hashes,
        "row_count": predictions.height,
        "personal_paths_emitted": False,
        "secret_values_emitted": False,
    }
    (temporary / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.rename(block_output)
    return {
        "status": "PASS_CANONICAL_VALIDATION",
        "predictions_sha256": output_hashes["predictions.parquet"],
    }


def run_canonical_block(
    *, block: str, evidence_root: Path, data_root: Path, output_root: Path
) -> dict[str, object]:
    """Run one canonical comparison block using fixed, hash-validated inputs.

    Parameters
    ----------
    block
        ``phase6`` or ``independent_replication``.
    evidence_root
        Read-only root holding compact historical artifacts.
    data_root
        Data root holding existing independent-replication panel/predictions and canonical output.
    output_root
        Repository-local compact artifact root.

    Returns
    -------
    dict[str, object]
        Sanitized summary of the completed or hash-reused block.

    Raises
    ------
    RuntimeError
        If roots, hashes, temporal order, origin equality or an existing output contract fail.
    """

    validate_roots(evidence_root=evidence_root, data_root=data_root, output_root=output_root)
    if block == "phase6":
        inputs = _phase6_inputs(evidence_root)
    elif block == "independent_replication":
        inputs = _independent_inputs(evidence_root, data_root)
    else:
        raise RuntimeError("CANONICAL_BLOCK_INVALID")
    repository_block = output_root / block
    data_block = data_root / "canonical_validation_v1" / block
    reused = reuse_hash_verified_block(data_block)
    if reused is not None:
        return {"block": block, **reused}
    if repository_block.exists():
        raise RuntimeError("CANONICAL_OUTPUT_ALREADY_EXISTS")
    predictions, causal_audit, variant_ledger, origin_audit = _build_predictions(inputs)
    data_result = _write_data_block(
        data_root=data_root,
        block=block,
        predictions=predictions,
        input_hashes=inputs.input_hashes,
    )
    _atomic_json(
        repository_block / "origin_set_audit.json",
        {
            "schema_version": "1.0",
            "status": "PASS",
            "block": block,
            "rows": origin_audit,
            "personal_paths_emitted": False,
            "secret_values_emitted": False,
        },
    )
    _atomic_json(
        repository_block / "model_variant_ledger.json",
        {
            "schema_version": "1.0",
            "status": "PASS",
            "block": block,
            "rows": variant_ledger,
            "all_outcomes_retained": True,
            "personal_paths_emitted": False,
            "secret_values_emitted": False,
        },
    )
    causal_path = repository_block / "causal_audit.parquet"
    causal_audit.write_parquet(causal_path, compression="zstd")
    summary = {
        "schema_version": "1.0",
        "status": "PASS_CANONICAL_VALIDATION",
        "block": block,
        "input_hashes": dict(sorted(inputs.input_hashes.items())),
        "prediction_rows": predictions.height,
        "prediction_sha256": data_result["predictions_sha256"],
        "causal_audit_sha256": _sha256(causal_path),
        "logical_prediction_path": (
            f"MDS650_DATA_ROOT/canonical_validation_v1/{block}/predictions.parquet"
        ),
        "model_roles": list(CANONICAL_MODEL_ROLES),
        "information_sets": list(_INFORMATION_SETS),
        "personal_paths_emitted": False,
        "secret_values_emitted": False,
    }
    _atomic_json(repository_block / "summary.json", summary)
    return summary


def _parse_args() -> argparse.Namespace:
    """Parse offline canonical-validation runner arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block", choices=("phase6", "independent_replication"), required=True)
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
        default=Path(os.environ.get("MDS650_DATA_ROOT", r"D:\MDS650")),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/canonical_validation_v1"),
    )
    return parser.parse_args()


def main() -> None:
    """Execute one explicit canonical block and print its sanitized status."""

    args = _parse_args()
    if args.evidence_root is None:
        raise SystemExit("MDS650_EVIDENCE_ROOT_REQUIRED")
    result = run_canonical_block(
        block=args.block,
        evidence_root=args.evidence_root,
        data_root=args.data_root,
        output_root=args.output,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
