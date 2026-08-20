"""Every producer that reports a delta must fit the families the contract decides on.

The contract froze `gamma_glm`, `ridge_log` and `lightgbm_qlike`. A producer whose default
model list is something else still writes a complete-looking artifact, and the verdict is
then read off families the contract never named. This is the same failure as a constant
with no caller, one level up: a contract with no producer.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from mds650.rp2.ladder import PRIMARY_MODELS, assert_primary_models

REPO = Path(__file__).resolve().parents[2]

PRODUCERS = (
    "rp2_block8_ladder",
    "rp2_block9_generalization",
    "rp2_block10_inference",
    "rp2_block11_economics",
    "rp2_block11b_forward_economics",
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("producer", PRODUCERS)
def test_every_producer_fits_every_primary_family_by_default(producer: str) -> None:
    module = _load(producer)
    default = getattr(module, "DEFAULT_MODELS", None) or tuple(module.LADDER)
    missing = [name for name in PRIMARY_MODELS if name not in default]
    assert not missing, f"{producer} does not fit {missing} by default"


def test_the_guard_names_the_family_that_is_missing() -> None:
    with pytest.raises(ValueError, match="RP2_PRIMARY_MODEL_MISSING:ridge_log"):
        assert_primary_models(("gamma_glm", "lightgbm_qlike"))
    assert_primary_models(PRIMARY_MODELS)
