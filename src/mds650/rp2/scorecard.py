"""The before/after scorecard: every field measured, or the run does not finish.

The schema in ``configs/rp2_v3_scorecard_fields.json`` says what a rebuild has to report.
This module produces it from the artifacts the run actually wrote, and refuses to emit a
scorecard with a field it could not measure. A missing metric is a hole in the evidence,
and a scorecard that quietly omits one looks exactly like a scorecard that had nothing to
hide.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import numpy as np
import numpy.typing as npt
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


#: The contract this document is written against. A consumer that cannot tell which
#: version it is reading cannot validate it.
SCHEMA_VERSION: Final = "rp2-v3-scorecard-v1.0"


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


def _quantile_where(path: Path, name: str, weight: str, quantile: float) -> float | None:
    """A quantile over the windows that observed something, ignoring the empty ones."""

    values = _column(path, name)
    weights = _column(path, weight)
    if values is None or weights is None:
        return None
    frame = pl.DataFrame({"v": values, "w": weights}).drop_nulls().filter(pl.col("w") > 0)
    if frame.height == 0:
        return None
    result = frame["v"].quantile(quantile)
    return None if result is None else float(result)


#: Latency bin edges, log-spaced from a hundredth of a second to a little over three hours.
#: A quantile of a population cannot be recovered from per-window quantiles - they do not
#: merge - but counts in fixed bins do, so the producer emits the bins and the scorecard adds
#: them. Sixty bins put the resolution near 20 % of the value, which is far finer than the
#: difference the reported tail exists to show.
LATENCY_BIN_EDGES: Final[npt.NDArray[np.float64]] = np.logspace(-2.0, 4.1, 60)


def latency_quantile(counts: npt.NDArray[np.int64], quantile: float) -> float:
    """The quantile of the latencies these bin counts describe.

    `counts` has one entry per bin plus one for everything above the last edge, exactly as
    `numpy.searchsorted(..., side="right")` produces. The value returned is the lower edge of
    the bin the quantile falls in, so it understates rather than overstates the tail, which
    is the safer direction for a number reported as a worst case.
    """

    total = int(counts.sum())
    if total <= 0:
        return 0.0
    target = quantile * total
    cumulative = np.cumsum(counts)
    index = int(np.searchsorted(cumulative, target, side="left"))
    if index == 0:
        return float(LATENCY_BIN_EDGES[0])
    if index >= len(LATENCY_BIN_EDGES):
        return float(LATENCY_BIN_EDGES[-1])
    return float(LATENCY_BIN_EDGES[index - 1])


def latency_histogram(path: Path, prefix: str) -> npt.NDArray[np.int64]:
    """Add every window's latency bins into one histogram of the run's trades.

    A window absent from the panel contributes nothing, and a run whose producer wrote no
    bins yields an empty histogram, which `latency_quantile` reports as zero rather than as
    a tail nobody measured.
    """

    expected = len(LATENCY_BIN_EDGES) + 1
    counts = np.zeros(expected, dtype=np.int64)
    missing: list[int] = []
    for index in range(expected):
        column = _column(path, f"{prefix}{index}")
        if column is None:
            missing.append(index)
            continue
        counts[index] = int(column.fill_null(0).sum())
    if missing:
        # A bin treated as empty because its column is absent is indistinguishable from a
        # bin no trade fell into, and if every column is absent the quantile below reads
        # 0.0 - a panel from an older or truncated producer published as perfect latency.
        # The set is required whole: a producer that emits these emits all of them.
        raise ValueError(
            f"RP2_SCORECARD_LATENCY_BINS_INCOMPLETE:{len(missing)} of {expected} absent, "
            f"first {missing[0]}"
        )
    return counts


def _weighted_mean(path: Path, name: str, weight: str) -> float | None:
    """A mean over observations, not over the windows that happened to contain them."""

    values = _column(path, name)
    weights = _column(path, weight)
    if values is None or weights is None:
        return None
    frame = pl.DataFrame({"v": values, "w": weights}).drop_nulls()
    total = float(frame["w"].sum())
    if total <= 0.0:
        return None
    weighted = float((frame["v"] * frame["w"]).sum())
    return weighted / total


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


def assemble_scorecard(
    run_dir: Path,
    manifest: RunManifest,
    *,
    elapsed_seconds: float | None = None,
    peak_memory_bytes: int = 0,
) -> dict[str, Any]:
    """Measure every field the schema names, from the artifacts this run produced."""

    if elapsed_seconds is None:
        elapsed_seconds = round(sum(step.runtime_seconds for step in manifest.steps), 3)

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
        "schema_version": SCHEMA_VERSION,
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
            # The schema declares a count. The ladder stores the sorted list, and copying
            # it here would emit an array under a field documented as an integer.
            "assets": len(ladder.get("D", {}).get("assets") or []) or None,
            "duplicate_keys": _duplicate_keys(panels["target"]),
            # One count, as the schema declares: session-assets with no tape to read at
            # all. A session whose tape opened and held too little to build a surface from
            # is a thin day, not an outage, and is counted separately by the producer.
            "provider_failures": int(surface.get("session_assets_without_tape") or 0)
            + int(flow.get("session_assets_without_tape") or 0),
            "sparse_session_assets": int(surface.get("session_assets_too_sparse") or 0),
        },
        "b1": {
            "b1_core_coverage": core_coverage,
            # The metric is a median. Averaging per-origin medians is a different number,
            # and on a skewed age distribution it can decide whether the reported
            # freshness clears its target.
            "b1_median_quote_age_s": _quantile(b1_panel, "b1_median_quote_age_s", 0.5),
            # The producer's own per-origin tail, summarised across origins. Taking a
            # quantile of per-origin medians would be a statistic about typical origins:
            # an origin of mostly fresh quotes with a stale tail has a fresh median.
            "b1_p95_quote_age_s": _quantile(b1_panel, "b1_p95_quote_age_s", 0.5),
            "b1_surface_contracts_per_origin": _mean(b1_panel, "b1_contracts"),
            "b1_surface_expiry_coverage": _coverage(b1_coverage, "b1_expiries"),
            # Rows *dropped* for a failed rate or dividend fit. Block 5 drops none: an
            # implausible fit is recorded as NaN and the origin is kept. The share of those
            # nulls is `b1_missing_rate_share` below; counting them here would report
            # retained rows as lost ones.
            "b1_rows_dropped_for_rate_or_dividend": _sum(
                b1_panel, "b1_rows_dropped_for_rate_or_dividend"
            ),
            "b1_post_cutoff_observations": _sum(b1_panel, "b1_post_cutoff_selected"),
            # Contracts appearing twice in a selected snapshot, which is the question the
            # field asks. `b1_quote_duplicates_dropped` counts the superseded observations
            # the collapse removed, which is ordinary and nonzero.
            "b1_duplicate_contracts_per_snapshot": _sum(
                b1_panel, "b1_duplicate_contracts_remaining"
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
            # Weighted by the trades each window actually saw, over the five-minute
            # windows that tile the session. Averaging the thirty-minute per-origin means
            # would give every origin equal weight, count an empty window's encoded zero as
            # an observed latency, and count each trade once per overlapping window.
            "b2_mean_provider_latency_s": _weighted_mean(
                panels["b2"], "b2_counting_mean_latency_s", "b2_counting_trades"
            ),
            # The 95th percentile of the run's record lags, read off the summed bins. A
            # median across windows of their own tails let a window of one trade weigh as
            # much as a window of ninety-nine, and quantiles do not merge that way in any
            # case, so the number was not the 95th percentile of any population.
            "b2_p95_provider_latency_s": latency_quantile(
                latency_histogram(panels["b2"], "b2_latency_bin_"), 0.95
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
            # Wall clock from the start of the run to the moment this scorecard was
            # assembled. Summing the recorded step runtimes would miss the steps that run
            # after it - the scorecard's own, the provenance and the verification - and
            # whatever the run spent between steps.
            "runtime_seconds": elapsed_seconds,
            # Including this process as it stands. The scorecard step's own record is
            # appended after the document is written, so a peak reached while assembling it
            # would otherwise never appear in the figure the document reports.
            "peak_memory_bytes": max(
                [peak_memory_bytes, *(step.peak_memory_bytes for step in manifest.steps)]
            ),
            "input_manifest_sha256": manifest.input_manifest_sha256,
            "model_config_sha256": manifest.model_config_sha256,
            "feature_registry_sha256": manifest.feature_registry_sha256,
            "code_commit": manifest.code_commit,
            # The *content* digests, not the byte digests. A producer stamps its output
            # with the time it wrote it, so the byte digests differ between two identical
            # executions - and this map is inside the scorecard, which is itself an
            # artifact of the run. The byte digests live in `run_manifest.json`, which is
            # where an integrity check belongs.
            "artifact_sha256": {
                name: digest for step in manifest.steps for name, digest in step.content.items()
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
    assert_scorecard_complete(scorecard, required_roles=manifest.roles)
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
    if isinstance(value, float) and not math.isfinite(value):
        # A degenerate fit or an all-null aggregation produces one of these. It is a
        # scalar, so a null check accepts it, and `json.dumps` then writes `NaN` - a token
        # no JSON reader is required to accept - into the document that gates the run.
        return True
    if isinstance(value, Mapping):
        return not value or any(_unmeasured(item) for item in value.values())
    if isinstance(value, list | tuple):
        return not value or any(_unmeasured(item) for item in value)
    return False


def assert_scorecard_complete(
    scorecard: Mapping[str, Any], *, required_roles: Sequence[str] = ("D", "V")
) -> None:
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
    from mds650.rp2.ladder import PRIMARY_MODELS

    leaves = _forecast_leaves(scorecard)
    if not leaves:
        missing.append("forecast:empty")
    # Present families are not the required families. A ladder that omitted one and kept
    # another complete would have passed on whatever happened to exist.
    reported = scorecard.get("forecast", {})
    for family in PRIMARY_MODELS:
        roles = reported.get(family, {})
        if not roles:
            missing.append(f"forecast.{family}:absent")
            continue
        # Every role the run fitted, for every family. Complete D metrics for all three
        # families and no V would otherwise pass, because only emitted leaves are checked.
        for role in required_roles:
            if not roles.get(role):
                missing.append(f"forecast.{family}.{role}:absent")
    for label, values in leaves:
        for field in forecast_fields:
            if _unmeasured(values.get(field)):
                missing.append(f"{label}.{field}:unmeasured")
    calibration = scorecard.get("forecast_calibration", {})
    for field in ("calibration_slope", "calibration_intercept"):
        if _unmeasured(calibration.get(field)):
            missing.append(f"forecast.{field}:unmeasured")
    # The headline pair is a pointer into the matrix, not a substitute for it. Validating
    # only the two scalars let the table omit, say, `ridge_log` on V - which is exactly the
    # comparison the calibration numbers exist to support.
    table = calibration.get("by_role_and_family", {})
    for role in required_roles:
        for family in PRIMARY_MODELS:
            entry = table.get(role, {}).get(family, {})
            for field in ("slope", "intercept"):
                if _unmeasured(entry.get(field)):
                    missing.append(f"forecast_calibration.{role}.{family}.{field}:unmeasured")
    if missing:
        raise ValueError("RP2_SCORECARD_INCOMPLETE:" + ",".join(sorted(missing)))
    assert_scorecard_invariants(scorecard)


#: Fields whose only admissible value is zero. They are zero by construction - the
#: selections are searchsorted at the availability cutoff, and the panel key is unique -
#: which is why a nonzero one is a regression rather than a datum, and why measuring them
#: without checking them would be a counter nobody reads.
_ZERO_INVARIANTS: Final = (
    ("data", "duplicate_keys"),
    ("b1", "b1_post_cutoff_observations"),
    ("b1", "b1_duplicate_contracts_per_snapshot"),
    ("b1", "b1_rows_dropped_for_rate_or_dividend"),
    ("b2", "b2_pit_violation_count"),
)


def assert_scorecard_invariants(scorecard: Mapping[str, Any]) -> None:
    """The counters that must be zero are zero, and the run stops if one is not."""

    breaches = [
        f"{group}.{field}={scorecard.get(group, {}).get(field)}"
        for group, field in _ZERO_INVARIANTS
        if scorecard.get(group, {}).get(field)
    ]
    if breaches:
        raise ValueError("RP2_SCORECARD_INVARIANT_BREACH:" + ",".join(breaches))

    # Zero is a legitimate latency and a legitimate way for a histogram to be absent, and
    # `assert_scorecard_complete` accepts it either way because it is a finite float. A run
    # whose producer emitted no latency bins would therefore have published an unmeasured
    # tail as a measured one, so the pair is checked: trades counted, nothing binned.
    flow = scorecard.get("b2", {})
    counted = flow.get("b2_counted_trades") or flow.get("b2_zero_dte_count") or 0
    if counted and not flow.get("b2_p95_provider_latency_s"):
        raise ValueError(
            "RP2_SCORECARD_LATENCY_TAIL_UNMEASURED:"
            f"{counted} trades counted and no latency binned"
        )


#: Fields the Markdown rendering points at rather than prints, because they vary between
#: two runs that produced the same result.
_RENDER_OMITTED: Final = frozenset({"runtime_seconds", "peak_memory_bytes"})


def render_scorecard(scorecard: Mapping[str, Any]) -> str:
    """The same numbers as Markdown, so the scorecard can be read without a JSON viewer."""

    lines = [
        "# RP2-v3 scorecard",
        "",
        f"Schema `{scorecard.get('schema_version', SCHEMA_VERSION)}`. The run this describes"
        " is named by the directory it sits in and by `run_manifest.json` beside it; the"
        " rendering does not repeat it, so two runs of the same experiment produce the same"
        " document.",
        "",
        f"Code commit `{scorecard['code_commit']}`.",
        "",
    ]
    for group in ("data", "b1", "b2", "engineering"):
        lines += [f"## {group}", "", "| Field | Value |", "| --- | ---: |"]
        for field, value in sorted(scorecard[group].items()):
            # Runtime and peak memory are engineering facts about one execution, not
            # findings. Printing them here would make the rendered scorecard - an artifact
            # whose digest is part of the run's identity - differ between two identical
            # runs. They are in `run_manifest.json`.
            if field in _RENDER_OMITTED:
                lines.append(f"| `{field}` | see `run_manifest.json` |")
                continue
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
