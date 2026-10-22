/**
 * One rule for a road's state, shared by the map's layers, the map's table and
 * the flood readings (North, 22 October 2026; design note section 10).
 *
 * A road is closed only on a stored true flag, and open or slowed only on a
 * stored false flag with a speed. Anything less is unknown, never open; this
 * mirrors the API's own classification in api/flood_summary.py.
 */

export type RoadState = "open" | "slowed" | "closed" | "unknown";

/** Any speed reduction counts as slowed. */
export const SLOWED_BELOW = 1;

export function roadState(closed: boolean | null, speed: number | null): RoadState {
  if (closed === true) return "closed";
  if (closed !== false || speed === null || !Number.isFinite(speed)) return "unknown";
  return speed < SLOWED_BELOW ? "slowed" : "open";
}

/* MapLibre filters with the same meaning, for the `links` source. */

const IS_CLOSED = [
  "any",
  ["==", ["get", "closed"], true],
  ["==", ["to-string", ["get", "closed"]], "true"],
] as unknown[];

const IS_PASSABLE = [
  "any",
  ["==", ["get", "closed"], false],
  ["==", ["to-string", ["get", "closed"]], "false"],
] as unknown[];

const HAS_SPEED = ["==", ["typeof", ["get", "speed_multiplier"]], "number"] as unknown[];
const SPEED = ["to-number", ["get", "speed_multiplier"]] as unknown[];

export const ROAD_FILTERS: Record<RoadState, unknown[]> = {
  closed: IS_CLOSED,
  slowed: ["all", IS_PASSABLE, HAS_SPEED, ["<", SPEED, SLOWED_BELOW]],
  open: ["all", IS_PASSABLE, HAS_SPEED, [">=", SPEED, SLOWED_BELOW]],
  unknown: [
    "!",
    [
      "any",
      IS_CLOSED,
      ["all", IS_PASSABLE, HAS_SPEED],
    ],
  ],
};
