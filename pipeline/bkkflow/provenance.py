"""Verify staged bytes and recover original retrieval records without networking."""
from datetime import datetime
from pathlib import Path
from .util import RAW_DIR, read_json, sha256_file, stable_hash, write_json


def verify_source(path: Path, url: str, *, cache_dir: Path | None = None) -> dict:
    sidecar = path.with_suffix(".provenance.json")
    original = sidecar.is_file()
    key = stable_hash({"url": url, "accept": False})
    record = sidecar if original else (cache_dir or RAW_DIR / "_http_cache") / key[:2] / f"{key}.json"
    if not record.is_file():
        raise ValueError(f"Missing source provenance for {path.name}; restore the original "
                         "HTTP cache record or re-download into a new staged location")
    metadata = read_json(record)
    digest = sha256_file(path)
    if ((metadata.get("resource_url") or metadata.get("url")) != url
            or metadata.get("content_sha256") != digest):
        raise ValueError(f"Source provenance does not match staged bytes: {path.name}")
    try:
        timestamp = datetime.fromisoformat(metadata["retrieved_at"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("retrieval timestamp must include its timezone")
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid retrieval timestamp in source provenance: {path.name}") from error
    result = {"resource_url": url, "retrieved_at": metadata["retrieved_at"],
              "content_sha256": digest}
    if not original:
        write_json(sidecar, result)
    return result
