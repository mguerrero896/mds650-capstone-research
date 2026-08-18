"""Block 2 - derive the per-session PIT admissibility list from the measured ledger.

Reads the already-computed per-session latency statistics and classifies each session
against the empirical B2 cutoff.  Kept separate from the measurement pass so the
1.46-billion-row scan is not repeated when only the rule changes.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from mds650.b1v3_confirmation import canonical_sha256
from mds650.rp2.pit_ledger import session_admissibility

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "artifacts" / "rp2_block2_pit"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--max-backfill-share", type=float, default=0.01)
    args = parser.parse_args(argv)

    ledger = json.loads((args.ledger_dir / "ledger.json").read_text(encoding="utf-8"))
    sessions = json.loads((args.ledger_dir / "per_session.json").read_text(encoding="utf-8"))
    cutoff = float(ledger["recommended_b2_cutoff_seconds"])

    verdicts = session_admissibility(
        sessions, cutoff_seconds=cutoff, max_backfill_share=args.max_backfill_share
    )
    inadmissible = [asdict(item) for item in verdicts if not item.admissible]
    document: dict[str, object] = {
        "block": 2,
        "cutoff_seconds": cutoff,
        "max_backfill_share": args.max_backfill_share,
        "sessions_evaluated": len(verdicts),
        "sessions_admissible": len(verdicts) - len(inadmissible),
        "sessions_inadmissible": len(inadmissible),
        "inadmissible_share": len(inadmissible) / len(verdicts) if verdicts else float("nan"),
        "inadmissible_sessions": inadmissible,
    }
    document["admissibility_sha256"] = canonical_sha256(document)
    document["generated_at_utc"] = datetime.now(UTC).isoformat()
    (args.ledger_dir / "admissibility.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
