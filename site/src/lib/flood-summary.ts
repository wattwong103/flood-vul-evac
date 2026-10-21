/**
 * Readings for the flood screen (BKK-055c): how big, how deep, can people move.
 *
 * They turn `/v1/runs/{id}/flood-summary` into the words on the tiles. A null
 * from the API is never rendered as 0: it becomes "not available" with the
 * API's own reason beside it.
 */

import type { FloodSummary, ModeMovement, ModeStopArea } from "./api.ts";
import { formatNumber, formatShare, NOT_AVAILABLE } from "./format.ts";

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

export type RulerMark = { depthM: number; label: string };

/** Reader-facing names for the two PFLOW modes the summary reports. */
const MODE_LABELS: Record<string, string> = { walk: "Walking", car: "Car / motorcycle" };
const MODE_STOP_LABELS: Record<string, string> = {
  walk: "Walkers stop",
  car: "Cars and motorcycles stop",
};

const twoDecimals = (value: number) => value.toFixed(2);

export function howBigReading(summary: FloodSummary): Reading {
  const { flooded_area_km2: area, share_of_aoi: share, aoi_area_km2: aoi, reason } =
    summary.how_big;
  const threshold = `${twoDecimals(summary.flood_area_threshold_m)} m`;
  if (area === null) {
    return { value: NOT_AVAILABLE, unit: null, detail: `Area under ${threshold} of water or more`, reason };
  }
  let detail: string;
  if (share !== null && aoi !== null) {
    detail = `${formatShare(share)} of the district (${formatNumber(aoi)} km²) is under ${threshold} of water or more`;
  } else if (aoi !== null) {
    detail = `Area under ${threshold} of water or more; share of the district withheld`;
  } else {
    detail = `Area under ${threshold} of water or more; the district's area is not recorded`;
  }
  return { value: formatNumber(area), unit: "km²", detail, reason };
}

function stopPhrase(stop: ModeStopArea | undefined, name: string, lead: string): string {
  const who = name === "car" ? "cars and motorcycles" : "walkers";
  if (!stop || stop.closed_depth_m === null) return `${who}: closing depth unknown`;
  if (stop.area_km2 === null) return `${who}: area unknown`;
  return `${lead} ${twoDecimals(stop.area_km2)} km² (${twoDecimals(stop.closed_depth_m)} m or deeper)`;
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
    }));
  if (summary.how_deep.max_depth_m !== null) {
    marks.push({ depthM: summary.how_deep.max_depth_m, label: "Deepest water now" });
  }
  return marks.sort((a, b) => a.depthM - b.depthM);
}
