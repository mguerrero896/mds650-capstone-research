"""The frozen RP2-v3 feature sets, and the one place that decides what is in them.

A hundred-plus dimensions against a few dozen independent sessions is estimation variance,
not information. The programme therefore separates a **core** set — chosen for economic
mechanism, coverage, stability and point-in-time availability — from a **rich** set that is
emitted, reported and hashed but never fitted in a primary contrast.

Nothing here is chosen by an individual feature's historical p-value. Selecting features on
the sample they will be tested on is how a null becomes a finding.

The sets live in ``configs/rp2_v3_feature_sets.json`` and are loaded, not restated: a second
copy of a list is a list that drifts. ``src/mds650/rp2/panel.py`` builds its information
sets from here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Final

import polars as pl

#: The frozen sets live in the repository's `configs/` directory and are force-included in
#: the wheel beside this module, because importing the panel resolves them eagerly and an
#: installed package cannot reach back into a source tree.
_PACKAGED: Final = Path(__file__).resolve().parent / "configs" / "rp2_v3_feature_sets.json"
_IN_TREE: Final = (
    Path(__file__).resolve().parents[3] / "configs" / "rp2_v3_feature_sets.json"
)
CONFIG: Final = _IN_TREE if _IN_TREE.is_file() else _PACKAGED
SCHEMA_VERSION: Final = "rp2-v3-feature-sets-v1.0"
#: Transform kinds a feature may declare; `panel.transform_column` implements them.
TRANSFORM_KINDS: Final = frozenset({"log", "signed", "raw"})


@dataclass(frozen=True, slots=True)
class FeatureSet:
    """One frozen set: what is in it, how complete it must be, and why it exists."""

    name: str
    version: str
    features: tuple[str, ...]
    minimum_coverage: float

    def __post_init__(self) -> None:
        if not self.features:
            raise ValueError(f"RP2_FEATURE_SET_EMPTY:{self.name}")
        if len(set(self.features)) != len(self.features):
            raise ValueError(f"RP2_FEATURE_SET_DUPLICATED:{self.name}")
        if not 0.0 <= self.minimum_coverage <= 1.0:
            raise ValueError(f"RP2_FEATURE_SET_COVERAGE_INVALID:{self.name}")


@cache
def _document() -> dict[str, object]:
    document: dict[str, object] = json.loads(CONFIG.read_text(encoding="utf-8"))
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"RP2_FEATURE_SETS_SCHEMA:{document.get('schema_version')}")
    return document


@cache
def registry() -> Mapping[str, FeatureSet]:
    """Every frozen set, keyed by name."""

    sets: dict[str, FeatureSet] = {}
    for name, entry in dict(_document()["sets"]).items():  # type: ignore[call-overload]
        features = dict(entry["features"])
        unknown = sorted(k for k in features.values() if k not in TRANSFORM_KINDS)
        if unknown:
            raise ValueError(f"RP2_FEATURE_SET_TRANSFORM:{name}:{','.join(unknown)}")
        sets[name] = FeatureSet(
            name=name,
            version=str(entry["version"]),
            features=tuple(features),
            minimum_coverage=float(entry["minimum_coverage"]),
        )
    return sets


@cache
def transforms() -> Mapping[str, str]:
    """Feature name to transform kind, across every set.

    A feature that appears in two sets must declare the same transform in both: the same
    column cannot be a log in one design and a level in another.
    """

    out: dict[str, str] = {}
    for entry in dict(_document()["sets"]).values():  # type: ignore[call-overload]
        for name, kind in dict(entry["features"]).items():
            if out.setdefault(name, kind) != kind:
                raise ValueError(f"RP2_FEATURE_TRANSFORM_CONFLICT:{name}")
    return out


def feature_map(*names: str) -> dict[str, str]:
    """The column-to-transform map for one or more sets, in declaration order."""

    known = registry()
    kinds = transforms()
    out: dict[str, str] = {}
    for name in names:
        if name not in known:
            raise ValueError(f"RP2_FEATURE_SET_UNKNOWN:{name}")
        for feature in known[name].features:
            out[feature] = kinds[feature]
    return out


@cache
def registry_sha256() -> str:
    """Content hash of the frozen sets.

    Over the sets alone, canonically serialised: prose in the configuration may be edited
    without invalidating a run, and a feature may not.
    """

    payload = {
        name: {
            "version": entry.version,
            "features": list(entry.features),
            "minimum_coverage": entry.minimum_coverage,
        }
        for name, entry in sorted(registry().items())
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def coverage_by_feature(panel: pl.DataFrame, features: Sequence[str]) -> dict[str, float]:
    """Share of rows where each feature is present and finite."""

    height = max(panel.height, 1)
    out: dict[str, float] = {}
    for name in features:
        if name not in panel.columns:
            out[name] = 0.0
            continue
        values = panel[name].cast(pl.Float64)
        out[name] = float((values.is_finite() & values.is_not_null()).sum()) / height
    return out


def describe_coverage(panel: pl.DataFrame, *names: str) -> dict[str, object]:
    """The provenance a run must record about the sets it fitted."""

    covered = coverage_by_feature(panel, list(feature_map(*names)))
    return {
        "feature_registry_sha256": registry_sha256(),
        "feature_sets": list(names),
        "feature_names": sorted(covered),
        "feature_count": len(covered),
        "coverage_by_feature": covered,
        "missingness_by_feature": {name: 1.0 - share for name, share in covered.items()},
    }


def assert_minimum_coverage(panel: pl.DataFrame, *names: str) -> None:
    """Fail closed when a set does not meet the coverage it declares.

    A floor that is written down and never checked is a floor that is not there. This runs
    once per rebuild, against the panel the run will actually fit.
    """

    known = registry()
    breaches: list[str] = []
    for name in names:
        entry = known[name]
        covered = coverage_by_feature(panel, entry.features)
        breaches.extend(
            f"{name}:{feature}={share:.4f}<{entry.minimum_coverage:.2f}"
            for feature, share in sorted(covered.items())
            if share < entry.minimum_coverage
        )
    if breaches:
        raise ValueError(f"RP2_FEATURE_SET_COVERAGE_BREACH:{','.join(breaches)}")
