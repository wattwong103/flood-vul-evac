from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline.stage_bma_flood_risk import inventory


VALID_HEADER = "risk_id,risk_year,risk_group,District,risk_type,area\n"


class InventoryTests(unittest.TestCase):
    def test_inventory_reports_rows_hash_and_no_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "source.csv"
            source.write_text(
                VALID_HEADER
                + "49,2566,2,เขตภาษีเจริญ,2,ถนนเพชรเกษม\n"
                + "48,2566,2,เขตบางขุนเทียน,2,ถนนบางขุนเทียน\n",
                encoding="utf-8",
            )

            report = inventory(source)

            self.assertEqual(report["row_count"], 2)
            self.assertEqual(report["coordinate_fields"], [])
            self.assertEqual(report["spatial_use"], "qualitative_only")
            self.assertEqual(len(str(report["content_sha256"])), 64)

    def test_inventory_rejects_missing_expected_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "source.csv"
            source.write_text("risk_id,District\n1,เขตพระนคร\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Missing expected fields"):
                inventory(source)


if __name__ == "__main__":
    unittest.main()
