/**
 * Render-level checks for the flood screen's three readings (BKK-055c).
 * tests/flood-summary.test.ts proves the helpers; this proves the tiles show
 * them, and that a missing value reaches the reader as its reason, not as 0.
 *
 * As in run-wiring.test.ts, the component is mounted in a happy-dom window and
 * loaded through Vite so the "@/" aliases resolve.
 */

import assert from "node:assert/strict";
import { after, afterEach, before, test } from "node:test";
import { Window } from "happy-dom";

const win = new Window({ url: "http://localhost:5173/" });
Object.assign(globalThis, {
  window: win,
  document: win.document,
  IS_REACT_ACT_ENVIRONMENT: true,
});

const { createElement, act } = await import("react");
const { createRoot } = await import("react-dom/client");

let server: { ssrLoadModule: (url: string) => Promise<Record<string, any>>; close: () => Promise<void> };
let FloodReadings: any;

before(async () => {
  const { createServer } = await import("vite");
  server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: "custom" });
  ({ FloodReadings } = await server.ssrLoadModule("/src/components/FloodReadings.tsx"));
});

after(async () => {
  await server?.close();
});

let container: any;
let root: any;

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
});

async function render(summary: unknown): Promise<string> {
  container = win.document.createElement("div");
  win.document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      createElement(FloodReadings, { summary, status: "demonstration", modelTime: "19:00" }),
    );
  });
  return container.textContent ?? "";
}

const moderate = {
  run_id: "daa9a8dc",
  validation_status: "demonstration",
  time_s: 68400,
  source_role: "scenario",
  flood_area_threshold_m: 0.15,
  how_big: { flooded_area_km2: 5.1475, share_of_aoi: 0.863573, aoi_area_km2: 5.9607, cell_size_m: 50, reason: null },
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
      { mode: 0, mode_name: "walk", closed_depth_m: 0.5, total_km: 173.167, open_km: 13.305, slowed_km: 135.008,
        closed_km: 24.854, unknown_km: 0, open_share: 0.076833, slowed_share: 0.779638, closed_share: 0.143529,
        unknown_share: 0, reason: null },
      { mode: 3, mode_name: "car", closed_depth_m: 0.3, total_km: 124.542, open_km: 0.577, slowed_km: 61.584,
        closed_km: 62.38, unknown_km: 0, open_share: 0.004633, slowed_share: 0.494484, closed_share: 0.500874,
        unknown_share: 0, reason: null },
    ],
    reason: null,
  },
  warnings: [],
};

test("the three readings show size, depth and road states", async () => {
  const text = await render(moderate);

  assert.match(text, /How big/);
  assert.match(text, /5\.15/);
  assert.match(text, /How deep/);
  assert.match(text, /0\.55/);
  assert.match(text, /Can people move\?/);
  assert.match(text, /Walking/);
  assert.match(text, /14\.4% closed/);
  assert.match(text, /Car \/ motorcycle/);
  assert.match(text, /50\.1% closed/);
});

test("a run without a flood layer shows reasons, not zeros", async () => {
  const reason = "No city-scale flood layer in this run.";
  const text = await render({
    ...moderate,
    source_role: null,
    how_big: { flooded_area_km2: null, share_of_aoi: null, aoi_area_km2: 1643.5, cell_size_m: null, reason },
    how_deep: { max_depth_m: null, at_or_above_closing_depth: [], reason },
    movement: { modes: [], reason: "this run has no road states (edge_states.parquet is absent)" },
  });

  assert.match(text, /not available/);
  assert.match(text, /No city-scale flood layer/);
  assert.match(text, /no road states/);
  assert.doesNotMatch(text, /\b0 km²/);
  assert.doesNotMatch(text, /0\.0% closed/);
});


test("a tiny closed share and the API's warnings reach the reader", async () => {
  const walk = { ...moderate.movement.modes[0], closed_share: 0.0004, closed_km: 0.07 };
  const text = await render({
    ...moderate,
    movement: { modes: [walk, moderate.movement.modes[1]], reason: null },
    warnings: [{ code: "inconsistent_aoi", message: "flooded area exceeds the AOI area; its share is withheld", artefact: null }],
  });

  assert.match(text, /< 0\.1% closed/);
  assert.doesNotMatch(text, /0\.0% closed/);
  assert.match(text, /its share is withheld/);
});
