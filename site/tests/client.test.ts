import assert from "node:assert/strict";
import test from "node:test";

import { asRunList, floodPath, routesPath, loadViewportLayer } from "../src/lib/client.ts";
import {
  availableModelTimes,
  layerFooterText,
  shouldLoadStaticFallback,
} from "../src/lib/map-copy.ts";
import { stringPropertyExpression } from "../src/lib/map-expressions.ts";
import { geoJsonBounds } from "../src/lib/map-bounds.ts";
import { updateMapSources } from "../src/lib/map-sources.ts";
import { isRefugeRecord } from "../src/lib/map-refuges.ts";

test("ordinary buildings are not refuge candidates merely because verification is false", () => {
  assert.equal(isRefugeRecord({ refuge_verified: false, refuge_status: "not_a_refuge" }), false);
  assert.equal(isRefugeRecord({ refuge_verified: false, height_m: 30 }), false);
  assert.equal(isRefugeRecord({ refuge_verified: false, refuge_status: "osm_tagged_candidate_unverified" }), true);
  assert.equal(isRefugeRecord({ refuge_verified: true }), true);
  assert.equal(isRefugeRecord({ refuge_id: "candidate-1", refuge_verified: false }), true);
});

test("table mode retains the map container for a working return to map mode", async () => {
  const { createServer } = await import("vite");
  const { createElement } = await import("react");
  const { renderToStaticMarkup } = await import("react-dom/server");
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: "custom" });
  try {
    const { MapPanel } = await server.ssrLoadModule("/src/components/MapPanel.tsx");
    for (const visible of [true, false, true]) {
      const html = renderToStaticMarkup(createElement(MapPanel, { visible }, createElement("canvas")));
      assert.match(html, /<canvas/);
      assert.equal(html.includes("display:none"), !visible);
    }
  } finally { await server.close(); }
});

test("asRunList unwraps the API run-list envelope", () => {
  const runs = asRunList({
    count: 1,
    runs: [{ run_id: "city-run", validation_status: "demonstration" }],
    skipped: [],
    warnings: [],
  });

  assert.deepEqual(runs.map((run) => run.run_id), ["city-run"]);
});

test("viewport loader follows pages and preserves bounds and run identity", async () => {
  const original = globalThis.fetch;
  const urls: string[] = [];
  globalThis.fetch = async (url) => {
    urls.push(String(url));
    const second = String(url).includes("after=9");
    return new Response(JSON.stringify({ available: true, run_id: "city run", layer: "network",
      type: "FeatureCollection", features: [{ type: "Feature", geometry: null, properties: { edge_id: second ? "east2" : "east1" } }],
      matched_rows: 2, next_cursor: second ? null : 9 }));
  };
  try {
    const result = await loadViewportLayer("city run", "network", [100.7, 13.4, 100.9, 13.6]);
    assert.equal(result.features.length, 2);
    assert.equal(result.truncated, false);
    assert.equal(urls.length, 2);
    assert.ok(urls.every(url => url.includes("city%20run/map/network") && new URL(url).searchParams.get("bbox") === "100.7,13.4,100.9,13.6"));
  } finally { globalThis.fetch = original; }
});

test("viewport budget reports incomplete coverage and rejects mixed runs", async () => {
  const original = globalThis.fetch;
  let run = "chosen";
  globalThis.fetch = async () => new Response(JSON.stringify({ available: true, run_id: run, layer: "buildings",
    type: "FeatureCollection", features: [{ type: "Feature", geometry: null, properties: {} }], matched_rows: 50, next_cursor: 1 }));
  try {
    const result = await loadViewportLayer("chosen", "buildings", [100, 13, 101, 14], undefined, 1);
    assert.equal(result.truncated, true);
    assert.match(result.note, /Zoom in/);
    run = "different";
    await assert.rejects(loadViewportLayer("chosen", "buildings", [100, 13, 101, 14]), /run or layer/);
  } finally { globalThis.fetch = original; }
});

test("validation stamp renders valid paragraph content", async () => {
  const { createServer } = await import("vite");
  const { createElement } = await import("react");
  const { renderToStaticMarkup } = await import("react-dom/server");
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: "custom" });
  try {
    const { ValidationStamp } = await server.ssrLoadModule("/src/components/primitives.tsx");
    const html = renderToStaticMarkup(createElement(ValidationStamp, { status: "demonstration", modelTime: null }));
    assert.match(html, /demonstration/);
    assert.match(html, /model time/);
    // HTML parsing closes a paragraph before a div, separating the stamp's content.
    assert.doesNotMatch(html, /^<p\b[^>]*>[\s\S]*<(?:div|section|p)\b/);
  } finally { await server.close(); }
});

test("unrelated renders never re-upload unchanged map geometry", () => {
  const calls: string[] = [];
  const map = { getSource: (id: string) => ({ setData: () => { calls.push(id); } }) };
  const roads = { type: "FeatureCollection", features: [{ properties: { edge_id: "a" } }] };
  const buildings = { type: "FeatureCollection", features: [] };
  const previous = new Map<string, unknown>();
  updateMapSources(map, { roads, buildings }, previous);
  assert.deepEqual(calls, ["roads", "buildings"]);
  updateMapSources(map, { roads: { ...roads }, buildings: { ...buildings } }, previous);
  assert.equal(calls.length, 2);
  updateMapSources(map, { roads: { ...roads, features: [] }, buildings }, previous);
  assert.deepEqual(calls, ["roads", "buildings", "roads"]);
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
