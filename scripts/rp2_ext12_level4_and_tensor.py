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
from mds650.rp2.feature_registry import assert_segment_coverage, describe_coverage
from mds650.rp2.inference import DEFAULT_BOOTSTRAP, DEFAULT_SEED
from mds650.rp2.ladder import LADDER
from mds650.rp2.panel import (
    B0_FEATURES,
    B1_FEATURES,
    B2_FEATURES,
    CORE_SETS,
    VARIANCE_FLOOR,
    build_design,
    chronological_split,
    common_evaluation_mask,
    describe_information_set,
    lift_mask,
    load_merged_panel,
    session_rank,
    standardise,
)
from mds650.rp2.preprocessing import describe_preprocessor, fold_design

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


def _contrast_squared_error(
    base: FloatArray, expanded: FloatArray, target: FloatArray,
    sessions: npt.NDArray[np.str_]
) -> dict[str, float]:
    """The paired session contrast on squared error, for the scale the model minimised."""

    difference = (target - base) ** 2 - (target - expanded) ** 2
    boot = paired_day_bootstrap(
        pl.DataFrame({"session_date": sessions, "loss_difference": difference}),
        repetitions=DEFAULT_BOOTSTRAP, seed=DEFAULT_SEED,
    )
    return {
        "delta_squared_error": float(boot["estimate"]),
        "ci_low": float(boot["ci_low"]),
        "ci_high": float(boot["ci_high"]),
        "p_value": float(boot["p_value_two_sided"]),
        "clusters": float(boot["clusters"]),
    }


def _contrast(
    base: FloatArray, expanded: FloatArray, target: FloatArray,
    sessions: npt.NDArray[np.str_]
) -> dict[str, float]:
    difference = qlike_losses(target, base) - qlike_losses(target, expanded)
    boot = paired_day_bootstrap(
        pl.DataFrame({"session_date": sessions, "loss_difference": difference}),
        repetitions=DEFAULT_BOOTSTRAP, seed=DEFAULT_SEED,
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
    _, base_names = build_design(frame, [B0_FEATURES, B1_FEATURES, B2_FEATURES])
    registry_features = [*B0_FEATURES, *B1_FEATURES, *B2_FEATURES]
    # The tensor and the trade sequence are inputs to two of the three published arms, so
    # they belong in the mask the run fails closed on. A tape row with a null premium makes
    # a non-finite tensor cell; leaving those rows in lets the neural arm produce NaN
    # predictions on a sample the tabular arm never had to survive, and the arms would then
    # be compared on different rows.
    extension_finite = np.isfinite(
        tensor[index].reshape(index.size, -1).astype(np.float64)
    ).all(axis=1) & np.isfinite(sequence[index].astype(np.float64)).all(axis=(1, 2))
    keep = common_evaluation_mask(frame, target) & extension_finite
    information_sets: dict[str, object] = {
        "B0+B1+B2": describe_information_set(("B0", "B1", "B2"), base_names, keep)
    }
    if int(keep.sum()) < 2000:
        return {
            "status": "INSUFFICIENT_ROWS",
            "rows": int(keep.sum()),
            "information_sets": information_sets,
        }

    role_frame = frame
    frame = frame.filter(pl.Series(keep))
    target, index = target[keep], index[keep]
    ranks = session_rank(frame["session_date"].to_numpy())
    train, test = chronological_split(ranks, train_share=train_share)
    # The tabular arm is a registry design and is imputed and scaled fold-locally. The
    # tensor and sequence arms are inputs the registry does not describe, so they keep
    # the plain standardisation and are never part of a primary contrast.
    base_design, _, base_fitted = fold_design(frame, registry_features, train)
    # The floor holds on the panel and on this role; it also has to hold on the two
    # segments this run fits and scores, which is where a held-out tail with a gap in it
    # would otherwise become a result. The masks are lifted back onto the unfiltered role
    # frame: checking them on the frame the common mask has already pruned would be
    # checking that the rows which survived are the rows which survived.
    assert_segment_coverage(
        role_frame,
        {"train": lift_mask(keep, train), "test": lift_mask(keep, test)},
        *CORE_SETS.values(),
    )
    information_sets["B0+B1+B2"] = describe_information_set(
        ("B0", "B1", "B2"), base_names, lift_mask(keep, test)
    )
    labels = frame["session_date"].to_numpy()
    response = np.log(np.maximum(target, VARIANCE_FLOOR))

    results: dict[str, object] = {
        "status": "MEASURED",
        "rows": int(keep.sum()),
        "train_share": train_share,
        "test_rows": int(test.sum()),
        "sessions": int(np.unique(ranks).size),
        "information_sets": information_sets,
        # The tabular arm is a registry design and its fitted statistics are what any
        # reproduction of these forecasts needs. The tensor and sequence arms are
        # standardised plainly and are described per arm above.
        "preprocessing": {"B0+B1+B2": describe_preprocessor(base_fitted)},
    }

    # ---- Extension 2: the moneyness x DTE tensor through the same tree family --------
    tensor_block = tensor[index].reshape(index.size, -1).astype(np.float64)
    tensor_block = np.sign(tensor_block) * np.log1p(np.abs(tensor_block))
    with_tensor = np.column_stack([base_design, tensor_block])
    information_sets["B0+B1+B2+tensor"] = describe_information_set(
        ("B0", "B1", "B2", "tensor"),
        base_names + tuple(f"tensor_{index}" for index in range(tensor_block.shape[1])),
        lift_mask(keep, test),
    )
    forecasts = {
        "tabular": LADDER["lightgbm"](base_design, target, train),
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
    standardised = base_design
    sequence_block = sequence[index]
    flat = sequence_block.reshape(-1, sequence_block.shape[-1])
    centre = flat[flat[:, 2] != 0.0].mean(axis=0)
    spread = np.where(flat[flat[:, 2] != 0.0].std(axis=0) > 0, flat.std(axis=0), 1.0)
    normalised = (sequence_block - centre) / spread
    information_sets["B0+B1+B2+sequence"] = describe_information_set(
        ("B0", "B1", "B2", "sequence"),
        base_names
        + tuple(f"sequence_channel_{index}" for index in range(sequence_block.shape[-1])),
        lift_mask(keep, test),
    )

    tabular_t = torch.tensor(standardised, dtype=torch.float32, device=device)
    sequence_t = torch.tensor(normalised, dtype=torch.float32, device=device)
    mask_t = torch.tensor(
        (sequence_block[:, :, 2] != 0.0).astype(np.float32), dtype=torch.float32, device=device
    )
    response_t = torch.tensor(response, dtype=torch.float32, device=device)
    train_index = torch.tensor(np.flatnonzero(train), dtype=torch.long)

    neural: dict[str, FloatArray] = {}
    log_rmse: dict[str, float] = {}
    fitted_by_arm: dict[str, FloatArray] = {}
    for name, use_sequence in (("mlp_tabular", False), ("deepsets_sequence", True)):
        torch.manual_seed(SEED)
        model = DeepSetsForecaster(
            tabular_t.shape[1], sequence_t.shape[2], use_sequence=use_sequence
        ).to(device)
        _train(model, tabular_t, sequence_t, mask_t, response_t, train_index, device)
        fitted = _predict(model, tabular_t, sequence_t, mask_t)
        fitted_by_arm[name] = fitted
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
        # The second reference the preregistration requires. The run of 2026-08-18 reported
        # +0.634 at p=0.004 against the control alone while scoring QLIKE 0.1496 against the
        # ladder's 0.1374 - it lost to the model already in production and the delta was
        # significant anyway, because the control was five times worse than a tree on the
        # same features. One reference cannot tell "the sequence helps" from "our control is
        # bad".
        "delta_sequence_over_lightgbm": _contrast(
            forecasts["tabular"][test], neural["deepsets_sequence"][test],
            target[test], labels[test],
        ),
        # The same contrast on the scale the networks were fitted on. A QLIKE delta that
        # disagrees in magnitude with this one is reporting the exp() transform's
        # sensitivity to level error, not predictive skill.
        "delta_log_scale_sequence_over_tabular": _contrast_squared_error(
            fitted_by_arm["mlp_tabular"][test], fitted_by_arm["deepsets_sequence"][test],
            response[test], labels[test],
        ),
        "qlike_lightgbm_reference": float(
            np.mean(qlike_losses(target[test], forecasts["tabular"][test]))
        ),
    }
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=INPUTS)
    parser.add_argument(
        "--panel-root",
        type=Path,
        default=ROOT / "artifacts",
        help="directory holding rp2_blockN_* panels; a run directory reads that run",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-share", type=float, default=0.6)
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


    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tensor = np.load(args.inputs / "tensor.npy")
    sequence = np.load(args.inputs / "sequence.npy")
    keys = pl.read_parquet(args.inputs / "keys.parquet").with_row_index("_row")

    panel = load_merged_panel(B0_PANEL, B1_PANEL, B2_PANEL).join(
        keys, on=["asset", "session_date", "origin_minute"], how="inner"
    )
    document: dict[str, object] = {
        # Which frozen sets were fitted, how complete they were, and the hash of the
        # registry that decided them. Without it an artifact records a design width and
        # nothing a reader can check that width against.
        "feature_registry": describe_coverage(panel, *CORE_SETS.values()),
        "extension_inputs": "the tensor and sequence arms add inputs outside the registry; "
        "their resolved names are recorded per arm under information_sets",
        "extensions": [1, 2],
        "program": "docs/research_program_v2.md",
        "label": "EXPLORATORY_MECHANISM_DISCOVERY",
        "gate_met_by": "Block 7 signal present + Block 8 tabular ladder fails to convert it",
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "seed": SEED,
        "panel_rows": panel.height,
    }
    # Development only, per the preregistration: V holds 32 evaluated sessions with an
    # MDE of 0.0027 to 0.0177 against effects near 0.004, and it is the only untouched
    # comparison left. Spending it on an exploratory family would leave nothing to
    # confirm whatever this finds.
    for role in ("D",):
        document[role] = run_role(
            panel, tensor, sequence, role=role, train_share=args.train_share, device=device
        )
    document["ext12_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "level4_and_tensor.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # Development only, per the preregistration: V holds 32 evaluated sessions with an
    # MDE of 0.0027 to 0.0177 against effects near 0.004, and it is the only untouched
    # comparison left. Spending it on an exploratory family would leave nothing to
    # confirm whatever this finds.
    for role in ("D",):
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
