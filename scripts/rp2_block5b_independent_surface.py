"""Block 5b - how much of the traded surface is an artefact of what traded.

B1 is reconstructed from the NBBO carried on option *trades*, so a contract enters the
surface only because somebody traded it. Block 5 made B1 and B2 read disjoint rows, which
removes the mechanical overlap, and said plainly that it does not remove the selection: the
quotes are still chosen by flow.

Rebuilding all 184,632 origins from an independent quote feed is not affordable — the listed
chain runs to roughly a thousand contracts per underlying per session, which is millions of
directed requests. What *is* affordable, and answers the scientific question the limitation
raises, is to measure the bias on a designed subsample.

For each sampled origin this builds the same surface twice:

* **traded** — the latest NBBO carried on a trade, exactly as Block 5 does it;
* **listed** — a directed quote per contract taken from the *listed* chain, which includes
  every strike the exchange published whether or not it traded.

The listing comes from the contract reference endpoint and the quotes from one directed
request per contract at or before the origin, so the second surface never consults trade
activity. The paired difference in smile level, slope and coverage is the selection effect,
reported with a sign rather than asserted.

This is a bounded acquisition by construction: one listing per (asset, session, type) and one
quote per contract per origin, never a chain download. `assert_directed_only` is called to
make that explicit rather than implied.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import polars as pl

from mds650.b1v3_confirmation import canonical_sha256
from mds650.providers.massive import (
    MassiveProvider,
    assert_directed_only,
    parse_directed_quotes,
)
from mds650.rp2.bars import MARKET_TZ, SESSION_OPEN_MINUTE, build_session_grid, load_bar_sources
from mds650.rp2.surface import fit_smile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_block5b_independent"
INVENTORY = ROOT / "artifacts" / "rp2_block1_partition" / "inventory.jsonl"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"

CUTOFF_SECONDS = 120
LOOKBACK_SECONDS = 1800
CALENDAR_YEAR = 365.0
NY = ZoneInfo(MARKET_TZ)
RUN_ID = "rp2_block5b_independent_surface"

#: The sample. Small on purpose and fixed in advance, because an independent surface costs a
#: directed request per contract per origin.
SAMPLE_ORIGINS: tuple[int, ...] = (60, 180, 300)
#: Strikes within this fraction of spot: the region the smile fit and the wings are read on.
STRIKE_BAND = 0.15
#: Expiries in this window; the surface features are read on the bucket nearest 30 days.
DTE_MIN_DAYS = 20
DTE_MAX_DAYS = 45
#: Contracts per side per origin, nearest the money. Bounds the request count.
MAX_CONTRACTS_PER_SIDE = 16

TAPE_COLUMNS = (
    "underlying_symbol",
    "created_at",
    "nbbo_bid",
    "nbbo_ask",
    "implied_volatility",
    "expiry",
    "strike",
    "option_type",
)

type FloatArray = npt.NDArray[np.float64]


def load_inventory() -> dict[tuple[str, str], list[str]]:
    index: dict[tuple[str, str], list[str]] = {}
    with INVENTORY.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            index.setdefault((row["session_date"], row["asset"]), []).append(row["path"])
    return index


def implied_volatility_from_price(
    price: float, spot: float, strike: float, tenor: float, *, is_call: bool
) -> float:
    """Bisect Black-Scholes for the volatility that reproduces ``price``.

    The listed-chain quotes carry no implied volatility of their own — that field exists on
    the trade tape because the provider computes it there. Solving for it here keeps the two
    surfaces on the same scale; using the tape's number for the listed side would import the
    very selection this block is trying to measure.
    """

    if not (price > 0.0 and spot > 0.0 and strike > 0.0 and tenor > 0.0):
        return float("nan")
    intrinsic = max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
    if price <= intrinsic:
        return float("nan")
    low, high = 1e-4, 5.0
    for _ in range(60):
        mid = 0.5 * (low + high)
        value = _black_scholes(spot, strike, tenor, mid, is_call=is_call)
        if value > price:
            high = mid
        else:
            low = mid
    return 0.5 * (low + high)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _black_scholes(spot: float, strike: float, tenor: float, vol: float, *, is_call: bool) -> float:
    if vol <= 0.0 or tenor <= 0.0:
        return max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
    root = vol * math.sqrt(tenor)
    d1 = (math.log(spot / strike) + 0.5 * vol * vol * tenor) / root
    d2 = d1 - root
    if is_call:
        return spot * _normal_cdf(d1) - strike * _normal_cdf(d2)
    return strike * _normal_cdf(-d2) - spot * _normal_cdf(-d1)


def traded_surface(
    paths: Sequence[str],
    asset: str,
    session: str,
    minute: int,
    spot: float,
    *,
    span: tuple[float, float] | None = None,
) -> dict[str, float]:
    """The Block 5 construction: latest NBBO carried on a trade, per contract.

    ``span`` restricts the fit to a log-moneyness range, so the same quadratic is fitted
    over the same interval on both sides of the comparison. A quadratic over a wider range
    has a different slope and curvature for reasons that have nothing to do with which
    contracts traded, and leaving that in would mix my sampling into the effect I am
    measuring.
    """

    frames = [
        pl.read_parquet(path, columns=list(TAPE_COLUMNS)).filter(
            pl.col("underlying_symbol") == asset
        )
        for path in paths
    ]
    tape = pl.concat(frames, how="vertical").filter(
        (pl.col("nbbo_bid") > 0.0)
        & (pl.col("nbbo_ask") > pl.col("nbbo_bid"))
        & pl.col("implied_volatility").is_between(0.01, 5.0)
    )
    if tape.height == 0:
        return {"contracts": 0.0}
    tape = tape.sort("created_at")
    created = tape["created_at"].dt.replace_time_zone(None).cast(pl.Int64).to_numpy()
    base = datetime.fromisoformat(session).replace(tzinfo=NY)
    cutoff = base + timedelta(minutes=int(SESSION_OPEN_MINUTE + minute))
    cutoff_us = int(
        np.datetime64(
            cutoff.astimezone(UTC).replace(tzinfo=None) - timedelta(seconds=CUTOFF_SECONDS), "us"
        ).astype(np.int64)
    )
    hi = int(np.searchsorted(created, cutoff_us, side="right"))
    lo = int(np.searchsorted(created, cutoff_us - LOOKBACK_SECONDS * 1_000_000, side="left"))
    if hi - lo < 3:
        return {"contracts": 0.0}

    strike = tape["strike"].cast(pl.Float64).to_numpy().astype(np.float64)
    expiry = tape["expiry"].cast(pl.Date).to_numpy()
    iv = tape["implied_volatility"].cast(pl.Float64).to_numpy().astype(np.float64)
    is_call = (tape["option_type"] == "call").to_numpy()
    days = (expiry - np.datetime64(session, "D")).astype("timedelta64[D]").astype(np.int64)
    keys = days * 20_000_000 + np.round(strike * 1000.0).astype(np.int64) * 2 + is_call
    reversed_keys = keys[lo:hi][::-1]
    _, first = np.unique(reversed_keys, return_index=True)
    picked = hi - 1 - first

    inside = (
        (days[picked] >= DTE_MIN_DAYS)
        & (days[picked] <= DTE_MAX_DAYS)
        & (np.abs(strike[picked] / spot - 1.0) <= STRIKE_BAND)
    )
    if span is not None:
        moneyness = np.log(strike[picked] / spot)
        inside &= (moneyness >= span[0]) & (moneyness <= span[1])
    picked = picked[inside]
    if picked.size < 3:
        return {"contracts": float(picked.size)}
    log_moneyness = np.log(strike[picked] / spot)
    smile = fit_smile(log_moneyness, iv[picked])
    return {
        "contracts": float(picked.size),
        "strikes": float(np.unique(strike[picked]).size),
        "level": smile.level,
        "slope": smile.slope,
        "curvature": smile.curvature,
        "min_log_moneyness": float(log_moneyness.min()),
        "max_log_moneyness": float(log_moneyness.max()),
    }


def listed_surface(
    provider: MassiveProvider,
    asset: str,
    session: str,
    minute: int,
    spot: float,
    counters: dict[str, int],
) -> dict[str, float]:
    """The independent construction: the listed chain, quoted contract by contract."""

    base = datetime.fromisoformat(session).replace(tzinfo=NY)
    cutoff = (
        base
        + timedelta(minutes=int(SESSION_OPEN_MINUTE + minute))
        - timedelta(seconds=CUTOFF_SECONDS)
    )
    cutoff_ns = int(cutoff.astimezone(UTC).timestamp() * 1_000_000_000)
    session_date = datetime.fromisoformat(session).date()
    low = (session_date + timedelta(days=DTE_MIN_DAYS)).isoformat()
    high = (session_date + timedelta(days=DTE_MAX_DAYS)).isoformat()

    records: list[dict[str, float]] = []
    for contract_type in ("call", "put"):
        listing = provider.option_contract_listing(
            asset,
            expiration_gte=low,
            expiration_lte=high,
            strike_gte=spot * (1.0 - STRIKE_BAND),
            strike_lte=spot * (1.0 + STRIKE_BAND),
            contract_type=contract_type,
            limit=250,
            # The chain as it stood on the session, not as it stands today: an unlisted
            # contract returns no quotes, and counting that as an illiquid strike would be
            # a look-ahead wearing the costume of a data gap.
            as_of=session,
        )
        counters["listings"] += 1
        results = listing.payload.get("results") if isinstance(listing.payload, dict) else None
        if not isinstance(results, list) or not results:
            continue
        contracts = sorted(
            (row for row in results if isinstance(row, dict) and row.get("ticker")),
            key=lambda row: abs(float(row.get("strike_price", 0.0)) - spot),
        )[:MAX_CONTRACTS_PER_SIDE]
        for row in contracts:
            ticker = str(row["ticker"])
            expiry = datetime.fromisoformat(str(row["expiration_date"])[:10]).date()
            tenor = max((expiry - session_date).days, 1) / CALENDAR_YEAR
            response = provider.directed_quotes(ticker, forecast_origin_ns=cutoff_ns)
            counters["quotes"] += 1
            quotes = parse_directed_quotes(
                response.payload,
                contract_id=ticker,
                source_response_id=f"{RUN_ID}:{ticker}:{cutoff_ns}",
                run_id=RUN_ID,
            )
            if not quotes:
                counters["quotes_empty"] += 1
                continue
            quote = quotes[0]
            if quote.bid is None or quote.ask is None or quote.ask <= quote.bid or quote.bid <= 0:
                counters["quotes_unusable"] += 1
                continue
            strike = float(row["strike_price"])
            vol = implied_volatility_from_price(
                0.5 * (quote.bid + quote.ask),
                spot,
                strike,
                tenor,
                is_call=contract_type == "call",
            )
            if not np.isfinite(vol) or not 0.01 <= vol <= 5.0:
                counters["iv_unsolvable"] += 1
                continue
            records.append({"strike": strike, "iv": vol})

    if len(records) < 3:
        return {"contracts": float(len(records))}
    strikes = np.array([row["strike"] for row in records], dtype=np.float64)
    vols = np.array([row["iv"] for row in records], dtype=np.float64)
    log_moneyness = np.log(strikes / spot)
    smile = fit_smile(log_moneyness, vols)
    return {
        "contracts": float(len(records)),
        "strikes": float(np.unique(strikes).size),
        "level": smile.level,
        "slope": smile.slope,
        "curvature": smile.curvature,
        "min_log_moneyness": float(log_moneyness.min()),
        "max_log_moneyness": float(log_moneyness.max()),
    }


def _json_safe(value: object) -> dict[str, object]:
    """Replace every non-finite float with null, recursively."""

    def clean(item: object) -> object:
        if isinstance(item, dict):
            return {key: clean(inner) for key, inner in item.items()}
        if isinstance(item, list):
            return [clean(inner) for inner in item]
        if isinstance(item, float) and not math.isfinite(item):
            return None
        return item

    cleaned = clean(value)
    assert isinstance(cleaned, dict)
    return cleaned


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("D:/MDS650"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sessions", type=int, default=6, help="session-assets to sample")
    parser.add_argument("--seed", type=int, default=650)
    args = parser.parse_args(argv)

    api_key = os.environ.get("MASSIVE_API_KEY")
    if not api_key:
        raise SystemExit("RP2_BLOCK5B_MASSIVE_KEY_MISSING")
    # One listing per asset-session-side and one quote per contract per origin. Recorded as
    # a directed acquisition rather than merely being one.
    assert_directed_only(full_market_download=False)

    inventory = load_inventory()
    bars = load_bar_sources(args.data_root)
    grids: dict[tuple[str, str], FloatArray] = {}
    for (asset, session_date), group in bars.sort(["asset", "session_date", "minute"]).group_by(
        ["asset", "session_date"], maintain_order=True
    ):
        grid = build_session_grid(group, session=session_date)
        if grid.minutes:
            grids[(str(asset), str(session_date))] = grid.close

    available = sorted(
        (session, asset)
        for (session, asset) in inventory
        if (asset, session) in grids and grids[(asset, session)].size > max(SAMPLE_ORIGINS)
    )
    if not available:
        raise SystemExit("RP2_BLOCK5B_NO_SESSIONS")
    generator = np.random.default_rng(args.seed)
    chosen_index = generator.choice(
        len(available), size=min(args.sessions, len(available)), replace=False
    )
    chosen = [available[int(index)] for index in sorted(chosen_index)]

    provider = MassiveProvider(api_key)
    counters = {
        "listings": 0,
        "quotes": 0,
        "quotes_empty": 0,
        "quotes_unusable": 0,
        "iv_unsolvable": 0,
    }
    rows: list[dict[str, object]] = []
    for session, asset in chosen:
        closes = grids[(asset, session)]
        paths = inventory[(session, asset)]
        for minute in SAMPLE_ORIGINS:
            if minute >= closes.size:
                continue
            spot = float(closes[minute])
            if not np.isfinite(spot) or spot <= 0.0:
                continue
            # The listed side goes first so its span can bound the traded fit. Both
            # surfaces are then read over the same interval of log-moneyness.
            listed = listed_surface(provider, asset, session, minute, spot, counters)
            traded = traded_surface(paths, asset, session, minute, spot)
            span = (
                (listed["min_log_moneyness"], listed["max_log_moneyness"])
                if "min_log_moneyness" in listed
                else None
            )
            matched = (
                traded_surface(paths, asset, session, minute, spot, span=span)
                if span is not None
                else {"contracts": 0.0}
            )
            row: dict[str, object] = {
                "asset": asset,
                "session_date": session,
                "origin_minute": minute,
                "spot": spot,
            }
            row.update({f"traded_{key}": value for key, value in traded.items()})
            row.update({f"matched_{key}": value for key, value in matched.items()})
            row.update({f"listed_{key}": value for key, value in listed.items()})
            rows.append(row)
            print(
                f"[5b] {asset} {session} m{minute} traded={traded.get('contracts', 0):.0f} "
                f"listed={listed.get('contracts', 0):.0f}",
                flush=True,
            )
    provider.close()

    frame = pl.DataFrame(rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(args.output_dir / "paired_surfaces.parquet")

    paired = frame.filter(
        pl.col("matched_level").is_not_null() & pl.col("listed_level").is_not_null()
    )
    document: dict[str, object] = {
        "block": "5b",
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "question": "how much of the traded surface is an artefact of what traded",
        "sample": {
            "session_assets": len(chosen),
            "origins_per_session": list(SAMPLE_ORIGINS),
            "strike_band": STRIKE_BAND,
            "dte_window_days": [DTE_MIN_DAYS, DTE_MAX_DAYS],
            "max_contracts_per_side": MAX_CONTRACTS_PER_SIDE,
        },
        "requests": dict(counters),
        "paired_origins": int(paired.height),
    }
    if paired.height >= 3:
        # `matched` is the traded surface restricted to the listed side's own moneyness
        # span, so the two quadratics are fitted over the same interval. `traded` is kept
        # in the artifact as the unrestricted Block 5 construction for reference.
        for field in ("level", "slope", "curvature", "contracts", "strikes"):
            traded_values = paired[f"matched_{field}"].to_numpy().astype(np.float64)
            listed_values = paired[f"listed_{field}"].to_numpy().astype(np.float64)
            difference = listed_values - traded_values
            finite = np.isfinite(difference)
            if int(finite.sum()) < 3:
                continue
            difference = difference[finite]
            standard_error = float(np.std(difference, ddof=1) / np.sqrt(difference.size))
            document[f"selection_effect_{field}"] = {
                "span_matched": True,
                "traded_median": float(np.median(traded_values[finite])),
                "listed_median": float(np.median(listed_values[finite])),
                "mean_difference_listed_minus_traded": float(np.mean(difference)),
                "standard_error": standard_error,
                "t": (
                    float(np.mean(difference) / standard_error)
                    if standard_error > 0.0
                    else float("nan")
                ),
                "pairs": int(difference.size),
            }
    # NaN is not JSON, and a surface that could not be fitted must say so as null rather
    # than break the digest that makes the artifact checkable.
    document = _json_safe(document)
    document["independent_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()
    (args.output_dir / "independent_surface.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
