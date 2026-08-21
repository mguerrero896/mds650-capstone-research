"""Extensions 1 and 2 - one tape pass producing the inputs both of them need.

Block 8 showed the tabular ladder does not convert the Block 7 signal into forecast
value, and Block 7 showed the signal is there. That is exactly the demonstration the
program requires before the moneyness x DTE tensor (§6.5) and the level-4 sequence models
(§8) may be built, so the gate is now met.

Two artefacts per origin, from the same pass over the raw tape:

* **tensor** - signed vega flow and premium on a moneyness x DTE x option-type grid,
  the representation §6.5 asks for; and
* **sequence** - the last N trades before the cutoff as a (N, F) matrix, which is what a
  DeepSets / temporal-convolution / event-transformer model consumes.

Point-in-time rule unchanged: only rows with ``created_at <= origin - 120 s`` are visible.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt
import polars as pl

from mds650.b1v3_confirmation import canonical_sha256
from mds650.rp2.bars import MARKET_TZ, SESSION_OPEN_MINUTE, build_session_grid, load_bar_sources
from mds650.rp2.flow import CONTRACT_MULTIPLIER, black_scholes_greeks

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("D:/MDS650/data/rp2_ext2")
INVENTORY = ROOT / "artifacts" / "rp2_block1_partition" / "inventory.jsonl"
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
CUTOFF_SECONDS = 120
WINDOW_SECONDS = 300
CALENDAR_YEAR = 365.0
NY = ZoneInfo(MARKET_TZ)

#: Log-moneyness cut points; seven buckets from deep OTM put to deep OTM call.
MONEYNESS_EDGES: tuple[float, ...] = (-0.10, -0.05, -0.02, 0.02, 0.05, 0.10)
#: Day-to-expiry cut points; four buckets.
DTE_EDGES: tuple[float, ...] = (7.0, 30.0, 90.0)
MONEYNESS_BUCKETS = len(MONEYNESS_EDGES) + 1
DTE_BUCKETS = len(DTE_EDGES) + 1
TYPE_BUCKETS = 2
TENSOR_CELLS = MONEYNESS_BUCKETS * DTE_BUCKETS * TYPE_BUCKETS
TENSOR_CHANNELS = 2  # signed vega flow, signed premium
#: Trades kept per origin for the sequence models, most recent last.
SEQUENCE_LENGTH = 48
SEQUENCE_FEATURES = 8

TAPE_COLUMNS = (
    "underlying_symbol",
    "created_at",
    "nbbo_bid",
    "nbbo_ask",
    "size",
    "premium",
    "implied_volatility",
    "expiry",
    "strike",
    "option_type",
    "tags",
)

type FloatArray = npt.NDArray[np.float64]


def load_inventory() -> dict[tuple[str, str], list[str]]:
    index: dict[tuple[str, str], list[str]] = {}
    with INVENTORY.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            index.setdefault((row["session_date"], row["asset"]), []).append(row["path"])
    return index


def _read_tape(paths: Sequence[str], asset: str) -> pl.DataFrame | None:
    frames = [
        pl.read_parquet(path, columns=list(TAPE_COLUMNS)).filter(
            pl.col("underlying_symbol") == asset
        )
        for path in paths
    ]
    if not frames:
        return None
    tape = pl.concat(frames, how="vertical").filter(
        (pl.col("size") > 0)
        & pl.col("strike").is_not_null()
        & pl.col("implied_volatility").is_between(0.01, 5.0)
    )
    return tape.sort("created_at") if tape.height else None


def build_session_arrays(
    asset: str,
    session: str,
    paths: Sequence[str],
    origins: npt.NDArray[np.int64],
    closes: FloatArray,
) -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32], list[tuple[str, str, int]]] | None:
    """Tensor and sequence for every origin of one session-asset."""

    tape = _read_tape(paths, asset)
    if tape is None or tape.height < 50:
        return None
    created = tape["created_at"].dt.replace_time_zone(None).cast(pl.Int64).to_numpy()
    strike = tape["strike"].cast(pl.Float64).to_numpy().astype(np.float64)
    expiry = tape["expiry"].cast(pl.Date).to_numpy()
    tenor_days = np.maximum(
        (expiry - np.datetime64(session, "D")).astype("timedelta64[D]").astype(np.float64), 1.0
    )
    iv = tape["implied_volatility"].cast(pl.Float64).to_numpy().astype(np.float64)
    size = tape["size"].cast(pl.Float64).to_numpy().astype(np.float64)
    premium = tape["premium"].cast(pl.Float64).to_numpy().astype(np.float64)
    is_call = (tape["option_type"] == "call").to_numpy()
    tags = tape["tags"].cast(pl.Utf8).fill_null("")
    direction = np.where(
        tags.str.contains("ask_side").to_numpy(),
        1.0,
        np.where(tags.str.contains("bid_side").to_numpy(), -1.0, 0.0),
    )

    session_open = datetime.fromisoformat(session).replace(tzinfo=NY) + timedelta(
        minutes=SESSION_OPEN_MINUTE
    )
    open_us = int(
        np.datetime64(session_open.astimezone(UTC).replace(tzinfo=None), "us").astype(np.int64)
    )
    minute_of_trade = np.clip(
        ((created - open_us) // 60_000_000).astype(np.int64), 0, closes.size - 1
    )
    spot = closes[minute_of_trade]
    greeks = black_scholes_greeks(spot, strike, tenor_days / CALENDAR_YEAR, iv, is_call)
    log_moneyness = np.log(np.maximum(strike, 1e-9) / np.maximum(spot, 1e-9))
    vega_flow = greeks.vega * size * CONTRACT_MULTIPLIER * direction
    signed_premium = premium * direction

    moneyness_bucket = np.searchsorted(np.asarray(MONEYNESS_EDGES), log_moneyness)
    dte_bucket = np.searchsorted(np.asarray(DTE_EDGES), tenor_days)
    cell = (
        moneyness_bucket * (DTE_BUCKETS * TYPE_BUCKETS)
        + dte_bucket * TYPE_BUCKETS
        + is_call.astype(np.int64)
    )

    tensors = np.zeros((origins.size, TENSOR_CHANNELS, TENSOR_CELLS), dtype=np.float32)
    sequences = np.zeros((origins.size, SEQUENCE_LENGTH, SEQUENCE_FEATURES), dtype=np.float32)
    keys: list[tuple[str, str, int]] = []
    for position, minute in enumerate(origins):
        origin_time = datetime.fromisoformat(session).replace(tzinfo=NY) + timedelta(
            minutes=int(SESSION_OPEN_MINUTE + minute)
        )
        cutoff = origin_time.astimezone(UTC).replace(tzinfo=None) - timedelta(
            seconds=CUTOFF_SECONDS
        )
        cutoff_us = int(np.datetime64(cutoff, "us").astype(np.int64))
        hi = int(np.searchsorted(created, cutoff_us, side="right"))
        lo = int(np.searchsorted(created, cutoff_us - WINDOW_SECONDS * 1_000_000, side="left"))
        keys.append((asset, session, int(minute)))
        if hi <= lo:
            continue
        span = slice(lo, hi)
        tensors[position, 0] = np.bincount(
            cell[span], weights=vega_flow[span], minlength=TENSOR_CELLS
        ).astype(np.float32)
        tensors[position, 1] = np.bincount(
            cell[span], weights=signed_premium[span], minlength=TENSOR_CELLS
        ).astype(np.float32)

        start = max(lo, hi - SEQUENCE_LENGTH)
        taken = slice(start, hi)
        count = hi - start
        block = np.empty((count, SEQUENCE_FEATURES), dtype=np.float32)
        block[:, 0] = np.log1p((cutoff_us - created[taken]) / 1e6)  # age in seconds
        block[:, 1] = direction[taken]
        block[:, 2] = np.log1p(premium[taken])
        block[:, 3] = log_moneyness[taken]
        block[:, 4] = np.log(tenor_days[taken])
        block[:, 5] = iv[taken]
        block[:, 6] = is_call[taken].astype(np.float32)
        block[:, 7] = np.log1p(size[taken])
        sequences[position, SEQUENCE_LENGTH - count :] = block
    return tensors, sequences, keys


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("D:/MDS650"))
    parser.add_argument(
        "--panel-root",
        type=Path,
        default=ROOT / "artifacts",
        help="directory holding rp2_blockN_* panels; a run directory reads that run",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit-sessions", type=int, default=0)
    args = parser.parse_args(argv)
    global B0_PANEL, B1_PANEL, B2_PANEL, TARGET_PANEL  # noqa: PLW0603
    for _name, _sub in (
        ("B0_PANEL", "rp2_block4_b0/b0_panel.parquet"),
        ("B1_PANEL", "rp2_block5_surface/b1_surface_panel.parquet"),
        ("B2_PANEL", "rp2_block6_flow/b2_flow_panel.parquet"),
        ("TARGET_PANEL", "rp2_block3_target/target_panel.parquet"),
    ):
        if _name in globals():
            globals()[_name] = args.panel_root / _sub


    panel = pl.read_parquet(B0_PANEL)
    inventory = load_inventory()
    bars = load_bar_sources(args.data_root)
    grids: dict[tuple[str, str], FloatArray] = {}
    for (asset, session_date), group in bars.sort(["asset", "session_date", "minute"]).group_by(
        ["asset", "session_date"], maintain_order=True
    ):
        grid = build_session_grid(group, session=session_date)
        grids[(str(asset), str(session_date))] = grid.close

    jobs: list[tuple[str, str, list[str], npt.NDArray[np.int64], FloatArray]] = []
    for (asset, session_date), group in panel.sort(
        ["asset", "session_date", "origin_minute"]
    ).group_by(["asset", "session_date"], maintain_order=True):
        paths = inventory.get((str(session_date), str(asset))) or inventory.get(
            (str(session_date), "__ALL__")
        )
        closes = grids.get((str(asset), str(session_date)))
        if paths is None or closes is None:
            continue
        jobs.append(
            (
                str(asset),
                str(session_date),
                paths,
                group["origin_minute"].to_numpy().astype(np.int64),
                closes,
            )
        )
    if args.limit_sessions:
        jobs = jobs[: args.limit_sessions]

    tensors: list[npt.NDArray[np.float32]] = []
    sequences: list[npt.NDArray[np.float32]] = []
    keys: list[tuple[str, str, int]] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(lambda job: build_session_arrays(*job), jobs):
            if result is None:
                failures += 1
                continue
            tensor_block, sequence_block, key_block = result
            tensors.append(tensor_block)
            sequences.append(sequence_block)
            keys.extend(key_block)
    if not tensors:
        raise SystemExit("RP2_EXT2_EMPTY")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    tensor_array = np.concatenate(tensors, axis=0)
    sequence_array = np.concatenate(sequences, axis=0)
    np.save(args.output_dir / "tensor.npy", tensor_array)
    np.save(args.output_dir / "sequence.npy", sequence_array)
    pl.DataFrame(
        {
            "asset": [k[0] for k in keys],
            "session_date": [k[1] for k in keys],
            "origin_minute": [k[2] for k in keys],
        }
    ).write_parquet(args.output_dir / "keys.parquet")

    document: dict[str, object] = {
        "extension": "1+2 inputs",
        "gate_met_by": "Block 7 shows the signal exists; Block 8 shows the tabular ladder "
        "does not convert it — the program's precondition for the tensor and level 4",
        "cutoff_seconds": CUTOFF_SECONDS,
        "window_seconds": WINDOW_SECONDS,
        "moneyness_edges": list(MONEYNESS_EDGES),
        "dte_edges": list(DTE_EDGES),
        "tensor_shape": list(tensor_array.shape),
        "sequence_shape": list(sequence_array.shape),
        "sequence_features": [
            "log_age_s",
            "direction",
            "log1p_premium",
            "log_moneyness",
            "log_dte_days",
            "implied_volatility",
            "is_call",
            "log1p_size",
        ],
        "rows": len(keys),
        "session_assets_without_tape": failures,
        "tensor_nonzero_share": float(np.mean(tensor_array != 0.0)),
        "sequence_padded_share": float(np.mean(sequence_array[:, :, 2] == 0.0)),
    }
    document["inputs_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()
    (args.output_dir / "inputs.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(document, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
