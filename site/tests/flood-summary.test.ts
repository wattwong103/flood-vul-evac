/**
 * The flood screen's readings (BKK-055c): how big, how deep, can people move.
 * Every null from /flood-summary must reach the reader as its reason, never as 0.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { floodSummaryPath } from "../src/lib/client.ts";
import {
  depthRulerMarks,
  howBigReading,
  howDeepReading,
  movementReason,
  movementRows,
} from "../src/lib/flood-summary.ts";
import { NOT_AVAILABLE } from "../src/lib/format.ts";
import type { FloodSummary } from "../src/lib/api.ts";

/** Shaped like the real answer for run daa9a8dc (Khlong San, moderate, 19:00). */
function moderate(): FloodSummary {
  return {
    run_id: "daa9a8dc",
    validation_status: "demonstration",
    available: true,
    time_s: 68400,
    time_defaulted: true,
    available_times: [64800, 68400],
    peak_time_s: 68400,
    source_role: "scenario",
    flood_area_threshold_m: 0.15,
    threshold_set_version: "bkk-demo-thresholds-v0.1",
    how_big: {
      flooded_area_km2: 5.1475,
      share_of_aoi: 0.863573,
      aoi_area_km2: 5.9607,
      cell_size_m: 50,
      reason: null,
    },
    how_deep: {
      max_depth_m: 0.5499,
      at_or_above_closing_depth: [
        { mode: 0, mode_name: "walk", closed_depth_m: 0.5, area_km2: 0.525 },
        { mode: 3, mode_name: "car", closed_depth_m: 0.3, area_km2: 3.0225 },
      ],
      reason: null,
    },
    movement: {
      modes: [
        {
          mode: 0, mode_name: "walk", closed_depth_m: 0.5, total_km: 173.167,
          open_km: 13.305, slowed_km: 135.008, closed_km: 24.854, unknown_km: 0,
          open_share: 0.076833, slowed_share: 0.779638, closed_share: 0.143529,
          unknown_share: 0, reason: null,
        },
        {
          mode: 3, mode_name: "car", closed_depth_m: 0.3, total_km: 124.542,
          open_km: 0.577, slowed_km: 61.584, closed_km: 62.38, unknown_km: 0,
          open_share: 0.004633, slowed_share: 0.494484, closed_share: 0.500874,
          unknown_share: 0, reason: null,
        },
      ],
      reason: null,
    },
    warnings: [],
  };
}

test("the summary path encodes the run and omits a missing time", () => {
  assert.equal(floodSummaryPath("a b", 300), "/v1/runs/a%20b/flood-summary?time=300");
  assert.equal(floodSummaryPath("run", null), "/v1/runs/run/flood-summary");
});

test("how big reports area and its share of the district", () => {
  const reading = howBigReading(moderate());
  assert.equal(reading.value, "5.15");
  assert.equal(reading.unit, "km²");
  assert.match(reading.detail, /86\.4% of the district/);
  assert.equal(reading.reason, null);
});

test("a null area shows its reason, never zero", () => {
  const summary = moderate();
  summary.how_big = {
    flooded_area_km2: null, share_of_aoi: null, aoi_area_km2: 1643.5,
    cell_size_m: null, reason: "No city-scale flood layer in this run.",
  };
  const reading = howBigReading(summary);
  assert.equal(reading.value, NOT_AVAILABLE);
  assert.equal(reading.unit, null);
  assert.equal(reading.reason, "No city-scale flood layer in this run.");
});

test("a dry run's zero is labelled as a declared scenario value", () => {
  const summary = moderate();
  summary.how_big = {
    flooded_area_km2: 0, share_of_aoi: 0, aoi_area_km2: 5.9607,
    cell_size_m: null, reason: "declared dry scenario",
  };
  const reading = howBigReading(summary);
  assert.equal(reading.value, "0");
  assert.equal(reading.reason, "declared dry scenario");
});

test("a withheld share is said to be withheld", () => {
  const summary = moderate();
  summary.how_big.share_of_aoi = null;
  assert.match(howBigReading(summary).detail, /share of the district withheld/);
});

test("how deep names where cars and walkers stop", () => {
  const reading = howDeepReading(moderate());
  assert.equal(reading.value, "0.55");
  assert.equal(reading.unit, "m");
  assert.match(reading.detail, /Cars and motorcycles stop on 3\.02 km² \(0\.30 m or deeper\)/);
  assert.match(reading.detail, /walkers on 0\.53 km² \(0\.50 m or deeper\)/);
});

test("an unknown closing depth is said to be unknown", () => {
  const summary = moderate();
  summary.how_deep.at_or_above_closing_depth[1] = {
    mode: 3, mode_name: "car", closed_depth_m: null, area_km2: null,
  };
  assert.match(howDeepReading(summary).detail, /cars and motorcycles: closing depth unknown/i);
});

test("movement rows carry shares per mode and a mode's own reason", () => {
  const summary = moderate();
  summary.movement.modes[1] = {
    ...summary.movement.modes[1],
    open_share: null, slowed_share: null, closed_share: null, unknown_share: null,
    reason: "no road state for car at this time",
  };
  const [walk, car] = movementRows(summary);
  assert.equal(walk.label, "Walking");
  assert.equal(walk.closed, 0.143529);
  assert.equal(walk.reason, null);
  assert.equal(car.label, "Car / motorcycle");
  assert.equal(car.closed, null);
  assert.equal(car.reason, "no road state for car at this time");
});

test("with no road states the movement reason is shown", () => {
  const summary = moderate();
  summary.movement = { modes: [], reason: "this run has no road states (edge_states.parquet is absent)" };
  assert.deepEqual(movementRows(summary), []);
  assert.match(movementReason(summary) ?? "", /no road states/);
});

test("the depth ruler marks each closing depth and the deepest water", () => {
  assert.deepEqual(depthRulerMarks(moderate()), [
    { depthM: 0.3, label: "Cars and motorcycles stop" },
    { depthM: 0.5, label: "Walkers stop" },
    { depthM: 0.5499, label: "Deepest water now" },
  ]);
});

test("the depth ruler leaves out what it does not know", () => {
  const summary = moderate();
  summary.how_deep = { max_depth_m: null, at_or_above_closing_depth: [], reason: "no layer" };
  assert.deepEqual(depthRulerMarks(summary), []);
});
