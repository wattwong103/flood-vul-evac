/**
 * Readings for the flood screen (BKK-055c): how big, how deep, can people move.
 *
 * They turn `/v1/runs/{id}/flood-summary` into the words on the tiles. A null
 * from the API is never rendered as 0: it becomes "not available" with the
 * API's own reason beside it.
 */

import type { FloodSummary, ModeMovement, ModeStopArea } from "./api.ts";
import { formatModelClock, formatNumber, formatShare, NOT_AVAILABLE } from "./format.ts";

export type Reading = {
  value: string;
  unit: string | null;
  detail: string;
  /** Why the value is missing, or the caveat a zero carries (a dry scenario). */
  reason: string | null;
};

export type MovementRow = {
  mode: number;
  label: string;
  open: number | null;
  slowed: number | null;
  closed: number | null;
  unknown: number | null;
  totalKm: number | null;
  reason: string | null;
};

export type RulerMark = { depthM: number; label: string; deepest: boolean };

/** Reader-facing names for the two PFLOW modes the summary reports. */
const MODE_LABELS: Record<string, string> = { walk: "Walking", car: "Car / motorcycle" };
const MODE_STOP_LABELS: Record<string, string> = {
  walk: "Walkers stop",
  car: "Cars and motorcycles stop",
};

const twoDecimals = (value: number) => value.toFixed(2);

/** A real value that would round to 0 at two decimals reads "< 0.01", never "0". */
const SMALLEST_AREA = 0.005;
const SMALLEST_SHARE = 0.0005;

function areaText(km2: number): string {
  return km2 > 0 && km2 < SMALLEST_AREA ? "< 0.01" : formatNumber(km2);
}

/** A share for a reading: "< 0.1%" for a real but tiny share, never "0.0%". */
export function formatReadingShare(share: number | null): string {
  if (share !== null && share > 0 && share < SMALLEST_SHARE) return "< 0.1%";
  return formatShare(share);
}

/**
 * The summary only if it belongs to the selected run. `useApi` keeps the last
 * answer while the next one loads, and another run's numbers must never sit
 * under this run's name.
 */
export function summaryForRun(
  summary: FloodSummary | null,
  runId: string | null,
): FloodSummary | null {
  return summary !== null && summary.run_id === runId ? summary : null;
}

/**
 * True when a map layer's response was asked for this run, time and (for
 * roads) mode. `/flood` names them at the top level and `/links` under `meta`;
 * anything else is a leftover from an earlier request and is not drawn.
 */
export function layerMatches(
  payload: unknown,
  runId: string | null,
  timeS: number | null,
  mode: string | null = null,
): boolean {
  if (payload === null || typeof payload !== "object") return false;
  const record = payload as Record<string, unknown>;
  const meta = (record.meta ?? record) as Record<string, unknown>;
  if (meta.run_id !== runId || meta.time_s !== timeS) return false;
  return mode === null || String(meta.mode) === mode;
}

/** The time the reader picked shows at once; the server's echo arrives later. */
export function displayedTime(picked: number | null, served: number | null): number | null {
  return picked ?? served;
}

/** What kind of flood this is, so a scenario is never mistaken for an observation. */
export function floodSourceNote(sourceRole: string | null): string {
  if (sourceRole === null) return "The flood source is not recorded for this run.";
  if (sourceRole.startsWith("mixed:")) {
    return `This run mixes flood sources (${sourceRole.slice(6).replaceAll(",", ", ")}); read each layer's label.`;
  }
  const notes: Record<string, string> = {
    scenario: "A what-if flood: a declared scenario, not a forecast and not an observation.",
    modelled: "A modelled flood: computed by a flood model, not an observation.",
    observed: "An observed flood extent: measured, not modelled, with no depth.",
    mapped: "A mapped past flood: an agency's flood map, not a model, with no depth.",
  };
  return notes[sourceRole] ?? `Flood source: ${sourceRole}.`;
}

export function howBigReading(summary: FloodSummary): Reading {
  const { flooded_area_km2: area, share_of_aoi: share, aoi_area_km2: aoi, reason } =
    summary.how_big;
  const threshold = `${twoDecimals(summary.flood_area_threshold_m)} m`;
  if (area === null) {
    return { value: NOT_AVAILABLE, unit: null, detail: `Area with ${threshold} of water or more`, reason };
  }
  let detail: string;
  if (share !== null && aoi !== null) {
    detail = `${formatReadingShare(share)} of the district (${formatNumber(aoi)} km²) has ${threshold} of water or more`;
  } else if (aoi !== null) {
    detail = `Area with ${threshold} of water or more; share of the district withheld (see the notes below)`;
  } else {
    detail = `Area with ${threshold} of water or more; the district's area is not recorded`;
  }
  return { value: areaText(area), unit: "km²", detail, reason };
}

function stopPhrase(stop: ModeStopArea | undefined, name: string, lead: string): string {
  const who = name === "car" ? "cars and motorcycles" : "walkers";
  if (!stop || stop.closed_depth_m === null) return `${who}: closing depth unknown`;
  if (stop.area_km2 === null) return `${who}: area unknown`;
  return `${lead} ${stop.area_km2 > 0 && stop.area_km2 < SMALLEST_AREA ? "< 0.01" : twoDecimals(stop.area_km2)} km² (${twoDecimals(stop.closed_depth_m)} m or deeper)`;
}

export function howDeepReading(summary: FloodSummary): Reading {
  const { max_depth_m: deepest, at_or_above_closing_depth: stops, reason } = summary.how_deep;
  if (deepest === null) {
    return { value: NOT_AVAILABLE, unit: null, detail: "Deepest water at this time", reason };
  }
  const byMode = new Map(stops.map((stop) => [stop.mode_name, stop]));
  const sentence = [
    stopPhrase(byMode.get("car"), "car", "cars and motorcycles stop on"),
    stopPhrase(byMode.get("walk"), "walk", "walkers on"),
  ].join("; ");
  const detail = `${sentence.charAt(0).toUpperCase()}${sentence.slice(1)}.`;
  return { value: formatNumber(deepest), unit: "m", detail, reason };
}

export function movementRows(summary: FloodSummary): MovementRow[] {
  return summary.movement.modes.map((mode: ModeMovement) => ({
    mode: mode.mode,
    label: MODE_LABELS[mode.mode_name] ?? mode.mode_name,
    open: mode.open_share,
    slowed: mode.slowed_share,
    closed: mode.closed_share,
    unknown: mode.unknown_share,
    totalKm: mode.total_km,
    reason: mode.reason,
  }));
}

export function movementReason(summary: FloodSummary): string | null {
  return summary.movement.reason;
}

/** Depths a reader can measure the flood against, shallowest first. */
export function depthRulerMarks(summary: FloodSummary): RulerMark[] {
  const marks: RulerMark[] = summary.how_deep.at_or_above_closing_depth
    .filter((stop) => stop.closed_depth_m !== null)
    .map((stop) => ({
      depthM: stop.closed_depth_m as number,
      label: MODE_STOP_LABELS[stop.mode_name] ?? `${stop.mode_name} stops`,
      deepest: false,
    }));
  if (summary.how_deep.max_depth_m !== null) {
    marks.push({
      depthM: summary.how_deep.max_depth_m,
      label: `Deepest water at ${formatModelClock(summary.time_s)}`,
      deepest: true,
    });
  }
  return marks.sort((a, b) => a.depthM - b.depthM);
}
