"""Output publication rejects duplicate names and stale final-byte hashes."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bkkflow import manifest, runner
from bkkflow.util import sha256_file


def test_register_output_rejects_duplicate_uri(tmp_path):
    path = tmp_path / "trips.parquet"
    path.write_bytes(b"routed trips")
    context = SimpleNamespace(outputs=[])

    runner.register_output(context, "trips", path, rows=1)
    with pytest.raises(ValueError, match="Duplicate output URI: trips.parquet"):
        runner.register_output(context, "trips", path, rows=1)

    assert len(context.outputs) == 1


def test_output_integrity_requires_hash_of_final_bytes(tmp_path):
    path = tmp_path / "trips.parquet"
    path.write_bytes(b"unrouted trips")
    outputs = [manifest.output_entry("trips", path, row_count=1)]
    stale_hash = outputs[0]["content_sha256"]

    path.write_bytes(b"routed final trips")
    with pytest.raises(ValueError, match="Output hash mismatch: trips.parquet"):
        manifest.verify_output_integrity(tmp_path, outputs)

    outputs[0]["content_sha256"] = sha256_file(path)
    manifest.verify_output_integrity(tmp_path, outputs)


def test_output_integrity_rejects_duplicate_manifest_uri(tmp_path):
    path = tmp_path / "trips.parquet"
    path.write_bytes(b"routed trips")
    entry = manifest.output_entry("trips", path, row_count=1)

    with pytest.raises(ValueError, match="Duplicate output URI: trips.parquet"):
        manifest.verify_output_integrity(tmp_path, [entry, dict(entry)])
