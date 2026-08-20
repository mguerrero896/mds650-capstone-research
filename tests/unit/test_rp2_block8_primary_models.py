"""The three primary families must be fitted by the run, not merely named in a module.

A frozen contract that lives only in a constant is a comment. The producer has to refuse a
run that would report a ladder missing one of the families the contract decides on, and the
artifact has to say which families those were, so a reader is not left inferring it from the
list of everything that happened to be fitted.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from mds650.rp2.ladder import PRIMARY_MODELS

REPO = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_the_producer_refuses_a_ladder_without_every_primary_family() -> None:
    block8 = _load("rp2_block8_ladder")
    with pytest.raises(ValueError, match="RP2_BLOCK8_PRIMARY_MODEL_MISSING:lightgbm_qlike"):
        block8.assert_primary_models(("gamma_glm", "ridge_log", "lightgbm"))
    block8.assert_primary_models(PRIMARY_MODELS)
    block8.assert_primary_models((*PRIMARY_MODELS, "spline_additive"))


def test_the_artifact_declares_the_primary_families() -> None:
    """A robustness family and a decision family must be distinguishable in the record."""

    block8 = _load("rp2_block8_ladder")
    source = (REPO / "scripts" / "rp2_block8_ladder.py").read_text(encoding="utf-8")
    assert '"primary_models"' in source
    assert block8.PRIMARY_MODELS == PRIMARY_MODELS
