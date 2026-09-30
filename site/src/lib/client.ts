/**
 * The single fetch layer for the BKK/FLOW API.
 *
 * Everything the site shows comes through `apiGet`. Failures are turned into
 * `ApiError` values that the UI renders as visible, non-fatal states — a run
 * that does not exist yet is an expected condition, not a crash.
 */

import type {
  BuildingResult,
  ConnectivityResponse,
  DestinationResult,
  DrainageCellsResult,
  DrainageResponse,
  EvacuationResult,
  Feature,
  FeatureCollection,
  HealthResponse,
  LinkResult,
  MeshResult,
  NetworkResult,
  ObservedWaterCellsResult,
  ObservedWaterResponse,
  PopulationGridResponse,
  RouteResult,
  RunDetail,
  RunStats,
  RunSummary,
  SiteConfig,
  SourceRecord,
  SourceRegistry,
  ValidationReport,
} from "./api";

export const API_BASE_URL: string = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ""
).replace(/\/+$/, "") || "http://127.0.0.1:8000";

export type ApiErrorKind =
  /** The server could not be reached at all (not started, wrong base URL, CORS). */
  | "network"
  /** HTTP 404. For runs this means "no completed run yet", not a failure. */
  | "not_found"
  /** Any other non-2xx response. */
  | "http"
  /** 2xx but the body was not JSON. */
  | "parse";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;
  readonly detail: string | null;

  constructor(
    kind: ApiErrorKind,
    status: number,
    message: string,
    detail: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }

  /** True when the request did not reach the API. */
  get isOffline(): boolean {
    return this.kind === "network";
  }
}

function describe(status: number): string {
  if (status === 404) return "The API has no record for this request.";
  if (status === 401 || status === 403) return "The API refused this request.";
  if (status >= 500) return "The API reported an internal error.";
  return `The API responded with HTTP ${status}.`;
}

function isAbort(error: unknown): boolean {
  return (
    error instanceof DOMException &&
    (error.name === "AbortError" || error.name === "TimeoutError")
  );
}

async function readDetail(response: Response): Promise<string | null> {
  try {
    const text = await response.text();
    if (!text) return null;
    try {
      const parsed: unknown = JSON.parse(text);
      if (parsed && typeof parsed === "object") {
        const record = parsed as Record<string, unknown>;
        for (const key of ["detail", "message", "error"]) {
          const value = record[key];
          if (typeof value === "string") return value;
        }
      }
      return null;
    } catch {
      return text.slice(0, 300);
    }
  } catch {
    return null;
  }
}

/**
 * One fetch helper. Every call site gets either a parsed body or an
 * `ApiError` that carries enough context to render a specific message.
 */
export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const url = `${API_BASE_URL}${path}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (isAbort(error)) throw error;
    throw new ApiError(
      "network",
      0,
      `Cannot reach the BKK/FLOW API at ${API_BASE_URL}. Start the service, or set VITE_API_BASE_URL.`,
      error instanceof Error ? error.message : null,
    );
  }

  if (!response.ok) {
    const detail = await readDetail(response);
    throw new ApiError("http", response.status, describe(response.status), detail);
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  if (!text.trim()) {
    throw new ApiError("parse", response.status, "The API returned an empty body.");
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(
      "parse",
      response.status,
      "The API returned a body that is not JSON.",
      text.slice(0, 300),
    );
  }
}

/* ------------------------------------------------------------------ *
 * Endpoints — contract section 5
 * ------------------------------------------------------------------ */

export const fetchHealth = (signal?: AbortSignal) =>
  apiGet<HealthResponse>("/v1/health", signal);

export const fetchConfig = (signal?: AbortSignal) =>
  apiGet<SiteConfig>("/v1/config", signal);

export const fetchSources = (signal?: AbortSignal) =>
  apiGet<SourceRegistry | SourceRecord[]>("/v1/sources", signal);

export const fetchRuns = (signal?: AbortSignal) =>
  apiGet<RunSummary[] | { runs?: RunSummary[] | null } | null>(
    "/v1/runs",
    signal,
  );

export const fetchRun = (runId: string, signal?: AbortSignal) =>
  apiGet<RunDetail>(`/v1/runs/${encodeURIComponent(runId)}`, signal);

export const fetchStats = (runId: string, signal?: AbortSignal) =>
  apiGet<RunStats>(`/v1/runs/${encodeURIComponent(runId)}/stats`, signal);

export const fetchMesh = (runId: string, time: number | null, signal?: AbortSignal) => {
  const query = time === null ? "" : `?time=${encodeURIComponent(String(time))}`;
  return apiGet<MeshResult>(`/v1/runs/${encodeURIComponent(runId)}/mesh${query}`, signal);
};

export const fetchLinks = (
  runId: string,
  time: number | null,
  mode: string | null,
  signal?: AbortSignal,
) => {
  const params = new URLSearchParams();
  if (time !== null) params.set("time", String(time));
  if (mode !== null) params.set("mode", mode);
  const query = params.toString();
  return apiGet<LinkResult>(
    `/v1/runs/${encodeURIComponent(runId)}/links${query ? `?${query}` : ""}`,
    signal,
  );
};

export const fetchBuildings = (runId: string, signal?: AbortSignal) =>
  apiGet<BuildingResult>(`/v1/runs/${encodeURIComponent(runId)}/buildings`, signal);

export const fetchEvacuation = (runId: string, signal?: AbortSignal) =>
  apiGet<EvacuationResult | RouteResult>(
    `/v1/runs/${encodeURIComponent(runId)}/evacuation`,
    signal,
  );

export const fetchValidation = (runId: string, signal?: AbortSignal) =>
  apiGet<ValidationReport>(`/v1/runs/${encodeURIComponent(runId)}/validation`, signal);

export const exportUrl = (runId: string) =>
  `${API_BASE_URL}/v1/runs/${encodeURIComponent(runId)}/export`;

/* ------------------------------------------------------------------ *
 * City-scale observed and asset routes
 *
 * Each route is defined once, as a path builder, and then wrapped in the
 * `fetchX = (runId, …, signal?) => apiGet<T>(…)` shape used above. Screens
 * compose the same path builders into `useApi` calls so that a route has a
 * single definition and there is still only one fetch mechanism.
 * ------------------------------------------------------------------ */

export const populationGridPath = (runId: string) =>
  `/v1/runs/${encodeURIComponent(runId)}/population-grid`;

export const observedWaterPath = (runId: string) =>
  `/v1/runs/${encodeURIComponent(runId)}/observed-water`;

export const observedWaterCellsPath = (
  runId: string,
  year: number | null = null,
  minShare: number | null = null,
) => {
  const params = new URLSearchParams();
  if (year !== null) params.set("year", String(year));
  if (minShare !== null) params.set("min_share", String(minShare));
  const query = params.toString();
  return `/v1/runs/${encodeURIComponent(runId)}/observed-water/cells${
    query ? `?${query}` : ""
  }`;
};

export const destinationsPath = (
  runId: string,
  destinationClass: string | null = null,
  limit: number | null = null,
) => {
  const params = new URLSearchParams();
  if (destinationClass !== null) params.set("destination_class", destinationClass);
  if (limit !== null) params.set("limit", String(limit));
  const query = params.toString();
  return `/v1/runs/${encodeURIComponent(runId)}/destinations${query ? `?${query}` : ""}`;
};

export const networkPath = (runId: string, limit: number | null = null) => {
  const query = limit === null ? "" : `?limit=${encodeURIComponent(String(limit))}`;
  return `/v1/runs/${encodeURIComponent(runId)}/network${query}`;
};

/**
 * `year` is optional. Without it the route serves the whole screened record,
 * which is what a year selector needs; with it the route serves that year alone
 * and substitutes nothing if the year was never screened.
 */
export const connectivityPath = (runId: string, year: number | null = null) => {
  const query = year === null ? "" : `?year=${encodeURIComponent(String(year))}`;
  return `/v1/runs/${encodeURIComponent(runId)}/connectivity${query}`;
};

export const drainagePath = (runId: string) =>
  `/v1/runs/${encodeURIComponent(runId)}/drainage`;

export const drainageCellsPath = (
  runId: string,
  band: string | null = null,
  minRisk: number | null = null,
  limit: number | null = null,
) => {
  const params = new URLSearchParams();
  if (band !== null) params.set("band", band);
  if (minRisk !== null) params.set("min_risk", String(minRisk));
  if (limit !== null) params.set("limit", String(limit));
  const query = params.toString();
  return `/v1/runs/${encodeURIComponent(runId)}/drainage/cells${query ? `?${query}` : ""}`;
};

export const fetchPopulationGrid = (runId: string, signal?: AbortSignal) =>
  apiGet<PopulationGridResponse>(populationGridPath(runId), signal);

export const fetchObservedWater = (runId: string, signal?: AbortSignal) =>
  apiGet<ObservedWaterResponse>(observedWaterPath(runId), signal);

export const fetchObservedWaterCells = (
  runId: string,
  year: number | null = null,
  minShare: number | null = null,
  signal?: AbortSignal,
) => apiGet<ObservedWaterCellsResult>(observedWaterCellsPath(runId, year, minShare), signal);

export const fetchDestinations = (
  runId: string,
  destinationClass: string | null = null,
  signal?: AbortSignal,
) => apiGet<DestinationResult>(destinationsPath(runId, destinationClass), signal);

export const fetchNetwork = (runId: string, limit: number | null = null, signal?: AbortSignal) =>
  apiGet<NetworkResult>(networkPath(runId, limit), signal);

export const fetchConnectivity = (
  runId: string,
  year: number | null = null,
  signal?: AbortSignal,
) => apiGet<ConnectivityResponse>(connectivityPath(runId, year), signal);

export const fetchDrainage = (runId: string, signal?: AbortSignal) =>
  apiGet<DrainageResponse>(drainagePath(runId), signal);

export const fetchDrainageCells = (
  runId: string,
  band: string | null = null,
  minRisk: number | null = null,
  limit: number | null = null,
  signal?: AbortSignal,
) => apiGet<DrainageCellsResult>(drainageCellsPath(runId, band, minRisk, limit), signal);

/* ------------------------------------------------------------------ *
 * Normalisers — tolerate the shapes a contract-conforming server may use
 * ------------------------------------------------------------------ */

const EMPTY_COLLECTION: FeatureCollection<never> = {
  type: "FeatureCollection",
  features: [],
};

/**
 * Accepts a GeoJSON FeatureCollection, or a bare array of features, and
 * returns a FeatureCollection. Anything else becomes an empty collection,
 * which the UI renders as an explicit "no features served" state.
 */
export function asFeatureCollection<TProps>(
  value: unknown,
): FeatureCollection<TProps> {
  if (!value) return { ...EMPTY_COLLECTION } as FeatureCollection<TProps>;
  if (Array.isArray(value)) {
    return {
      type: "FeatureCollection",
      features: value.filter(
        (item): item is Feature<TProps> =>
          !!item && typeof item === "object" && (item as Feature<TProps>).type === "Feature",
      ),
    };
  }
  if (typeof value === "object" && Array.isArray((value as FeatureCollection<TProps>).features)) {
    return {
      ...(value as FeatureCollection<TProps>),
      type: "FeatureCollection",
    };
  }
  // A single bare feature.
  if (
    typeof value === "object" &&
    (value as Feature<TProps>).type === "Feature"
  ) {
    return { type: "FeatureCollection", features: [value as Feature<TProps>] };
  }
  return { ...EMPTY_COLLECTION } as FeatureCollection<TProps>;
}

/** `/v1/sources` may be a bare array, a wrapper object, or a GeoJSON-ish list. */
export function asSourceList(value: unknown): SourceRecord[] {
  if (Array.isArray(value)) return value as SourceRecord[];
  if (value && typeof value === "object") {
    const record = value as SourceRegistry;
    if (Array.isArray(record.sources)) return record.sources;
    if (Array.isArray((record as { features?: unknown }).features)) {
      return (record as unknown as { features: Array<{ properties?: SourceRecord }> }).features
        .map((feature) => feature?.properties)
        .filter((properties): properties is SourceRecord => !!properties);
    }
  }
  return [];
}

/** `/v1/runs` may be a bare array or a wrapper object. */
export function asRunList(value: unknown): RunSummary[] {
  if (Array.isArray(value)) return value as RunSummary[];
  if (value && typeof value === "object") {
    const record = value as { runs?: RunSummary[] | null };
    if (Array.isArray(record.runs)) return record.runs;
  }
  return [];
}

/**
 * `warnings` is a list of sentences in some routes and a list of
 * `{ code, message }` records in others. Both are reduced to one readable
 * sentence each, so an empty state can always say why the layer is missing.
 */
export function asWarningList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item.trim();
      if (item && typeof item === "object") {
        const record = item as Record<string, unknown>;
        for (const key of ["message", "detail", "note"]) {
          const text = record[key];
          if (typeof text === "string" && text.trim().length > 0) return text.trim();
        }
        if (typeof record.code === "string" && record.code.trim().length > 0) {
          return record.code.trim();
        }
      }
      return "";
    })
    .filter((item) => item.length > 0);
}
