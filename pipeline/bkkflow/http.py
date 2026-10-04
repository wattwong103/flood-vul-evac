"""Polite HTTP client with disk caching, retry and mirror rotation.

Public endpoints used by this project (Overpass, WorldPop, data.go.th) rate
limit aggressively and occasionally reset connections. Raw responses are cached
under ``data/raw`` keyed by request hash so a re-run never re-downloads the same
bytes, and every cached response keeps its own provenance sidecar.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

import requests

from .util import RAW_DIR, ensure_dir, sha256_bytes, sha256_file, stable_hash, utc_now_iso, write_json

USER_AGENT = (
    "BKK-FLOW research pipeline/0.1 "
    "(flood-exposure research prototype; non-commercial; contact via repository)"
)

OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

# Community mirrors are frequently unreachable from a given network. Probe them
# with a short timeout so a dead mirror costs seconds rather than minutes.
MIRROR_TIMEOUT_SECONDS = 25

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    """A fetched payload plus the provenance needed for a run manifest."""

    url: str
    body: bytes
    content_sha256: str
    retrieved_at: str
    status_code: int
    from_cache: bool
    request_parameters: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")

    def json(self) -> Any:
        import json

        return json.loads(self.body.decode("utf-8"))


class HttpClient:
    """Small wrapper that prefers the cache and degrades politely."""

    def __init__(self, cache_dir: str | Path | None = None, timeout: int = 180) -> None:
        self.cache_dir = ensure_dir(cache_dir or RAW_DIR / "_http_cache")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})

    def _cache_paths(self, key: str) -> tuple[Path, Path]:
        bucket = ensure_dir(self.cache_dir / key[:2])
        return bucket / f"{key}.bin", bucket / f"{key}.json"

    def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        *,
        use_cache: bool = True,
        retries: int = 3,
        backoff: float = 4.0,
        expect_json: bool = False,
        timeout: int | None = None,
    ) -> FetchResult:
        request_timeout = timeout or self.timeout
        full_url = url
        if params:
            full_url = f"{url}?{urlencode(params, doseq=True)}"
        key = stable_hash({"url": full_url, "accept": expect_json})
        body_path, meta_path = self._cache_paths(key)

        if use_cache and body_path.is_file() and meta_path.is_file():
            import json

            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return FetchResult(
                url=full_url,
                body=body_path.read_bytes(),
                content_sha256=meta["content_sha256"],
                retrieved_at=meta["retrieved_at"],
                status_code=meta.get("status_code", 200),
                from_cache=True,
                request_parameters=dict(params or {}),
                headers=meta.get("headers", {}),
            )

        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=request_timeout)
                if response.status_code in RETRYABLE_STATUS:
                    raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
                response.raise_for_status()
                body = response.content
                digest = sha256_bytes(body)
                body_path.parent.mkdir(parents=True, exist_ok=True)
                body_path.write_bytes(body)
                write_json(
                    meta_path,
                    {
                        "url": full_url,
                        "content_sha256": digest,
                        "retrieved_at": utc_now_iso(),
                        "status_code": response.status_code,
                        "byte_count": len(body),
                        "headers": {
                            key: value
                            for key, value in response.headers.items()
                            if key.lower() in {"content-type", "etag", "last-modified", "content-length"}
                        },
                    },
                )
                return FetchResult(
                    url=full_url,
                    body=body,
                    content_sha256=digest,
                    retrieved_at=utc_now_iso(),
                    status_code=response.status_code,
                    from_cache=False,
                    request_parameters=dict(params or {}),
                    headers=dict(response.headers),
                )
            except Exception as error:  # noqa: BLE001 - retried and re-raised below
                last_error = error
                if attempt < retries:
                    time.sleep(backoff * attempt)
        raise RuntimeError(f"GET failed after {retries} attempts: {full_url}") from last_error

    def download_large(
        self,
        url: str,
        destination: str | Path,
        *,
        chunk_size: int = 1 << 20,
        max_attempts: int = 6,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Stream a large file to disk with HTTP range resume.

        Country-scale rasters run to hundreds of megabytes. Buffering them in
        memory loses the whole transfer on a dropped connection, so bytes are
        appended to a ``.part`` file and a Range request continues an
        interrupted transfer. The file is only promoted to its final name once
        the byte count matches the server's Content-Length.
        """
        from pathlib import Path as _Path

        target = _Path(destination)
        ensure_dir(target.parent)
        partial = target.with_suffix(target.suffix + ".part")

        expected: int | None = None
        try:
            head = self.session.head(url, timeout=60, allow_redirects=True)
            if head.ok and head.headers.get("Content-Length"):
                expected = int(head.headers["Content-Length"])
        except requests.RequestException:
            expected = None

        if target.is_file() and (expected is None or target.stat().st_size == expected):
            return {
                "url": url,
                "path": str(target),
                "byte_count": target.stat().st_size,
                "content_sha256": sha256_file(target),
                "resumed": False,
                "already_present": True,
            }

        if expected is not None and target.is_file() and target.stat().st_size != expected:
            # A truncated file from an earlier run: start it over rather than
            # appending to bytes that may not align with the source.
            target.unlink()

        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            already = partial.stat().st_size if partial.is_file() else 0
            if expected is not None and already >= expected:
                break
            headers = {"Range": f"bytes={already}-"} if already else {}
            try:
                with self.session.get(
                    url, stream=True, timeout=timeout, headers=headers
                ) as response:
                    if already and response.status_code == 200:
                        # Server ignored the range request; restart cleanly.
                        already = 0
                        if partial.is_file():
                            partial.unlink()
                    response.raise_for_status()
                    mode = "ab" if already else "wb"
                    with partial.open(mode) as handle:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if chunk:
                                handle.write(chunk)
                if expected is None or partial.stat().st_size == expected:
                    break
            except requests.RequestException as error:
                last_error = error
                time.sleep(min(backoff_delay := 3.0 * attempt, 30.0))
                continue
            del backoff_delay
        else:
            raise RuntimeError(f"download did not complete: {url}") from last_error

        if expected is not None and partial.stat().st_size != expected:
            raise RuntimeError(
                f"incomplete download for {url}: {partial.stat().st_size:,} of {expected:,} bytes"
            )

        partial.replace(target)
        return {
            "url": url,
            "path": str(target),
            "byte_count": target.stat().st_size,
            "content_sha256": sha256_file(target),
            "resumed": True,
            "already_present": False,
        }

    def overpass(self, query: str, *, use_cache: bool = True, mirrors: tuple[str, ...] = OVERPASS_MIRRORS, timeout: int | None = None) -> FetchResult:
        """POST an Overpass QL query, rotating mirrors on failure.

        A query is cached per mirror, because Overpass results legitimately
        change over time and a cached result is a snapshot worth keeping.
        """
        last_error: Exception | None = None
        primary = mirrors[0]
        for mirror in mirrors:
            key = stable_hash({"mirror": mirror, "query": query})
            bucket = ensure_dir(self.cache_dir / "overpass" / key[:2])
            cached_body = bucket / f"{key}.json"
            cached_meta = bucket / f"{key}.meta.json"
            if use_cache and cached_body.is_file() and cached_meta.is_file():
                import json

                meta = json.loads(cached_meta.read_text(encoding="utf-8"))
                return FetchResult(
                    url=mirror,
                    body=cached_body.read_bytes(),
                    content_sha256=meta["content_sha256"],
                    retrieved_at=meta["retrieved_at"],
                    status_code=meta.get("status_code", 200),
                    from_cache=True,
                    request_parameters={"query_sha256": stable_hash(query)},
                )
            attempt_timeout = timeout or (self.timeout if mirror == primary else MIRROR_TIMEOUT_SECONDS)
            try:
                response = self.session.post(
                    mirror, data={"data": query}, timeout=attempt_timeout
                )
                if response.status_code in RETRYABLE_STATUS:
                    raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
                response.raise_for_status()
                body = response.content
                digest = sha256_bytes(body)
                key = stable_hash({"mirror": mirror, "query": query})
                bucket = ensure_dir(self.cache_dir / "overpass" / key[:2])
                (bucket / f"{key}.json").write_bytes(body)
                write_json(
                    bucket / f"{key}.meta.json",
                    {
                        "mirror": mirror,
                        "query_sha256": stable_hash(query),
                        "content_sha256": digest,
                        "retrieved_at": utc_now_iso(),
                        "status_code": response.status_code,
                        "byte_count": len(body),
                    },
                )
                return FetchResult(
                    url=mirror,
                    body=body,
                    content_sha256=digest,
                    retrieved_at=utc_now_iso(),
                    status_code=response.status_code,
                    from_cache=False,
                    request_parameters={"query_sha256": stable_hash(query)},
                )
            except Exception as error:  # noqa: BLE001 - try the next mirror
                last_error = error
                continue
        raise RuntimeError("all Overpass mirrors failed") from last_error
