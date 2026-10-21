/**
 * The flood screen's Past tab (BKK-055c part 2): observed water by year and
 * the 1984-2021 ever-water extent. Extent only: depth is Unknown, movement is
 * Not yet, and nothing missing reads as zero.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { everWaterPath, observedWaterCellsPath } from "../src/lib/client.ts";
import { NOT_AVAILABLE } from "../src/lib/format.ts";
import {
  EVER,
  everReading,
  newestCityRun,
  PAST_DEPTH,
  PAST_MOVEMENT,
  pastCellsPath,
  pastYears,
  yearReading,
} from "../src/lib/past-flood.ts";
import type { EverWater, ObservedWaterYear, RunSummary } from "../src/lib/api.ts";

/** Shaped like city run 55cc7d9d's 2011 record. */
const year2011: ObservedWaterYear = {
  year: 2011,
  aoi_water_km2: 170.7147,
  aoi_water_share: 0.104212,
  share_status: "ok",
  known_km2: 1638.1555,
  aoi_seasonal_pixels: 75124,
  aoi_permanent_pixels: 151639,
};

/** Shaped like the ever-water answer for run 55cc7d9d. */
const ever: EverWater = {
  run_id: "55cc7d9d",
  available: true,
  verified: true,
  is_observation: true,
  measures: "everywhere ever detected as water in 1984-2021 (JRC Maximum Water Extent); not one flood, not depth",
  aoi_km2: 1654.7404,
  ever_water_km2: 294.9849,
  no_data_km2: 6.2839,
  ever_water_share_of_observed: 0.178946,
  reason: null,
  type: "FeatureCollection",
  features: [],
  warnings: [],
};

test("the Past tab reads the newest city run, never a pilot or a sensitivity case", () => {
  const runs = [
    { run_id: "case", aoi_id: "bangkok-bma", active_scenario: { state: null, case_id: "delay-1800" } },
    { run_id: "pilot", aoi_id: "sai-mai-district", active_scenario: { state: "moderate", case_id: null } },
    { run_id: "city-new", aoi_id: "bangkok-bma", active_scenario: null },
    { run_id: "city-old", aoi_id: "bangkok-bma", active_scenario: null },
  ] as RunSummary[];
  assert.equal(newestCityRun(runs)?.run_id, "city-new");
  assert.equal(newestCityRun(runs.slice(1, 2)), null);
  assert.equal(newestCityRun(null), null);
});

test("past years are the record's years, oldest first", () => {
  assert.deepEqual(pastYears({ years: [{ year: 2020 }, { year: 2010 }, { year: null }] }), [2010, 2020]);
  assert.deepEqual(pastYears(null), []);
});

test("a year's water reads as a minimum, split into seasonal and permanent", () => {
  const reading = yearReading(year2011);
  assert.equal(reading.value, "≥ 170.71");
  assert.equal(reading.unit, "km²");
  assert.match(reading.detail, /seasonal 56\.56 km²/);
  assert.match(reading.detail, /permanent 114\.16 km²/);
  assert.match(reading.detail, /10\.4% of the area with a known status/);
  assert.match(reading.reason ?? "", /misses short floods/);
});

test("a year without a water record shows its reason, not zero", () => {
  const reading = yearReading({ year: 2011, aoi_water_km2: null });
  assert.equal(reading.value, NOT_AVAILABLE);
  assert.ok(reading.reason);
  assert.equal(yearReading(null).value, NOT_AVAILABLE);
});

test("the ever-water extent states its share and its unknown area", () => {
  const reading = everReading(ever);
  assert.equal(reading.value, "294.98");
  assert.equal(reading.unit, "km²");
  assert.match(reading.detail, /17\.9% of the observed area/);
  assert.match(reading.detail, /not one flood/);
  assert.match(reading.reason ?? "", /No data for 6\.28 km²/);
});

test("an unavailable ever-water extent shows the API's reason", () => {
  const reading = everReading({ ...ever, available: false, ever_water_km2: null, reason: "the recorded extent tile is not staged" });
  assert.equal(reading.value, NOT_AVAILABLE);
  assert.equal(reading.reason, "the recorded extent tile is not staged");
  assert.equal(everReading(null).value, NOT_AVAILABLE);
});

test("past depth is Unknown and movement is Not yet, never zero", () => {
  assert.equal(PAST_DEPTH.value, "Unknown");
  assert.match(PAST_DEPTH.detail, /not how deep/);
  assert.equal(PAST_MOVEMENT.value, "Not yet");
  assert.match(PAST_MOVEMENT.detail, /BKK-040/);
});

test("the map reads yearly cells for a year and the extent for 1984-2021", () => {
  assert.equal(pastCellsPath("city", 2011), observedWaterCellsPath("city", 2011, 0.05));
  assert.equal(pastCellsPath("city", EVER), everWaterPath("city", 0.05));
  assert.equal(everWaterPath("a b", 0.05), "/v1/runs/a%20b/observed-water/ever?min_share=0.05");
});
