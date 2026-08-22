"""Fetch the volume for minutes whose own bar contradicts the zero the provider wrote.

A price cannot move without trades. Measured across the six bar stores, 2,355 minutes
carry `volume == 0.0` with `high > low`, and they are not the thin ones: 60 % sit at
midday, 3.5 % in the first half hour, on the six most heavily traded US equities. Asked
about one of them - AAPL, 2025-07-07 11:53 New York, which FMP reports ranging 211.65 to
211.77 on zero volume - the second provider reports 53,676 shares across 809 trades.

So the volume exists and the primary provider lost it. This asks the second provider for
those minutes and writes an overlay keyed on (asset, bar_start_utc), which
`load_bar_sources` applies to the loaded bars. The source stores are not modified.

INTEGRITY GATE: the two series must be the same series before a volume is spliced between
them, and that is checked on the minutes where BOTH providers have good data - the ones
whose recorded volume is positive - rather than on the broken minute against itself. Gate
5.1 measured the two providers agreeing to a median relative close difference of 3.1e-06
under identical labels; a day whose healthy minutes do not reproduce that is not the same
series and is refused. Checking the contradicted minute against itself was the first
version of this gate and it was the wrong test: it rejected every day, because a tolerance
of 1e-6 in dollars is a same-file round-trip tolerance, not a cross-provider one.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, "src")

from mds650.providers.massive import MassiveProvider  # noqa: E402
from mds650.rp2.bars import BAR_SOURCES, MARKET_TZ  # noqa: E402

#: Gate 5.1 measured the two providers under identical bar labels at a median relative
#: close difference of 3.1e-06, and the shifted-label alternative at 3.66e-04. The
#: threshold has to separate those two, not separate "identical" from "nearly identical":
#: it sits an order of magnitude below the shifted figure and above the spread the
#: same-label case actually shows. Twenty-four days measured between 1.6e-05 and 6.9e-05,
#: which is under half a cent on a two-hundred-dollar share - the same series, quoted from
#: a different consolidated tape. A tighter threshold rejects those for being imperfect
#: rather than for being different, which is not what this gate is for.
HEALTHY_CLOSE_TOLERANCE = 1e-4
#: What the shifted-label convention produces, per gate 5.1. Kept beside the threshold so
#: a reader can see what it is meant to catch.
SHIFTED_LABEL_AGREEMENT = 3.66e-4
#: And enough of them to mean something: a day matched on a handful of minutes proves
#: nothing about the two providers describing the same session.
MINIMUM_HEALTHY_MINUTES = 100

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--data-root", default="D:/MDS650")
parser.add_argument("--out", required=True)
parser.add_argument("--limit-pairs", type=int, default=0)
#: The second provider returned HTTP 429 on 416 of 501 unpaced requests. Its own client
#: already backs off and retries; this spaces the calls so the retries are not what carries
#: the run. Two seconds over five hundred days is under twenty minutes.
parser.add_argument("--pace-seconds", type=float, default=2.0)
#: Merging with an earlier attempt means a rate-limited run is resumed rather than repeated,
#: and the minutes already verified are not fetched again.
parser.add_argument("--merge-with", type=Path, default=None)
args = parser.parse_args()

key = os.environ.get("MASSIVE_API_KEY")
if not key:
    raise SystemExit("MASSIVE_API_KEY ausente del entorno")


def _store(path: str) -> pl.DataFrame | None:
    """One store's minutes, on a common UTC key, with the volume it recorded."""
    schema = pl.scan_parquet(path).collect_schema().names()
    if not {"volume", "high", "low", "close"} <= set(schema):
        return None
    stamp = "bar_start_utc" if "bar_start_utc" in schema else "bar_timestamp_raw_utc"
    return (
        pl.scan_parquet(path)
        .select(
            pl.col("asset"),
            pl.col(stamp).dt.convert_time_zone("UTC").alias("bar_start_utc"),
            pl.col("close").cast(pl.Float64),
            pl.col("volume").cast(pl.Float64),
            (pl.col("high") > pl.col("low")).alias("moved"),
        )
        .collect()
    )


blocks = [
    frame
    for _, _, relative in BAR_SOURCES
    if (frame := _store(f"{args.data_root}/{relative}")) is not None
]
if not blocks:
    raise SystemExit("no bar store carries a volume column")
everything = pl.concat(blocks, how="vertical").unique(subset=["asset", "bar_start_utc"])
wanted = everything.filter((pl.col("volume") == 0.0) & pl.col("moved"))
wanted = wanted.with_columns(
    pl.col("bar_start_utc").dt.convert_time_zone(MARKET_TZ).dt.date().alias("session_date")
)
already = (
    pl.read_parquet(args.merge_with)
    if args.merge_with is not None and args.merge_with.is_file()
    else pl.DataFrame(
        schema={
            "asset": pl.String,
            "bar_start_utc": wanted.schema["bar_start_utc"],
            "volume": pl.Float64,
        }
    )
)
if already.height:
    print(f"reanudando: {already.height:,} minutos ya recuperados y verificados", flush=True)
    done = already.with_columns(
        pl.col("bar_start_utc").dt.convert_time_zone(MARKET_TZ).dt.date().alias("session_date")
    ).select("asset", "session_date").unique()
    wanted = wanted.join(done, on=["asset", "session_date"], how="anti")
pairs = sorted(wanted.select("asset", "session_date").unique().rows())
if args.limit_pairs:
    pairs = pairs[: args.limit_pairs]
processed = wanted.join(
    pl.DataFrame(pairs, schema=["asset", "session_date"], orient="row"),
    on=["asset", "session_date"],
    how="semi",
)
print(
    f"minutos contradictorios: {processed.height:,} en los {len(pairs)} pares que se "
    f"consultan, de {wanted.height:,} en total",
    flush=True,
)

provider = MassiveProvider(key)
recovered: list[pl.DataFrame] = []
absent: list[tuple[str, str]] = []
mismatched: list[tuple[str, str, float]] = []
agreements: list[float] = []

for position, (asset, session) in enumerate(pairs, start=1):
    stamp = (session if isinstance(session, date) else date.fromisoformat(str(session))).isoformat()
    try:
        response = provider.stock_minute_aggregates(asset, from_date=stamp, to_date=stamp)
        body = getattr(response, "payload", response)
        rows = body.get("results") or [] if isinstance(body, dict) else []
    except Exception as error:  # noqa: BLE001 - a provider failure is a reported outcome
        # The code, not just the class: a 403 is a plan limit and a 429 is a pace, and the
        # first version of this recorded only "ProviderBlockedError", which says neither.
        absent.append((asset, f"{stamp}: {type(error).__name__}({error})"))
        continue
    if not rows:
        absent.append((asset, f"{stamp}: sin barras"))
        continue

    fetched = pl.DataFrame(
        [
            {
                "bar_start_utc": row["t"],
                "second_close": float(row["c"]),
                "second_volume": float(row["v"]),
            }
            for row in rows
            if row.get("t") is not None and row.get("c") is not None and row.get("v") is not None
        ]
    ).with_columns(
        pl.from_epoch(pl.col("bar_start_utc"), time_unit="ms")
        .dt.replace_time_zone("UTC")
        .alias("bar_start_utc")
    )

    # First establish that the two providers are describing the same session, using the
    # minutes where both recorded a positive volume.
    day = everything.filter(
        (pl.col("asset") == asset)
        & (pl.col("bar_start_utc").dt.convert_time_zone(MARKET_TZ).dt.date() == session)
    ).join(fetched, on="bar_start_utc", how="inner")
    healthy = day.filter(pl.col("volume") > 0.0).with_columns(
        ((pl.col("close") - pl.col("second_close")).abs() / pl.col("close")).alias("relative")
    )
    if healthy.height < MINIMUM_HEALTHY_MINUTES:
        absent.append((asset, f"{stamp}: solo {healthy.height} minutos sanos emparejados"))
        continue
    agreement = float(np.median(healthy["relative"].to_numpy()))
    agreements.append(agreement)
    if agreement > HEALTHY_CLOSE_TOLERANCE:
        mismatched.append((asset, stamp, agreement))
        continue
    recovered.append(
        day.filter((pl.col("volume") == 0.0) & pl.col("moved") & (pl.col("second_volume") > 0.0))
        .select("asset", "bar_start_utc", pl.col("second_volume").alias("volume"))
    )
    if position % 100 == 0:
        print(f"  {position}/{len(pairs)} ...", flush=True)
    if args.pace_seconds > 0 and position < len(pairs):
        time.sleep(args.pace_seconds)

provider.close()

print()
print(f"pares consultados: {len(pairs)}")
print(f"pares sin datos en el segundo proveedor: {len(absent)}")
for asset, why in absent[:8]:
    print(f"  {asset} {why}")
if agreements:
    spread = np.asarray(agreements)
    print(
        f"acuerdo entre proveedores en minutos sanos, sobre {spread.size} dias: "
        f"mediana {np.median(spread):.2e}  p90 {np.quantile(spread, 0.9):.2e}  "
        f"max {spread.max():.2e}  (umbral {HEALTHY_CLOSE_TOLERANCE:.0e}, "
        f"etiqueta desplazada {SHIFTED_LABEL_AGREEMENT:.2e})"
    )
print(f"dias cuyos minutos sanos NO reproducen el acuerdo de la puerta 5.1: {len(mismatched)}")
for asset, stamp, worst in mismatched[:8]:
    print(f"  {asset} {stamp}: acuerdo mediano en minutos sanos {worst:.2e}")
if mismatched:
    raise SystemExit("ABORTA: el segundo proveedor no reproduce los cierres registrados")
if not recovered:
    raise SystemExit("ABORTA: no se recupero ningun minuto")

blocks_out = (
    [*recovered, already.select("asset", "bar_start_utc", "volume")]
    if already.height
    else recovered
)
out = pl.concat(blocks_out, how="vertical").unique(subset=["asset", "bar_start_utc"])
out = out.sort("asset", "bar_start_utc")
out.write_parquet(args.out)
print()
print(f"escrito {args.out}: {out.height:,} minutos con volumen recuperado")
print(
    f"  de los {processed.height:,} contradictorios consultados, quedan sin dato: "
    f"{processed.height - out.height:,}"
)
print(f"  volumen recuperado: mediana {float(np.median(out['volume'].to_numpy())):,.0f} acciones")
