/**
 * The flood screen's readings (BKK-055c): how big, how deep, can people move.
 * Every null from /flood-summary must reach the reader as its reason, never as 0.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { floodSummaryPath } from "../src/lib/client.ts";
import {
  depthRulerMarks,
  displayedTime,
  floodSourceNote,
  formatReadingShare,
  howBigReading,
  howDeepReading,
  movementReason,
  movementRows,
  summaryForRun,
} from "../src/lib/flood-summary.ts";
import { roadState, SLOWED_BELOW } from "../src/lib/road-state.ts";
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

test("the depth ruler marks each closing depth and the deepest water at its time", () => {
  assert.deepEqual(depthRulerMarks(moderate()), [
    { depthM: 0.3, label: "Cars and motorcycles stop", deepest: false },
    { depthM: 0.5, label: "Walkers stop", deepest: false },
    { depthM: 0.5499, label: "Deepest water at 19:00", deepest: true },
  ]);
});

test("the depth ruler leaves out what it does not know", () => {
  const summary = moderate();
  summary.how_deep = { max_depth_m: null, at_or_above_closing_depth: [], reason: "no layer" };
  assert.deepEqual(depthRulerMarks(summary), []);
});


// ---------------------------------------------------------------------------
// Code-review regressions.
// ---------------------------------------------------------------------------

test("a summary for another run is not shown under the selected run", () => {
  assert.equal(summaryForRun(moderate(), "another-run"), null);
  assert.equal(summaryForRun(moderate(), "daa9a8dc")?.run_id, "daa9a8dc");
  assert.equal(summaryForRun(null, "daa9a8dc"), null);
});

test("the slider shows the picked time before the server answers", () => {
  assert.equal(displayedTime(65100, 68400), 65100);
  assert.equal(displayedTime(null, 68400), 68400);
  assert.equal(displayedTime(null, null), null);
});

test("a real but tiny area never reads as zero", () => {
  const summary = moderate();
  summary.how_big.flooded_area_km2 = 0.0025; // one 50 m cell
  summary.how_big.share_of_aoi = 0.0004;
  const reading = howBigReading(summary);
  assert.equal(reading.value, "< 0.01");
  assert.match(reading.detail, /< 0\.1% of the district/);
  summary.how_deep.at_or_above_closing_depth[1].area_km2 = 0.0025;
  assert.match(howDeepReading(summary).detail, /stop on < 0\.01 km²/);
});

test("a real but tiny share never reads as 0.0%", () => {
  assert.equal(formatReadingShare(0.0004), "< 0.1%");
  assert.equal(formatReadingShare(0), "0.0%");
  assert.equal(formatReadingShare(0.143529), "14.4%");
  assert.equal(formatReadingShare(null), NOT_AVAILABLE);
});

test("the flood source is named, not assumed to be a scenario", () => {
  assert.match(floodSourceNote("scenario"), /declared scenario/);
  assert.match(floodSourceNote("modelled"), /modelled/);
  assert.doesNotMatch(floodSourceNote("modelled"), /scenario/);
  assert.match(floodSourceNote("mixed:modelled,scenario"), /mixes/);
  assert.match(floodSourceNote(null), /not recorded/);
});

test("road states follow the readings' rule, and an unrecorded state is unknown", () => {
  assert.equal(SLOWED_BELOW, 1);
  assert.equal(roadState(true, null), "closed");
  assert.equal(roadState(false, 0.97), "slowed");
  assert.equal(roadState(false, 1), "open");
  assert.equal(roadState(null, 0.5), "unknown");
  assert.equal(roadState(false, null), "unknown");
});
