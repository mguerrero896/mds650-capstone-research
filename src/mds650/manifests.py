"""Sanitized provider-audit manifest validation and fail-closed gates."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mds650.errors import QualityGateError

_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "password",
}
_CREDENTIAL_URL = re.compile(r"(?i)[?&](?:api[_-]?key|token|authorization)=")
_PERSONAL_PATH = re.compile(
    r"(?i)(?:^[a-z]:[\\/](?:users|documents and settings)[\\/]|^/(?:users|home)/|"
    r"[\\/]appdata[\\/]local[\\/]temp[\\/]|[\\/]onedrive[\\/])"
)
_REQUIRED_FIELDS = {
    "schema_version",
    "run_id",
    "generated_at_utc",
    "research_feature",
    "research_only",
    "secrets_present",
    "secret_values_emitted",
    "provider_results",
    "cross_provider_summary",
    "acceptance",
}


@dataclass(frozen=True, slots=True)
class AuditValidation:
    """Machine-readable result of validating a sanitized audit manifest."""

    run_id: str
    sanitized: bool
    authorized_for_backfill: bool
    blockers: tuple[str, ...]


def load_and_validate_audit_manifest(path: Path) -> AuditValidation:
    """Load a manifest and classify provider gates without enabling backfill.

    Parameters
    ----------
    path:
        JSON manifest produced by a bounded provider audit.

    Returns
    -------
    AuditValidation
        Sanitization result, exact blockers, and conservative authorization flag.

    Raises
    ------
    QualityGateError
        If JSON is invalid, required fields are missing, the run is not research
        only, or secret-like content is present.
    OSError
        If the manifest cannot be read.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
        document = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        raise QualityGateError("AUDIT_MANIFEST_INVALID_JSON") from exc
    if not isinstance(document, dict) or not _REQUIRED_FIELDS.issubset(document):
        raise QualityGateError("AUDIT_MANIFEST_REQUIRED_FIELDS_MISSING")
    if document["research_only"] is not True:
        raise QualityGateError("RESEARCH_ONLY_REQUIRED")
    if document["secret_values_emitted"] is not False:
        raise QualityGateError("AUDIT_MANIFEST_SECRET_VALUES_EMITTED")
    _reject_secret_content(document)
    if document.get("schema_version") == "1.1":
        _validate_v11_integrity(document)
    summary = document["cross_provider_summary"]
    if not isinstance(summary, Mapping):
        raise QualityGateError("AUDIT_MANIFEST_SUMMARY_INVALID")
    blockers: list[str] = []
    if summary.get("b1_point_in_time_status") != "PASS":
        blockers.append("B1_NOT_AUTHORIZED")
    if not _massive_directed_probe_passed(summary):
        blockers.append("MASSIVE_NOT_AUTHORIZED")
    if summary.get("common_history_status") != "PASS":
        blockers.append("COMMON_HISTORY_NOT_ESTABLISHED")
    if any(
        isinstance(result, Mapping) and result.get("failure_code")
        for result in document["provider_results"]
        if isinstance(document["provider_results"], list)
    ):
        blockers.append("PROVIDER_FAILURES_PRESENT")
    return AuditValidation(
        run_id=str(document["run_id"]),
        sanitized=True,
        authorized_for_backfill=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _massive_directed_probe_passed(summary: Mapping[str, Any]) -> bool:
    trades = summary.get("massive_directed_trade_statuses")
    quotes = summary.get("massive_directed_quote_statuses")
    def successful_directed_probe(statuses: Any) -> bool:
        if not isinstance(statuses, list) or not statuses:
            return False
        for status in statuses:
            if not isinstance(status, str) or not status.startswith("200:"):
                return False
            try:
                if int(status.split(":", maxsplit=1)[1]) < 1:
                    return False
            except ValueError:
                return False
        return True

    return successful_directed_probe(trades) and successful_directed_probe(quotes)


def _reject_secret_content(document: Mapping[str, Any]) -> None:
    def walk(value: Any, key: str = "") -> None:
        if key.lower() in _SECRET_KEYS and value not in (None, "", "[REDACTED]"):
            raise QualityGateError("AUDIT_MANIFEST_SECRET_CONTENT")
        if isinstance(value, Mapping):
            for child_key, child_value in value.items():
                walk(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif isinstance(value, str) and _CREDENTIAL_URL.search(value):
            raise QualityGateError("AUDIT_MANIFEST_CREDENTIAL_URL")

    walk(document)


def _validate_v11_integrity(document: Mapping[str, Any]) -> None:
    """Enforce v1.1 identity, hash and distributable-path invariants.

    JSON Schema validates each record's shape, while this cross-record check
    enforces uniqueness of the composite identity and raw-response hashes.
    """
    results = document.get("provider_results")
    if not isinstance(results, list):
        raise QualityGateError("AUDIT_MANIFEST_PROVIDER_RESULTS_INVALID")
    seen_keys: set[str] = set()
    hash_to_key: dict[str, str] = {}
    for record in results:
        if not isinstance(record, Mapping):
            raise QualityGateError("AUDIT_MANIFEST_PROVIDER_RESULT_INVALID")
        record_key = record.get("record_key")
        if not isinstance(record_key, str) or not record_key:
            raise QualityGateError("AUDIT_MANIFEST_RECORD_KEY_MISSING")
        try:
            identity_key = _identity_key(record)
        except (KeyError, TypeError):
            raise QualityGateError("AUDIT_MANIFEST_IDENTITY_FIELDS_INVALID") from None
        if identity_key in seen_keys:
            raise QualityGateError("AUDIT_MANIFEST_DUPLICATE_RECORD_KEY")
        if record_key != identity_key:
            raise QualityGateError("AUDIT_MANIFEST_RECORD_KEY_MISMATCH")
        seen_keys.add(identity_key)
        hashes = record.get("raw_response_hashes", [])
        if not isinstance(hashes, list):
            raise QualityGateError("AUDIT_MANIFEST_RAW_HASHES_INVALID")
        for raw_hash in hashes:
            if not isinstance(raw_hash, str) or not raw_hash:
                raise QualityGateError("AUDIT_MANIFEST_RAW_HASH_INVALID")
            previous_key = hash_to_key.get(raw_hash)
            if previous_key is not None and previous_key != identity_key:
                raise QualityGateError("AUDIT_MANIFEST_DUPLICATE_RAW_HASH")
            hash_to_key[raw_hash] = identity_key
        for key, value in record.items():
            if (
                isinstance(value, str)
                and key.lower().endswith(("path", "uri"))
                and _PERSONAL_PATH.search(value)
            ):
                raise QualityGateError("AUDIT_MANIFEST_PERSONAL_PATH")


def _identity_key(record: Mapping[str, Any]) -> str:
    """Serialize the manifest's seven-field request identity deterministically."""
    fields = (
        "run_id",
        "provider",
        "component",
        "asset",
        "request_start",
        "request_end",
        "endpoint_fingerprint",
    )
    values = tuple(record[field] for field in fields)
    if any(not isinstance(value, (str, int, float, type(None))) for value in values):
        raise TypeError("identity field has unsupported type")
    return "|".join("null" if value is None else str(value) for value in values)
