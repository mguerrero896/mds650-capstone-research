import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from mds650.phase6 import b1v2_coverage_status, build_b1v2_features

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import run_b1_calibration_20d as b1_builder  # noqa: E402


def _origins(count: int = 7) -> pl.DataFrame:
    start = datetime(2025, 8, 4, 14, 0, tzinfo=UTC)
    rows = []
    for index in range(count):
        origin = start + timedelta(minutes=5 * index)
        rows.append(
            {
                "origin_id": f"AAPL:{origin.isoformat()}",
                "asset": "AAPL",
                "session_date": "2025-08-04",
                "forecast_origin_utc": origin,
                "session_tercile": "first",
            }
        )
    return pl.DataFrame(rows)


def _states(origins: pl.DataFrame) -> pl.DataFrame:
    contracts = (
        ("O:AAPL250912P00190000", "2025-09-12", 190.0, "put", 39, 0.975, 0.31),
        ("O:AAPL250912C00195000", "2025-09-12", 195.0, "call", 39, 1.000, 0.29),
        ("O:AAPL250912C00200000", "2025-09-12", 200.0, "call", 39, 1.025, 0.27),
        ("O:AAPL250822C00195000", "2025-08-22", 195.0, "call", 18, 1.000, 0.34),
        ("O:AAPL251219C00195000", "2025-12-19", 195.0, "call", 137, 1.000, 0.25),
    )
    rows = []
    for origin in origins.iter_rows(named=True):
        origin_ns = int(origin["forecast_origin_utc"].timestamp() * 1_000_000_000)
        for contract, expiry, strike, option_type, dte, moneyness, iv in contracts:
            rows.append(
                {
                    "origin_id": origin["origin_id"],
                    "contract": contract,
                    "expiry": expiry,
                    "strike": strike,
                    "option_type": option_type,
                    "dte": dte,
                    "moneyness": moneyness,
                    "sip_timestamp_ns": origin_ns - 1_000_000_000,
                    "bid": 2.0,
                    "ask": 2.2,
                    "implied_volatility": iv,
                }
            )
    return pl.DataFrame(rows)


def test_b1v2_selects_last_quote_not_after_origin() -> None:
    origins = _origins(1)
    states = _states(origins)
    origin_ns = int(origins.item(0, "forecast_origin_utc").timestamp() * 1e9)
    contract = states.item(0, "contract")
    candidates = pl.DataFrame(
        [
            {
                **states.row(0, named=True),
                "sip_timestamp_ns": origin_ns - 2_000_000_000,
                "bid": 1.9,
                "ask": 2.1,
            },
            {
                **states.row(0, named=True),
                "sip_timestamp_ns": origin_ns - 1_000_000_000,
                "bid": 2.0,
                "ask": 2.2,
            },
            {
                **states.row(0, named=True),
                "sip_timestamp_ns": origin_ns + 1,
                "bid": 9.0,
                "ask": 9.2,
            },
        ]
    ).with_columns(pl.lit(contract).alias("contract"))

    row = build_b1v2_features(origins, candidates).row(0, named=True)

    assert row["max_sip_timestamp_ns"] <= row["forecast_origin_ns"]
    assert row["selected_midpoint"] == 2.1


def test_b1v2_benchmarks_are_nested() -> None:
    result = build_b1v2_features(_origins(), _states(_origins()))

    assert result.filter(
        pl.col("b1v2c_complete") & ~pl.col("b1v2b_complete")
    ).is_empty()
    assert result.filter(
        pl.col("b1v2b_complete") & ~pl.col("b1v2a_complete")
    ).is_empty()
    assert result.filter(pl.col("b1v2c_complete")).height == 1


def test_b1v2_coverage_gate_requires_global_asset_and_tercile_thresholds() -> None:
    rows = []
    for asset in ("AAPL", "AMZN"):
        for segment in ("first", "middle", "last"):
            for index in range(10):
                rows.append(
                    {
                        "asset": asset,
                        "session_tercile": segment,
                        "b1v2a_complete": index < 9,
                    }
                )
    assert b1v2_coverage_status(pl.DataFrame(rows)) == "PASS_B1V2A_COVERAGE"

    failing = pl.DataFrame(rows).with_columns(
        pl.when(pl.col("asset") == "AMZN")
        .then(False)
        .otherwise(pl.col("b1v2a_complete"))
        .alias("b1v2a_complete")
    )
    assert b1v2_coverage_status(failing) == "REVISE_B1V2"


def test_contract_resolution_cache_is_reused_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = b1_builder.B1BuildConfig(
        output_root=tmp_path / "out",
        cache_root=tmp_path / "cache",
        sessions=("2025-08-04",),
    )
    config.cache_root.mkdir(parents=True)
    contracts = [
        {
            "contract": "O:AAPL250912C00195000",
            "expiry": "2025-09-12",
            "strike": 195.0,
            "option_type": "call",
            "dte": 39,
            "bucket": "medium",
        }
    ]
    (config.cache_root / "resolved_contracts_phase6_strict_v3.json").write_text(
        json.dumps(
            {
                "schema_version": "b1q-contract-grid-3.0",
                "records": [
                    {
                        "asset": "AAPL",
                        "session_date": "2025-08-04",
                        "spot": 195.0,
                        "contracts": contracts,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    origins = pl.DataFrame(
        {"asset": ["AAPL"], "session_date": ["2025-08-04"], "spot": [195.0]}
    )
    monkeypatch.setattr(
        b1_builder.closure,
        "resolve_contracts",
        lambda *_args, **_kwargs: pytest.fail("network resolution was repeated"),
    )

    assert b1_builder._resolve_contracts(origins, "unused", config) == {
        ("AAPL", "2025-08-04"): contracts
    }
