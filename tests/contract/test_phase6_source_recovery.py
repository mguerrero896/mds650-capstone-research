from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_phase6_source_recovery as recovery  # noqa: E402


def _write_blob(repository_root: Path, payload: bytes) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository_root), "hash-object", "-w", "--stdin"],
        input=payload,
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("ascii").strip()


def _fixture_roots(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    repository_root = tmp_path / "repository"
    evidence_root = tmp_path / "evidence"
    repository_root.mkdir()
    evidence_root.mkdir()
    subprocess.run(["git", "-C", str(repository_root), "init", "-q"], check=True)

    source_bytes = {
        "src/mds650/phase6.py": b"frozen phase6 source\n",
        "scripts/finalize_phase6_evidence.py": b"frozen finalizer source\n",
    }
    blobs = {
        artifact: _write_blob(repository_root, payload)
        for artifact, payload in source_bytes.items()
    }
    (evidence_root / "artifacts/phase6").mkdir(parents=True)
    (evidence_root / "artifacts/phase6/method_freeze.json").write_text(
        json.dumps(
            {
                "source_code_hashes": {
                    artifact: hashlib.sha256(payload).hexdigest()
                    for artifact, payload in source_bytes.items()
                }
            }
        ),
        encoding="utf-8",
    )
    return repository_root, evidence_root, blobs


def test_phase6_source_recovery_records_exact_frozen_blobs(tmp_path: Path) -> None:
    repository_root, evidence_root, blobs = _fixture_roots(tmp_path)

    payload = recovery.audit_phase6_source_recovery(
        evidence_root=evidence_root,
        repository_root=repository_root,
        frozen_blobs=blobs,
        create_refs=True,
    )

    assert payload["status"] == "PASS"
    assert payload["audited_source_count"] == 2
    assert all(item["expected_sha256"] == item["recovered_sha256"] for item in payload["artifacts"])
    for item in payload["artifacts"]:
        assert (
            subprocess.run(
                ["git", "-C", str(repository_root), "rev-parse", item["recovery_ref"]],
                capture_output=True,
                check=True,
                text=True,
            ).stdout.strip()
            == item["frozen_blob"]
        )


def test_phase6_source_recovery_fails_on_frozen_hash_mismatch(tmp_path: Path) -> None:
    repository_root, evidence_root, blobs = _fixture_roots(tmp_path)
    method_freeze = evidence_root / "artifacts/phase6/method_freeze.json"
    payload = json.loads(method_freeze.read_text(encoding="utf-8"))
    payload["source_code_hashes"]["src/mds650/phase6.py"] = "0" * 64
    method_freeze.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="PHASE6_FROZEN_SOURCE_RECOVERY_FAILED"):
        recovery.audit_phase6_source_recovery(
            evidence_root=evidence_root,
            repository_root=repository_root,
            frozen_blobs=blobs,
            create_refs=False,
        )


def test_source_recovery_manifest_is_sanitized(tmp_path: Path) -> None:
    repository_root, evidence_root, blobs = _fixture_roots(tmp_path)
    payload = recovery.audit_phase6_source_recovery(
        evidence_root=evidence_root,
        repository_root=repository_root,
        frozen_blobs=blobs,
        create_refs=False,
    )

    serialized = json.dumps(payload)
    assert "C:\\Users\\" not in serialized
    assert str(repository_root) not in serialized
    assert str(evidence_root) not in serialized
