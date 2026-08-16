"""Contracts for the Phase 5 development-only provider sources."""

from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_b2_calibration_20d as b2_builder  # noqa: E402
import build_phase5_common_panel as panel_builder  # noqa: E402
import run_b1_calibration_20d as b1_builder  # noqa: E402
import run_b1_closure as b1_closure  # noqa: E402


def test_existing_quote_cache_reads_are_memory_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only one large JSON cache may be decoded at a time."""
    path = tmp_path / "cache.json"
    path.write_text('{"http_status":200,"results":[]}', encoding="utf-8")
    original_read_text = Path.read_text
    active = 0
    maximum_active = 0
    counter_lock = threading.Lock()

    def tracked_read_text(self: Path, *args: object, **kwargs: object) -> str:
        nonlocal active, maximum_active
        with counter_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        try:
            time.sleep(0.03)
            return original_read_text(self, *args, **kwargs)
        finally:
            with counter_lock:
                active -= 1

    monkeypatch.setattr(Path, "read_text", tracked_read_text)

    with ThreadPoolExecutor(max_workers=4) as executor:
        payloads = list(executor.map(b1_closure._read_cache_payload, [path] * 4))

    assert all(payload["http_status"] == 200 for payload in payloads)
    assert maximum_active == 1


def test_fmp_source_filters_exact_session_and_records_both_delays() -> None:
    rows, returned_dates = b2_builder._normalize_fmp_session_rows(
        "AAPL",
        date(2026, 3, 24),
        [
            {
                "date": "2026-03-24 09:30:00",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100.5,
                "volume": 123,
            },
            {
                "date": "2026-03-25 09:30:00",
                "open": 200,
                "high": 201,
                "low": 199,
                "close": 200.5,
                "volume": 456,
            },
        ],
    )

    assert returned_dates == ["2026-03-24", "2026-03-25"]
    assert len(rows) == 1
    assert rows[0]["bar_timestamp_raw_utc"] == datetime(
        2026,
        3,
        24,
        13,
        30,
        tzinfo=UTC,
    )
    assert rows[0]["available_at_utc"] == datetime(
        2026,
        3,
        24,
        13,
        31,
        tzinfo=UTC,
    )
    assert rows[0]["available_at_plus_2m_utc"] == datetime(
        2026,
        3,
        24,
        13,
        32,
        tzinfo=UTC,
    )


def test_b1q_reads_origins_from_explicit_fmp_source(tmp_path: Path) -> None:
    origins_path = tmp_path / "fmp" / "origins.parquet"
    origins_path.parent.mkdir()
    pl.DataFrame(
        {
            "origin_id": ["AAPL:2026-03-24T13:35:00+00:00"],
            "asset": ["AAPL"],
            "session_date": ["2026-03-24"],
            "forecast_origin_utc": [datetime(2026, 3, 24, 13, 35, tzinfo=UTC)],
            "spot": [100.0],
            "session_segment": ["first"],
        }
    ).write_parquet(origins_path)
    config = b1_builder.B1BuildConfig(
        output_root=tmp_path / "b1q",
        cache_root=tmp_path / "cache",
        sessions=("2026-03-24",),
        origins_path=origins_path,
    )

    result = b1_builder._load_origins(config)

    assert result.height == 1
    assert result["origin_id"].to_list() == ["AAPL:2026-03-24T13:35:00+00:00"]
    assert result["origin_ns"].to_list() == [1774359300000000000]


def test_b1q_market_inputs_cover_full_trailing_year(tmp_path: Path) -> None:
    config = b1_builder.B1BuildConfig(
        output_root=tmp_path / "b1q",
        cache_root=tmp_path / "cache",
        sessions=("2026-03-24", "2026-06-10"),
    )

    assert b1_builder._market_input_window(config) == (
        date(2025, 3, 24),
        date(2026, 6, 10),
    )


def test_b1q_rate_windows_are_bounded_contiguous_and_complete() -> None:
    """FMP's bounded response must not truncate a long Treasury request."""
    windows = b1_builder._date_windows(
        date(2025, 1, 1),
        date(2025, 3, 5),
    )

    assert windows == (
        (date(2025, 1, 1), date(2025, 1, 31)),
        (date(2025, 2, 1), date(2025, 3, 3)),
        (date(2025, 3, 4), date(2025, 3, 5)),
    )
    assert all((end - start).days <= 30 for start, end in windows)


def test_atomic_json_retries_a_transient_windows_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "checkpoint.json"
    original = Path.replace
    calls = 0

    def flaky_replace(source: Path, destination: Path) -> Path:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("transient lock")
        return original(source, destination)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    monkeypatch.setattr(b1_builder.time_module, "sleep", lambda _: None)

    b1_builder._atomic_json(target, {"status": "ok"})

    assert calls == 2
    assert json.loads(target.read_text(encoding="utf-8")) == {"status": "ok"}


def test_b1q_origin_records_observed_quote_pit_evidence() -> None:
    origin_ns = 1774359300000000000

    valid = b1_builder._quote_pit_evidence(
        [
            {"sip_timestamp": origin_ns - 2_000_000_000},
            {"sip_timestamp": origin_ns - 1_000_000_000},
            {"sip_timestamp": None},
        ],
        origin_ns,
    )
    assert valid == {
        "b1q_max_sip_timestamp_ns": origin_ns - 1_000_000_000,
        "b1q_quote_not_after_origin": True,
        "b1q_pit_evidence_valid": True,
    }

    assert b1_builder._quote_pit_evidence([], origin_ns)[
        "b1q_pit_evidence_valid"
    ] is False
    assert b1_builder._quote_pit_evidence(
        [{"sip_timestamp": origin_ns + 1}],
        origin_ns,
    )["b1q_quote_not_after_origin"] is False


def test_massive_request_retries_transient_transport_failure() -> None:
    class FlakyClient:
        calls = 0

        def get(
            self,
            url: str,
            *,
            params: dict[str, str],
        ) -> httpx.Response:
            self.calls += 1
            request = httpx.Request("GET", url, params=params)
            if self.calls == 1:
                raise httpx.ConnectError("transient TLS EOF", request=request)
            return httpx.Response(
                200,
                json={"results": []},
                headers={"x-request-id": "request-1"},
                request=request,
            )

    client = FlakyClient()
    status, payload, request_id = b1_closure._request_json(
        client,
        "https://api.massive.com/v3/quotes/O:AAPL",
        {"timestamp": "2026-03-24"},
        "secret-not-emitted",
        backoff_seconds=0,
    )

    assert client.calls == 2
    assert status == 200
    assert payload == {"results": []}
    assert request_id == "request-1"


def test_b1q_fetch_retains_paths_instead_of_quote_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = tmp_path / "quote.json"
    cache_path.write_text("{}", encoding="utf-8")
    calls = 0

    def fetch_contract_day(
        job: object,
        key: str,
    ) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "http_status": 200,
            "cache_path": str(cache_path),
            "source_request_hash": "abc",
            "pagination_complete": True,
            "pages": 1,
            "provider_duplicate_rows_removed": 0,
            "cache_hit": True,
            "results": [{"sip_timestamp": 999}],
        }

    monkeypatch.setattr(
        b1_builder.closure,
        "fetch_contract_day",
        fetch_contract_day,
    )
    config = b1_builder.B1BuildConfig(
        output_root=tmp_path / "output",
        cache_root=tmp_path / "cache",
        sessions=("2026-03-24",),
    )

    result, audit = b1_builder._fetch_quotes(
        {
            ("AAPL", "2026-03-24"): [
                {
                    "contract": "O:AAPL260417C00100000",
                    "expiry": "2026-04-17",
                    "strike": 100.0,
                    "option_type": "call",
                },
                {
                    "contract": "O:AAPL260417C00100000",
                    "expiry": "2026-04-17",
                    "strike": 100.0,
                    "option_type": "call",
                },
            ]
        },
        "secret-not-emitted",
        config,
    )

    assert result[
        ("AAPL", "2026-03-24", "O:AAPL260417C00100000")
    ] == (cache_path, "abc")
    assert calls == 1
    assert audit["contract_day_jobs"] == 1
    assert audit["pagination_explicit"] == 1


def test_corrupt_quote_cache_is_preserved_and_refetched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def request_json(*args: object, **kwargs: object) -> tuple[int, dict[str, object], str]:
        nonlocal calls
        calls += 1
        return 200, {"results": []}, "request-1"

    monkeypatch.setattr(b1_closure, "CACHE", tmp_path)
    monkeypatch.setattr(b1_closure, "_request_json", request_json)
    item = (
        "AAPL",
        "2026-03-24",
        {
            "contract": "O:AAPL260417C00100000",
            "expiry": "2026-04-17",
            "strike": 100.0,
            "option_type": "call",
        },
    )
    first = b1_closure.fetch_contract_day(item, "secret-not-emitted")
    cache_path = Path(str(first["cache_path"]))
    cache_path.write_text('{"first":1}{"second":2}', encoding="utf-8")

    second = b1_closure.fetch_contract_day(item, "secret-not-emitted")

    assert calls == 2
    assert second["http_status"] == 200
    assert json.loads(cache_path.read_text(encoding="utf-8"))["http_status"] == 200
    assert len(list(tmp_path.glob("*.json.invalid-*"))) == 1


def test_contract_day_uses_exact_session_nanosecond_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, str]] = []

    def request_json(
        _client: object,
        _url: str,
        params: dict[str, str],
        _key: str,
    ) -> tuple[int, dict[str, object], str]:
        captured.append(params)
        return 200, {"results": []}, "request-1"

    monkeypatch.setattr(b1_closure, "CACHE", tmp_path)
    monkeypatch.setattr(b1_closure, "_request_json", request_json)
    item = (
        "AAPL",
        "2025-07-07",
        {
            "contract": "O:AAPL250718C00210000",
            "expiry": "2025-07-18",
            "strike": 210.0,
            "option_type": "call",
        },
    )

    result = b1_closure.fetch_contract_day(item, "secret-not-emitted")

    assert captured == [
        {
            "timestamp.gte": "1751895000000000000",
            "timestamp.lte": "1751918400000000000",
            "sort": "timestamp",
            "order": "asc",
            "limit": "50000",
        }
    ]
    assert result["schema_version"] == 4
    assert "schema_version=4" in result["cache_key"]


def test_contract_day_streams_large_cache_to_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Avoid materializing a second full JSON copy of quote results in RAM."""
    real_dumps = json.dumps

    def reject_full_payload_dumps(value: object, *args: object, **kwargs: object) -> str:
        if isinstance(value, dict) and "results" in value:
            raise MemoryError("simulated oversized contract-day")
        return real_dumps(value, *args, **kwargs)

    def request_json(*_args: object, **_kwargs: object) -> tuple[int, dict[str, object], str]:
        return (
            200,
            {
                "results": [
                    {
                        "sip_timestamp": 1_751_895_000_000_000_000,
                        "sequence_number": 1,
                        "bid_price": 1.0,
                        "ask_price": 1.2,
                    }
                ]
            },
            "request-1",
        )

    monkeypatch.setattr(b1_closure, "CACHE", tmp_path)
    monkeypatch.setattr(b1_closure, "_request_json", request_json)
    monkeypatch.setattr(b1_closure.json, "dumps", reject_full_payload_dumps)
    item = (
        "AAPL",
        "2025-07-07",
        {
            "contract": "O:AAPL250718C00210000",
            "expiry": "2025-07-18",
            "strike": 210.0,
            "option_type": "call",
        },
    )

    result = b1_closure.fetch_contract_day(item, "secret-not-emitted")

    cache_path = Path(str(result["cache_path"]))
    assert json.loads(cache_path.read_text(encoding="utf-8"))["results"] == [
        {
            "sip_timestamp": 1_751_895_000_000_000_000,
            "sequence_number": 1,
            "bid_price": 1.0,
            "ask_price": 1.2,
        }
    ]
    assert not cache_path.with_suffix(cache_path.suffix + ".part").exists()


def test_contract_day_rejects_quotes_outside_requested_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def request_json(*_args: object, **_kwargs: object) -> tuple[int, dict[str, object], str]:
        return (
            200,
            {
                "results": [
                    {
                        "sip_timestamp": 1_752_784_000_000_000_000,
                        "sequence_number": 1,
                        "bid_price": 1.0,
                        "ask_price": 1.2,
                    }
                ]
            },
            "request-1",
        )

    monkeypatch.setattr(b1_closure, "CACHE", tmp_path)
    monkeypatch.setattr(b1_closure, "_request_json", request_json)
    item = (
        "AAPL",
        "2025-07-07",
        {
            "contract": "O:AAPL250718C00210000",
            "expiry": "2025-07-18",
            "strike": 210.0,
            "option_type": "call",
        },
    )

    with pytest.raises(RuntimeError, match="MASSIVE_QUOTE_OUTSIDE_REQUESTED_SESSION"):
        b1_closure.fetch_contract_day(item, "secret-not-emitted")


def test_contract_day_pagination_reapplies_exact_session_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, str]] = []

    def request_json(
        _client: object,
        _url: str,
        params: dict[str, str],
        _key: str,
    ) -> tuple[int, dict[str, object], str]:
        captured.append(params)
        if len(captured) == 1:
            return (
                200,
                {
                    "results": [],
                    "next_url": "https://api.massive.com/v3/quotes/O:AAPL?cursor=abc%3D",
                },
                "request-1",
            )
        return 200, {"results": []}, "request-2"

    monkeypatch.setattr(b1_closure, "CACHE", tmp_path)
    monkeypatch.setattr(b1_closure, "_request_json", request_json)
    item = (
        "AAPL",
        "2025-07-07",
        {
            "contract": "O:AAPL250718C00210000",
            "expiry": "2025-07-18",
            "strike": 210.0,
            "option_type": "call",
        },
    )

    b1_closure.fetch_contract_day(item, "secret-not-emitted")

    assert captured[1] == {**captured[0], "cursor": "abc="}


def test_contract_day_rejects_repeated_pagination_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    next_url = "https://api.massive.com/v3/quotes/O:AAPL?cursor=repeat"

    def request_json(*_args: object, **_kwargs: object) -> tuple[int, dict[str, object], str]:
        return 200, {"results": [], "next_url": next_url}, "request-1"

    monkeypatch.setattr(b1_closure, "CACHE", tmp_path)
    monkeypatch.setattr(b1_closure, "_request_json", request_json)
    item = (
        "AAPL",
        "2025-07-07",
        {
            "contract": "O:AAPL250718C00210000",
            "expiry": "2025-07-18",
            "strike": 210.0,
            "option_type": "call",
        },
    )

    with pytest.raises(RuntimeError, match="MASSIVE_QUOTE_PAGINATION_REPEATED"):
        b1_closure.fetch_contract_day(item, "secret-not-emitted")


def test_contract_day_rejects_failed_later_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def request_json(
        *_args: object, **_kwargs: object
    ) -> tuple[int, dict[str, object], str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return (
                200,
                {
                    "results": [],
                    "next_url": "https://api.massive.com/v3/quotes/O:AAPL?cursor=next",
                },
                "request-1",
            )
        return 503, {}, "request-2"

    monkeypatch.setattr(b1_closure, "CACHE", tmp_path)
    monkeypatch.setattr(b1_closure, "_request_json", request_json)
    item = (
        "AAPL",
        "2025-07-07",
        {
            "contract": "O:AAPL250718C00210000",
            "expiry": "2025-07-18",
            "strike": 210.0,
            "option_type": "call",
        },
    )

    with pytest.raises(RuntimeError, match="MASSIVE_QUOTE_PAGE_HTTP_503"):
        b1_closure.fetch_contract_day(item, "secret-not-emitted")


def test_legacy_quote_cache_requires_a_terminal_partial_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(b1_closure, "QUOTE_PAGE_LIMIT", 2)
    partial = {
        "results": [{"sip_timestamp": 1, "sequence_number": 1}],
        "provider_duplicate_rows_removed": 0,
    }
    aligned = {
        "results": [
            {"sip_timestamp": index, "sequence_number": index}
            for index in range(2)
        ],
        "provider_duplicate_rows_removed": 0,
    }

    assert b1_closure._legacy_cache_has_terminal_page(partial) is True
    assert b1_closure._legacy_cache_has_terminal_page(aligned) is False


def test_contract_reference_rejects_failed_later_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def request_json(
        *_args: object, **_kwargs: object
    ) -> tuple[int, dict[str, object], str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return (
                200,
                {
                    "results": [],
                    "next_url": "https://api.massive.com/v3/reference/options/contracts?cursor=next",
                },
                "request-1",
            )
        return 503, {}, "request-2"

    monkeypatch.setattr(b1_closure, "_request_json", request_json)

    with pytest.raises(RuntimeError, match="MASSIVE_CONTRACT_PAGE_HTTP_503"):
        b1_closure.resolve_contracts(
            object(),  # type: ignore[arg-type]
            "secret-not-emitted",
            "AAPL",
            "2026-03-24",
            100.0,
        )


def test_contract_day_deduplicates_identical_provider_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        "sip_timestamp": 1_751_895_001_000_000_000,
        "sequence_number": 10,
        "bid_price": 1.0,
        "ask_price": 1.2,
    }

    def request_json(*_args: object, **_kwargs: object) -> tuple[int, dict[str, object], str]:
        return 200, {"results": [row, row.copy()]}, "request-1"

    monkeypatch.setattr(b1_closure, "CACHE", tmp_path)
    monkeypatch.setattr(b1_closure, "_request_json", request_json)
    item = (
        "AAPL",
        "2025-07-07",
        {
            "contract": "O:AAPL250718C00210000",
            "expiry": "2025-07-18",
            "strike": 210.0,
            "option_type": "call",
        },
    )

    result = b1_closure.fetch_contract_day(item, "secret-not-emitted")

    assert len(result["results"]) == 1
    assert result["provider_duplicate_rows_removed"] == 1


def test_contract_day_rejects_conflicting_provider_event_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "sip_timestamp": 1_751_895_001_000_000_000,
            "sequence_number": 10,
            "bid_price": 1.0,
            "ask_price": 1.2,
        },
        {
            "sip_timestamp": 1_751_895_001_000_000_000,
            "sequence_number": 10,
            "bid_price": 0.9,
            "ask_price": 1.2,
        },
    ]

    def request_json(*_args: object, **_kwargs: object) -> tuple[int, dict[str, object], str]:
        return 200, {"results": rows}, "request-1"

    monkeypatch.setattr(b1_closure, "CACHE", tmp_path)
    monkeypatch.setattr(b1_closure, "_request_json", request_json)
    item = (
        "AAPL",
        "2025-07-07",
        {
            "contract": "O:AAPL250718C00210000",
            "expiry": "2025-07-18",
            "strike": 210.0,
            "option_type": "call",
        },
    )

    with pytest.raises(RuntimeError, match="MASSIVE_QUOTE_EVENT_KEY_COLLISION"):
        b1_closure.fetch_contract_day(item, "secret-not-emitted")


def test_latest_quote_builds_a_sorted_asof_index() -> None:
    cache = {
        "results": [
            {"sip_timestamp": 1_003, "bid_price": 1.0, "ask_price": 1.2},
            {"sip_timestamp": 999, "bid_price": 0.8, "ask_price": 1.0},
            {"sip_timestamp": 1_001, "bid_price": 0.9, "ask_price": 1.1},
        ]
    }

    quote = b1_closure.latest_quote(cache, 1_002)

    assert quote is not None
    assert quote["sip_timestamp"] == 1_001
    assert cache["_sip_timestamps"] == [999, 1_001, 1_003]


def test_latest_quote_breaks_equal_sip_timestamps_by_sequence_number() -> None:
    cache = {
        "results": [
            {
                "sip_timestamp": 1_000,
                "sequence_number": 10,
                "bid_price": 1.0,
                "ask_price": 1.2,
            },
            {
                "sip_timestamp": 1_000,
                "sequence_number": 11,
                "bid_price": 1.1,
                "ask_price": 1.3,
            },
        ]
    }

    quote = b1_closure.latest_quote(cache, 1_000)

    assert quote is not None
    assert quote["sequence_number"] == 11
    assert quote["midpoint"] == pytest.approx(1.2)


def test_historical_contract_resolution_uses_asof_active_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, str]] = []

    def request_json(
        client: object,
        url: str,
        params: dict[str, str],
        key: str,
    ) -> tuple[int, dict[str, object], str]:
        requests.append(dict(params))
        expiry = params["expiration_date.gte"]
        rows = []
        for strike in (95.0, 97.5, 100.0, 102.5, 105.0):
            scaled = f"{int(strike * 1000):08d}"
            for kind, code in (("call", "C"), ("put", "P")):
                rows.append(
                    {
                        "ticker": f"O:AAPL{expiry.replace('-', '')}{code}{scaled}",
                        "underlying_ticker": "AAPL",
                        "expiration_date": expiry,
                        "strike_price": strike,
                        "contract_type": kind,
                    }
                )
        return (
            200,
            {"results": rows},
            "request-1",
        )

    monkeypatch.setattr(b1_closure, "_request_json", request_json)

    contracts = b1_closure.resolve_contracts(
        object(),  # type: ignore[arg-type]
        "secret-not-emitted",
        "AAPL",
        "2026-03-24",
        100.0,
    )

    assert len(requests) == 3
    assert all(request["as_of"] == "2026-03-24" for request in requests)
    assert all(request["expired"] == "false" for request in requests)
    assert len(contracts) == 30
    assert {contract["target_moneyness"] for contract in contracts} == {
        0.95,
        0.975,
        1.0,
        1.025,
        1.05,
    }
    assert {contract["bucket"] for contract in contracts} == {
        "short",
        "medium",
        "long",
    }


def test_fmp_list_request_retries_and_rejects_non_list_payload() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json=[{"date": "2026-03-24", "month3": 4.1}])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        payload = b1_builder._fmp_list_request(
            client,
            "https://financialmodelingprep.com/stable/treasury-rates",
            {"from": "2026-03-24", "to": "2026-03-24"},
            "secret-not-emitted",
            backoff_seconds=0,
        )
    assert calls == 2
    assert payload == [{"date": "2026-03-24", "month3": 4.1}]

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"unexpected": True})
        )
    ) as client, pytest.raises(RuntimeError, match="FMP_RESPONSE_NOT_LIST"):
        b1_builder._fmp_list_request(
            client,
            "https://financialmodelingprep.com/stable/dividends",
            {"symbol": "AAPL"},
            "secret-not-emitted",
            backoff_seconds=0,
        )

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"not-json")
        )
    ) as client, pytest.raises(RuntimeError, match="FMP_RESPONSE_NOT_JSON"):
        b1_builder._fmp_list_request(
            client,
            "https://financialmodelingprep.com/stable/dividends",
            {"symbol": "AAPL"},
            "secret-not-emitted",
            backoff_seconds=0,
        )


def test_rate_observation_is_never_selected_from_the_future() -> None:
    """B1Q must use the latest Treasury observation before the session."""
    source_date, rate = b1_builder._rate_observation_for(
        "2026-03-24",
        {"2026-03-23": 0.041, "2026-03-25": 0.042},
    )
    assert source_date == "2026-03-23"
    assert rate == 0.041

    source_date, rate = b1_builder._rate_observation_for(
        "2026-03-24",
        {"2026-03-23": 0.041, "2026-03-24": 0.099},
    )
    assert source_date == "2026-03-23"
    assert rate == 0.041

    with pytest.raises(RuntimeError, match="B1Q_RATE_NOT_AVAILABLE"):
        b1_builder._rate_observation_for(
            "2026-03-24",
            {"2026-03-25": 0.042},
        )


def test_b1_attempt_ledger_is_hashed_and_pit_validated(tmp_path: Path) -> None:
    ledger = tmp_path / "attempts.parquet"
    frame = pl.DataFrame(
        {
            "session_date": ["2026-03-24"],
            "forecast_origin_ns": [1_000],
            "rate_source_date": ["2026-03-23"],
            "sip_timestamp": [999],
            "source_request_hash": ["abc"],
        }
    )
    frame.write_parquet(ledger)

    assert panel_builder._validate_b1_attempt_ledger(
        ledger,
        {"iv_attempt_rows": 1},
    ) == {
        "rows": 1,
        "future_rate_rows": 0,
        "future_quote_rows": 0,
        "missing_request_hash_rows": 0,
    }

    frame.with_columns(pl.lit(1_001).alias("sip_timestamp")).write_parquet(ledger)
    with pytest.raises(ValueError, match="PHASE5_B1_ATTEMPT_LEDGER_INVALID"):
        panel_builder._validate_b1_attempt_ledger(
            ledger,
            {"iv_attempt_rows": 1},
        )
