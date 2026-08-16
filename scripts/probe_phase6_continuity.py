"""Reuse hashed Phase 5 evidence and probe only missing Phase 6 metadata."""

from __future__ import annotations

import asyncio
import importlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from mds650.phase5_storage import GIB, Phase5StorageConfig, sha256_file
from mds650.phase6 import (
    MARKET_CONTROLS,
    OUTCOME_ASSETS,
    continuity_verdict,
    phase6_sessions,
    phase6_storage_preflight,
)
from mds650.study_design import canonical_sha256

v5: Any = importlib.import_module("probe_daily_common_history_v5")

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts" / "api_audit" / "common_history_continuity_v5.json"
SOURCE_EXPECTED_SHA256 = (
    "ddf1d5314b40ecff8d7ec58f415d2a0b44ca9b2016ec53612d522552165460d4"
)
OUT = ROOT / "artifacts" / "phase6" / "continuity_probe.json"
STORAGE_OUT = ROOT / "artifacts" / "phase6" / "storage_preflight.json"
CHECKPOINT = ROOT / "artifacts" / "phase6" / ".continuity_probe.checkpoint.json"
DATA_ROOT = Path("D:/MDS650")
ASSETS = (*OUTCOME_ASSETS, *MARKET_CONTROLS)
PROJECTED_RESIDENT_GIB = 252 + 37
PROJECTED_PEAK_GIB = 376  # ceil((252 GiB raw + 37 GiB Parquet) * 1.30)


def _phase6_dates() -> tuple[date, ...]:
    """Return the frozen Phase 6 dates as date objects."""
    return tuple(date.fromisoformat(row["session_date"]) for row in phase6_sessions())


def _load_source() -> dict[str, Any]:
    """Load the immutable v5 audit only when its handoff hash matches."""
    if sha256_file(SOURCE) != SOURCE_EXPECTED_SHA256:
        raise RuntimeError("SOURCE_CONTINUITY_HASH_MISMATCH")
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("SOURCE_CONTINUITY_SCHEMA_MISMATCH")
    if payload.get("schema_version") != "common-history-continuity-v5":
        raise RuntimeError("SOURCE_CONTINUITY_SCHEMA_MISMATCH")
    return payload


def _load_checkpoint() -> dict[str, dict[str, Any]]:
    """Load the Phase 6-only resumable checkpoint."""
    if not CHECKPOINT.exists():
        return {"fmp": {}, "massive": {}, "uw": {}}
    payload = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("PHASE6_CONTINUITY_CHECKPOINT_INVALID")
    return {
        name: dict(payload.get(name, {}))
        for name in ("fmp", "massive", "uw")
    }


def _save_checkpoint(state: dict[str, dict[str, Any]]) -> None:
    """Persist sanitized metadata atomically."""
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    temporary = CHECKPOINT.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    temporary.replace(CHECKPOINT)


def _source_rows(payload: dict[str, Any], expected: set[str]) -> dict[str, dict[str, Any]]:
    """Index only allow-listed records from the hashed source artifact."""
    rows = payload.get("records")
    if not isinstance(rows, list):
        raise RuntimeError("SOURCE_CONTINUITY_RECORDS_INVALID")
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("date") not in expected:
            continue
        key = v5._key(str(row.get("asset")), date.fromisoformat(str(row["date"])))
        if key in indexed:
            raise RuntimeError("SOURCE_CONTINUITY_DUPLICATE")
        indexed[key] = dict(row)
    return indexed


def _merge_record(
    asset: str,
    day: date,
    source: dict[str, Any] | None,
    state: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Merge reused and newly probed metadata into one stable asset-day row."""
    day_text = day.isoformat()
    key = v5._key(asset, day)
    record = dict(source or {"asset": asset, "date": day_text})
    fmp = state["fmp"].get(key)
    massive = state["massive"].get(key)
    uw = state["uw"].get(day_text)
    if fmp:
        record.update(
            {
                "fmp_session_pass": fmp["exact_session_pass"],
                "fmp_rows_exact_session": fmp["rows_exact_session"],
                "fmp_expected_rows": fmp["expected_xnys_session"]["expected_count"],
                "fmp_returned_dates": fmp["returned_dates"],
                "fmp_provider_over_return": fmp["provider_over_return"],
                "fmp_spot_at_midday": fmp["spot_at_midday"],
                "fmp_missing_expected_labels": fmp["missing_expected_labels"],
                "fmp_first_raw_timestamp": fmp["first_raw_timestamp"],
                "fmp_last_raw_timestamp": fmp["last_raw_timestamp"],
            }
        )
    if uw:
        record.update(
            {
                "uw_file_metadata_pass": uw["file_metadata_pass"],
                "uw_http_status": uw["http_status"],
                "uw_bytes_total": uw["bytes_total"],
                "uw_pit_claim": False,
            }
        )
    if massive:
        record.update(
            {
                "massive_contract": massive["contract"],
                "massive_contract_pass": massive["contract"] is not None,
                "massive_quote_pass": massive["quote_valid_before_origin"],
                "massive_reference_http_status": massive["reference_http_status"],
                "massive_quote_http_status": massive["quote_http_status"],
                "massive_selected_sip_timestamp": massive["selected_sip_timestamp"],
                "massive_timestamp_lte_ns": massive["timestamp_lte_ns"],
                "massive_sip_le_origin": massive["sip_timestamp_le_origin"],
                "massive_blocker": massive["blocker"],
            }
        )
    record["fmp_provider_available"] = bool(
        record.get("fmp_rows_exact_session", 0)
        and record.get("fmp_returned_dates") == [day_text]
        and isinstance(record.get("fmp_spot_at_midday"), (int, float))
    )
    required = (
        record.get("fmp_provider_available"),
        record.get("uw_file_metadata_pass"),
        record.get("massive_quote_pass"),
    )
    record["common_component_pass"] = all(value is True for value in required)
    record["evidence_source"] = (
        "LIVE_PHASE6_METADATA_PROBE"
        if fmp or uw or massive
        else "REUSED_HASHED_COMMON_HISTORY_V5"
    )
    return record


async def probe_asset_day(day: date, asset: str) -> dict[str, Any]:
    """Run one sanitized live asset-day probe for the bounded live test."""
    fmp_key = v5._secret("FMP_API_KEY")
    uw_key = v5._secret("UNUSUALWHALES_API_KEY")
    massive_key = v5._secret("MASSIVE_API_KEY")
    async with httpx.AsyncClient(timeout=httpx.Timeout(45), follow_redirects=True) as client:
        fmp = await v5._fmp_day(client, fmp_key, asset, day)
        uw = await v5._uw_day(client, uw_key, day)
        massive = await v5._massive_day(
            client, massive_key, asset, day, fmp.get("spot_at_midday"), 3
        )
    state = {
        "fmp": {v5._key(asset, day): fmp},
        "massive": {v5._key(asset, day): massive},
        "uw": {day.isoformat(): uw},
    }
    return _merge_record(asset, day, None, state)


async def _probe_required(
    source_rows: dict[str, dict[str, Any]], dates: tuple[date, ...]
) -> dict[str, dict[str, Any]]:
    """Probe missing dates and recheck prior failed provider components."""
    state = _load_checkpoint()
    fmp_key = v5._secret("FMP_API_KEY")
    uw_key = v5._secret("UNUSUALWHALES_API_KEY")
    massive_key = v5._secret("MASSIVE_API_KEY")
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=8)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(45), follow_redirects=True, limits=limits
    ) as client:
        for index, day in enumerate(dates, start=1):
            day_text = day.isoformat()
            missing_date = not any(
                v5._key(asset, day) in source_rows for asset in ASSETS
            )
            if missing_date and day_text not in state["uw"]:
                state["uw"][day_text] = await v5._uw_day(client, uw_key, day)

            fmp_assets = [
                asset
                for asset in ASSETS
                if v5._key(asset, day) not in state["fmp"]
                and (
                    missing_date
                    or source_rows.get(v5._key(asset, day), {}).get(
                        "fmp_session_pass"
                    )
                    is not True
                )
            ]
            if fmp_assets:
                results = await asyncio.gather(
                    *(v5._fmp_day(client, fmp_key, asset, day) for asset in fmp_assets)
                )
                state["fmp"].update(
                    {v5._key(str(row["asset"]), day): row for row in results}
                )

            massive_assets = [
                asset
                for asset in ASSETS
                if v5._key(asset, day) not in state["massive"]
                and (
                    missing_date
                    or source_rows.get(v5._key(asset, day), {}).get(
                        "massive_quote_pass"
                    )
                    is not True
                )
            ]
            if massive_assets:
                results = await asyncio.gather(
                    *(
                        v5._massive_day(
                            client,
                            massive_key,
                            asset,
                            day,
                            state["fmp"][v5._key(asset, day)].get(
                                "spot_at_midday"
                            ),
                            3,
                        )
                        for asset in massive_assets
                    )
                )
                state["massive"].update(
                    {v5._key(str(row["asset"]), day): row for row in results}
                )
            if fmp_assets or massive_assets or missing_date:
                _save_checkpoint(state)
                print(
                    json.dumps(
                        {
                            "status": "RUNNING_METADATA_ONLY",
                            "date": day_text,
                            "session": index,
                            "sessions_total": len(dates),
                            "secret_values_emitted": False,
                        }
                    ),
                    flush=True,
                )
    return state


def _write_storage_evidence(dates: tuple[date, ...]) -> dict[str, object]:
    """Run the inherited 80-GiB storage gate on the Samsung SSD."""
    config = Phase5StorageConfig(
        sessions=dates,
        excluded_dates=frozenset(),
        data_root=DATA_ROOT,
        minimum_free_bytes=80 * GIB,
        projected_peak_additional_bytes=PROJECTED_PEAK_GIB * GIB,
    )
    evidence = phase6_storage_preflight(config)
    evidence.update(
        {
            "schema_version": "phase6-storage-preflight-1.0",
            "projected_raw_gib": 252,
            "projected_parquet_gib": 37,
            "projected_resident_gib": PROJECTED_RESIDENT_GIB,
            "safety_margin_rate": 0.30,
            "projection_formula": "ceil((252 GiB raw + 37 GiB Parquet) * 1.30)",
            "volume_label_expected": "Samsung",
            "code_and_manifests_remain_in_repository": True,
            "personal_paths_emitted": False,
        }
    )
    evidence["manifest_sha256"] = canonical_sha256(evidence)
    STORAGE_OUT.parent.mkdir(parents=True, exist_ok=True)
    STORAGE_OUT.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return evidence


async def run() -> dict[str, object]:
    """Execute the resumable metadata-only continuity and storage gates."""
    dates = _phase6_dates()
    expected = {day.isoformat() for day in dates}
    source_payload = _load_source()
    source_rows = _source_rows(source_payload, expected)
    state = await _probe_required(source_rows, dates)
    records = [
        _merge_record(
            asset,
            day,
            source_rows.get(v5._key(asset, day)),
            state,
        )
        for day in dates
        for asset in ASSETS
    ]
    verdict = continuity_verdict(records, expected)
    failures = [
        {
            "asset": row["asset"],
            "date": row["date"],
            "fmp_provider_available": row.get("fmp_provider_available"),
            "fmp_session_pass": row.get("fmp_session_pass"),
            "fmp_missing_expected_labels": row.get("fmp_missing_expected_labels", []),
            "uw_file_metadata_pass": row.get("uw_file_metadata_pass"),
            "massive_quote_pass": row.get("massive_quote_pass"),
            "massive_blocker": row.get("massive_blocker"),
        }
        for row in records
        if row["common_component_pass"] is not True
    ]
    incomplete_fmp_asset_days = [
        {
            "asset": row["asset"],
            "date": row["date"],
            "rows_observed": row.get("fmp_rows_exact_session"),
            "rows_expected": row.get("fmp_expected_rows"),
            "missing_labels": row.get("fmp_missing_expected_labels", []),
            "treatment": "INVALIDATE_AFFECTED_ORIGINS_WITHOUT_INTERPOLATION",
        }
        for row in records
        if row.get("fmp_session_pass") is not True
    ]
    payload: dict[str, Any] = {
        "schema_version": "phase6-continuity-probe-1.0",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": verdict,
        "calendar": "XNYS",
        "sessions_expected": len(dates),
        "sessions_checked": len({str(row["date"]) for row in records}),
        "asset_date_records": len(records),
        "assets": list(ASSETS),
        "records": sorted(records, key=lambda row: (str(row["date"]), str(row["asset"]))),
        "failures": failures,
        "fmp_incomplete_asset_days": incomplete_fmp_asset_days,
        "fmp_incomplete_asset_day_count": len(incomplete_fmp_asset_days),
        "continuity_definition": (
            "PROVIDER_AND_EXACT_DATE_AVAILABLE; MINUTE_COMPLETENESS_IS_A_SEPARATE_"
            "FR085_ORIGIN_ELIGIBILITY_GATE"
        ),
        "missing_price_policy": "NO_INTERPOLATION_NO_PROXY_NO_SILENT_SUBSTITUTION",
        "source_evidence": {
            "artifact": "artifacts/api_audit/common_history_continuity_v5.json",
            "sha256": sha256_file(SOURCE),
            "trusted_handoff": "reports/CODEX_LAST_GOAL_HANDOFF.md",
            "reused_asset_date_records": sum(
                row["evidence_source"] == "REUSED_HASHED_COMMON_HISTORY_V5"
                for row in records
            ),
        },
        "live_metadata_asset_date_records": sum(
            row["evidence_source"] == "LIVE_PHASE6_METADATA_PROBE"
            for row in records
        ),
        "checkpoint_sha256": sha256_file(CHECKPOINT) if CHECKPOINT.exists() else None,
        "full_tape_downloaded": False,
        "uw_file_existence_is_not_pit_proof": True,
        "secret_values_emitted": False,
        "personal_paths_emitted": False,
    }
    payload["manifest_sha256"] = canonical_sha256(payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    storage = _write_storage_evidence(dates)
    return {
        "continuity_status": verdict,
        "continuity_failures": len(failures),
        "storage_status": storage["status"],
        "full_tape_downloaded": False,
        "secret_values_emitted": False,
    }


def main() -> int:
    """Run both gates and exit nonzero on any fail-closed decision."""
    result = asyncio.run(run())
    print(json.dumps(result, sort_keys=True))
    return int(
        result["continuity_status"] != "PASS_PHASE6_CONTINUITY"
        or result["storage_status"] != "PASS_PHASE6_STORAGE"
    )


if __name__ == "__main__":
    raise SystemExit(main())
