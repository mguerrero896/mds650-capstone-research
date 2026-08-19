"""Block 1 — Gate 0: the frozen discovery / validation / confirmation partition.

The program requires three *temporally* separated universes, ``D < V < C``.  This
module enumerates the locally available point-in-time option-trade tape, assigns
every session to exactly one role, and produces a deterministic manifest digest so
that the partition can be hash-frozen.

The confirmation universe is **declared, never enumerated**: its evidence is sealed
and must not be touched.  It is represented by :data:`SEALED_CONFIRMATION`, whose
fields come from the frozen protocol document, not from the filesystem.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Literal

Role = Literal["D", "V", "BURNED"]

_DATE_DIR = re.compile(r"^date=(\d{4})-(\d{2})-(\d{2})$")
_ASSET_DIR = re.compile(r"^asset=([A-Z.]+)$")


#: Store root holding every per-campaign tape directory.  ``MDS650_DATA_ROOT`` points at
#: ``<root>/data`` by repo convention, so the store root is its parent when set.
def _default_data_root() -> Path:
    configured = os.environ.get("MDS650_RP2_STORE_ROOT")
    if configured:
        return Path(configured)
    legacy = os.environ.get("MDS650_DATA_ROOT")
    if legacy:
        path = Path(legacy)
        return path.parent if path.name == "data" else path
    return Path("D:/MDS650")


DEFAULT_DATA_ROOT: Final = _default_data_root()

#: Asset label for a session stored as one un-partitioned multi-asset file.
MULTI_ASSET: Final = "__ALL__"


@dataclass(frozen=True, slots=True)
class TapeSource:
    """One on-disk ``option_events`` hive store contributing sessions."""

    name: str
    relative_root: str

    def root(self, data_root: Path) -> Path:
        return data_root / self.relative_root


@dataclass(frozen=True, slots=True)
class SealedCohort:
    """A sealed, unread confirmation cohort, described only from its protocol."""

    name: str
    first_session: date
    last_session: date
    sessions: int
    protocol_document: str
    reads_permitted: int
    note: str


#: Every local per-trade tape store, oldest first.
TAPE_SOURCES: Final[tuple[TapeSource, ...]] = (
    TapeSource("b1v3_confirmation", "b1v3_confirmation/data/option_events"),
    TapeSource("b1_diagnostic_replication", "b1_diagnostic_replication/data/option_events"),
    TapeSource("independent_replication_30", "independent_replication_30/data/option_events"),
    TapeSource("phase6", "phase6/data/option_events"),
    TapeSource("development_2026", "data/option_events"),
)

#: Sessions strictly before this date are Discovery.
VALIDATION_FIRST_SESSION: Final = date(2026, 3, 24)
#: Sessions on/after this date belong to the sealed confirmation window.
CONFIRMATION_FIRST_SESSION: Final = date(2026, 7, 20)

SEALED_CONFIRMATION: Final = SealedCohort(
    name="phase8_one_shot",
    first_session=date(2026, 7, 20),
    last_session=date(2026, 8, 28),
    sessions=30,
    protocol_document="docs/phase8_one_shot_protocol_v1.md",
    reads_permitted=1,
    note=(
        "Sealed at capture time; its first ten sessions (2026-07-20..07-31) coincide with "
        "the already-read Phase 5 prospective holdout C2, so only 2026-08-03..08-28 is "
        "genuinely unobserved. Recorded here, never read."
    ),
)


@dataclass(frozen=True, slots=True)
class SessionFile:
    """One ``(session, asset)`` tape partition on disk."""

    session_date: date
    asset: str
    role: Role
    source: str
    path: str
    size_bytes: int

    def as_row(self) -> dict[str, str | int]:
        return {
            "session_date": self.session_date.isoformat(),
            "asset": self.asset,
            "role": self.role,
            "source": self.source,
            "path": self.path,
            "size_bytes": self.size_bytes,
        }


def assign_role(session_date: date) -> Role:
    """Map a session date to its frozen partition role."""

    if session_date >= CONFIRMATION_FIRST_SESSION:
        return "BURNED"
    if session_date >= VALIDATION_FIRST_SESSION:
        return "V"
    return "D"


def _parse_date_dir(name: str) -> date | None:
    match = _DATE_DIR.match(name)
    if match is None:
        return None
    year, month, day = (int(part) for part in match.groups())
    return date(year, month, day)


def discover_sessions(
    sources: Iterable[TapeSource] = TAPE_SOURCES,
    data_root: Path = DEFAULT_DATA_ROOT,
) -> list[SessionFile]:
    """Enumerate every available ``(session, asset)`` tape partition.

    Sessions on or after :data:`CONFIRMATION_FIRST_SESSION` are labelled ``BURNED``
    and are never used for anything; the sealed cohort itself is not enumerated.
    """

    found: list[SessionFile] = []
    for source in sources:
        root = source.root(data_root)
        if not root.is_dir():
            continue
        for date_dir in sorted(root.iterdir()):
            session_date = _parse_date_dir(date_dir.name)
            if session_date is None or not date_dir.is_dir():
                continue
            role = assign_role(session_date)
            flat = date_dir / "events.parquet"
            if flat.is_file():
                # Late 2026 sessions were written un-partitioned: one file, every asset.
                found.append(
                    SessionFile(
                        session_date=session_date,
                        asset=MULTI_ASSET,
                        role=role,
                        source=source.name,
                        path=flat.as_posix(),
                        size_bytes=flat.stat().st_size,
                    )
                )
            for asset_dir in sorted(date_dir.iterdir()):
                asset_match = _ASSET_DIR.match(asset_dir.name)
                if asset_match is None or not asset_dir.is_dir():
                    continue
                for parquet in sorted(asset_dir.glob("*.parquet")):
                    found.append(
                        SessionFile(
                            session_date=session_date,
                            asset=asset_match.group(1),
                            role=role,
                            source=source.name,
                            path=parquet.as_posix(),
                            size_bytes=parquet.stat().st_size,
                        )
                    )
    found.sort(key=lambda item: (item.session_date, item.asset, item.source, item.path))
    return found


def temporal_ordering_holds(files: Sequence[SessionFile]) -> bool:
    """True when ``max(D) < min(V) < min(confirmation)`` — the ``D < V < C`` rule."""

    discovery = [item.session_date for item in files if item.role == "D"]
    validation = [item.session_date for item in files if item.role == "V"]
    if not discovery or not validation:
        return False
    return max(discovery) < min(validation) < SEALED_CONFIRMATION.first_session


def inventory_digest(files: Sequence[SessionFile]) -> str:
    """Deterministic SHA-256 over the ordered inventory rows."""

    digest = hashlib.sha256()
    for item in files:
        payload = json.dumps(item.as_row(), sort_keys=True, separators=(",", ":"))
        digest.update(payload.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def role_summary(files: Sequence[SessionFile]) -> dict[str, dict[str, object]]:
    """Per-role session/asset/byte counts, used as the frozen partition record."""

    summary: dict[str, dict[str, object]] = {}
    for role in ("D", "V", "BURNED"):
        subset = [item for item in files if item.role == role]
        sessions = sorted({item.session_date for item in subset})
        summary[role] = {
            "sessions": len(sessions),
            "first_session": sessions[0].isoformat() if sessions else None,
            "last_session": sessions[-1].isoformat() if sessions else None,
            "assets": sorted({item.asset for item in subset}),
            "files": len(subset),
            "bytes": sum(item.size_bytes for item in subset),
        }
    return summary
