"""Source registry: the licence gate every stage must pass.

The project's core data rule is two-part: a source must be publicly accessible
*and* explicitly reusable. Only ``approved`` resources may be ingested. A
``verify`` resource may be referenced in documentation, never in a run.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from ..util import DATA_DIR, read_json

REGISTRY_PATH = DATA_DIR / "source-registry.json"

APPROVED = "approved"
VERIFY = "verify"
REJECTED = "rejected"

STATUS_VALUES = (APPROVED, VERIFY, REJECTED)


class LicenceGateError(RuntimeError):
    """Raised when a run attempts to ingest a non-approved resource."""


@dataclass(frozen=True)
class Source:
    source_id: str
    agency: str
    dataset: str
    model_role: str
    resource_url: str
    licence: str
    status: str
    raw: dict[str, Any]

    @property
    def is_approved(self) -> bool:
        return self.status == APPROVED

    def manifest_entry(
        self,
        *,
        retrieved_at: str,
        content_sha256: str,
        licence_snapshot: str,
        request_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the ``source_versions`` item required by the run schema."""
        entry: dict[str, Any] = {
            "source_id": self.source_id,
            "retrieved_at": retrieved_at,
            "content_sha256": content_sha256,
            "licence_snapshot": licence_snapshot,
        }
        if request_parameters:
            entry["request_parameters"] = request_parameters
        return entry


class SourceRegistry:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.registry_version: str = payload["registry_version"]
        self.country: str = payload["country"]
        self.policy: str = payload.get("policy", "")
        self._sources: dict[str, Source] = {}
        for item in payload["sources"]:
            status = item.get("status", VERIFY)
            if status not in STATUS_VALUES:
                raise ValueError(f"{item.get('source_id')}: unknown status {status!r}")
            self._sources[item["source_id"]] = Source(
                source_id=item["source_id"],
                agency=item.get("agency", ""),
                dataset=item.get("dataset", ""),
                model_role=item.get("model_role", ""),
                resource_url=item.get("resource_url", ""),
                licence=item.get("licence", ""),
                status=status,
                raw=item,
            )

    def __len__(self) -> int:
        return len(self._sources)

    def __iter__(self):
        return iter(self._sources.values())

    def __contains__(self, source_id: object) -> bool:
        return source_id in self._sources

    def get(self, source_id: str) -> Source:
        if source_id not in self._sources:
            raise KeyError(f"unknown source_id {source_id!r}")
        return self._sources[source_id]

    def require_approved(self, source_ids: Iterable[str]) -> list[Source]:
        """Validate that every id is approved, or raise with the full reason."""
        resolved: list[Source] = []
        problems: list[str] = []
        for source_id in source_ids:
            try:
                source = self.get(source_id)
            except KeyError as error:
                problems.append(f"{source_id}: not in registry")
                continue
            if not source.is_approved:
                problems.append(
                    f"{source_id}: status={source.status} licence={source.licence!r} "
                    f"notes={source.raw.get('notes', '')}"
                )
                continue
            resolved.append(source)
        if problems:
            raise LicenceGateError(
                "licence gate failed; no run may ingest these resources:\n  - "
                + "\n  - ".join(problems)
            )
        return resolved

    def by_status(self, status: str) -> list[Source]:
        return [source for source in self._sources.values() if source.status == status]

    def summary(self) -> dict[str, Any]:
        counts = {status: len(self.by_status(status)) for status in STATUS_VALUES}
        return {
            "registry_version": self.registry_version,
            "country": self.country,
            "policy": self.policy,
            "counts": counts,
            "sources": [
                {
                    "source_id": source.source_id,
                    "agency": source.agency,
                    "dataset": source.dataset,
                    "model_role": source.model_role,
                    "resource_url": source.resource_url,
                    "licence": source.licence,
                    "status": source.status,
                    "notes": source.raw.get("notes", ""),
                }
                for source in sorted(self._sources.values(), key=lambda s: s.source_id)
            ],
        }


@lru_cache(maxsize=4)
def load_registry(path: str | Path = str(REGISTRY_PATH)) -> SourceRegistry:
    return SourceRegistry(read_json(path))
