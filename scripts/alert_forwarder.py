"""Off-machine alert forwarder for the three unattended campaigns.

Watches the Phase 8, UW-latency and Phase 9 alert files and pushes any NEW
lines to an ntfy.sh topic, so the owner is notified away from the machine.
The topic name is a locally stored random secret (never committed); subscribe
at https://ntfy.sh/<topic> or in the ntfy mobile app. State (per-file offsets)
is kept beside the logs so each alert is forwarded exactly once. Runs every
30 minutes via the MDS650_AlertForwarder scheduled task.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import secrets
from pathlib import Path

import httpx

DATA_ROOT = Path(os.environ.get("MDS650_EXTERNAL_ROOT", "D:/MDS650"))
LOGS = DATA_ROOT / "logs"
TOPIC_FILE = LOGS / "ntfy_topic.txt"
STATE_FILE = LOGS / "alert_forwarder_state.json"
ALERT_FILES = {
    "phase8": LOGS / "PHASE8_ALERT.txt",
    "uw_latency": LOGS / "UW_LATENCY_ALERT.txt",
    "phase9": LOGS / "PHASE9_ALERT.txt",
}


def _topic() -> str:
    LOGS.mkdir(parents=True, exist_ok=True)
    if TOPIC_FILE.exists():
        return TOPIC_FILE.read_text(encoding="utf-8").strip()
    topic = f"mds650-{secrets.token_hex(8)}"
    TOPIC_FILE.write_text(topic + "\n", encoding="utf-8")
    return topic


def main() -> None:
    topic = _topic()
    state: dict[str, int] = (
        json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    )
    forwarded = 0
    with httpx.Client(timeout=30) as client:
        for name, path in ALERT_FILES.items():
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            offset = int(state.get(name, 0))
            if len(content) <= offset:
                state[name] = min(offset, len(content))
                continue
            new_lines = [line for line in content[offset:].splitlines() if line.strip()]
            for line in new_lines[-10:]:  # cap a burst; the file keeps the full record
                try:
                    client.post(
                        f"https://ntfy.sh/{topic}",
                        content=line.encode("utf-8"),
                        headers={
                            "Title": f"MDS650 {name} alert",
                            "Priority": "high",
                            "Tags": "rotating_light",
                        },
                    )
                    forwarded += 1
                except httpx.HTTPError:
                    break  # keep offset unadvanced for this file; retry next cycle
            else:
                state[name] = len(content)
                continue
            break
    STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    stamp = dt.datetime.now(dt.UTC).isoformat()
    print(f"[alert-forwarder] {stamp} forwarded={forwarded} topic={topic}")


if __name__ == "__main__":
    main()
