"""Extensions 1 and 2 - the level-4 sequence model and the moneyness x DTE tensor.

Both were gated by the program behind "only after demonstrating that the tabular baseline
does not capture the signal". Block 7 showed the signal is present; Block 8 showed the
tabular ladder does not convert it into forecast value. The gate is met, so both run here.

**Extension 2 (tensor).** The moneyness x DTE x type grid of signed vega flow and signed
premium is appended to the tabular design and passed through the same LightGBM the ladder
used, so the comparison is like-for-like.

**Extension 1 (level 4).** A DeepSets encoder over the last 48 trades before the cutoff -
a shared per-trade MLP, masked mean-and-max pooling, concatenated with the tabular
features. The control is the identical network with the sequence branch removed, trained
with the same seed, schedule and data, so the only difference is the trade sequence.

Selection stays in D and V. No sealed cohort is read.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import numpy.typing as npt
import polars as pl

try:
    import torch
    from torch import nn
except ModuleNotFoundError as error:  # pragma: no cover - explicit, actionable failure
    raise SystemExit(
        "RP2_EXT12_TORCH_MISSING: this experiment needs a CUDA GPU and PyTorch, which are "
        "an optional extra rather than a project dependency. Install with: "
        "uv sync --extra gpu"
    ) from error

from mds650.b1v3_confirmation import canonical_sha256
from mds650.metrics import paired_day_bootstrap, qlike_losses
from mds650.rp2.baseline import mincer_zarnowitz
from mds650.rp2.ladder import LADDER
from mds650.rp2.panel import (
    B0_FEATURES,
    B1_FEATURES,
    B2_FEATURES,
    VARIANCE_FLOOR,
    build_design,
    chronological_split,
    common_usable_rows,
    describe_information_set,
    load_merged_panel,
    session_rank,
    standardise,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "rp2_ext12_level4"
INPUTS = Path("D:/MDS650/data/rp2_ext2")
B0_PANEL = ROOT / "artifacts" / "rp2_block4_b0" / "b0_panel.parquet"
B1_PANEL = ROOT / "artifacts" / "rp2_block5_surface" / "b1_surface_panel.parquet"
B2_PANEL = ROOT / "artifacts" / "rp2_block6_flow" / "b2_flow_panel.parquet"
SEED = 20260819
EPOCHS = 30
BATCH = 1024
HIDDEN = 128

type FloatArray = npt.NDArray[np.float64]


class DeepSetsForecaster(nn.Module):
    """Tabular head, optionally fed by a permutation-invariant trade-set encoder."""

    def __init__(self, tabular_features: int, trade_features: int, *, use_sequence: bool):
        super().__init__()
        self.use_sequence = use_sequence
        self.encoder = nn.Sequential(
            nn.Linear(trade_features, HIDDEN), nn.GELU(),
            nn.Linear(HIDDEN, HIDDEN), nn.GELU(),
        )
        pooled = 2 * HIDDEN if use_sequence else 0
        self.head = nn.Sequential(
            nn.Linear(tabular_features + pooled, HIDDEN), nn.GELU(),
            nn.Linear(HIDDEN, HIDDEN), nn.GELU(),
            nn.Linear(HIDDEN, 1),
        )

    def forward(self, tabular: torch.Tensor, sequence: torch.Tensor,
                mask: torch.Tensor) -> torch.Tensor:
        if not self.use_sequence:
            tabular_only: torch.Tensor = self.head(tabular).squeeze(-1)
            return tabular_only
        encoded = self.encoder(sequence) * mask.unsqueeze(-1)
        counts = mask.sum(dim=1, keepdim=True).clamp(min=1.0)
        mean_pooled = encoded.sum(dim=1) / counts
        max_pooled = encoded.masked_fill(mask.unsqueeze(-1) == 0, -1e9).max(dim=1).values
        max_pooled = torch.nan_to_num(max_pooled, neginf=0.0)
        combined = torch.cat([tabular, mean_pooled, max_pooled], dim=1)
        out: torch.Tensor = self.head(combined).squeeze(-1)
        return out


def _train(
    model: nn.Module, tabular: torch.Tensor, sequence: torch.Tensor, mask: torch.Tensor,
    response: torch.Tensor, train_index: torch.Tensor, device: torch.device
) -> None:
    optimiser = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=EPOCHS)
    loss_fn = nn.MSELoss()
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    model.train()
    for _epoch in range(EPOCHS):
        order = train_index[torch.randperm(train_index.numel(), generator=generator)]
        for start in range(0, order.numel(), BATCH):
            batch = order[start : start + BATCH].to(device)
            optimiser.zero_grad(set_to_none=True)
            predicted = model(tabular[batch], sequence[batch], mask[batch])
            loss = loss_fn(predicted, response[batch])
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimiser.step()
        schedule.step()


def _predict(
    model: nn.Module, tabular: torch.Tensor, sequence: torch.Tensor, mask: torch.Tensor
) -> FloatArray:
    model.eval()
    out: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, tabular.shape[0], 4096):
            stop = start + 4096
            out.append(
                model(tabular[start:stop], sequence[start:stop], mask[start:stop])
                .float().cpu().numpy()
            )
    return np.concatenate(out).astype(np.float64)


def _contrast(
    base: FloatArray, expanded: FloatArray, target: FloatArray,
    sessions: npt.NDArray[np.str_]
) -> dict[str, float]:
    difference = qlike_losses(target, base) - qlike_losses(target, expanded)
    boot = paired_day_bootstrap(
        pl.DataFrame({"session_date": sessions, "loss_difference": difference}),
        repetitions=2000, seed=650,
    )
    return {
        "delta_qlike": float(boot["estimate"]),
        "ci_low": float(boot["ci_low"]),
        "ci_high": float(boot["ci_high"]),
        "p_value": float(boot["p_value_two_sided"]),
        "clusters": float(boot["clusters"]),
    }


def run_role(
    panel: pl.DataFrame, tensor: npt.NDArray[np.float32], sequence: npt.NDArray[np.float32],
    *, role: str, train_share: float, device: torch.device
) -> dict[str, object]:
    frame = panel.filter(pl.col("role") == role).sort(
        ["session_date", "asset", "origin_minute"]
    )
    index = np.asarray(frame["_row"].to_numpy(), dtype=np.int64)
    target = np.asarray(frame["rv30"].to_numpy(), dtype=np.float64)
    base_design, base_names = build_design(frame, [B0_FEATURES, B1_FEATURES, B2_FEATURES])
    keep = common_usable_rows({"B0+B1+B2": base_design}, target)
    information_sets = {
        "B0+B1+B2": describe_information_set(("B0", "B1", "B2"), base_names, keep)
    }
    if int(keep.sum()) < 2000:
        return {
            "status": "INSUFFICIENT_ROWS",
            "rows": int(keep.sum()),
            "information_sets": information_sets,
        }

    frame = frame.filter(pl.Series(keep))
    target, base_design, index = target[keep], base_design[keep], index[keep]
    ranks = session_rank(frame["session_date"].to_numpy())
    train, test = chronological_split(ranks, train_share=train_share)
    labels = frame["session_date"].to_numpy()
    response = np.log(np.maximum(target, VARIANCE_FLOOR))

    results: dict[str, object] = {
        "status": "MEASURED",
        "rows": int(keep.sum()),
        "test_rows": int(test.sum()),
        "sessions": int(np.unique(ranks).size),
        "information_sets": information_sets,
    }

    # ---- Extension 2: the moneyness x DTE tensor through the same tree family --------
    tensor_block = tensor[index].reshape(index.size, -1).astype(np.float64)
    tensor_block = np.sign(tensor_block) * np.log1p(np.abs(tensor_block))
    with_tensor = np.column_stack([base_design, tensor_block])
    forecasts = {
        "tabular": LADDER["lightgbm"](standardise(base_design, train), target, train),
        "tabular+tensor": LADDER["lightgbm"](standardise(with_tensor, train), target, train),
    }
    results["extension_2_tensor"] = {
        "tensor_columns": int(tensor_block.shape[1]),
        "qlike": {
            name: float(np.mean(qlike_losses(target[test], values[test])))
            for name, values in forecasts.items()
        },
        "delta_tensor_over_tabular": _contrast(
            forecasts["tabular"][test], forecasts["tabular+tensor"][test],
            target[test], labels[test],
        ),
    }

    # ---- Extension 1: DeepSets over the raw trade sequence ---------------------------
    torch.manual_seed(SEED)
    standardised = standardise(base_design, train)
    sequence_block = sequence[index]
    flat = sequence_block.reshape(-1, sequence_block.shape[-1])
    centre = flat[flat[:, 2] != 0.0].mean(axis=0)
    spread = np.where(flat[flat[:, 2] != 0.0].std(axis=0) > 0, flat.std(axis=0), 1.0)
    normalised = (sequence_block - centre) / spread

    tabular_t = torch.tensor(standardised, dtype=torch.float32, device=device)
    sequence_t = torch.tensor(normalised, dtype=torch.float32, device=device)
    mask_t = torch.tensor(
        (sequence_block[:, :, 2] != 0.0).astype(np.float32), dtype=torch.float32, device=device
    )
    response_t = torch.tensor(response, dtype=torch.float32, device=device)
    train_index = torch.tensor(np.flatnonzero(train), dtype=torch.long)

    neural: dict[str, FloatArray] = {}
    log_rmse: dict[str, float] = {}
    for name, use_sequence in (("mlp_tabular", False), ("deepsets_sequence", True)):
        torch.manual_seed(SEED)
        model = DeepSetsForecaster(
            tabular_t.shape[1], sequence_t.shape[2], use_sequence=use_sequence
        ).to(device)
        _train(model, tabular_t, sequence_t, mask_t, response_t, train_index, device)
        fitted = _predict(model, tabular_t, sequence_t, mask_t)
        log_rmse[name] = float(np.sqrt(np.mean((response[test] - fitted[test]) ** 2)))
        # Lognormal smearing amplifies a poorly fit network's level error into an
        # enormous QLIKE, which makes the two arms incomparable. Recalibrate BOTH on
        # the training period, exactly as Block 8 does, so the contrast is about
        # information rather than about which arm happened to converge.
        raw = np.exp(fitted) * float(np.exp(0.5 * np.var(response[train] - fitted[train])))
        calibration = mincer_zarnowitz(target[train], raw[train])
        neural[name] = np.exp(
            calibration.intercept
            + calibration.slope * np.log(np.maximum(raw, VARIANCE_FLOOR))
        )

    results["extension_1_level4"] = {
        "device": str(device),
        "epochs": EPOCHS,
        "sequence_length": int(sequence_block.shape[1]),
        "mean_trades_per_origin": float(mask_t.sum(dim=1).mean().item()),
        "qlike_recalibrated": {
            name: float(np.mean(qlike_losses(target[test], values[test])))
            for name, values in neural.items()
        },
        "log_scale_rmse": log_rmse,
        "delta_sequence_over_tabular": _contrast(
            neural["mlp_tabular"][test], neural["deepsets_sequence"][test],
            target[test], labels[test],
        ),
        "qlike_lightgbm_reference": float(
            np.mean(qlike_losses(target[test], forecasts["tabular"][test]))
        ),
    }
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=INPUTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-share", type=float, default=0.6)
    args = parser.parse_args(argv)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tensor = np.load(args.inputs / "tensor.npy")
    sequence = np.load(args.inputs / "sequence.npy")
    keys = pl.read_parquet(args.inputs / "keys.parquet").with_row_index("_row")

    panel = load_merged_panel(B0_PANEL, B1_PANEL, B2_PANEL).join(
        keys, on=["asset", "session_date", "origin_minute"], how="inner"
    )
    document: dict[str, object] = {
        "extensions": [1, 2],
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "gate_met_by": "Block 7 signal present + Block 8 tabular ladder fails to convert it",
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "seed": SEED,
        "panel_rows": panel.height,
    }
    for role in ("D", "V"):
        document[role] = run_role(
            panel, tensor, sequence, role=role, train_share=args.train_share, device=device
        )
    document["ext12_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "level4_and_tensor.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for role in ("D", "V"):
        block = document[role]
        assert isinstance(block, dict)
        print(f"=== role {role}: {block.get('status')} rows={block.get('rows')} ===")
        for key in ("extension_2_tensor", "extension_1_level4"):
            entry = block.get(key)
            if not isinstance(entry, dict):
                continue
            qlike = entry.get("qlike") or entry["qlike_recalibrated"]
            assert isinstance(qlike, dict)
            print(f"  {key}: " + "  ".join(f"{n}={v:.5f}" for n, v in qlike.items()))
            delta_key = (
                "delta_tensor_over_tabular" if "2" in key else "delta_sequence_over_tabular"
            )
            delta = entry[delta_key]
            assert isinstance(delta, dict)
            print(
                f"      delta={delta['delta_qlike']:+.5f} "
                f"[{delta['ci_low']:+.5f},{delta['ci_high']:+.5f}] p={delta['p_value']:.4f}"
            )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
