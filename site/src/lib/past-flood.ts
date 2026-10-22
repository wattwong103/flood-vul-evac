/**
 * Readings for the flood screen's Past tab (BKK-055c part 2): water seen by
 * satellite in a past year, and everywhere ever seen as water in 1984-2021.
 *
 * Observations record extent only. Depth is Unknown, movement waits for an
 * admitted citywide run, and a missing value reads as "not available" with
 * its reason, never as zero.
 */

import type { EverWater, ObservedWaterResponse, ObservedWaterYear, RunSummary } from "./api.ts";
import { everWaterPath, observedWaterCellsPath } from "./client.ts";
import { formatReadingShare, type Reading } from "./flood-summary.ts";
import { formatNumber, NOT_AVAILABLE } from "./format.ts";

/** The citywide area; only its runs carry the observed-water record. */
export const CITY_AOI = "bangkok-bma";
/** The 1984-2021 extent, offered beside the past years. */
export const EVER = "ever" as const;
export type PastChoice = number | typeof EVER;

/** Cells below this water share are left off the map, as on the observed screen. */
const MAP_MIN_SHARE = 0.05;

export const PAST_DEPTH: Reading = {
  value: "Unknown",
  unit: null,
  detail: "Satellites record where water was, not how deep.",
  reason: null,
};

export const PAST_MOVEMENT: Reading = {
  value: "Not yet",
  unit: null,
  detail: "Needs an admitted citywide run on current map data (BKK-040).",
  reason: null,
};

/** The newest ordinary citywide run; the run list is newest first. */
export function newestCityRun(runs: RunSummary[] | null): RunSummary | null {
  return (runs ?? []).find((run) => run.aoi_id === CITY_AOI && !run.active_scenario?.case_id) ?? null;
}

export function pastYears(observed: Pick<ObservedWaterResponse, "years"> | null): number[] {
  const years = (observed?.years ?? [])
    .map((entry) => entry.year)
    .filter((year): year is number => typeof year === "number");
  return [...new Set(years)].sort((a, b) => a - b);
}

/** A year's water as a minimum: a yearly layer misses floods shorter than its passes. */
export function yearReading(entry: ObservedWaterYear | null): Reading {
  const km2 = entry?.aoi_water_km2 ?? entry?.water_km2 ?? null;
  if (entry === null || km2 === null) {
    return {
      value: NOT_AVAILABLE,
      unit: null,
      detail: "Water seen during the year",
      reason: "This run has no water record for that year.",
    };
  }
  const parts: string[] = [];
  const seasonalPx = entry.aoi_seasonal_pixels ?? null;
  const permanentPx = entry.aoi_permanent_pixels ?? null;
  if (seasonalPx !== null && permanentPx !== null && seasonalPx + permanentPx > 0) {
    const perPixel = km2 / (seasonalPx + permanentPx);
    parts.push(
      `seasonal ${formatNumber(seasonalPx * perPixel)} km² · permanent ${formatNumber(permanentPx * perPixel)} km²; seasonal water includes paddies and ponds`,
    );
  }
  const share = entry.aoi_water_share ?? null;
  if (entry.share_status === "ok" && share !== null) {
    parts.push(`${formatReadingShare(share)} of the area with a known status`);
  }
  const detail = parts.length > 0 ? `Water seen during the year: ${parts.join("; ")}.` : "Water seen during the year.";
  return {
    value: `≥ ${formatNumber(km2)}`,
    unit: "km²",
    detail,
    reason: "A yearly layer misses short floods, so this is a minimum.",
  };
}

export function everReading(ever: Pick<EverWater, "available" | "ever_water_km2" | "reason" | "no_data_km2" | "ever_water_share_of_observed"> | null): Reading {
  const km2 = ever?.ever_water_km2 ?? null;
  if (ever === null || !ever.available || km2 === null) {
    return {
      value: NOT_AVAILABLE,
      unit: null,
      detail: "Everywhere seen as water at least once in 1984–2021",
      reason: ever?.reason ?? "The 1984–2021 extent is not available.",
    };
  }
  const share = ever.ever_water_share_of_observed ?? null;
  const shareText = share !== null ? ` (${formatReadingShare(share)} of the observed area)` : "";
  const noData = ever.no_data_km2 ?? 0;
  return {
    value: formatNumber(km2),
    unit: "km²",
    detail: `Everywhere seen as water at least once in 1984–2021${shareText}; not one flood.`,
    reason: noData > 0 ? `No data for ${formatNumber(noData)} km², which is not counted as dry.` : null,
  };
}

/** Where the map's cells come from: yearly cells, or the 1984-2021 extent. */
export function pastCellsPath(runId: string, choice: PastChoice): string {
  return choice === EVER
    ? everWaterPath(runId, MAP_MIN_SHARE)
    : observedWaterCellsPath(runId, choice, MAP_MIN_SHARE);
}
