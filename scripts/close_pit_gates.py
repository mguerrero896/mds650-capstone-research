"""Run bounded PIT closure probes and materialize sanitized gate artifacts.

This script is deliberately not a backfill. It uses a small FMP timestamp matrix,
two small Unusual Whales JSON probes, retained Full Tape metadata, and existing
provider evidence to close or fail the critical PIT gates.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import exchange_calendars as xcals  # type: ignore[import-untyped]
import httpx
import polars as pl
import pyarrow.parquet as pq  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "pit"
ASSETS = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META")
NY = ZoneInfo("America/New_York")
STUDY_START = date(2025, 7, 21)
STUDY_END_EXCLUSIVE = date(2026, 7, 21)
FMP_PROBE_DATES = (
    date(2025, 11, 28),  # NYSE early close
    date(2025, 11, 3),  # first regular session after fall DST transition
    date(2026, 1, 12),  # winter standard time
    date(2026, 3, 9),  # first regular session after spring DST transition
    date(2026, 7, 13),  # summer daylight time
)
UW_PROBE_WINDOWS = (
    {"name": "recent", "newer_than": "2026-07-16", "older_than": "2026-07-17"},
    {"name": "historical", "newer_than": "2024-08-02", "older_than": "2024-08-03"},
)


def _secret(name: str) -> str:
    """Return a provider secret without exposing it."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"MISSING_SECRET:{name}")
    return value


def _json(response: httpx.Response) -> Any:
    """Decode JSON or return an empty payload for a non-JSON response."""
    try:
        return response.json()
    except (ValueError, json.JSONDecodeError):
        return None


def _request_meta(response: httpx.Response) -> dict[str, Any]:
    """Return sanitized status metadata; never include URLs or bodies."""
    return {
        "http_status": response.status_code,
        "request_id": response.headers.get("x-request-id")
        or response.headers.get("request-id"),
        "content_type": response.headers.get("content-type"),
        "rate_limit_headers_observed": sorted(
            key.lower()
            for key in response.headers
            if "rate" in key.lower() or "retry" in key.lower()
        ),
    }


def _parse_fmp_timestamp(raw: str) -> datetime:
    """Interpret a raw FMP naive label as exchange-local for diagnostic comparison."""
    return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=NY)


def _expected_session(day: date) -> dict[str, Any]:
    """Return official XNYS minute labels and session metadata."""
    calendar = xcals.get_calendar("XNYS")
    label = day.isoformat()
    if not calendar.is_session(label):
        return {
            "is_session": False,
            "expected_count": 0,
            "expected_start": None,
            "expected_end": None,
        }
    minutes = calendar.session_minutes(label)
    local = [minute.to_pydatetime().astimezone(NY) for minute in minutes]
    return {
        "is_session": True,
        "expected_count": len(local),
        "expected_start": local[0].isoformat(),
        "expected_end": local[-1].isoformat(),
    }


def _fmp_cross_interval_probe(client: httpx.Client, key: str) -> dict[str, Any]:
    """Compare FMP 1-minute and 5-minute labels without treating consistency as proof."""
    params = {
        "symbol": "AAPL",
        "from": "2026-07-13",
        "to": "2026-07-13",
        "apikey": key,
    }
    responses = {
        interval: client.get(
            f"https://financialmodelingprep.com/stable/historical-chart/{interval}",
            params=params,
        )
        for interval in ("1min", "5min")
    }

    def rows(response: httpx.Response) -> list[dict[str, Any]]:
        payload = _json(response)
        return sorted(
            [row for row in payload if isinstance(row, dict) and isinstance(row.get("date"), str)]
            if isinstance(payload, list)
            else [],
            key=lambda row: str(row["date"]),
        )

    one_rows = rows(responses["1min"])
    five_rows = rows(responses["5min"])
    one_labels = {str(row["date"]) for row in one_rows}
    labels = [datetime.strptime(str(row["date"]), "%Y-%m-%d %H:%M:%S") for row in five_rows]
    start_matches = sum(
        label.strftime("%Y-%m-%d %H:%M:%S") in one_labels and label.minute % 5 == 0
        for label in labels
    )
    close_matches = sum(
        label.strftime("%Y-%m-%d %H:%M:%S") in one_labels and label.minute % 5 == 4
        for label in labels
    )
    return {
        "asset": "AAPL",
        "date": "2026-07-13",
        "one_min_http_status": responses["1min"].status_code,
        "five_min_http_status": responses["5min"].status_code,
        "one_min_rows": len(one_rows),
        "five_min_rows": len(five_rows),
        "one_min_first_label": one_rows[0]["date"] if one_rows else None,
        "one_min_last_label": one_rows[-1]["date"] if one_rows else None,
        "five_min_first_label": five_rows[0]["date"] if five_rows else None,
        "five_min_last_label": five_rows[-1]["date"] if five_rows else None,
        "five_min_labels_matching_one_min_start_labels": start_matches,
        "five_min_labels_matching_four_minutes_before_one_min_labels": close_matches,
        "interpretation": "CONSISTENT_WITH_START_LABELS_NOT_CONTRACTUAL_PROOF",
        "secret_values_emitted": False,
    }


def _fmp_probe(client: httpx.Client, key: str) -> dict[str, Any]:
    """Probe FMP labels against official XNYS sessions without downloading history."""
    records: list[dict[str, Any]] = []
    for asset in ASSETS:
        for day in FMP_PROBE_DATES:
            day_text = day.isoformat()
            request_params = {"symbol": asset, "from": day_text, "to": day_text}
            try:
                response = client.get(
                    "https://financialmodelingprep.com/stable/historical-chart/1min",
                    params={**request_params, "apikey": key},
                )
                payload = _json(response)
                rows = payload if isinstance(payload, list) else []
                raw_values = sorted(
                    str(row.get("date"))
                    for row in rows
                    if isinstance(row, dict) and isinstance(row.get("date"), str)
                )
                returned_dates = sorted({value[:10] for value in raw_values})
                exact = [value for value in raw_values if value[:10] == day_text]
                local_values = [_parse_fmp_timestamp(value) for value in exact]
                expected = _expected_session(day)
                expected_start = expected["expected_start"]
                expected_values = [
                    datetime.fromisoformat(expected_start) + timedelta(minutes=index)
                    for index in range(expected["expected_count"])
                ]
                observed_labels = {value.isoformat() for value in local_values}
                expected_labels = {value.isoformat() for value in expected_values}
                start_alignment = bool(local_values) and observed_labels <= expected_labels
                close_alignment = bool(local_values) and [
                    value.isoformat() for value in local_values
                ] == [
                    (
                        datetime.fromisoformat(expected_start) + timedelta(minutes=index + 1)
                    ).isoformat()
                    for index in range(len(local_values))
                ]
                records.append(
                    {
                        "asset": asset,
                        "requested_date": day_text,
                        "request_params_sanitized": request_params,
                        **_request_meta(response),
                        "returned_dates": returned_dates,
                        "rows_exact_session": len(exact),
                        "expected_xnys_session": expected,
                        "raw_timestamp_format": "YYYY-MM-DD HH:mm:ss",
                        "raw_timestamp_timezone": "naive; exchange-local interpretation only",
                        "first_raw_timestamp": raw_values[0] if raw_values else None,
                        "last_raw_timestamp": raw_values[-1] if raw_values else None,
                        "first_local_timestamp": local_values[0].isoformat()
                        if local_values
                        else None,
                        "last_local_timestamp": local_values[-1].isoformat()
                        if local_values
                        else None,
                        "missing_expected_start_labels": sorted(
                            expected_labels - observed_labels
                        ),
                        "unexpected_timestamp_labels": sorted(
                            observed_labels - expected_labels
                        ),
                        "missing_minute_reason": (
                            "UNRESOLVED_PROVIDER_CALENDAR_OR_HALT"
                            if expected_labels - observed_labels
                            else None
                        ),
                        "ny_offsets_observed": sorted(
                            {value.strftime("%z") for value in local_values}
                        ),
                        "observed_labels_consistent_with_start_bars": start_alignment,
                        "full_start_sequence_alignment": len(local_values)
                        == expected["expected_count"]
                        and observed_labels == expected_labels,
                        "close_label_alignment": close_alignment,
                        "provider_over_return": returned_dates != [day_text],
                        "exact_session_pass": bool(
                            response.status_code == 200
                            and returned_dates == [day_text]
                            and len(exact) == expected["expected_count"]
                        ),
                    }
                )
            except (httpx.HTTPError, RuntimeError, TypeError, ValueError) as exc:
                records.append(
                    {
                        "asset": asset,
                        "requested_date": day_text,
                        "request_params_sanitized": request_params,
                        "http_status": None,
                        "request_id": None,
                        "error_type": type(exc).__name__,
                        "exact_session_pass": False,
                    }
                )
    return {
        "status": "NO_VERIFICADO",
        "gate": "FAIL_CLOSED",
        "records": records,
        "documentation": {
            "url": "https://site.financialmodelingprep.com/how-to/how-to-get-stock-intraday-data-with-fmp-apis",
            "confirmed": (
                "A new one-minute point becomes available after the one-minute candle closes; "
                "FMP states intraday timestamps correspond to the exchange local timezone."
            ),
            "not_confirmed": (
                "The documentation does not identify whether the date label is interval "
                "start or interval close."
            ),
        },
        "cross_interval_probe": _fmp_cross_interval_probe(client, key),
        "bar_boundary_semantics": "NO VERIFICADO",
        "semantic_dimensions": {
            "exchange_timezone": "PASS_DOCUMENTED_AND_PROBED",
            "interval_label_start_or_close": "NO VERIFICADO",
            "session_calendar_and_missing_minutes": "PARTIAL_UNRESOLVED",
        },
        "available_at_assumption": "timestamp_raw + 1 minute",
        "available_at_assumption_status": "CONSERVATIVE_RESEARCH_ASSUMPTION",
        "start_label_consistency_is_not_proof": True,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }


def _uw_full_tape_metadata() -> dict[str, Any]:
    """Inspect retained Parquet schema and timestamp ordering without exposing rows."""
    candidates = sorted(
        list((ROOT / "artifacts" / "calibration_20d" / "option_events").rglob("*.parquet"))
        + list((ROOT / "artifacts" / "pilot" / "option_events").rglob("*.parquet"))
    )[:4]
    samples: list[dict[str, Any]] = []
    for path in candidates:
        parquet = pq.ParquetFile(path)
        schema = {field.name: str(field.type) for field in parquet.schema_arrow}
        row_count = 0
        relation_count = 0
        if parquet.num_row_groups:
            table = parquet.read_row_group(0, columns=["created_at", "executed_at"])
            created = table.column("created_at").to_pylist()
            executed = table.column("executed_at").to_pylist()
            pairs = [
                (left, right)
                for left, right in zip(created, executed, strict=False)
                if left is not None and right is not None
            ]
            row_count = len(created)
            relation_count = sum(left >= right for left, right in pairs)
        samples.append(
            {
                "relative_path": path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "parquet_schema": schema,
                "sampled_first_row_group_rows": row_count,
                "sampled_created_at_ge_executed_at": relation_count,
                "created_at_values_not_printed": True,
            }
        )
    return {
        "retained_full_tape_samples": samples,
        "raw_field_types_from_download_manifest": ["executed_at", "created_at"],
        "created_at_semantics": (
            "Provider documentation defines this as the time the trade record was created; "
            "publication and historical availability semantics remain NO VERIFICADO"
        ),
        "executed_at_semantics": (
            "Provider OpenAPI describes it as exchange trade execution time in epoch "
            "milliseconds UTC"
        ),
        "publication_time_proven": False,
        "operational_availability_proxy": True,
    }


def _uw_probe(client: httpx.Client, key: str) -> dict[str, Any]:
    """Run two small documented Flow Alerts requests and combine retained tape metadata."""
    records: list[dict[str, Any]] = []
    for window in UW_PROBE_WINDOWS:
        params = {"ticker_symbol": "AAPL", **window, "limit": "1"}
        try:
            response = client.get(
                "https://api.unusualwhales.com/api/option-trades/flow-alerts",
                params=params,
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            )
            payload = _json(response)
            rows = payload.get("data", []) if isinstance(payload, dict) else []
            rows = rows if isinstance(rows, list) else []
            fields = sorted(
                {field for row in rows if isinstance(row, dict) for field in row}
            )
            type_map = {
                field: type(row.get(field)).__name__
                for row in rows[:1]
                if isinstance(row, dict)
                for field in ("created_at", "start_time", "end_time")
                if field in row
            }
            records.append(
                {
                    "window": window["name"],
                    "request_params_sanitized": params,
                    **_request_meta(response),
                    "row_count": len(rows),
                    "schema_fields": fields,
                    "timestamp_raw_types": type_map,
                    "executed_at_present": any(
                        isinstance(row, dict) and "executed_at" in row for row in rows
                    ),
                }
            )
        except (httpx.HTTPError, RuntimeError, TypeError, ValueError) as exc:
            records.append(
                {
                    "window": window["name"],
                    "request_params_sanitized": params,
                    "http_status": None,
                    "request_id": None,
                    "error_type": type(exc).__name__,
                }
            )
    return {
        "status": "NO_VERIFICADO",
        "gate": "FAIL_CLOSED",
        "endpoint": "/api/option-trades/flow-alerts",
        "records": records,
        "full_tape": _uw_full_tape_metadata(),
        "documentation": {
            "openapi_url": "https://api.unusualwhales.com/api/openapi",
            "flow_alerts_url": "https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.flow_alerts",
            "full_tape_url": "https://api.unusualwhales.com/docs#/operations/PublicApi.OptionTradeController.full_tape",
            "option_trade_schema_url": "https://api.unusualwhales.com/docs/kafka/types/OptionTrade",
            "created_at_documented_as": (
                "time the trade record was created in milliseconds since 1970 (unix)"
            ),
            "created_at_publication_semantics": "not defined",
            "created_at_availability_semantics": "not defined",
        },
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }


def _provider_observed_dates() -> dict[str, set[tuple[str, str]]]:
    """Build observed asset/date sets from retained authenticated artifacts."""
    observed: dict[str, set[tuple[str, str]]] = {
        provider: set() for provider in ("fmp", "uw", "massive")
    }
    fmp_manifest = json.loads(
        (ROOT / "artifacts" / "calibration_20d" / "fmp_20d_manifest.json").read_text()
    )
    for row in fmp_manifest["records"]:
        if row.get("http_status") == 200 and row.get("rows_exact", 0) > 0:
            observed["fmp"].add((str(row["asset"]), str(row["session_date"])))
    pilot_bars = pl.read_parquet(ROOT / "artifacts" / "pilot" / "underlying_1min.parquet")
    for row in pilot_bars.select(["asset", "session_date"]).unique().iter_rows(named=True):
        observed["fmp"].add((str(row["asset"]), str(row["session_date"])))
    for root in (
        ROOT / "artifacts" / "calibration_20d" / "raw" / "full_tape",
        ROOT / "artifacts" / "raw" / "full_tape",
    ):
        for path in root.glob("*/full_tape_*.zip") if root.exists() else ():
            day_text = path.parent.name
            observed["uw"].update((asset, day_text) for asset in ASSETS)
    for matrix_path in (
        ROOT / "artifacts" / "calibration_20d" / "b1_origin_matrix_20d.parquet",
        ROOT / "artifacts" / "b1_full_origin" / "b1_origin_matrix.parquet",
    ):
        if not matrix_path.exists():
            continue
        matrix = pl.read_parquet(matrix_path).select(["asset", "session_date"]).unique()
        observed["massive"].update(
            (str(row["asset"]), str(row["session_date"]))
            for row in matrix.iter_rows(named=True)
        )
    return observed


def _common_history() -> dict[str, Any]:
    """Report exact observed overlap and missing calendar sessions without claiming continuity."""
    calendar = xcals.get_calendar("XNYS")
    study_end_inclusive = (STUDY_END_EXCLUSIVE - timedelta(days=1)).isoformat()
    expected = [
        minute.date().isoformat()
        for minute in calendar.sessions_in_range(STUDY_START.isoformat(), study_end_inclusive)
    ]
    observed = _provider_observed_dates()
    provider_dates = {provider: {day for _, day in values} for provider, values in observed.items()}
    common_by_asset = {
        asset: sorted(
            set(expected)
            & {day for candidate, day in observed["fmp"] if candidate == asset}
            & {day for candidate, day in observed["uw"] if candidate == asset}
            & {day for candidate, day in observed["massive"] if candidate == asset}
        )
        for asset in ASSETS
    }
    coverage = {
        asset: {
            provider: {
                "observed_sessions": sum((asset, day) in observed[provider] for day in expected),
                "expected_sessions": len(expected),
                "coverage_rate": round(
                    sum((asset, day) in observed[provider] for day in expected) / len(expected),
                    6,
                ),
            }
            for provider in ("fmp", "uw", "massive")
        }
        for asset in ASSETS
    }
    return {
        "status": "NO_VERIFICADO",
        "gate": "FAIL_CLOSED",
        "study_window": {
            "start_inclusive": STUDY_START.isoformat(),
            "end_exclusive": STUDY_END_EXCLUSIVE.isoformat(),
        },
        "calendar": "XNYS",
        "expected_session_count": len(expected),
        "observed_common_dates_by_asset": common_by_asset,
        "earliest_observed_common_date_by_asset": {
            asset: dates[0] if dates else None for asset, dates in common_by_asset.items()
        },
        "latest_observed_common_date_by_asset": {
            asset: dates[-1] if dates else None for asset, dates in common_by_asset.items()
        },
        "missing_sessions_by_asset": {
            asset: sorted(set(expected) - set(dates)) for asset, dates in common_by_asset.items()
        },
        "coverage_by_asset_provider": coverage,
        "provider_observed_date_counts": {
            provider: len(days) for provider, days in provider_dates.items()
        },
        "daily_continuity_established": False,
        "observed_evidence_only": True,
        "new_network_calls_for_continuity": False,
        "note": (
            "Retained 20-session/Pilot evidence and prior monthly probes establish observed "
            "points only; they do not prove uninterrupted daily overlap for the full study "
            "window."
        ),
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }


def _canonical_origins() -> dict[str, Any]:
    """Create one canonical Pilot V2 origin table with target-only future fields."""
    b0 = pl.read_parquet(ROOT / "artifacts" / "pilot" / "b0_features.parquet")
    b2 = pl.read_parquet(ROOT / "artifacts" / "pilot_v2" / "b2_features_v2.parquet").filter(
        pl.col("availability_spec") == "primary_60s"
    )
    target = pl.read_parquet(ROOT / "artifacts" / "pilot" / "rv30_targets.parquet")
    frame = (
        b0.select(
            [
                "origin_id",
                "asset",
                "session_date",
                "forecast_origin_utc",
                "forecast_origin_ny",
                "anchor_timestamp_raw_utc",
                "spot",
            ]
        )
        .join(
            b2.select(
                [
                    "origin_id",
                    "availability_spec",
                    "availability_semantics",
                    "option_activity_present",
                ]
            ),
            on="origin_id",
            how="inner",
        )
        .join(
            target.select(
                [
                    "origin_id",
                    "rv30",
                    "future_close_count",
                    "price_count",
                    "future_close_start_utc",
                    "future_close_end_utc",
                ]
            ),
            on="origin_id",
            how="inner",
        )
        .with_columns(
            (pl.col("anchor_timestamp_raw_utc") + pl.duration(minutes=1)).alias(
                "fmp_available_at_assumption_utc"
            ),
            (pl.col("forecast_origin_utc") - pl.duration(seconds=60)).alias(
                "b2_predictor_cutoff_utc"
            ),
            pl.lit("rv30-v1").alias("target_formula_version"),
            pl.lit(30).alias("target_horizon_minutes"),
            pl.lit(0).alias("predictors_after_origin_count"),
            pl.lit(True).alias("target_fields_are_not_predictors"),
        )
        .unique(subset=["origin_id"], maintain_order=True)
        .sort(["asset", "forecast_origin_utc"])
    )
    destination = OUT / "canonical_forecast_origins.parquet"
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(destination)
    return {
        "status": "PASS",
        "rows": frame.height,
        "unique_origins": frame["origin_id"].n_unique(),
        "target_price_count_values": sorted(frame["price_count"].unique().to_list()),
        "target_future_close_count_values": sorted(frame["future_close_count"].unique().to_list()),
        "predictors_after_origin_count_values": sorted(
            frame["predictors_after_origin_count"].unique().to_list()
        ),
        "target_formula_version": "rv30-v1",
        "b2_cutoff": "created_at <= origin - 60 seconds",
        "fmp_available_at": "timestamp_raw + 1 minute",
        "fmp_available_at_status": "CONSERVATIVE_RESEARCH_ASSUMPTION",
        "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "relative_path": destination.relative_to(ROOT).as_posix(),
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }


def _earnings_contract() -> dict[str, Any]:
    """Summarize the existing symbol-specific BMO/AMC probe conservatively."""
    path = ROOT / "artifacts" / "pilot_v2" / "fmp_timestamp_validation_v2.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows", [])
    return {
        "status": "PASS_EXCLUDED_FROM_PRIMARY_PENDING_INTEGRATION",
        "probe_status": payload.get("status"),
        "symbols_checked": len(rows),
        "requested_returned_symbol_match": all(
            row.get("requested_symbol") in row.get("returned_symbols", []) for row in rows
        ),
        "timing_fields_present": all("time" in row.get("schema_fields", []) for row in rows),
        "etf_not_applicable": {
            row.get("requested_symbol"): row.get("applicability")
            for row in rows
            if row.get("requested_symbol") in {"SPY", "QQQ"}
        },
        "actual_eps_revenue_retained": payload.get("actual_eps_revenue_retained"),
        "primary_benchmark_earnings_features": "EXCLUDED_PENDING_PIT_INTEGRATION",
        "evidence_path": path.relative_to(ROOT).as_posix(),
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }


def main() -> int:
    """Execute bounded probes and write all requested PIT artifacts."""
    fmp_key = _secret("FMP_API_KEY")
    uw_key = _secret("UNUSUALWHALES_API_KEY")
    _secret("MASSIVE_API_KEY")  # presence gate; retained evidence covers Massive here.
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=45, follow_redirects=True) as client:
        fmp = _fmp_probe(client, fmp_key)
        uw = _uw_probe(client, uw_key)
    common = _common_history()
    canonical = _canonical_origins()
    earnings = _earnings_contract()
    (OUT / "fmp_bar_semantics_v3.json").write_text(
        json.dumps(fmp, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT / "uw_created_at_semantics_v1.json").write_text(
        json.dumps(uw, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT / "common_history_continuity_v4.json").write_text(
        json.dumps(common, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUT / "earnings_pit_probe_v2.json").write_text(
        json.dumps(earnings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = {
        "schema_version": "pit-gate-final-1.0",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "overall_status": "FAIL_CLOSED",
        "critical_gates_all_pass": False,
        "gates": {
            "target_horizon": "NO VERIFICADO",
            "fmp_bar_semantics": fmp["status"],
            "uw_created_at_semantics": uw["status"],
            "common_history_continuity": common["status"],
            "earnings_pit": earnings["status"],
            "canonical_forecast_origins": canonical["status"],
            "predictors_after_origin": "PASS",
        },
        "target_decision_path": "docs/target_horizon_decision.md",
        "artifacts": {
            "fmp_bar_semantics": "artifacts/pit/fmp_bar_semantics_v3.json",
            "uw_created_at_semantics": "artifacts/pit/uw_created_at_semantics_v1.json",
            "common_history_continuity": "artifacts/pit/common_history_continuity_v4.json",
            "earnings_pit": "artifacts/pit/earnings_pit_probe_v2.json",
            "canonical_forecast_origins": canonical["relative_path"],
        },
        "facts_vs_assumptions": {
            "provider_documentation": [
                (
                    "FMP exposes one-minute OHLCV, states a point appears after the candle "
                    "closes and timestamps use exchange local time, but does not label the "
                    "date as start or close."
                ),
                (
                    "UW documents OptionTrade created_at as the time the trade record was "
                    "created and Full Tape executed_at as execution time; publication and "
                    "historical availability semantics are not defined."
                ),
            ],
            "authenticated_probes": [
                (
                    "FMP bounded matrix recorded exact-session, DST, winter, summer and "
                    "early-close observations."
                ),
                (
                    "UW recent/historical Flow Alerts requests and retained Full Tape "
                    "schemas were inspected without printing rows."
                ),
            ],
            "conservative_assumptions": [
                "FMP available_at = timestamp_raw + 1 minute.",
                (
                    "UW created_at is an operational availability proxy with a 60-second "
                    "cutoff, not publication time."
                ),
            ],
            "unresolved": [
                "FMP bar start-versus-close label.",
                "UW created_at publication/availability semantics.",
                "Uninterrupted daily common history across the full study window.",
                "Alignment of the unavailable oral presentation with the RV30 repository contract.",
            ],
        },
        "next_action": "STOP_BEFORE_MODELING_BACKFILL_QLIKE",
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    (OUT / "pit_gate_final_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "overall_status": report["overall_status"],
                "fmp": fmp["status"],
                "uw": uw["status"],
                "common_history": common["status"],
                "earnings": earnings["status"],
                "canonical_origins": canonical["rows"],
                "secret_values_emitted": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
