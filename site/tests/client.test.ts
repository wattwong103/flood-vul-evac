import assert from "node:assert/strict";
import test from "node:test";

import { asRunList, floodPath, routesPath } from "../src/lib/client.ts";
import {
  availableModelTimes,
  layerFooterText,
  shouldLoadStaticFallback,
} from "../src/lib/map-copy.ts";
import { stringPropertyExpression } from "../src/lib/map-expressions.ts";
import { geoJsonBounds } from "../src/lib/map-bounds.ts";

test("asRunList unwraps the API run-list envelope", () => {
  const runs = asRunList({
    count: 1,
    runs: [{ run_id: "city-run", validation_status: "demonstration" }],
    skipped: [],
    warnings: [],
  });

  assert.deepEqual(runs.map((run) => run.run_id), ["city-run"]);
});

test("stringPropertyExpression has no duplicate match branches", () => {
  assert.deepEqual(stringPropertyExpression("source_role"), [
    "to-string",
    ["coalesce", ["get", "source_role"], ""],
  ]);
});

test("floodPath carries the selected model time and display cap", () => {
  assert.equal(
    floodPath("run / one", 300, 5000),
    "/v1/runs/run%20%2F%20one/flood?time=300&limit=5000",
  );
});

test("routesPath identifies the aggregate evacuation map", () => {
  assert.equal(routesPath("pilot one"), "/v1/runs/pilot%20one/routes");
});

test("layer footer uses the selected model time", () => {
  assert.match(
    layerFooterText("19:00"),
    /Selected model time for time-varying layers: 19:00/,
  );
  assert.doesNotMatch(layerFooterText("19:00"), /not available/);
});

test("model timeline includes flood-only times", () => {
  assert.deepEqual(availableModelTimes([0, 300], [300, 600]), [0, 300]);
  assert.deepEqual(availableModelTimes(undefined, [900]), [900]);
});

test("city fallback waits for an empty primary layer", () => {
  assert.equal(shouldLoadStaticFallback("loading", 0), false);
  assert.equal(shouldLoadStaticFallback("ready", 4), false);
  assert.equal(shouldLoadStaticFallback("ready", 0), true);
});

test("geoJsonBounds covers the full Bangkok study-area geometry", () => {
  const bounds = geoJsonBounds({
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: { scope: "study_area" },
        geometry: {
          type: "MultiPolygon",
          coordinates: [
            [
              [
                [100.3279, 13.2191],
                [100.9386, 13.2191],
                [100.9386, 13.9552],
                [100.3279, 13.9552],
                [100.3279, 13.2191],
              ],
            ],
          ],
        },
      },
    ],
  });

  assert.deepEqual(bounds, [100.3279, 13.2191, 100.9386, 13.9552]);
});
