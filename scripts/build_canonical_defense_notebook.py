"""Generate the portable, evidence-only canonical RV30 defense notebook.

The notebook is intentionally an offline presentation layer.  It reads the
sanitized canonical manifest and registered contrast table through the same
loader used by the HTML/Markdown defense package; it does not acquire data or
reimplement forecasting logic.
"""

from __future__ import annotations

import argparse
import json
import textwrap
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _source(text: str) -> list[str]:
    """Return a notebook source as one deterministic line list."""

    return textwrap.dedent(text).strip("\n").splitlines(keepends=True)


def _markdown(text: str) -> dict[str, Any]:
    """Build a Markdown notebook cell."""

    return {"cell_type": "markdown", "metadata": {}, "source": _source(text)}


def _code(text: str) -> dict[str, Any]:
    """Build a code notebook cell without execution state."""

    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": _source(text),
    }


def build_notebook() -> dict[str, Any]:
    """Return the portable canonical RV30 notebook document.

    Returns
    -------
    dict[str, Any]
        Notebook JSON compatible with nbformat 4.
    """

    cells = [
        _markdown(
            """
            # MDS650 — Canonical RV30 Defense Evidence

            **Pregunta:** ¿el estado ordinario de opciones (B1v2a) mejora el
            pronóstico de la varianza realizada a 30 minutos frente a B0v2, y
            la actividad de operaciones (B2v2) aporta información incremental
            sobre B1v2a?

            Esta libreta solo presenta evidencia canónica ya validada. No hace
            llamadas de proveedor: el objetivo es que un lector pueda repetir
            la inspección sin secretos ni datos comerciales.
            """
        ),
        _code(
            """
            import json
            import os
            import sys
            from pathlib import Path

            def locate_repo() -> Path:
                requested = os.environ.get("MDS650_REPO_ROOT")
                candidates = [Path(requested)] if requested else []
                candidates.extend([Path.cwd(), *Path.cwd().parents])
                for candidate in candidates:
                    manifest = candidate / "artifacts/canonical_validation_v1/report_manifest.json"
                    if manifest.is_file():
                        return candidate.resolve()
                raise RuntimeError("MDS650_REPO_ROOT_NOT_FOUND")

            REPO_ROOT = locate_repo()
            if str(REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(REPO_ROOT))
            SOURCE = REPO_ROOT / "artifacts/canonical_validation_v1"
            print(f"Repository root: {REPO_ROOT.name}")
            print(f"Evidence source: {SOURCE.relative_to(REPO_ROOT)}")
            """
        ),
        _code(
            """
            from scripts.build_canonical_defense_package import load_validated_contrasts

            REPORT_MANIFEST, REGISTERED_CONTRASTS = load_validated_contrasts(SOURCE)
            CONTRASTS_PAYLOAD = json.loads(
                (SOURCE / "contrasts.json").read_text(encoding="utf-8")
            )
            print("Source status:", REPORT_MANIFEST["status"])
            print("Registered rows:", len(REGISTERED_CONTRASTS))
            print(
                "Unpaired rows:",
                CONTRASTS_PAYLOAD["contrast_integrity"]["unpaired_rows"],
            )
            """
        ),
        _code(
            """
            frozen_contract = {
                "target": "RV30",
                "origin_definition": "fully observed close at t plus the next 30 one-minute closes",
                "prices_per_target": 31,
                "log_returns_per_target": 30,
                "information_sets": ["B0v2", "B1v2a", "B2v2"],
                "B1v2a": "ATM implied volatility as ordinary option state",
                "B2v2": "nine target-blind trade-activity features",
                "uw_created_at": (
                    "operational_availability_proxy with a 60-second conservative cutoff"
                ),
                "feature_construction_used_target": False,
            }
            print(json.dumps(frozen_contract, indent=2))
            """
        ),
        _code(
            """
            import csv

            registered_csv = (
                REPO_ROOT
                / "reports/canonical_validation_v1/tables/canonical_registered_contrasts.csv"
            )
            with registered_csv.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            print("Columns:", list(rows[0]))
            for row in rows:
                print(row)
            """
        ),
        _code(
            """
            manifest_path = SOURCE / "report_manifest.json"
            phase6_summary = SOURCE / "phase6/summary.json"
            independent_summary = SOURCE / "independent_replication/summary.json"
            for path in (manifest_path, phase6_summary, independent_summary):
                print(path.relative_to(REPO_ROOT), "exists=", path.is_file())

            print("Outcome assets: AAPL, AMZN, META, MSFT, NVDA, TSLA")
            print("Acquired controls: SPY, QQQ")
            print(
                "Causal audits: phase6/causal_audit.parquet and "
                "independent_replication/causal_audit.parquet"
            )
            """
        ),
        _code(
            """
            run_state = {
                "provider_calls": "DISABLED",
                "secret_values": "NOT_LOADED",
                "new_data_acquisition": "NOT_PERFORMED",
                "model_execution": "NOT_PERFORMED_BY_NOTEBOOK",
                "evidence_validation": "PASS_CANONICAL_REPORT",
                "claim_rule": "preserve positive, negative and null signs",
            }
            print(json.dumps(run_state, indent=2))
            """
        ),
        _markdown(
            """
            ## Lectura final

            El paquete conserva todos los signos y separa evidencia histórica
            de replicación independiente. La conclusión canónica registrada es
            `MODEL_FAMILY_DEPENDENT`: el resultado de Gamma no autoriza afirmar
            un edge universal cuando la familia LightGBM no reproduce la misma
            dirección.

            Los informes completos, las figuras y sus hashes están en
            `reports/canonical_validation_v1/`.
            """
        ),
    ]
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def write_notebook(output: Path) -> dict[str, Any]:
    """Write the deterministic notebook and return its metadata.

    Parameters
    ----------
    output:
        Destination notebook path.

    Returns
    -------
    dict[str, Any]
        Path and byte count of the generated document.
    """

    payload = json.dumps(build_notebook(), ensure_ascii=False, indent=1) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload, encoding="utf-8", newline="\n")
    return {"path": output.as_posix(), "bytes": output.stat().st_size}


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the canonical RV30 defense notebook."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("notebooks/MDS650_Canonical_RV30_Defense.ipynb"),
    )
    args = parser.parse_args(argv)
    print(json.dumps(write_notebook(args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
