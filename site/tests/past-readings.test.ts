/**
 * Render-level checks for the Past tab's readings (BKK-055c part 2), mounted
 * in happy-dom and loaded through Vite like flood-readings.test.ts.
 */

import assert from "node:assert/strict";
import { after, afterEach, before, test } from "node:test";
import { Window } from "happy-dom";

const win = new Window({ url: "http://localhost:5173/" });
Object.assign(globalThis, { window: win, document: win.document, IS_REACT_ACT_ENVIRONMENT: true });

const { createElement, act } = await import("react");
const { createRoot } = await import("react-dom/client");

let server: { ssrLoadModule: (url: string) => Promise<Record<string, any>>; close: () => Promise<void> };
let PastReadings: any;

before(async () => {
  const { createServer } = await import("vite");
  server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: "custom" });
  ({ PastReadings } = await server.ssrLoadModule("/src/components/PastReadings.tsx"));
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

async function render(props: Record<string, unknown>): Promise<string> {
  container = win.document.createElement("div");
  win.document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(createElement(PastReadings, { status: "demonstration", label: "2011", ...props }));
  });
  return container.textContent ?? "";
}

test("a past year shows a minimum area, Unknown depth and Not yet movement", async () => {
  const text = await render({
    choice: 2011,
    year: { year: 2011, aoi_water_km2: 170.7147, aoi_water_share: 0.104212, share_status: "ok",
            aoi_seasonal_pixels: 75124, aoi_permanent_pixels: 151639 },
    ever: null,
  });

  assert.match(text, /How big/);
  assert.match(text, /≥ 170\.71/);
  assert.match(text, /How deep/);
  assert.match(text, /Unknown/);
  assert.match(text, /Can people move\?/);
  assert.match(text, /Not yet/);
  assert.doesNotMatch(text, /\b0 m\b/);
});

test("an unavailable extent shows its reason, not zero", async () => {
  const text = await render({
    choice: "ever",
    label: "1984–2021",
    year: null,
    ever: { available: false, ever_water_km2: null, reason: "the recorded extent tile is not staged" },
  });

  assert.match(text, /not available/);
  assert.match(text, /not staged/);
  assert.doesNotMatch(text, /\b0 km²/);
});
