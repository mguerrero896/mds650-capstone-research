"""The before/after scorecard: every field measured, or the run does not finish.

The schema in ``configs/rp2_v3_scorecard_fields.json`` says what a rebuild has to report.
This module produces it from the artifacts the run actually wrote, and refuses to emit a
scorecard with a field it could not measure. A missing metric is a hole in the evidence,
and a scorecard that quietly omits one looks exactly like a scorecard that had nothing to
hide.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import polars as pl

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mds650.rp2.run_manifest import RunManifest

def _config() -> Path:
    """The schema file, in the tree or beside the package once it is installed."""

    in_tree = Path(__file__).resolve().parents[3] / "configs" / "rp2_v3_scorecard_fields.json"
    if in_tree.is_file():
        return in_tree
    return Path(__file__).resolve().parent / "rp2_v3_scorecard_fields.json"


CONFIG: Final = _config()


def required_fields() -> dict[str, tuple[str, ...]]:
    """The schema's groups, read once from the file that states the requirement."""

    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    return {group: tuple(fields) for group, fields in payload["groups"].items()}


def _coverage(payload: Mapping[str, Any], feature: str) -> float | None:
    """The non-null share of one feature, from a block's coverage report.

    Each entry is a small record, not a bare number, so a reader can see the median beside
    the coverage; taking the record for the number is how a share becomes a dict.
    """

    entry = payload.get(feature)
    if isinstance(entry, Mapping):
        value = entry.get("coverage")
        return None if value is None else float(value)
    return None if entry is None else float(entry)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _height(path: Path) -> int | None:
    if not path.is_file():
        return None
    return int(pl.scan_parquet(path).select(pl.len()).collect().item())


def _column(path: Path, name: str) -> pl.Series | None:
    if not path.is_file():
        return None
    schema = pl.scan_parquet(path).collect_schema()
    if name not in schema.names():
        return None
    return pl.scan_parquet(path).select(name).collect()[name]


def _quantile(path: Path, name: str, quantile: float) -> float | None:
    column = _column(path, name)
    if column is None:
        return None
    value = column.drop_nulls().quantile(quantile)
    return None if value is None else float(value)


def _mean(path: Path, name: str) -> float | None:
    column = _column(path, name)
    if column is None:
        return None
    value = column.drop_nulls().mean()
    return None if value is None else float(value)  # type: ignore[arg-type]


def _share(path: Path, name: str, predicate: Callable[[pl.Series], pl.Series]) -> float | None:
    column = _column(path, name)
    if column is None or column.len() == 0:
        return None
    return float(predicate(column).sum() / column.len())


def _sum(path: Path, name: str) -> int | None:
    column = _column(path, name)
    if column is None:
        return None
    return int(column.drop_nulls().sum())


def _null_count(path: Path, name: str) -> int | None:
    column = _column(path, name)
    if column is None:
        return None
    return int(column.null_count() + int(column.is_nan().sum() if column.dtype.is_float() else 0))


def _duplicate_keys(path: Path) -> int | None:
    """Origins that appear twice. The key is asset, session and origin minute."""

    if not path.is_file():
        return None
    frame = pl.scan_parquet(path).select("asset", "session_date", "origin_minute").collect()
    return int(frame.height - frame.unique().height)


def _forecast_block(ladder: Mapping[str, Any], family: str) -> dict[str, Any]:
    """QLIKE levels and the three deltas for one family, read from the ladder artifact."""

    out: dict[str, Any] = {}
    for role in ("D", "V"):
        role_block = ladder.get(role, {})
        models = role_block.get("models", {})
        if family not in models:
            continue
        qlike = models[family].get("qlike", {})
        contrasts = models[family].get("contrasts", {})

        def raw(label: str, contrasts: Mapping[str, Any] = contrasts) -> Mapping[str, Any]:
            entry = contrasts.get(label, {})
            return entry.get("raw", {}) if isinstance(entry, dict) else {}

        out[role] = {
            "qlike_b0": qlike.get("B0"),
            "qlike_b0_b1": qlike.get("B0+B1"),
            "qlike_b0_b1_b2": qlike.get("B0+B1+B2"),
            "delta_b1": raw("delta_b1").get("estimate"),
            "delta_b2_given_b1": raw("delta_b2_given_b1").get("estimate"),
            "delta_total": raw("delta_total").get("estimate"),
            "ci_by_session": {
                label: [raw(label).get("ci_low"), raw(label).get("ci_high")]
                for label in ("delta_b1", "delta_b2_given_b1", "delta_total")
            },
            "mde": {
                label: raw(label).get("mde")
                for label in ("delta_b1", "delta_b2_given_b1", "delta_total")
            },
            "common_mask_sha256": role_block.get("evaluation_mask_sha256"),
        }
    return out


def calibration_table(
    ladder: Mapping[str, Any], roles: Sequence[str], *, information_set: str = "B0+B1+B2"
) -> dict[str, dict[str, dict[str, float]]]:
    """Mincer-Zarnowitz slope and intercept per role and per primary family.

    One family on one role is not the run's calibration. A smooth family can be well
    calibrated where the booster is not, and V can differ from D; reporting a single pair
    hides exactly the comparison the number exists to support. A family the run did not fit
    is absent rather than reported as zero.
    """

    from mds650.rp2.ladder import PRIMARY_MODELS

    table: dict[str, dict[str, dict[str, float]]] = {}
    for role in roles:
        models = ladder.get(role, {}).get("models", {})
        entries: dict[str, dict[str, float]] = {}
        for family in PRIMARY_MODELS:
            calibration = models.get(family, {}).get("calibration", {})
            entry = calibration.get(f"{family}|{information_set}")
            if isinstance(entry, Mapping) and entry.get("slope") is not None:
                entries[family] = {
                    "slope": float(entry["slope"]),
                    "intercept": float(entry["intercept"]),
                }
        if entries:
            table[role] = entries
    return table


def assemble_scorecard(run_dir: Path, manifest: RunManifest) -> dict[str, Any]:
    """Measure every field the schema names, from the artifacts this run produced."""

    from mds650.rp2.feature_registry import coverage_by_feature, feature_map
    from mds650.rp2.panel import panel_paths

    panels = panel_paths(run_dir)
    ladder = _json(run_dir / "rp2_block8_ladder" / "ladder.json")
    inference = _json(run_dir / "rp2_block10_inference" / "inference.json")
    surface = _json(run_dir / "rp2_block5_surface" / "surface_coverage.json")
    flow = _json(run_dir / "rp2_block6_flow" / "flow_coverage.json")
    b1_coverage = surface.get("coverage", {})

    b1_core = feature_map("B1_CORE")
    b1_panel = panels["b1"]
    core_coverage: float | None = None
    if b1_panel.is_file():
        frame = pl.read_parquet(b1_panel)
        present = [name for name in b1_core if name in frame.columns]
        if present:
            core_coverage = min(coverage_by_feature(frame, present).values())

    # Every primary family, on every role the run fitted. The headline pair below is the
    # non-linear family on D, which is the forecast the verdict is read off, but it is a
    # pointer into this table rather than a substitute for it.
    calibration_by_role = calibration_table(ladder, manifest.roles)
    calibration = calibration_by_role.get("D", {}).get("lightgbm_qlike", {})

    scorecard: dict[str, Any] = {
        "run_id": manifest.run_id,
        "code_commit": manifest.code_commit,
        "data": {
            "b0_rows": _height(panels["b0"]),
            "b1_rows": _height(panels["b1"]),
            "b2_rows": _height(panels["b2"]),
            # The rows the contrasts were *evaluated* on, which is the held-out segment,
            # not every row that survived the common mask. Reporting the latter under this
            # name overstates the evaluated sample by the train share.
            "common_evaluation_rows": {
                role: ladder.get(role, {}).get("test_rows") for role in manifest.roles
            },
            "masked_rows_by_role": {
                role: ladder.get(role, {}).get("rows") for role in manifest.roles
            },
            "sessions_by_role": {
                role: ladder.get(role, {}).get("sessions") for role in manifest.roles
            },
            "assets": ladder.get("D", {}).get("assets"),
            "duplicate_keys": _duplicate_keys(panels["target"]),
            "provider_failures": (
                surface.get("session_assets_without_tape"),
                flow.get("session_assets_without_tape"),
            ),
        },
        "b1": {
            "b1_core_coverage": core_coverage,
            "b1_median_quote_age_s": _mean(b1_panel, "b1_median_quote_age_s"),
            "b1_p95_quote_age_s": _quantile(b1_panel, "b1_median_quote_age_s", 0.95),
            "b1_surface_contracts_per_origin": _mean(b1_panel, "b1_contracts"),
            "b1_surface_expiry_coverage": _coverage(b1_coverage, "b1_expiries"),
            # An origin whose implied rate did not survive the plausibility gate carries a
            # null there, and the run has to say how many did.
            "b1_rows_dropped_for_rate_or_dividend": _null_count(b1_panel, "b1_implied_rate"),
            "b1_post_cutoff_observations": _sum(b1_panel, "b1_post_cutoff_selected"),
            "b1_duplicate_contracts_per_snapshot": _mean(
                b1_panel, "b1_quote_duplicates_dropped"
            ),
            "b1_missing_rate_share": (
                None
                if _coverage(b1_coverage, "b1_implied_rate") is None
                else 1.0 - float(_coverage(b1_coverage, "b1_implied_rate") or 0.0)
            ),
        },
        "b2": {
            "b2_pit_violation_count": _sum(panels["b2"], "b2_pit_violations"),
            "b2_zero_dte_count": _sum(panels["b2"], "b2_zero_dte_trades"),
            "b2_mean_provider_latency_s": _mean(panels["b2"], "b2_30m_mean_provider_latency_s"),
            "b2_p95_provider_latency_s": _quantile(
                panels["b2"], "b2_30m_mean_provider_latency_s", 0.95
            ),
            "b2_multileg_share": _mean(panels["b2"], "b2_30m_multileg_premium_share"),
            "b2_empty_window_share": flow.get(
                "empty_window_share_5m",
                _share(panels["b2"], "b2_5m_is_empty_window", lambda column: column > 0),
            ),
            "b2_provider_failure_share": (
                None
                if not flow.get("session_assets_requested")
                else float(len(flow.get("provider_failures", ())))
                / float(flow["session_assets_requested"])
            ),
        },
        "forecast": {
            family: _forecast_block(ladder, family)
            for family in ("gamma_glm", "ridge_log", "lightgbm_qlike")
        },
        "engineering": {
            "runtime_seconds": round(sum(step.runtime_seconds for step in manifest.steps), 3),
            "peak_memory_bytes": max(
                (step.peak_memory_bytes for step in manifest.steps), default=0
            ),
            "input_manifest_sha256": manifest.input_manifest_sha256,
            "model_config_sha256": manifest.model_config_sha256,
            "feature_registry_sha256": manifest.feature_registry_sha256,
            "code_commit": manifest.code_commit,
            "artifact_sha256": {
                name: digest for step in manifest.steps for name, digest in step.artifacts.items()
            },
        },
        "inference_sessions": {
            role: inference.get(role, {}).get("clusters") for role in manifest.roles
        },
    }
    # The forecast group is reported per family, so its required fields are checked inside
    # each family's roles rather than at the top of the group.
    scorecard["forecast_calibration"] = {
        "calibration_slope": calibration.get("slope"),
        "calibration_intercept": calibration.get("intercept"),
        "by_role_and_family": calibration_by_role,
        "headline": "lightgbm_qlike on D at B0+B1+B2",
    }
    assert_scorecard_complete(scorecard)
    return scorecard


def _forecast_leaves(scorecard: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    leaves: list[tuple[str, Mapping[str, Any]]] = []
    for family, roles in scorecard.get("forecast", {}).items():
        for role, values in roles.items():
            leaves.append((f"forecast.{family}.{role}", values))
    return leaves


def _unmeasured(value: Any) -> bool:
    """Whether a value, or anything nested inside it, was never measured.

    Checking only the top level is not enough: `sessions_by_role` is a mapping and
    `provider_failures` is a pair, so a field that measured nothing at all would still be
    a present, non-null container and would pass a shallower check.
    """

    if value is None:
        return True
    if isinstance(value, Mapping):
        return not value or any(_unmeasured(item) for item in value.values())
    if isinstance(value, list | tuple):
        return not value or any(_unmeasured(item) for item in value)
    return False


def assert_scorecard_complete(scorecard: Mapping[str, Any]) -> None:
    """Every field the schema names carries a measured value, in both directions."""

    required = required_fields()
    missing: list[str] = []
    for group in ("data", "b1", "b2", "engineering"):
        present = scorecard.get(group, {})
        for field in required[group]:
            if field not in present:
                missing.append(f"{group}.{field}:absent")
            elif _unmeasured(present[field]):
                missing.append(f"{group}.{field}:unmeasured")
        for field in present:
            if field not in required[group]:
                missing.append(f"{group}.{field}:undeclared")
    forecast_fields = tuple(
        field
        for field in required["forecast"]
        if field not in ("calibration_slope", "calibration_intercept")
    )
    leaves = _forecast_leaves(scorecard)
    if not leaves:
        missing.append("forecast:empty")
    for label, values in leaves:
        for field in forecast_fields:
            if _unmeasured(values.get(field)):
                missing.append(f"{label}.{field}:unmeasured")
    for field in ("calibration_slope", "calibration_intercept"):
        if _unmeasured(scorecard.get("forecast_calibration", {}).get(field)):
            missing.append(f"forecast.{field}:unmeasured")
    if missing:
        raise ValueError("RP2_SCORECARD_INCOMPLETE:" + ",".join(sorted(missing)))


def render_scorecard(scorecard: Mapping[str, Any]) -> str:
    """The same numbers as Markdown, so the scorecard can be read without a JSON viewer."""

    lines = [
        f"# RP2-v3 scorecard - {scorecard['run_id']}",
        "",
        f"Code commit `{scorecard['code_commit']}`.",
        "",
    ]
    for group in ("data", "b1", "b2", "engineering"):
        lines += [f"## {group}", "", "| Field | Value |", "| --- | ---: |"]
        for field, value in sorted(scorecard[group].items()):
            rendered = json.dumps(value) if isinstance(value, dict | list | tuple) else str(value)
            lines.append(f"| `{field}` | {rendered} |")
        lines.append("")
    lines += [
        "## forecast",
        "",
        "| Family | Role | QLIKE B0 | ΔB1 | ΔB2\\|B1 | MDE ΔB1 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for family, roles in sorted(scorecard["forecast"].items()):
        for role, values in sorted(roles.items()):
            lines.append(
                f"| `{family}` | {role} | {values['qlike_b0']:.5f} | {values['delta_b1']:+.5f} "
                f"| {values['delta_b2_given_b1']:+.5f} | {values['mde']['delta_b1']:.5f} |"
            )
    lines += [
        "",
        f"Calibration slope {scorecard['forecast_calibration']['calibration_slope']}, "
        f"intercept {scorecard['forecast_calibration']['calibration_intercept']}.",
        "",
    ]
    return "\n".join(lines)
