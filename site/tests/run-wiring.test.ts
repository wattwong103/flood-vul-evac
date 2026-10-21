/**
 * Render-level checks that the run provider and the header use the BKK-016a
 * run helpers; tests/client.test.ts proves only that the helpers are right.
 *
 * The provider picks its run in an effect once `/v1/runs` resolves, and a
 * static render never runs effects, so the real components are mounted in a
 * happy-dom window. `node --test` runs each file in its own process, so these
 * DOM globals never reach the other test file.
 */

import assert from "node:assert/strict";
import { after, afterEach, before, test } from "node:test";
import { Window } from "happy-dom";

const win = new Window({ url: "http://localhost:5173/" });
// React DOM decides whether it runs in a browser when it is first imported,
// so these globals must exist before react-dom/client is loaded below.
Object.assign(globalThis, {
  window: win,
  document: win.document,
  IS_REACT_ACT_ENVIRONMENT: true,
});

const { createElement, act } = await import("react");
const { createRoot } = await import("react-dom/client");

// Newest first, as the API lists them: the newest run is a sensitivity case.
const caseRun = {
  run_id: "4fa6ff39-1c2d-4e5f-8a9b-0c1d2e3f4a5b",
  created_at: "2026-06-01T00:00:00+00:00",
  status: "completed",
  validation_status: "research",
  active_scenario: { state: "moderate", case_id: "delay-mean-1800" },
};
const ordinaryRun = {
  run_id: "d3dd91f1-6a7b-4c8d-9e0f-1a2b3c4d5e6f",
  created_at: "2026-01-01T00:00:00+00:00",
  status: "completed",
  validation_status: "demonstration",
  active_scenario: { state: "dry", case_id: null },
};

let server: { ssrLoadModule: (url: string) => Promise<Record<string, any>>; close: () => Promise<void> };
let RunProvider: any;
let ApiStatus: any;
let apiBaseUrl = "";

before(async () => {
  const { createServer } = await import("vite");
  // No websocket: client.test.ts runs in parallel and binds the default port.
  server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: "custom" });
  ({ RunProvider, API_BASE_URL: apiBaseUrl } = await server.ssrLoadModule("/src/lib/run-context.tsx"));
  // The component alone, not App.tsx, which would pull every screen and maplibre into happy-dom.
  ({ ApiStatus } = await server.ssrLoadModule("/src/components/ApiStatus.tsx"));
});

after(async () => {
  try {
    await server?.close();
  } finally {
    await win.happyDOM.close();
  }
});

const originalFetch = globalThis.fetch;
let unmount: (() => Promise<void>) | null = null;

afterEach(async () => {
  // A failed unmount must not leak the stubbed fetch or a stored run into the next test.
  try {
    await unmount?.();
  } finally {
    unmount = null;
    globalThis.fetch = originalFetch;
    win.localStorage.clear();
  }
});

/** Serve the run list; every other path is a 404, as for a run with no stats yet. */
function stubApi(runs: unknown[]): string[] {
  const requested: string[] = [];
  globalThis.fetch = (async (input: string | URL | Request) => {
    // Relative to the configured base, so a local VITE_API_BASE_URL cannot break the match.
    const url = String(input);
    const path = url.startsWith(apiBaseUrl) ? url.slice(apiBaseUrl.length) : url;
    requested.push(path);
    if (path === "/v1/runs") return Response.json({ runs });
    return Response.json({ detail: "not found" }, { status: 404 });
  }) as typeof fetch;
  return requested;
}

/** Mount the header status inside the real provider; resolve with its text once a run is active. */
async function mountHeader(): Promise<string> {
  const container = win.document.createElement("div");
  win.document.body.appendChild(container);
  const root = createRoot(container as unknown as Element);
  unmount = async () => {
    await act(async () => root.unmount());
    container.remove();
  };
  await act(async () => {
    root.render(createElement(RunProvider, null, createElement(ApiStatus)));
  });
  const text = () => container.querySelector(".api-status")?.textContent ?? "";
  for (let tick = 0; tick < 100 && !/run [0-9a-f]{8}/.test(text()); tick += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
  return text();
}

test("the provider opens on the newest ordinary run, not a newer sensitivity case", async () => {
  const requested = stubApi([caseRun, ordinaryRun]);

  const header = await mountHeader();

  assert.match(header, /run d3dd91f1 · demonstration/);
  assert.doesNotMatch(header, /sensitivity case/);
  assert.ok(requested.includes(`/v1/runs/${ordinaryRun.run_id}/stats`), requested.join(", "));
  assert.ok(!requested.some((path) => path.includes(caseRun.run_id)), requested.join(", "));
});

test("the header names the sensitivity case when the reader chose a case run", async () => {
  win.localStorage.setItem("bkkflow.activeRunId", caseRun.run_id);
  stubApi([caseRun, ordinaryRun]);

  const header = await mountHeader();

  assert.match(header, /run 4fa6ff39 · research · sensitivity case delay-mean-1800/);
});
