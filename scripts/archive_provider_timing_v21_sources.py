"""Archive hash-addressed metadata for four official PIT v2.1 source pages.

This script never contacts a provider-data endpoint and never uses credentials.
Only documentation URLs hard-coded in ``provider_timing_v21`` are requested.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import httpx

from mds650.provider_timing_v21 import (
    OfficialSourceResponse,
    archive_official_source_records,
)

ROOT = Path(__file__).resolve().parents[1]


def _fetch_official_document(url: str, headers: dict[str, str]) -> OfficialSourceResponse:
    """Fetch one credential-free, allow-listed official document.

    Parameters
    ----------
    url:
        Official documentation URL supplied only by the fixed v2.1 source list.
    headers:
        Credential-free HTTP headers used consistently for documentation retrieval.

    Returns
    -------
    OfficialSourceResponse
        HTTP status, media type, and in-memory body. The caller records only the
        body hash and never persists the body.

    Raises
    ------
    httpx.HTTPError
        If the documentation server cannot be reached.
    """
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
    return OfficialSourceResponse(
        status_code=response.status_code,
        content_type=response.headers.get("content-type", ""),
        body=response.content,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Archive official source records without retaining raw documentation bodies.

    Parameters
    ----------
    argv:
        Optional command-line arguments for tests or programmatic invocation.

    Returns
    -------
    int
        Zero after writing deterministic source-record JSON files.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "artifacts" / "provider_timing_v21" / "official_sources",
    )
    args = parser.parse_args(argv)
    records = archive_official_source_records(
        output_dir=args.output_dir,
        fetch=_fetch_official_document,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "source_record_count": len(records),
                "raw_document_bodies_persisted": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
