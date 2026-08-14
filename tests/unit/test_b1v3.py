from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from mds650.b1v3 import (
    B1V3_FEATURES,
    IvObservation,
    build_b1v3_features,
    compute_forward_variance,
    pair_call_put_consensus,
    select_atm_iv,
    select_symmetric_skew,
    summarize_b1v3_coverage,
)


def _observation(
    *,
    expiry: str,
    dte: int,
    strike: float,
    option_type: str,
    iv: float,
    spot: float = 100.0,
    contract_suffix: str = "",
) -> IvObservation:
    contract = f"O:TEST{expiry.replace('-', '')}{option_type[0].upper()}{strike}{contract_suffix}"
    return IvObservation(
        contract=contract,
        expiry=date.fromisoformat(expiry),
        strike=strike,
        option_type=option_type,
        dte=dte,
        spot=spot,
        iv=iv,
        sip_timestamp_ns=1_750_000_000_000_000_000,
        source_request_hash="a" * 64,
    )


def _paired_strike(
    *, expiry: str, dte: int, strike: float, call_iv: float, put_iv: float
) -> list[IvObservation]:
    return [
        _observation(
            expiry=expiry,
            dte=dte,
            strike=strike,
            option_type="call",
            iv=call_iv,
        ),
        _observation(
            expiry=expiry,
            dte=dte,
            strike=strike,
            option_type="put",
            iv=put_iv,
        ),
    ]


def test_consensus_requires_same_expiry_and_strike() -> None:
    rows = [
        *_paired_strike(expiry="2025-09-03", dte=30, strike=95.0, call_iv=0.22, put_iv=0.26),
        _observation(
            expiry="2025-09-03",
            dte=30,
            strike=105.0,
            option_type="call",
            iv=0.24,
        ),
        _observation(
            expiry="2025-10-03",
            dte=60,
            strike=105.0,
            option_type="put",
            iv=0.28,
        ),
    ]

    points = pair_call_put_consensus(rows)

    assert len(points) == 1
    assert points[0].strike == 95.0
    assert points[0].iv == pytest.approx(0.24)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"contract": ""}, "B1V3_CONTRACT_EMPTY"),
        ({"option_type": "invalid"}, "B1V3_OPTION_TYPE_INVALID"),
        ({"dte": 0}, "B1V3_DTE_INVALID"),
        ({"strike": 0.0}, "B1V3_STRIKE_INVALID"),
        ({"spot": 0.0}, "B1V3_SPOT_INVALID"),
        ({"iv": 0.0}, "B1V3_IV_INVALID"),
        ({"sip_timestamp_ns": 0}, "B1V3_SIP_TIMESTAMP_INVALID"),
        ({"source_request_hash": "bad"}, "B1V3_SOURCE_REQUEST_HASH_INVALID"),
    ],
)
def test_consensus_rejects_invalid_observation_fields(
    changes: dict[str, object], code: str
) -> None:
    row = _observation(expiry="2025-09-03", dte=30, strike=100.0, option_type="call", iv=0.25)

    with pytest.raises(ValueError, match=code):
        pair_call_put_consensus([replace(row, **changes)])


def test_consensus_rejects_duplicate_side_and_metadata_mismatch() -> None:
    call = _observation(expiry="2025-09-03", dte=30, strike=100.0, option_type="call", iv=0.25)
    put = _observation(expiry="2025-09-03", dte=31, strike=100.0, option_type="put", iv=0.27)

    with pytest.raises(ValueError, match="B1V3_DUPLICATE_OPTION_SIDE"):
        pair_call_put_consensus([call, replace(call, contract="O:DUPLICATE")])
    with pytest.raises(ValueError, match="B1V3_PAIRED_METADATA_MISMATCH"):
        pair_call_put_consensus([call, put])


def test_atm_interpolates_in_log_moneyness() -> None:
    rows = [
        *_paired_strike(expiry="2025-09-03", dte=30, strike=95.0, call_iv=0.23, put_iv=0.25),
        *_paired_strike(expiry="2025-09-03", dte=30, strike=105.0, call_iv=0.25, put_iv=0.27),
    ]
    points = pair_call_put_consensus(rows)

    result = select_atm_iv(points, spot=100.0)

    assert result is not None
    weight = -math.log(0.95) / (math.log(1.05) - math.log(0.95))
    assert result.iv == pytest.approx(0.24 + weight * 0.02)
    assert result.interpolated is True
    assert result.lower_strike == 95.0
    assert result.upper_strike == 105.0


def test_atm_nearest_fallback_is_bounded() -> None:
    accepted = pair_call_put_consensus(
        _paired_strike(expiry="2025-09-03", dte=30, strike=102.0, call_iv=0.24, put_iv=0.26)
    )
    rejected = pair_call_put_consensus(
        _paired_strike(expiry="2025-09-03", dte=30, strike=103.0, call_iv=0.24, put_iv=0.26)
    )

    accepted_result = select_atm_iv(accepted, spot=100.0)

    assert accepted_result is not None
    assert accepted_result.interpolated is False
    assert select_atm_iv(rejected, spot=100.0) is None


def test_atm_expiry_tie_prefers_earlier_expiry() -> None:
    rows = [
        *_paired_strike(expiry="2025-08-29", dte=25, strike=100.0, call_iv=0.20, put_iv=0.22),
        *_paired_strike(expiry="2025-09-08", dte=35, strike=100.0, call_iv=0.40, put_iv=0.42),
    ]

    result = select_atm_iv(pair_call_put_consensus(rows), spot=100.0)

    assert result is not None
    assert result.expiry == date(2025, 8, 29)
    assert result.iv == pytest.approx(0.21)


def test_atm_rejects_invalid_arguments_and_inconsistent_spot() -> None:
    points = pair_call_put_consensus(
        _paired_strike(expiry="2025-09-03", dte=30, strike=100.0, call_iv=0.24, put_iv=0.26)
    )

    with pytest.raises(ValueError, match="B1V3_SPOT_INVALID"):
        select_atm_iv(points, spot=0.0)
    with pytest.raises(ValueError, match="B1V3_TENOR_ARGUMENT_INVALID"):
        select_atm_iv(points, spot=100.0, target_dte=0)
    with pytest.raises(ValueError, match="B1V3_CONSENSUS_SPOT_MISMATCH"):
        select_atm_iv((replace(points[0], moneyness=0.5),), spot=100.0)
    assert select_atm_iv(points, spot=100.0, target_dte=180, tolerance=1) is None


def test_atm_rejects_ambiguous_dte_for_one_expiry() -> None:
    points = pair_call_put_consensus(
        [
            *_paired_strike(expiry="2025-09-03", dte=30, strike=95.0, call_iv=0.24, put_iv=0.26),
            *_paired_strike(expiry="2025-09-03", dte=30, strike=105.0, call_iv=0.24, put_iv=0.26),
        ]
    )

    with pytest.raises(ValueError, match="B1V3_EXPIRY_DTE_AMBIGUOUS"):
        select_atm_iv((points[0], replace(points[1], dte=31)), spot=100.0)


def test_skew_uses_same_expiry_and_same_option_type_interpolation() -> None:
    expiry = "2025-09-03"
    rows = [
        _observation(expiry=expiry, dte=30, strike=95.0, option_type="put", iv=0.34),
        _observation(expiry=expiry, dte=30, strike=100.0, option_type="put", iv=0.30),
        _observation(expiry=expiry, dte=30, strike=100.0, option_type="call", iv=0.28),
        _observation(expiry=expiry, dte=30, strike=105.0, option_type="call", iv=0.24),
        _observation(expiry="2025-10-03", dte=60, strike=97.5, option_type="put", iv=0.90),
    ]

    result = select_symmetric_skew(rows, expiry=date.fromisoformat(expiry), spot=100.0)

    assert result is not None
    put_weight = (math.log(0.975) - math.log(0.95)) / (math.log(1.0) - math.log(0.95))
    call_weight = (math.log(1.025) - math.log(1.0)) / (math.log(1.05) - math.log(1.0))
    expected_put = 0.34 + put_weight * (0.30 - 0.34)
    expected_call = 0.28 + call_weight * (0.24 - 0.28)
    assert result.put_iv == pytest.approx(expected_put)
    assert result.call_iv == pytest.approx(expected_call)
    assert result.log_skew == pytest.approx(math.log(expected_put / expected_call))
    assert result.put_interpolated is True
    assert result.call_interpolated is True


def test_skew_exact_and_missing_sides_are_deterministic() -> None:
    expiry = date(2025, 9, 3)
    rows = [
        _observation(expiry=expiry.isoformat(), dte=30, strike=97.5, option_type="put", iv=0.32),
        _observation(expiry=expiry.isoformat(), dte=30, strike=102.5, option_type="call", iv=0.26),
    ]

    result = select_symmetric_skew(rows, expiry=expiry, spot=100.0)

    assert result is not None
    assert result.put_interpolated is False
    assert result.call_interpolated is False
    assert select_symmetric_skew(rows[:1], expiry=expiry, spot=100.0) is None


def test_skew_rejects_duplicate_or_inconsistent_side_and_bounded_fallback() -> None:
    expiry = date(2025, 9, 3)
    put = _observation(expiry=expiry.isoformat(), dte=30, strike=97.5, option_type="put", iv=0.32)
    call = _observation(
        expiry=expiry.isoformat(), dte=30, strike=102.5, option_type="call", iv=0.26
    )

    with pytest.raises(ValueError, match="B1V3_DUPLICATE_SKEW_STRIKE"):
        select_symmetric_skew(
            [put, replace(put, contract="O:DUPLICATE"), call], expiry=expiry, spot=100.0
        )
    with pytest.raises(ValueError, match="B1V3_SKEW_SPOT_MISMATCH"):
        select_symmetric_skew([replace(put, spot=101.0), call], expiry=expiry, spot=100.0)
    far_rows = [
        replace(put, strike=90.0),
        replace(call, strike=110.0),
    ]
    assert select_symmetric_skew(far_rows, expiry=expiry, spot=100.0) is None


def test_forward_variance_uses_total_variance_and_rejects_calendar_arbitrage() -> None:
    short = select_atm_iv(
        pair_call_put_consensus(
            _paired_strike(expiry="2025-08-14", dte=10, strike=100.0, call_iv=0.19, put_iv=0.21)
        ),
        spot=100.0,
        target_dte=7,
        tolerance=7,
        minimum_dte=7,
    )
    medium = select_atm_iv(
        pair_call_put_consensus(
            _paired_strike(expiry="2025-09-03", dte=30, strike=100.0, call_iv=0.24, put_iv=0.26)
        ),
        spot=100.0,
    )
    invalid_short = select_atm_iv(
        pair_call_put_consensus(
            _paired_strike(expiry="2025-08-14", dte=10, strike=100.0, call_iv=0.79, put_iv=0.81)
        ),
        spot=100.0,
        target_dte=7,
        tolerance=7,
        minimum_dte=7,
    )
    assert short is not None
    assert medium is not None
    assert invalid_short is not None

    value = compute_forward_variance(short, medium)

    expected = ((0.25**2) * (30 / 365) - (0.20**2) * (10 / 365)) / ((30 - 10) / 365)
    assert value == pytest.approx(expected)
    assert compute_forward_variance(invalid_short, medium) is None
    assert compute_forward_variance(medium, short) is None
    assert compute_forward_variance(replace(short, iv=math.nan), medium) is None
    equal_total_medium = replace(medium, iv=short.iv * math.sqrt(short.dte / medium.dte))
    assert compute_forward_variance(short, equal_total_medium) is None


def _attempt_rows(origin_count: int = 7) -> list[dict[str, object]]:
    first_origin = datetime(2025, 8, 4, 13, 35, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    expiries = (("2025-08-14", 10, 0.20), ("2025-09-03", 30, 0.25), ("2025-11-02", 90, 0.30))
    for origin_index in range(origin_count):
        origin = first_origin + timedelta(minutes=5 * origin_index)
        origin_ns = int(origin.timestamp() * 1_000_000_000)
        for expiry, dte, base_iv in expiries:
            for strike in (95.0, 100.0, 105.0):
                for option_type, side_shift in (("call", -0.01), ("put", 0.01)):
                    iv = base_iv + side_shift + origin_index * 0.001
                    rows.append(
                        {
                            "origin_id": f"AAPL:{origin.isoformat()}",
                            "asset": "AAPL",
                            "session_date": "2025-08-04",
                            "forecast_origin_utc": origin.isoformat(),
                            "forecast_origin_ns": origin_ns,
                            "contract": f"O:AAPL:{expiry}:{option_type}:{strike}",
                            "expiry": expiry,
                            "strike": strike,
                            "option_type": option_type,
                            "dte": dte,
                            "spot": 100.0,
                            "moneyness": strike / 100.0,
                            "target_moneyness": strike / 100.0,
                            "rate": 0.04,
                            "rate_source_date": "2025-08-01",
                            "dividend_yield": 0.005,
                            "dividend_assumption": "PRE_ORIGIN_TRAILING_DECLARATIONS",
                            "source_request_hash": "b" * 64,
                            "iv_success": True,
                            "iv": iv,
                            "failure_reason": None,
                            "sip_timestamp": origin_ns - 1_000_000_000,
                            "bid": 1.0,
                            "ask": 1.1,
                            "quote_age_seconds": 1.0,
                            "relative_spread": 0.1 / 1.05,
                            "midpoint": 1.05,
                        }
                    )
    return rows


def test_origin_builder_uses_exact_within_session_lags_and_nested_flags() -> None:
    result = build_b1v3_features(pl.DataFrame(_attempt_rows()))

    assert result.height == 7
    assert set(B1V3_FEATURES).issubset(result.columns)
    first = result.row(0, named=True)
    last = result.row(-1, named=True)
    assert first["session_tercile"] == "first"
    assert first["b1v3_log_atm_variance_change_5m"] is None
    assert first["b1v3a_complete"] is False
    assert last["b1v3_log_atm_variance_change_5m"] is not None
    assert last["b1v3_log_atm_variance_change_30m"] is not None
    assert last["b1v3a_complete"] is True
    assert last["b1v3b_complete"] is True
    assert last["b1v3c_complete"] is True
    assert result.filter(pl.col("b1v3c_complete") & ~pl.col("b1v3b_complete")).is_empty()
    assert result.filter(pl.col("b1v3b_complete") & ~pl.col("b1v3a_complete")).is_empty()


def test_origin_builder_rejects_outcome_columns_but_allows_target_moneyness() -> None:
    attempts = pl.DataFrame(_attempt_rows(1))

    assert build_b1v3_features(attempts).height == 1
    with pytest.raises(ValueError, match="B1V3_FORBIDDEN_INPUT_COLUMN"):
        build_b1v3_features(attempts.with_columns(pl.lit(0.1).alias("rv30")))


def test_origin_builder_rejects_future_quote() -> None:
    attempts = pl.DataFrame(_attempt_rows(1)).with_columns(
        (pl.col("forecast_origin_ns") + 1).alias("sip_timestamp")
    )

    with pytest.raises(ValueError, match="B1V3_FUTURE_QUOTE"):
        build_b1v3_features(attempts)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("sip_timestamp", "invalid"),
        ("bid", 0.0),
        ("ask", 5.0),
        ("iv_success", False),
        ("iv", math.nan),
        ("strike", 0.0),
        ("dte", 0),
        ("expiry", "2025-08-04"),
    ],
)
def test_origin_builder_records_invalid_attempts_as_missing(column: str, value: object) -> None:
    attempts = pl.DataFrame(_attempt_rows(1)).with_columns(pl.lit(value).alias(column))

    result = build_b1v3_features(attempts)

    assert result.item(0, "valid_contract_count") == 0
    assert result.item(0, "b1v3a_complete") is False


@pytest.mark.parametrize(
    ("column", "value", "code"),
    [
        ("rate_source_date", "invalid", "B1V3_RATE_SOURCE_DATE_INVALID"),
        ("rate_source_date", "2025-08-04", "B1V3_RATE_NOT_PRE_ORIGIN"),
        ("dividend_assumption", "UNKNOWN", "B1V3_DIVIDEND_ASSUMPTION_INVALID"),
        ("option_type", "unknown", "B1V3_OPTION_TYPE_INVALID"),
        ("source_request_hash", "bad", "B1V3_SOURCE_REQUEST_HASH_INVALID"),
    ],
)
def test_origin_builder_fails_closed_on_invalid_provenance(
    column: str, value: object, code: str
) -> None:
    attempts = pl.DataFrame(_attempt_rows(1)).with_columns(pl.lit(value).alias(column))

    with pytest.raises(ValueError, match=code):
        build_b1v3_features(attempts)


def test_origin_builder_schema_cutoff_and_identity_guards() -> None:
    attempts = pl.DataFrame(_attempt_rows(1))

    with pytest.raises(ValueError, match="B1V3_EMPTY_INPUT"):
        build_b1v3_features(attempts.clear())
    with pytest.raises(ValueError, match="B1V3_QUOTE_CUTOFF_INVALID"):
        build_b1v3_features(attempts, quote_cutoff_seconds=1)
    with pytest.raises(ValueError, match="B1V3_INPUT_SCHEMA_INVALID"):
        build_b1v3_features(attempts.drop("iv"))
    with pytest.raises(ValueError, match="B1V3_INPUT_COLUMN_NOT_ALLOWLISTED"):
        build_b1v3_features(attempts.with_columns(pl.lit(1).alias("unknown_metadata")))
    delayed = attempts.with_columns(pl.lit(2).alias("fmp_delay_minutes"))
    assert build_b1v3_features(delayed).height == 1
    massive_schema_compatible = attempts.with_columns(
        pl.lit(None, dtype=pl.Int64).alias("fmp_delay_minutes")
    )
    assert build_b1v3_features(massive_schema_compatible).height == 1
    with pytest.raises(ValueError, match="B1V3_FMP_DELAY_IDENTITY_INVALID"):
        build_b1v3_features(
            attempts.with_columns(pl.lit(3).alias("fmp_delay_minutes"))
        )
    with pytest.raises(ValueError, match="B1V3_SHIFTED_RESELECTION_IDENTITY_REQUIRED"):
        build_b1v3_features(attempts, quote_cutoff_seconds=60)
    shifted = attempts.with_columns(pl.lit(300).alias("quote_cutoff_seconds"))
    with pytest.raises(ValueError, match="B1V3_SHIFTED_RESELECTION_IDENTITY_MISMATCH"):
        build_b1v3_features(shifted, quote_cutoff_seconds=60)


def test_origin_builder_rejects_duplicate_contract_and_bad_origin_identity() -> None:
    attempts = pl.DataFrame(_attempt_rows(1))
    duplicate = pl.concat([attempts, attempts.head(1)])

    with pytest.raises(ValueError, match="B1V3_AMBIGUOUS_CONTRACT_ORIGIN"):
        build_b1v3_features(duplicate)
    with pytest.raises(ValueError, match="B1V3_ORIGIN_NS_MISMATCH"):
        build_b1v3_features(attempts.with_columns(pl.col("forecast_origin_ns") + 1))
    with pytest.raises(ValueError, match="B1V3_SESSION_TERCILE_MISMATCH"):
        build_b1v3_features(attempts.with_columns(pl.lit("last").alias("session_tercile")))


def test_origin_builder_derives_middle_and_last_session_terciles() -> None:
    attempts = pl.DataFrame(_attempt_rows(1))

    def shifted(hours: int) -> pl.DataFrame:
        origin = datetime(2025, 8, 4, hours, 0, tzinfo=UTC)
        origin_ns = int(origin.timestamp() * 1_000_000_000)
        return attempts.with_columns(
            pl.lit(origin.isoformat()).alias("forecast_origin_utc"),
            pl.lit(origin_ns).alias("forecast_origin_ns"),
            pl.lit(origin_ns - 1_000_000_000).alias("sip_timestamp"),
            pl.lit(f"AAPL:{origin.isoformat()}").alias("origin_id"),
        )

    assert build_b1v3_features(shifted(16)).item(0, "session_tercile") == "middle"
    assert build_b1v3_features(shifted(19)).item(0, "session_tercile") == "last"


def test_coverage_summary_enforces_nested_monotonicity_and_thresholds() -> None:
    rows: list[dict[str, object]] = []
    for asset in ("AAPL", "AMZN", "META", "MSFT", "NVDA", "TSLA"):
        for segment in ("first", "middle", "last"):
            for index in range(10):
                rows.append(
                    {
                        "asset": asset,
                        "session_date": "2025-08-04",
                        "session_tercile": segment,
                        "quote_cutoff_seconds": 0,
                        "b1v3a_complete": index < 9,
                        "b1v3b_complete": index < 8,
                        "b1v3c_complete": index < 7,
                    }
                )

    decision = summarize_b1v3_coverage(pl.DataFrame(rows))

    assert decision.status == "PASS_B1V3A_WITH_ENRICHED_ROBUSTNESS"
    assert decision.b1v3a.global_coverage == pytest.approx(0.9)
    assert decision.b1v3b.global_coverage == pytest.approx(0.8)
    assert decision.b1v3c.global_coverage == pytest.approx(0.7)

    broken = pl.DataFrame(rows).with_columns(pl.lit(True).alias("b1v3c_complete"))
    with pytest.raises(ValueError, match="B1V3_NESTED_COVERAGE_VIOLATION"):
        summarize_b1v3_coverage(broken)


def test_coverage_summary_reports_primary_only_and_revision_states() -> None:
    rows = [
        {
            "asset": "AAPL",
            "session_date": "2025-08-04",
            "session_tercile": "first",
            "quote_cutoff_seconds": 0,
            "b1v3a_complete": True,
            "b1v3b_complete": False,
            "b1v3c_complete": False,
        }
        for _ in range(10)
    ]

    primary_only = summarize_b1v3_coverage(pl.DataFrame(rows))

    assert primary_only.status == "PASS_B1V3A_ONLY"
    revised = summarize_b1v3_coverage(
        pl.DataFrame(rows).with_columns(pl.lit(False).alias("b1v3a_complete"))
    )
    assert revised.status == "REVISE_B1V3"
    with pytest.raises(ValueError, match="B1V3_COVERAGE_SCHEMA_INVALID"):
        summarize_b1v3_coverage(pl.DataFrame())


def test_coverage_summary_rejects_b1b_without_b1a() -> None:
    frame = pl.DataFrame(
        {
            "asset": ["AAPL"],
            "session_date": ["2025-08-04"],
            "session_tercile": ["first"],
            "quote_cutoff_seconds": [0],
            "b1v3a_complete": [False],
            "b1v3b_complete": [True],
            "b1v3c_complete": [False],
        }
    )

    with pytest.raises(ValueError, match="B1V3_NESTED_COVERAGE_VIOLATION"):
        summarize_b1v3_coverage(frame)
