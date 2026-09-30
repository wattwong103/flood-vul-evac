"""Stage and inventory the approved BMA flood-risk/watch CSV.

The source contains named roads and districts, not confirmed point coordinates.
It is therefore staged as qualitative review evidence and never geocoded by this
script. Downloaded data and the generated manifest live under data/raw, which is
ignored by Git.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


SOURCE_ID = "bma-flood-risk-watch-2023"
SOURCE_URL = (
    "https://data.bangkok.go.th/dataset/"
    "a1cc1d7a-6d87-4dd2-a662-79ed58c2623c/resource/"
    "b719945f-f10b-4b4c-afd2-2e8b43d21726/download/-2566.csv"
)
CATALOGUE_URL = "https://data.go.th/th/dataset/risk-flood-bangkok-area"
EXPECTED_FIELDS = {
    "risk_id",
    "risk_year",
    "risk_group",
    "District",
    "risk_type",
    "area",
}
MAX_BYTES = 5_000_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def detect_encoding(payload: bytes) -> str:
    if b"\x00" in payload:
        raise ValueError("NUL bytes found; refusing to parse as CSV")
    for encoding in ("utf-8-sig", "utf-8", "cp874"):
        try:
            payload.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("CSV is not valid UTF-8/UTF-8-BOM or CP874")


def download(destination: Path) -> None:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={
            "User-Agent": "BKK-FLOW research data pipeline/0.1",
            "Accept": "text/csv,*/*;q=0.8",
        },
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=45) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_BYTES:
            raise ValueError(f"Source exceeds {MAX_BYTES:,} byte safety limit")
        with destination.open("wb") as output:
            total = 0
            while chunk := response.read(64 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError(f"Source exceeds {MAX_BYTES:,} byte safety limit")
                output.write(chunk)


def inventory(path: Path) -> dict[str, object]:
    if path.suffix.lower() != ".csv":
        raise ValueError("Only a local .csv file is accepted")
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if size == 0 or size > MAX_BYTES:
        raise ValueError(f"Unexpected file size: {size:,} bytes")

    payload = path.read_bytes()
    encoding = detect_encoding(payload)
    decoded = payload.decode(encoding)
    reader = csv.DictReader(decoded.splitlines())
    fields = reader.fieldnames or []
    missing = sorted(EXPECTED_FIELDS.difference(fields))
    if missing:
        raise ValueError(f"Missing expected fields: {', '.join(missing)}")

    rows = list(reader)
    risk_ids = [row.get("risk_id", "").strip() for row in rows]
    duplicate_ids = sorted(key for key, count in Counter(risk_ids).items() if key and count > 1)
    blank_counts = {field: sum(not row.get(field, "").strip() for row in rows) for field in fields}
    coordinate_like = [field for field in fields if field.lower() in {"lat", "latitude", "lon", "lng", "longitude", "x", "y"}]

    return {
        "source_id": SOURCE_ID,
        "source_url": SOURCE_URL,
        "catalogue_url": CATALOGUE_URL,
        "licence": "Creative Commons Attribution",
        "retrieved_or_staged_at": datetime.now(timezone.utc).isoformat(),
        "content_sha256": sha256(path),
        "byte_count": size,
        "encoding": encoding,
        "row_count": len(rows),
        "fields": fields,
        "blank_counts": blank_counts,
        "duplicate_risk_ids": duplicate_ids,
        "coordinate_fields": coordinate_like,
        "spatial_use": (
            "qualitative_only"
            if not coordinate_like
            else "coordinates_require_crs_and_range_validation"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--download", action="store_true", help="Download from the approved BMA resource URL")
    mode.add_argument("--input", type=Path, help="Stage a manually downloaded local CSV")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/bma/flood-risk-watch-2023"),
        help="Ignored raw-data directory (default: %(default)s)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    final_csv = output_dir / "bma-flood-risk-watch-2023.csv"

    file_descriptor, temporary_name = tempfile.mkstemp(prefix="bma-flood-", suffix=".partial", dir=output_dir)
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        if args.download:
            download(temporary)
            temporary.replace(final_csv)
        else:
            source = args.input.resolve()
            if source == final_csv:
                pass
            else:
                shutil.copyfile(source, temporary)
                temporary.replace(final_csv)

        report = inventory(final_csv)
        manifest = output_dir / "manifest.json"
        manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:  # concise CLI boundary; preserves original cause in stderr
        print(f"staging failed: {error}", file=sys.stderr)
        return 1
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
