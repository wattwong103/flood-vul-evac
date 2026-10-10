/**
 * Types for the BKK/FLOW run artefact and API contract.
 * Contract version: bkkflow-run-v0.1
 * Source of truth: docs/RUN_ARTIFACT_CONTRACT.md sections 3, 4 and 5.
 *
 * Every field that the contract does not fix is typed as nullable and/or
 * carries an index signature, because the API is developed against the same
 * contract independently of this front end. Nothing here is invented data.
 */

/* ------------------------------------------------------------------ *
 * Section 2 — validation status vocabulary
 * ------------------------------------------------------------------ */

export type ValidationStatus =
  | "demonstration"
  | "research"
  | "reviewed"
  | "operational";

export const VALIDATION_STATUSES: readonly ValidationStatus[] = [
  "demonstration",
  "research",
  "reviewed",
  "operational",
] as const;

/** Copy that is shown next to every number the site renders. */
export const VALIDATION_STATUS_NOTE: Record<ValidationStatus, string> = {
  demonstration:
    "Demonstration model. Output has not been validated against ground truth. Not for emergency or operational use.",
  research:
    "Research status. Internally checked only; no independent or local validation has been performed.",
  reviewed:
    "Reviewed status. Independent review completed, but operational deployment is a separate approval.",
  operational:
    "Operational status. Operating procedures, data latency and institutional ownership have been signed off.",
};

export function isValidationStatus(value: unknown): value is ValidationStatus {
  return (
    typeof value === "string" &&
    (VALIDATION_STATUSES as readonly string[]).includes(value)
  );
}

/* ------------------------------------------------------------------ *
 * Shared enums
 * ------------------------------------------------------------------ */

export type FloodSourceRole = "observed" | "modelled" | "scenario";

export const FLOOD_SOURCE_ROLES: readonly FloodSourceRole[] = [
  "observed",
  "modelled",
  "scenario",
] as const;

export function isFloodSourceRole(value: unknown): value is FloodSourceRole {
  return (
    typeof value === "string" &&
    (FLOOD_SOURCE_ROLES as readonly string[]).includes(value)
  );
}

export type TimeProfile = "day" | "evening" | "night";

export const TIME_PROFILES: readonly TimeProfile[] = [
  "day",
  "evening",
  "night",
] as const;

export function isTimeProfile(value: unknown): value is TimeProfile {
  return (
    typeof value === "string" && (TIME_PROFILES as readonly string[]).includes(value)
  );
}

export type SourceStatus = "approved" | "verify" | "rejected";

export const SOURCE_STATUSES: readonly SourceStatus[] = [
  "approved",
  "verify",
  "rejected",
] as const;

export function isSourceStatus(value: unknown): value is SourceStatus {
  return (
    typeof value === "string" &&
    (SOURCE_STATUSES as readonly string[]).includes(value)
  );
}

/** Registry states carry a non-colour glyph and a sentence, never colour alone. */
export const SOURCE_STATUS_COPY: Record<
  SourceStatus,
  { label: string; glyph: string; sentence: string }
> = {
  approved: {
    label: "Approved",
    glyph: "✓",
    sentence: "Accessible to anyone and explicitly reusable.",
  },
  verify: {
    label: "Verify",
    glyph: "?",
    sentence:
      "Public, but the licence or access terms are not sufficiently clear. Not ingested.",
  },
  rejected: {
    label: "Rejected",
    glyph: "✕",
    sentence: "Proprietary, scraped, partner-only, or otherwise restricted.",
  },
};

export type StageStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped"
  | "partial"
  | string;

/* ------------------------------------------------------------------ *
 * Section 4 — the statistics payload (stats.json, GET /v1/runs/{id}/stats)
 * ------------------------------------------------------------------ */

export type Geography = {
  aoi_id?: string | null;
  name?: string | null;
  area_km2?: number | null;
  analysis_crs?: string | null;
};

export type PopulationStats = {
  residents_weighted?: number | null;
  people_present?: number | null;
  people_exposed?: number | null;
  exposed_share_of_present?: number | null;
  population_version?: string | null;
  time_profile?: string | null;
};

export type FloodModelRef = {
  name?: string | null;
  version?: string | null;
};

/**
 * `flood` has two published shapes. A pilot run carries a numeric depth and a
 * `status` / `reason` pair; a city run does not compute a depth at all, so
 * `max_depth_m` and `edges_closed` are `null` and the state of the computation
 * is reported as `depth_status` / `depth_reason`. Both keys are typed, and the
 * `floodStatus` / `floodReason` resolvers below read either shape.
 */
export type FloodStats = {
  max_depth_m?: number | null;
  flooded_area_km2?: number | null;
  edges_closed?: number | null;
  edges_total?: number | null;
  road_capacity_loss_share?: number | null;
  source_role?: string | null;
  model?: FloodModelRef | null;
  /** City runs: whether a depth was computed, and why not when it was not. */
  depth_status?: string | null;
  depth_reason?: string | null;
  /** City runs name the role of the depth separately from the extent layer. */
  depth_source_role?: string | null;
  /** Pilot runs: the same information under its earlier key. */
  status?: string | null;
  reason?: string | null;
};

/** First non-empty string, so a missing key falls through to the next. */
function firstString(
  ...values: Array<string | null | undefined>
): string | null {
  for (const value of values) {
    if (typeof value !== "string") continue;
    const trimmed = value.trim();
    if (trimmed.length > 0) return trimmed;
  }
  return null;
}

/** Null-safe read of the flood computation state across both run shapes. */
export function floodStatus(flood: FloodStats | null | undefined): string | null {
  return firstString(flood?.depth_status, flood?.status);
}

/** Null-safe read of the flood "not computed" reason across both run shapes. */
export function floodReason(flood: FloodStats | null | undefined): string | null {
  return firstString(flood?.depth_reason, flood?.reason);
}

export type ClearanceTimeMinutes = {
  p5?: number | null;
  median?: number | null;
  p95?: number | null;
};

/**
 * `top_bottleneck_edges` is declared as an empty array in the contract and its
 * item shape is not fixed, so items are read defensively by the UI.
 */
export type BottleneckEdge = {
  edge_id?: string | null;
  label?: string | null;
  [key: string]: unknown;
};

export type EvacuationStats = {
  cohort_weighted?: number | null;
  arrived_weighted?: number | null;
  unserved_weighted?: number | null;
  clearance_time_minutes?: ClearanceTimeMinutes | null;
  top_bottleneck_edges?: BottleneckEdge[] | null;
  /** Pilot runs published a run-level reason here; city runs do not. */
  reason?: string | null;
};

/** Null-safe read of the evacuation reason; absent means none was published. */
export function evacuationReason(
  evacuation: EvacuationStats | null | undefined,
): string | null {
  return firstString(evacuation?.reason);
}

export type StageRecord = {
  stage?: string | null;
  status?: StageStatus | null;
  seconds?: number | null;
  rows?: number | null;
  [key: string]: unknown;
};

export type StatsSourceRef = {
  source_id?: string | null;
  licence?: string | null;
  status?: string | null;
  [key: string]: unknown;
};

export type RunStats = {
  run_id?: string | null;
  scale?: string | null;
  validation_status?: string | null;
  created_at?: string | null;
  geography?: Geography | null;
  population?: PopulationStats | null;
  flood?: FloodStats | null;
  evacuation?: EvacuationStats | null;
  stages?: StageRecord[] | null;
  warnings?: unknown[] | null;
  sources?: StatsSourceRef[] | null;
  denominators?: Record<string, unknown> | null;
  [key: string]: unknown;
};

/* ------------------------------------------------------------------ *
 * Section 5 — other endpoints
 * ------------------------------------------------------------------ */

export type HealthResponse = {
  status?: string | null;
  version?: string | null;
  contract_version?: string | null;
  [key: string]: unknown;
};

export type RunSummary = {
  run_id: string;
  created_at?: string | null;
  validation_status?: string | null;
  stage?: string | null;
  status?: StageStatus | null;
  progress?: number | null;
  [key: string]: unknown;
};

export type RunManifest = {
  run_id?: string | null;
  created_at?: string | null;
  area_of_interest?: unknown;
  source_versions?: unknown[] | null;
  licence_registry_version?: string | null;
  flood_model?: Record<string, unknown> | null;
  network_version?: string | null;
  evacuation_model?: Record<string, unknown> | null;
  outputs?: unknown[] | null;
  warnings?: unknown[] | null;
  validation_status?: string | null;
  [key: string]: unknown;
};

/** `GET /v1/runs/{id}` — stage, progress, warnings, manifest. */
export type RunDetail = {
  run_id?: string | null;
  created_at?: string | null;
  validation_status?: string | null;
  stage?: string | null;
  status?: StageStatus | null;
  progress?: number | null;
  warnings?: unknown[] | null;
  manifest?: RunManifest | null;
  stages?: StageRecord[] | null;
  [key: string]: unknown;
};

/**
 * `GET /v1/sources` — the registry. The required field list is fixed by
 * PROJECT_PLAN.md section 3; all of them are optional here because a registry
 * row is only allowed into the pipeline once every gate has passed.
 */
export type SourceRecord = {
  source_id?: string | null;
  agency?: string | null;
  dataset?: string | null;
  resource_url?: string | null;
  format?: string | null;
  spatial_resolution?: string | null;
  temporal_resolution?: string | null;
  live_or_historical?: string | null;
  authentication?: string | null;
  licence?: string | null;
  licence_url?: string | null;
  attribution?: string | null;
  rate_limit?: string | null;
  archive_available?: string | boolean | null;
  status?: string | null;
  reviewed_at?: string | null;
  reviewer?: string | null;
  notes?: string | null;
  /** Model role. Named `role` / `model_role` / `use` by differing registries. */
  role?: string | null;
  model_role?: string | null;
  use?: string | null;
  [key: string]: unknown;
};

export type SourceRegistry = {
  sources?: SourceRecord[] | null;
  registry_version?: string | null;
  [key: string]: unknown;
};

export type SiteConfig = {
  aoi_id?: string | null;
  aoi_name?: string | null;
  name?: string | null;
  area_km2?: number | null;
  crs?: string | null;
  analysis_crs?: string | null;
  contract_version?: string | null;
  scenario_status?: string | null;
  declared_scenario_status?: string | null;
  [key: string]: unknown;
};

export type ValidationCheck = {
  check?: string | null;
  name?: string | null;
  metric?: string | null;
  threshold?: number | string | null;
  result?: number | string | null;
  passed?: boolean | null;
  status?: string | null;
  severity?: string | null;
  notes?: string | null;
  [key: string]: unknown;
};

export type ValidationReport = {
  run_id?: string | null;
  validation_status?: string | null;
  checks?: ValidationCheck[] | null;
  [key: string]: unknown;
};

/* ------------------------------------------------------------------ *
 * GeoJSON transport shapes
 * ------------------------------------------------------------------ */

export type Geometry =
  | { type: "Point"; coordinates: [number, number] }
  | { type: "MultiPoint"; coordinates: [number, number][] }
  | { type: "LineString"; coordinates: [number, number][] }
  | { type: "MultiLineString"; coordinates: [number, number][][] }
  | { type: "Polygon"; coordinates: [number, number][][] }
  | { type: "MultiPolygon"; coordinates: [number, number][][][] }
  | { type: string; coordinates?: unknown };

export type Feature<TProps> = {
  type: "Feature";
  id?: string | number | null;
  geometry?: Geometry | null;
  properties?: TProps | null;
  [key: string]: unknown;
};

export type FeatureCollection<TProps> = {
  type: "FeatureCollection";
  features: Array<Feature<TProps>>;
  [key: string]: unknown;
};

export type StudyAreaProperties = {
  scope?: "study_area" | null;
  area_name?: string | null;
  area_km2?: number | null;
  geometry_source?: string | null;
  attribution?: string | null;
  [key: string]: unknown;
};

export type StudyAreaResponse = FeatureCollection<StudyAreaProperties> & {
  area_id?: string | null;
  area_name?: string | null;
  area_km2?: number | null;
  bbox_wgs84?: [number, number, number, number] | null;
  coverage?: string | null;
  warnings?: unknown[] | null;
};

/** `mesh_volume.parquet` — `run_id, gcode, mesh_size_m, time_s, stationary_pop, travelling_pop, total_pop` */
export type MeshProperties = {
  cell_id?: string | null;
  gcode?: string | null;
  mesh_size_m?: number | null;
  time_s?: number | null;
  hour?: number | null;
  stationary_pop?: number | null;
  travelling_pop?: number | null;
  /** Population present at this cell and model time. */
  total_pop?: number | null;
  /** Optional: the exposed subset, which is a different quantity. */
  exposed_pop?: number | null;
  /** Prevents resident baselines and PFLOW people-present estimates being conflated. */
  population_quantity?: "people_present" | "resident_baseline" | string | null;
  source_role?: string | null;
  [key: string]: unknown;
};

/** One positive-depth cell from `flood_slices.parquet`. */
export type FloodProperties = {
  cell_id?: string | null;
  time_s?: number | null;
  depth_m?: number | null;
  peak_depth_m?: number | null;
  distance_to_water_m?: number | null;
  source_role?: string | null;
  confidence?: string | number | null;
  [key: string]: unknown;
};

/** `edge_states.parquet` + `link_volume.parquet` */
export type LinkProperties = {
  edge_id?: string | null;
  u?: string | number | null;
  v?: string | number | null;
  highway?: string | null;
  time_s?: number | null;
  hour?: number | null;
  mode?: string | number | null;
  volume?: number | null;
  distance_m?: number | null;
  depth_m?: number | null;
  speed_multiplier?: number | null;
  capacity_multiplier?: number | null;
  closed?: boolean | null;
  threshold_set_version?: string | null;
  reason_code?: string | null;
  [key: string]: unknown;
};

/** Aggregated building exposure. `refuge_verified` is the safety gate. */
export type BuildingProperties = {
  building_id?: string | null;
  height_m?: number | null;
  height_source?: string | null;
  height_confidence?: number | null;
  max_depth_m?: number | null;
  exposed?: boolean | null;
  exposed_pop?: number | null;
  ground_floor_dry?: boolean | null;
  refuge_id?: string | null;
  refuge_name?: string | null;
  refuge_status?: string | null;
  /** False means "not verified" — never render as a safe shelter. */
  refuge_verified?: boolean | null;
  refuge_capacity?: number | null;
  refuge_accessible?: boolean | null;
  refuge_operator?: string | null;
  [key: string]: unknown;
};

/** `evacuation_states.parquet` aggregates. */
export type EvacuationProperties = {
  edge_id?: string | null;
  traversal_weight?: number | null;
  route_quantity?: "aggregate_evacuation_bottleneck" | string | null;
  state?: string | null;
  reason?: string | null;
  dest_id?: string | null;
  event_time_s?: number | null;
  weight?: number | null;
  [key: string]: unknown;
};

export type EvacuationResult = {
  run_id?: string | null;
  validation_status?: string | null;
  clearance_time_minutes?: ClearanceTimeMinutes | null;
  states?: Array<Record<string, unknown>> | null;
  destination_overflow?: Array<Record<string, unknown>> | null;
  cohort_weighted?: number | null;
  arrived_weighted?: number | null;
  unserved_weighted?: number | null;
  top_bottleneck_edges?: BottleneckEdge[] | null;
  denominators?: Record<string, unknown> | null;
  [key: string]: unknown;
};

export type MeshResult = FeatureCollection<MeshProperties> & {
  run_id?: string | null;
  time_s?: number | null;
  time_defaulted?: boolean | null;
  available_times?: number[] | null;
  matched_rows?: number | null;
  returned?: number | null;
  truncated?: boolean | null;
  limit?: number | null;
  warnings?: unknown[] | null;
};
export type FloodResult = FeatureCollection<FloodProperties> & {
  run_id?: string | null;
  available?: boolean | null;
  time_s?: number | null;
  time_defaulted?: boolean | null;
  available_times?: number[] | null;
  peak_time_s?: number | null;
  matched_rows?: number | null;
  returned?: number | null;
  truncated?: boolean | null;
  limit?: number | null;
  sample_is_spatial_subset?: boolean | null;
  warnings?: unknown[] | null;
};
export type LinkResult = FeatureCollection<LinkProperties> | null;
export type BuildingResult = FeatureCollection<BuildingProperties> | null;
export type RouteResult = FeatureCollection<EvacuationProperties> | null;

/* ------------------------------------------------------------------ *
 * City-scale observed and asset layers
 *
 * These five routes exist only for a `scale: "city"` run. A pilot run answers
 * with `available: false` and a `warnings` array, which is an absence, not a
 * zero: the screen must say what is missing and render no number at all.
 * ------------------------------------------------------------------ */

/** `GET /v1/runs/{id}/population-grid` — one row per 1 km cell. */
export type PopulationGridRow = {
  cell_id?: string | null;
  /** Grid indices, as served when the cell is identified by origin rather than id. */
  gx?: number | null;
  gy?: number | null;
  /** Cell centroid in the analysis CRS (`x` easting, `y` northing). */
  x?: number | null;
  y?: number | null;
  lon?: number | null;
  lat?: number | null;
  /** The API's own WGS84 point, as `POINT (lon lat)`. */
  geometry_wkt?: string | null;
  /** Weighted residents in the cell. The field is `pop`, not `total_pop`. */
  pop?: number | null;
  [key: string]: unknown;
};

export type PopulationGridResponse = {
  type?: "FeatureCollection";
  features?: Array<Feature<MeshProperties>> | null;
  run_id?: string | null;
  available?: boolean | null;
  grid_size_m?: number | null;
  /** Names the quantity, e.g. "resident_baseline". */
  quantity?: string | null;
  quantity_note?: string | null;
  columns?: string[] | null;
  matched_rows?: number | null;
  returned?: number | null;
  truncated?: boolean | null;
  limit?: number | null;
  rows?: PopulationGridRow[] | null;
  warnings?: string[] | null;
  [key: string]: unknown;
};

/** One classified year of the JRC annual surface-water record. */
export type ObservedWaterYear = {
  year?: number | null;
  /**
   * The API names the annual aggregates with an `aoi_` prefix; the shorter
   * names are kept because the contract text uses them. Read both, in that
   * order, rather than assuming either one.
   */
  aoi_water_km2?: number | null;
  water_km2?: number | null;
  /** Water extent as a share of the area classified in that year, 0..1. */
  aoi_water_share?: number | null;
  water_share?: number | null;
  aoi_area_km2?: number | null;
  classified_km2?: number | null;
  excess_km2_vs_baseline?: number | null;
  baseline_year?: number | null;
  [key: string]: unknown;
};

/** `GET /v1/runs/{id}/observed-water` — the annual record and its framing. */
export type ObservedWaterResponse = {
  run_id?: string | null;
  available?: boolean | null;
  status?: string | null;
  is_observation?: boolean | null;
  source_id?: string | null;
  licence?: string | null;
  product?: string | null;
  /** What the layer does and does not measure. Quoted, not paraphrased. */
  measures?: string | null;
  baseline_year?: number | null;
  years?: ObservedWaterYear[] | null;
  /** Years the record cannot speak for, e.g. a flood year with no usable pass. */
  unavailable_years?: Array<number | string> | null;
  interpretation_notes?: string[] | null;
  note?: string | null;
  warnings?: string[] | null;
  [key: string]: unknown;
};

/** `observed-water/cells` feature properties. Extent per cell, never depth. */
export type ObservedWaterCellProperties = {
  cell_id?: string | null;
  year?: number | null;
  water_share?: number | null;
  water_km2?: number | null;
  source_role?: string | null;
  measures?: string | null;
  [key: string]: unknown;
};

/** `GET /v1/runs/{id}/observed-water/cells?year=&min_share=` */
export type ObservedWaterCellsResult = FeatureCollection<ObservedWaterCellProperties> & {
  available?: boolean | null;
  grid_size_m?: number | null;
  is_observation?: boolean | null;
  measures?: string | null;
  available_years?: number[] | null;
  year?: number | null;
  min_share?: number | null;
  matched_rows?: number | null;
  returned?: number | null;
  truncated?: boolean | null;
  warnings?: string[] | null;
};

/** One destination candidate record. A candidate is never a refuge. */
export type DestinationRow = {
  destination_id?: string | null;
  /** The source key, as served when no run-scoped id is present. */
  osm_id?: string | number | null;
  name?: string | null;
  amenity?: string | null;
  destination_class?: string | null;
  verified?: boolean | null;
  status?: string | null;
  capacity?: number | null;
  operator?: string | null;
  accessible?: boolean | null;
  lon?: number | null;
  lat?: number | null;
  [key: string]: unknown;
};

/** Display order for the classes the API reports; extra keys are appended. */
export const DESTINATION_CLASSES: readonly string[] = [
  "shelter_candidate",
  "community_facility",
  "education",
  "health_care",
  "commerce",
  "emergency_service",
] as const;

/** `GET /v1/runs/{id}/destinations?limit=&destination_class=` */
export type DestinationResult = {
  run_id?: string | null;
  available?: boolean | null;
  matched_rows?: number | null;
  returned?: number | null;
  truncated?: boolean | null;
  verified_count?: number | null;
  /** The API's own statement that no record may be presented as a refuge. */
  verified_note?: string | null;
  by_class?: Record<string, number> | null;
  rows?: DestinationRow[] | null;
  warnings?: string[] | null;
  [key: string]: unknown;
};

/** `network_edges.parquet` properties as the network route serves them. */
export type NetworkProperties = {
  edge_id?: string | null;
  length_m?: number | null;
  highway?: string | null;
  walk_allowed?: boolean | null;
  vehicle_allowed?: boolean | null;
  [key: string]: unknown;
};

export type NetworkSummary = {
  edges?: number | null;
  nodes?: number | null;
  total_length_km?: number | null;
  walk_length_km?: number | null;
  vehicle_length_km?: number | null;
  source_ways?: number | null;
  [key: string]: unknown;
};

/** `GET /v1/runs/{id}/network?limit=` — a spatial sample, never the whole graph. */
export type NetworkResult = {
  run_id?: string | null;
  available?: boolean | null;
  summary?: NetworkSummary | null;
  matched_rows?: number | null;
  returned?: number | null;
  /** True when the returned features are a subset in space, not in rank. */
  sample_is_spatial_subset?: boolean | null;
  features?: Array<Feature<NetworkProperties>> | null;
  warnings?: string[] | null;
  [key: string]: unknown;
};

/* ------------------------------------------------------------------ *
 * City-scale screening layers
 *
 * Two artefacts sit on top of the observed layer. Neither is a simulation
 * and neither is a measurement of water: a connectivity screen asks where a
 * yearly water classification breaks the graph, and the drainage index asks
 * where mapped drainage infrastructure is thin. Both carry the flags that
 * stop a client reading them as more than they are, and the flags are part
 * of the payload rather than of the prose around it.
 * ------------------------------------------------------------------ */

/**
 * Connectivity screening reports a `p50`, not the `median` the evacuation
 * payload uses. Both spellings are accepted so a field is never read as
 * absent when the API has actually served it.
 */
export type ConnectivityClearanceMinutes = {
  p5?: number | null;
  p50?: number | null;
  median?: number | null;
  p95?: number | null;
  [key: string]: number | null | undefined;
};

/** One classified year of connectivity screening. */
export type ConnectivityYear = {
  year?: number | null;
  source_role?: string | null;
  hazard_role?: string | null;
  is_evacuation_simulation?: boolean | null;
  /** The artefact's own severity framing. Quoted, never paraphrased. */
  severity_note?: string | null;
  water_cells?: number | null;
  closed_edges?: number | null;
  total_edges?: number | null;
  /** Share of edges treated as impassable. Not a depth-derived closure rate. */
  closed_edge_share?: number | null;
  exposed_cells?: number | null;
  exposed_population?: number | null;
  reachable_population?: number | null;
  unreachable_population?: number | null;
  reachable_share_of_exposed?: number | null;
  no_network_access_cells?: number | null;
  clearance_minutes?: ConnectivityClearanceMinutes | null;
  threshold_minutes_reached?: Record<string, number | null> | null;
  /** A scenario choice, not a property of the city. See `destination_note`. */
  designated_destinations?: number | null;
  elapsed_seconds?: number | null;
  warnings?: string[] | null;
  [key: string]: unknown;
};

/**
 * Used only when the API has not published `destination_note`. The destination
 * count is a scenario choice, not a property of the city, and a client that
 * receives the layer must still be made to say so.
 */
export const CONNECTIVITY_DESTINATION_FALLBACK =
  "The destination count is a scenario choice, not a property of the city: " +
  "these are unverified OSM tags with no capacity, operator or inspection date, " +
  "so 'reachable' means reachable to a tagged place, not to usable shelter.";

/** `GET /v1/runs/{id}/connectivity?year=` */
export type ConnectivityResponse = {
  run_id?: string | null;
  available?: boolean | null;
  /** Always false. This is a screening index, not an evacuation simulation. */
  is_evacuation_simulation?: boolean | null;
  is_simulation?: boolean | null;
  source_role?: string | null;
  /** The role of the hazard input, which is observed even though the output
   *  is a screening index. Distinct from `source_role`. */
  hazard_role?: string | null;
  measures?: string | null;
  /** Verbatim from the artefact. Required reading, not a footnote. */
  severity_note?: string | null;
  /** Why the destination count must not be read as a city property. */
  destination_note?: string | null;
  /** The year this request asked for, or null for the whole record. */
  year?: number | null;
  available_years?: number[] | null;
  years?: ConnectivityYear[] | null;
  warnings?: string[] | null;
  [key: string]: unknown;
};

/** One declared band of the screening scale, as the artefact publishes it. */
export type DrainageBand = {
  band?: string | null;
  min?: number | null;
  max?: number | null;
  [key: string]: unknown;
};

/** Display order for the declared bands; extra keys are appended. */
export const DRAINAGE_BANDS: readonly string[] = [
  "low",
  "moderate",
  "high",
  "very_high",
] as const;

/** The observed distribution of `risk_index` over the AOI. */
export type DrainageSummary = {
  rows?: number | null;
  rows_scored?: number | null;
  risk_index?: {
    min?: number | null;
    median?: number | null;
    mean?: number | null;
    max?: number | null;
  } | null;
  bands?: Record<string, number> | null;
  band_shares?: Record<string, number> | null;
  /** The artefact's own statement of what a band is not. */
  bands_note?: string | null;
  [key: string]: unknown;
};

/** `GET /v1/runs/{id}/drainage` — the index and its stated limitations. */
export type DrainageResponse = {
  run_id?: string | null;
  available?: boolean | null;
  index_version?: string | null;
  status?: string | null;
  source_role?: string | null;
  measures?: string | null;
  is_simulation?: boolean | null;
  is_observation?: boolean | null;
  /** Always false. The index is a susceptibility score, not metres of water. */
  is_flood_depth?: boolean | null;
  grid_size_m?: number | null;
  distance_cutoff_m?: number | null;
  /** The declared ordering of the components. Not a fitted result. */
  component_weights?: Record<string, number> | null;
  bands?: DrainageBand[] | null;
  rows?: number | null;
  inputs?: Record<string, unknown> | null;
  summary?: DrainageSummary | null;
  /** Served verbatim, one sentence per limitation. Never summarised. */
  limitations?: string[] | null;
  warnings?: string[] | null;
  [key: string]: unknown;
};

/** `drainage/cells` feature properties. A susceptibility score, not a depth. */
export type DrainageCellProperties = {
  cell_id?: string | null;
  gx?: number | null;
  gy?: number | null;
  lon?: number | null;
  lat?: number | null;
  drainage_m?: number | null;
  drainage_km_per_km2?: number | null;
  distance_to_drainage_m?: number | null;
  in_overflow_path?: boolean | null;
  basin_id?: string | null;
  susceptible_village?: boolean | null;
  /** The weighted components, served so the score can be checked. */
  index_components?: Record<string, number> | null;
  risk_index?: number | null;
  risk_band?: string | null;
  index_inputs_complete?: boolean | null;
  source_role?: string | null;
  /** Always false, on every feature. */
  is_flood_depth?: boolean | null;
  [key: string]: unknown;
};

/** `GET /v1/runs/{id}/drainage/cells?band=&min_risk=&limit=` */
export type DrainageCellsResult = FeatureCollection<DrainageCellProperties> & {
  run_id?: string | null;
  available?: boolean | null;
  source_role?: string | null;
  is_flood_depth?: boolean | null;
  measures?: string | null;
  available_bands?: string[] | null;
  band?: string | null;
  min_risk?: number | null;
  /** The order the features are served in; stated so it is not guessed at. */
  sorted_by?: string | null;
  matched_rows?: number | null;
  returned?: number | null;
  truncated?: boolean | null;
  limit?: number | null;
  warnings?: string[] | null;
};
