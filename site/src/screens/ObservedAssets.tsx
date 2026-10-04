/**
 * Observed & assets — the one screen that carries an observation.
 *
 * Everything else in this prototype is a model output at a stated model time.
 * The JRC Global Surface Water annual classification is a measurement of
 * *extent*: a cell is classified as water or not, for one year, with no depth,
 * no duration and no direction. The four rules at the top of this screen are
 * not disclaimers bolted on afterwards; they are the reading instructions for
 * every figure below, including observation gaps and unverified destinations.
 *
 * A pilot run has none of the city layers. Each of the five routes then answers
 * `available: false` with a `warnings` array, and this screen says so instead of
 * drawing an empty map or a zero.
 */

import { useMemo, useState, type ReactNode } from "react";
import {
  CircleDashed,
  Droplets,
  Landmark,
  Network,
  Route,
  Satellite,
  ShieldAlert,
  TriangleAlert,
  Waves,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DEFAULT_LAYERS, EMPTY_BUNDLE, MapView, type LayerState, type MapBundle } from "@/components/MapView";
import {
  ErrorState,
  LoadingState,
  MetricCard,
  NoRunState,
  PageIntro,
  Panel,
  ValidationStamp,
} from "@/components/primitives";
import { useApi, type AsyncPhase } from "@/hooks/useApi";
import { useRuns } from "@/lib/run-context";
import {
  asFeatureCollection,
  asWarningList,
  connectivityPath,
  destinationsPath,
  drainageCellsPath,
  drainagePath,
  networkPath,
  observedWaterCellsPath,
  observedWaterPath,
  populationGridPath,
  studyAreaPath,
  type ApiError,
} from "@/lib/client";
import {
  CONNECTIVITY_DESTINATION_FALLBACK,
  DRAINAGE_BANDS,
  DESTINATION_CLASSES,
  type ConnectivityResponse,
  type ConnectivityYear,
  type DestinationResult,
  type DrainageCellProperties,
  type DrainageCellsResult,
  type DrainageResponse,
  type FeatureCollection,
  type NetworkResult,
  type ObservedWaterCellsResult,
  type ObservedWaterCellProperties,
  type ObservedWaterResponse,
  type ObservedWaterYear,
  type PopulationGridResponse,
  type StudyAreaProperties,
  type StudyAreaResponse,
} from "@/lib/api";
import {
  formatCount,
  formatNumber,
  formatPeople,
  formatShare,
  formatSigned,
  formatText,
  NOT_COMPUTED,
  propNumber,
  propString,
} from "@/lib/format";

/** Cells below this water share are not listed on the map. Stated on screen. */
const MIN_SHARE = 0.05;

/**
 * The screening index covers 1,693 cells for the pilot AOI, so this serves the
 * whole layer there. A larger AOI truncates and the response says so; the site
 * never presents a subset as if it were the whole layer.
 */
const DRAINAGE_CELL_LIMIT = 2_000;

const ALL_CLASSES = "all";
const ALL_BANDS = "all";

export function ObservedAssets({ reducedMotion }: { reducedMotion: boolean }) {
  const { activeRunId, stats, hasNoRun, reloadAll } = useRuns();
  const runId = activeRunId;

  const [year, setYear] = useState<number | null>(null);
  const [destinationClass, setDestinationClass] = useState<string>(ALL_CLASSES);
  const [connectivityYear, setConnectivityYear] = useState<number | null>(null);
  const [drainageBand, setDrainageBand] = useState<string>(ALL_BANDS);
  const studyArea = useApi<StudyAreaResponse>(studyAreaPath, []);

  // One path per route, composed through the shared builders in `lib/client`
  // so the route is defined once. A null path skips the request entirely.
  const waterPath = runId ? observedWaterPath(runId) : null;
  const destinationsPathValue =
    runId && destinationClass !== ALL_CLASSES
      ? destinationsPath(runId, destinationClass)
      : runId
        ? destinationsPath(runId)
        : null;
  const networkPathValue = runId ? networkPath(runId, 50) : null;
  const populationGridPathValue = runId ? populationGridPath(runId) : null;
  const connectivityRecordPathValue = runId ? connectivityPath(runId) : null;
  const drainagePathValue = runId ? drainagePath(runId) : null;
  const drainageCellsPathValue =
    runId && drainageBand !== ALL_BANDS
      ? drainageCellsPath(runId, drainageBand, null, DRAINAGE_CELL_LIMIT)
      : runId
        ? drainageCellsPath(runId, null, null, DRAINAGE_CELL_LIMIT)
        : null;

  const water = useApi<ObservedWaterResponse>(waterPath, [runId]);

  /**
   * The year list comes from the annual record, so the newest year can be
   * resolved before any cell request is made. The cells route names the same
   * list as `available_years`; a difference between the two is reported rather
   * than silently reconciled.
   */
  const years = useMemo<number[]>(() => {
    const recorded = (water.data?.years ?? [])
      .map((entry) => entry?.year ?? null)
      .filter((value): value is number => typeof value === "number");
    return [...new Set(recorded)].sort((a, b) => a - b);
  }, [water.data]);

  /** The chosen year, or the newest one the record can answer for. */
  const shownYear =
    year !== null && years.includes(year) ? year : years.length > 0 ? years[years.length - 1] : null;

  const cellsPath =
    runId && shownYear !== null ? observedWaterCellsPath(runId, shownYear, MIN_SHARE) : null;

  const cells = useApi<ObservedWaterCellsResult>(cellsPath, [runId, shownYear]);

  const destinations = useApi<DestinationResult>(destinationsPathValue, [
    runId,
    destinationClass,
  ]);

  const network = useApi<NetworkResult>(networkPathValue, [runId]);

  const populationGrid = useApi<PopulationGridResponse>(populationGridPathValue, [runId]);

  /**
   * The screened years come from the whole record, so the selector can be drawn
   * before any single-year request is made; the year under the cursor is then
   * asked for by value. A year the record does not name is never substituted
   * here either, so the label above a number is always a year that was screened.
   */
  const connectivityRecord = useApi<ConnectivityResponse>(connectivityRecordPathValue, [
    runId,
  ]);

  const screenedYears = useMemo<number[]>(
    () =>
      Array.isArray(connectivityRecord.data?.available_years)
        ? [...connectivityRecord.data.available_years].sort((a, b) => a - b)
        : [],
    [connectivityRecord.data],
  );

  const shownConnectivityYear =
    connectivityYear !== null && screenedYears.includes(connectivityYear)
      ? connectivityYear
      : screenedYears.length > 0
        ? screenedYears[screenedYears.length - 1]
        : null;

  const connectivityYearPathValue =
    runId && shownConnectivityYear !== null
      ? connectivityPath(runId, shownConnectivityYear)
      : null;

  const connectivityYearRecord = useApi<ConnectivityResponse>(connectivityYearPathValue, [
    runId,
    shownConnectivityYear,
  ]);

  const drainage = useApi<DrainageResponse>(drainagePathValue, [runId]);
  const drainageCells = useApi<DrainageCellsResult>(drainageCellsPathValue, [
    runId,
    drainageBand,
  ]);

  const status = stats.data?.validation_status ?? null;
  const waterPayload = water.data ?? null;
  const waterAvailable = waterPayload?.available === true;

  /**
   * `available_years` on the cells route is checked against the annual record
   * rather than used to drive the selector, so the year under the cursor is
   * always one the record can answer for.
   */
  const cellRouteYears = useMemo<number[]>(
    () => (Array.isArray(cells.data?.available_years) ? cells.data.available_years : []),
    [cells.data],
  );
  const yearListAgrees =
    cellRouteYears.length === 0 ||
    (cellRouteYears.length === years.length &&
      cellRouteYears.every((value) => years.includes(value)));

  const layerState: LayerState = useMemo(
    () => ({ ...DEFAULT_LAYERS, observedWater: true }),
    [],
  );

  const bundle = useMemo<MapBundle>(
    () => ({
      ...EMPTY_BUNDLE,
      studyArea: asFeatureCollection<StudyAreaProperties>(studyArea.data),
      observedWater: asFeatureCollection<ObservedWaterCellProperties>(
        cells.phase === "ready" ? cells.data : null,
      ),
    }),
    [studyArea.data, cells.phase, cells.data],
  );

  return (
    <div className="page observed-page">
      <PageIntro
        kicker="05 · Observed &amp; assets"
        title="What was measured, and what is only a candidate"
        lead={
          <>
            The JRC annual surface-water record is an observation of{" "}
            <b>extent</b> for years up to 2021. The destination records are OSM
            tags, and the network is the extracted street graph. Nothing on this
            screen is a forecast, a warning or a routing instruction.
          </>
        }
        aside={
          <>
            <ValidationStamp status={status} modelTime={null} />
            <p className="muted">
              No model clock applies to this screen: the years below are calendar years
              of the observation, and the rest are static assets.
            </p>
            <p className="synthetic-label">
              <Satellite size={14} aria-hidden="true" /> Observation, not model output
            </p>
          </>
        }
      />

      {hasNoRun ? (
        <NoRunState
          what="observed layers or asset tables"
          onReload={reloadAll}
          detail={
            <p className="muted">
              The city-scale layers are attached to a run. Select or publish a run,
              then this screen will read its own record.
            </p>
          }
        />
      ) : null}

      <Panel
        title={
          <>
            <CircleDashed size={16} aria-hidden="true" /> How to read this screen
          </>
        }
        description="Four facts that change what the numbers below are allowed to mean."
      >
        <ul className="assumption-list">
          <li>
            <h3>Extent, never depth</h3>
            <p>
              A classified year says whether a cell contained water. It carries no
              depth, no duration and no direction, so no depth, exposure or
              evacuation figure may be derived from it.
            </p>
          </li>
          <li>
            <h3>Observation coverage varies</h3>
            <p>
              Unobserved pixels are not evidence of dry land. Compare classified area
              alongside water area; a share of classified pixels is not a share
              of the whole city. The API interpretation notes appear below.
            </p>
          </li>
          <li>
            <h3>Annual classes do not resolve an event</h3>
            <p>
              The annual record includes seasonal and permanent water. It cannot
              establish flood-event timing, peak extent or whether a particular
              event was absent. Differences between years are not event-flood
              estimates.
            </p>
          </li>
          <li>
            <h3>Zero destinations are verified</h3>
            <p>
              An OSM tag is a mapping decision, not an operational guarantee. No
              record below may be presented as a refuge, a shelter or a route to
              safety.
            </p>
          </li>
        </ul>
      </Panel>

      {/* ---------------------------------------------------------- Water */}
      <Panel
        title={
          <>
            <Droplets size={16} aria-hidden="true" /> Observed surface water
          </>
        }
        description="JRC Global Surface Water yearly classification, Landsat 5/7/8. Extent per year, for the selected year only."
        actions={
          water.phase === "ready" && waterAvailable ? (
            <Badge variant="outline" className="status-badge status-approved">
              <span aria-hidden="true" className="status-glyph">
                ◆
              </span>
              observation
            </Badge>
          ) : null
        }
      >
        {water.phase === "loading" ? <LoadingState label="Reading the annual water record" /> : null}
        {water.phase === "error" && water.error ? (
          <ErrorState error={water.error} onRetry={water.reload} context="Observed water record." />
        ) : null}
        {water.phase === "missing" ? (
          <p className="muted" role="status">
            This run published no observed-water record.
          </p>
        ) : null}

        {water.phase === "ready" && !waterAvailable ? (
          <AbsentLayer
            title="No observed water record on this run"
            what="the JRC annual surface-water classification"
            warnings={asWarningList(waterPayload?.warnings)}
          />
        ) : null}

        {waterAvailable ? (
          <div className="observed-stack">
            <dl className="kv">
              <div>
                <dt>Source</dt>
                <dd className="mono">{formatText(waterPayload?.source_id)}</dd>
              </div>
              <div>
                <dt>Licence</dt>
                <dd>{formatText(waterPayload?.licence)}</dd>
              </div>
              <div>
                <dt>Product</dt>
                <dd>{formatText(waterPayload?.product)}</dd>
              </div>
              <div>
                <dt>Measures</dt>
                <dd>{formatText(waterPayload?.measures)}</dd>
              </div>
              <div>
                <dt>Baseline year</dt>
                <dd>{formatCount(waterPayload?.baseline_year ?? null)}</dd>
              </div>
            </dl>

            {waterPayload?.note ? (
              <p className="panel-note">{formatText(waterPayload.note)}</p>
            ) : null}

            {asWarningList(waterPayload?.interpretation_notes).length > 0 ? (
              <ul className="warning-list" aria-label="How to interpret the annual record">
                {asWarningList(waterPayload?.interpretation_notes).map((note) => (
                  <li key={note}>
                    <span aria-hidden="true" className="check-glyph">
                      !
                    </span>
                    <span className="check-name">{note}</span>
                  </li>
                ))}
              </ul>
            ) : null}

            {asWarningList(waterPayload?.warnings).length > 0 ? (
              <WarningList items={asWarningList(waterPayload?.warnings)} />
            ) : null}

            <div className="registry-toolbar">
              <div className="rail-field">
                <label htmlFor="water-year">Classified year</label>
                <Select
                  value={shownYear === null ? undefined : String(shownYear)}
                  onValueChange={(value) => setYear(Number(value))}
                >
                  <SelectTrigger id="water-year" aria-label="Classified year">
                    <SelectValue placeholder="No year served" />
                  </SelectTrigger>
                  <SelectContent>
                    {years.map((option) => (
                      <SelectItem key={option} value={String(option)}>
                        {option}
                        {option === waterPayload?.baseline_year ? " · baseline" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <p className="muted">
                {years.length === 0
                  ? "The API served no classifiable year for this run."
                  : `${years.length} year${years.length === 1 ? "" : "s"} in the record. Cells are listed from a water share of ${formatShare(MIN_SHARE)} upwards.`}
                {yearListAgrees
                  ? ""
                  : " The cells route names a different set of years, so the two are not assumed to agree."}
              </p>
            </div>

            <YearTable
              years={waterPayload?.years ?? []}
              baselineYear={waterPayload?.baseline_year ?? null}
              unavailableYears={waterPayload?.unavailable_years ?? []}
              selectedYear={shownYear}
            />

            {shownYear !== null ? (
              <>
                <h3 className="table-section-title">
                  Cells classified as water in {shownYear}
                </h3>
                {cells.phase === "loading" ? (
                  <LoadingState label={`Reading cells for ${shownYear}`} />
                ) : null}
                {cells.phase === "error" && cells.error ? (
                  <ErrorState
                    error={cells.error}
                    onRetry={cells.reload}
                    context={`Observed water cells for ${shownYear}.`}
                  />
                ) : null}
                {cells.phase === "ready" && cells.data?.available === false ? (
                  <AbsentLayer
                    title={`No classified cells for ${shownYear}`}
                    what="cell-level water extent"
                    warnings={asWarningList(cells.data?.warnings)}
                  />
                ) : null}
                {cells.phase === "ready" && cells.data?.available !== false ? (
                  <>
                    <p className="tables-note">
                      {formatCount(cells.data?.matched_rows ?? null)} matched,{" "}
                      {formatCount(cells.data?.returned ?? null)} served
                      {cells.data?.truncated === true
                        ? " · truncated at the API limit, so the table and the map are the first rows only"
                        : ""}
                      . Marker size and colour both rise with the water share.
                    </p>
                    {servesGeographicPoints(bundle.observedWater) ? (
                      <div className="lab-map">
                        <MapView
                          bundle={bundle}
                          layers={layerState}
                          modelTime={null}
                          areaName={`the ${shownYear} observed water classification`}
                          reducedMotion={reducedMotion}
                        />
                      </div>
                    ) : (
                      <ProjectedGeometryNotice gridSizeM={cells.data?.grid_size_m ?? null} />
                    )}
                    <CellTable cells={cells.data} year={shownYear} />
                  </>
                ) : null}
              </>
            ) : null}
          </div>
        ) : null}
      </Panel>

      {/* ------------------------------------------------- Connectivity */}
      <Panel
        title={
          <>
            <Route size={16} aria-hidden="true" /> Connectivity under observed water
          </>
        }
        description="What the street graph looks like when the observed water classification of one year is imposed on it as impassable. Two shares per year, and what they do not measure."
        actions={
          connectivityRecord.phase === "ready" &&
          connectivityRecord.data?.available === true ? (
            <Badge variant="outline" className="status-badge status-verify">
              <span aria-hidden="true" className="status-glyph">
                ≠
              </span>
              screening index
            </Badge>
          ) : null
        }
      >
        {connectivityRecord.phase === "loading" ? (
          <LoadingState label="Reading the connectivity screening" />
        ) : null}
        {connectivityRecord.phase === "error" && connectivityRecord.error ? (
          <ErrorState
            error={connectivityRecord.error}
            onRetry={connectivityRecord.reload}
            context="Connectivity screening."
          />
        ) : null}
        {connectivityRecord.phase === "ready" &&
        connectivityRecord.data?.available !== true ? (
          <AbsentLayer
            title="No connectivity screening on this run"
            what="a connectivity screening artefact"
            warnings={asWarningList(connectivityRecord.data?.warnings)}
          />
        ) : null}

        {connectivityRecord.phase === "ready" &&
        connectivityRecord.data?.available === true ? (
          <ConnectivityView
            record={connectivityRecord.data}
            detail={connectivityYearRecord.data}
            detailPhase={connectivityYearRecord.phase}
            detailError={connectivityYearRecord.error}
            onReloadDetail={connectivityYearRecord.reload}
            screenedYears={screenedYears}
            selectedYear={shownConnectivityYear}
            onSelectYear={setConnectivityYear}
            status={status}
          />
        ) : null}
      </Panel>

      {/* ------------------------------------------------------ Drainage */}
      <Panel
        title={
          <>
            <Waves size={16} aria-hidden="true" /> Drainage-discharge index
          </>
        }
        description="A relative index of how thin mapped drainage infrastructure is in each 1 km cell. A susceptibility score from geometry, not a depth and not a hydraulic model."
        actions={
          drainage.phase === "ready" && drainage.data?.available === true ? (
            <Badge variant="outline" className="status-badge status-verify">
              <span aria-hidden="true" className="status-glyph">
                ≠
              </span>
              screening index · not a depth
            </Badge>
          ) : null
        }
      >
        {drainage.phase === "loading" ? (
          <LoadingState label="Reading the drainage-discharge index" />
        ) : null}
        {drainage.phase === "error" && drainage.error ? (
          <ErrorState
            error={drainage.error}
            onRetry={drainage.reload}
            context="Drainage-discharge index."
          />
        ) : null}
        {drainage.phase === "ready" && drainage.data?.available !== true ? (
          <AbsentLayer
            title="No drainage-discharge index on this run"
            what="a drainage screening artefact"
            warnings={asWarningList(drainage.data?.warnings)}
          />
        ) : null}

        {drainage.phase === "ready" && drainage.data?.available === true ? (
          <DrainageView
            index={drainage.data}
            cells={drainageCells.data}
            cellsPhase={drainageCells.phase}
            cellsError={drainageCells.error}
            onReloadCells={drainageCells.reload}
            band={drainageBand}
            onSelectBand={setDrainageBand}
            status={status}
          />
        ) : null}
      </Panel>

      {/* --------------------------------------------------- Destinations */}
      <Panel
        title={
          <>
            <Landmark size={16} aria-hidden="true" /> Destination candidates
          </>
        }
        description="Points of interest from the extracted OpenStreetMap data. A tag is a mapping decision, not an operational guarantee."
        actions={
          destinations.phase === "ready" ? (
            <Badge
              variant="outline"
              className={`status-badge ${
                (destinations.data?.verified_count ?? 0) > 0 ? "status-approved" : "status-rejected"
              }`}
            >
              <span aria-hidden="true" className="status-glyph">
                {(destinations.data?.verified_count ?? 0) > 0 ? "✓" : "✕"}
              </span>
              {formatCount(destinations.data?.verified_count ?? null)} verified
            </Badge>
          ) : null
        }
      >
        {destinations.phase === "loading" ? (
          <LoadingState label="Reading destination candidates" />
        ) : null}
        {destinations.phase === "error" && destinations.error ? (
          <ErrorState
            error={destinations.error}
            onRetry={destinations.reload}
            context="Destination candidates."
          />
        ) : null}

        {destinations.phase === "missing" ? (
          <p className="muted" role="status">
            The API has no destination record for this run, so there are no candidate
            tables to show. A zero is not substituted.
          </p>
        ) : null}

        {destinations.phase === "ready" && destinations.data?.available !== true ? (
          <AbsentLayer
            title="No destination candidates on this run"
            what="OSM-tagged destination records"
            warnings={asWarningList(destinations.data?.warnings)}
          />
        ) : null}

        {destinations.phase === "ready" && destinations.data?.available === true ? (
          <div className="observed-stack">
            <p className="status-note">
              <ShieldAlert size={15} aria-hidden="true" />
              <span>
                {formatText(
                  destinations.data?.verified_note ??
                    "No record on this run is verified. None may be presented as a refuge.",
                )}
              </span>
            </p>

            <ClassCounts byClass={destinations.data?.by_class ?? null} />

            <div className="registry-toolbar">
              <div className="rail-field">
                <label htmlFor="destination-class">Class</label>
                <Select value={destinationClass} onValueChange={setDestinationClass}>
                  <SelectTrigger id="destination-class" aria-label="Destination class">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL_CLASSES}>all classes</SelectItem>
                    {orderedClasses(destinations.data?.by_class ?? null).map((name) => (
                      <SelectItem key={name} value={name}>
                        {name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <p className="muted">
                {formatCount(destinations.data?.matched_rows ?? null)} matched,{" "}
                {formatCount(destinations.data?.returned ?? null)} served
                {destinations.data?.truncated === true ? " · truncated at the API limit" : ""}.
                No row below is a shelter.
              </p>
            </div>

            <DestinationTable result={destinations.data} />
          </div>
        ) : null}
      </Panel>

      {/* -------------------------------------------------------- Network */}
      <Panel
        title={
          <>
            <Network size={16} aria-hidden="true" /> Street network summary
          </>
        }
        description="The extracted routing graph for the run area. This is infrastructure, not a flood state: no edge here is closed or slowed."
      >
        {network.phase === "loading" ? <LoadingState label="Reading the network summary" /> : null}
        {network.phase === "error" && network.error ? (
          <ErrorState error={network.error} onRetry={network.reload} context="Network summary." />
        ) : null}
        {network.phase === "missing" ? (
          <p className="muted" role="status">
            The API has no network record for this run.
          </p>
        ) : null}
        {network.phase === "ready" && network.data?.available !== true ? (
          <AbsentLayer
            title="No network layer on this run"
            what="the extracted street graph"
            warnings={asWarningList(network.data?.warnings)}
          />
        ) : null}
        {network.phase === "ready" && network.data?.available === true ? (
          <NetworkSummaryView result={network.data} status={status} />
        ) : null}
      </Panel>

      {/* ----------------------------------------------- Resident baseline */}
      <Panel
        title={
          <>
            <Droplets size={16} aria-hidden="true" /> Resident baseline grid
          </>
        }
        description="The weighted resident grid the run starts from. This is a model input, not an observation, and it is not a daytime count."
      >
        {populationGrid.phase === "loading" ? (
          <LoadingState label="Reading the resident baseline grid" />
        ) : null}
        {populationGrid.phase === "error" && populationGrid.error ? (
          <ErrorState
            error={populationGrid.error}
            onRetry={populationGrid.reload}
            context="Resident baseline grid."
          />
        ) : null}
        {populationGrid.phase === "missing" ? (
          <p className="muted" role="status">
            The API has no resident baseline record for this run.
          </p>
        ) : null}
        {populationGrid.phase === "ready" && populationGrid.data?.available !== true ? (
          <AbsentLayer
            title="No resident baseline grid on this run"
            what="the 1 km resident grid"
            warnings={asWarningList(populationGrid.data?.warnings)}
          />
        ) : null}
        {populationGrid.phase === "ready" && populationGrid.data?.available === true ? (
          <PopulationGridView payload={populationGrid.data} status={status} />
        ) : null}
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Pieces
 * ------------------------------------------------------------------ */

/**
 * MapLibre reads GeoJSON coordinates as WGS84 longitude and latitude. The cells
 * route currently serves centroids in the analysis CRS (metres), which is out of
 * range for a lon/lat pair, so the map is mounted only when the geometry really
 * is geographic. Drawing projected metres on a web map would place every cell in
 * the wrong part of the world, which is worse than showing nothing.
 */
function servesGeographicPoints(
  collection: FeatureCollection<ObservedWaterCellProperties>,
): boolean {
  for (const feature of collection.features) {
    if (feature.geometry?.type !== "Point") continue;
    const coordinates = feature.geometry.coordinates;
    if (!Array.isArray(coordinates) || coordinates.length < 2) continue;
    const [first, second] = coordinates as [number, number];
    if (!Number.isFinite(first) || !Number.isFinite(second)) continue;
    if (Math.abs(first) > 180 || Math.abs(second) > 90) return false;
  }
  return true;
}

function ProjectedGeometryNotice({ gridSizeM }: { gridSizeM: number | null }) {
  return (
    <div className="state-block empty" role="status">
      <CircleDashed size={22} aria-hidden="true" />
      <div>
        <strong>The map is withheld: this route serves projected coordinates.</strong>
        <p>
          The cells arrive as {formatCount(gridSizeM)} m centroids in the analysis CRS
          (EPSG:32647) rather than as longitude and latitude, so drawing them on a web
          map would place every cell in the wrong location. Nothing is estimated in
          their place: the table below carries every served cell, and the map draws as
          soon as the route serves WGS84 coordinates.
        </p>
      </div>
    </div>
  );
}

function AbsentLayer({
  title,
  what,
  warnings,
}: {
  title: string;
  what: string;
  warnings: string[];
}) {
  return (
    <div className="state-block empty" role="status">
      <CircleDashed size={22} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>
          This run does not carry {what}, so there is nothing to draw and no number
          to show. A zero is not substituted for an absent layer.
        </p>
        {warnings.length > 0 ? <WarningList items={warnings} /> : null}
      </div>
    </div>
  );
}

/**
 * The annual record names its aggregates with an `aoi_` prefix while the
 * contract text uses the short names. Both are accepted, in that order, so a
 * field is never read as absent when the API has actually served it.
 */
function firstNumber(source: unknown, ...keys: string[]): number | null {
  for (const key of keys) {
    const value = propNumber(source, key);
    if (value !== null) return value;
  }
  return null;
}

function WarningList({ items, label = "API warnings" }: { items: string[]; label?: string }) {
  if (items.length === 0) return null;
  return (
    <ul className="warning-list" aria-label={label}>
      {items.map((item) => (
        <li key={item}>
          <span aria-hidden="true" className="check-glyph fail">
            !
          </span>
          <span className="check-name">{item}</span>
        </li>
      ))}
    </ul>
  );
}

function DataTable({
  head,
  rows,
  empty,
  note,
}: {
  head: string[];
  rows: string[][];
  empty: string;
  note?: ReactNode;
}) {
  return (
    <div className="table-section">
      <p className="muted">
        {rows.length === 0 ? empty : `${rows.length} row${rows.length === 1 ? "" : "s"}.`}
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            {head.map((cell) => (
              <TableHead key={cell} scope="col">
                {cell}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${row[0]}-${index}`}>
              {row.map((cell, cellIndex) => (
                <TableCell key={`${cell}-${cellIndex}`}>{cell}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {note ? <p className="muted">{note}</p> : null}
    </div>
  );
}

function YearTable({
  years,
  baselineYear,
  unavailableYears,
  selectedYear,
}: {
  years: ObservedWaterYear[];
  baselineYear: number | null;
  unavailableYears: Array<number | string>;
  selectedYear: number | null;
}) {
  const unavailable = new Set(unavailableYears.map((value) => String(value)));

  const rows: string[][] = years.map((entry) => {
    const value = entry.year ?? null;
    const isBaseline = value !== null && value === baselineYear;
    return [
      value === null ? NOT_COMPUTED : String(value),
      formatNumber(firstNumber(entry, "aoi_water_km2", "water_km2"), 2),
      formatShare(firstNumber(entry, "aoi_water_share", "water_share")),
      formatNumber(firstNumber(entry, "aoi_area_km2", "classified_km2"), 1),
      entry.excess_km2_vs_baseline === null ||
      entry.excess_km2_vs_baseline === undefined
        ? NOT_COMPUTED
        : isBaseline
          ? "baseline year"
          : `${formatSigned(entry.excess_km2_vs_baseline, 2)} km²`,
      isBaseline
        ? "◆ baseline"
        : unavailable.has(String(value))
          ? "✕ no usable classification"
          : "✓ classified",
      value !== null && value === selectedYear ? "shown on the map" : "",
    ];
  });

  for (const value of unavailableYears) {
    if (years.some((entry) => String(entry.year ?? "") === String(value))) continue;
    rows.push([
      String(value),
      NOT_COMPUTED,
      NOT_COMPUTED,
      NOT_COMPUTED,
      NOT_COMPUTED,
      "✕ no usable classification",
      "",
    ]);
  }

  return (
    <DataTable
      head={[
        "year",
        "water area (km²)",
        "share of classified area",
        "classified area (km²)",
        "excess vs baseline",
        "state",
        "map",
      ]}
      rows={rows}
      empty="The API published no annual water record for this run."
      note="Water share uses classified pixels only; unobserved pixels are excluded. Annual area is not an event-flood footprint. The baseline year is named."
    />
  );
}

function CellTable({
  cells,
  year,
}: {
  cells: ObservedWaterCellsResult | null;
  year: number;
}) {
  const features = asFeatureCollection<ObservedWaterCellProperties>(cells).features;
  const rows = features.map((feature, index) => {
    const p = feature.properties ?? {};
    return [
      propString(p, "cell_id") ?? (feature.id != null ? String(feature.id) : `row ${index + 1}`),
      formatCount(propNumber(p, "year")),
      formatShare(propNumber(p, "water_share")),
      formatNumber(propNumber(p, "water_km2"), 2),
      formatText(propString(p, "source_role")),
      formatText(propString(p, "measures")),
    ];
  });

  return (
    <DataTable
      head={["cell", "year", "water share", "water area (km²)", "source role", "measures"]}
      rows={rows.slice(0, 200)}
      empty={`No cell in ${year} reached the minimum water share.`}
      note={
        rows.length > 200
          ? `Showing the first 200 of ${formatCount(rows.length)} cells. The map's table view lists the same layer.`
          : "Table equivalent of the observed water map layer. Share is extent, not depth."
      }
    />
  );
}

/** Display order is fixed where the class is known, appended where it is not. */
function orderedClasses(byClass: Record<string, number> | null): string[] {
  if (!byClass) return [];
  const known = DESTINATION_CLASSES.filter((name) => name in byClass);
  const extra = Object.keys(byClass).filter((name) => !DESTINATION_CLASSES.includes(name));
  return [...known, ...extra];
}

function ClassCounts({ byClass }: { byClass: Record<string, number> | null }) {
  const names = orderedClasses(byClass);
  if (names.length === 0) {
    return (
      <p className="muted">
        The API reported no class breakdown, so no count is shown. Zero is not
        inferred.
      </p>
    );
  }
  return (
    <ul className="role-list" aria-label="Candidates by class">
      {names.map((name) => (
        <li key={name} className="present">
          <span aria-hidden="true" className="role-glyph">
            ■
          </span>
          <b>{name}</b>
          <span className="role-state">{formatCount(byClass?.[name] ?? null)} candidates</span>
        </li>
      ))}
    </ul>
  );
}

function DestinationTable({ result }: { result: DestinationResult }) {
  const rows = (result.rows ?? []).map((row) => [
    formatText(row.destination_id ?? (row.osm_id != null ? String(row.osm_id) : null)),
    formatText(row.name),
    formatText(row.amenity),
    formatText(row.destination_class),
    row.verified === true ? "✓ verified" : row.verified === false ? "✕ unverified" : "○ not reported",
    formatText(row.status),
    formatCount(row.capacity ?? null),
    formatText(row.operator),
    row.accessible === true ? "✓ yes" : row.accessible === false ? "✕ no" : "○ not reported",
    formatNumber(row.lon, 5),
    formatNumber(row.lat, 5),
  ]);

  return (
    <DataTable
      head={[
        "id",
        "name",
        "amenity",
        "class",
        "verified",
        "status",
        "capacity",
        "operator",
        "accessible",
        "lon",
        "lat",
      ]}
      rows={rows.slice(0, 200)}
      empty="The API served no destination rows for this filter."
      note={
        rows.length > 200
          ? `Showing the first 200 of ${formatCount(rows.length)} served rows.`
          : "A row with a class is a candidate. Capacity and operator are null when the tag did not carry them, which is not the same as zero."
      }
    />
  );
}

function NetworkSummaryView({
  result,
  status,
}: {
  result: NetworkResult;
  status: string | null;
}) {
  const summary = result.summary ?? null;
  return (
    <div className="observed-stack">
      <section className="metric-grid" aria-label="Network summary">
        <MetricCard
          label="Edges"
          icon={<Network size={15} aria-hidden="true" />}
          value={formatCount(summary?.edges ?? null)}
          quantity="directed graph edges extracted for the run area"
          caption={`${formatCount(summary?.source_ways ?? null)} source ways contributed.`}
          status={status}
          modelTime={null}
        />
        <MetricCard
          label="Nodes"
          icon={<Network size={15} aria-hidden="true" />}
          value={formatCount(summary?.nodes ?? null)}
          quantity="graph nodes after junction simplification"
          status={status}
          modelTime={null}
        />
        <MetricCard
          label="Total length"
          icon={<Network size={15} aria-hidden="true" />}
          value={formatNumber(summary?.total_length_km ?? null, 1)}
          unit="km"
          quantity="summed edge length, both directions counted once per edge"
          caption={`walk ${formatNumber(summary?.walk_length_km ?? null, 1)} km · vehicle ${formatNumber(
            summary?.vehicle_length_km ?? null,
            1,
          )} km`}
          status={status}
          modelTime={null}
        />
      </section>
      <p className="panel-note">
        {result.sample_is_spatial_subset === true
          ? `The API returned ${formatCount(result.returned ?? null)} of ${formatCount(
              result.matched_rows ?? null,
            )} edges as a spatial sample. The sample is a subset in place, not a ranking, and its length is not a summary of the network.`
          : `The API returned ${formatCount(result.returned ?? null)} of ${formatCount(
              result.matched_rows ?? null,
            )} edges.`}
        {" "}No edge on this screen carries a flood state; closures appear only in the
        Scenario Lab, at a stated model time.
      </p>
      {asWarningList(result.warnings).length > 0 ? (
        <WarningList items={asWarningList(result.warnings)} />
      ) : null}
    </div>
  );
}

function PopulationGridView({
  payload,
  status,
}: {
  payload: PopulationGridResponse;
  status: string | null;
}) {
  // The grid is served as EPSG:32647 metres plus a WGS84 point in WKT; there is
  // no cell id on every row, so the grid indices name the cell in the table.
  const rows = [...(payload.rows ?? [])]
    .sort((a, b) => (propNumber(b, "pop") ?? 0) - (propNumber(a, "pop") ?? 0))
    .slice(0, 25)
    .map((row) => {
      const [lon, lat] = pointWkt(row.geometry_wkt ?? null);
      return [
        formatText(row.cell_id ?? (row.gx != null || row.gy != null ? `${row.gx}, ${row.gy}` : null)),
        formatNumber(row.pop, 1),
        formatNumber(row.x, 1),
        formatNumber(row.y, 1),
        formatNumber(row.lon ?? lon, 5),
        formatNumber(row.lat ?? lat, 5),
      ];
    });

  return (
    <div className="observed-stack">
      <section className="metric-grid" aria-label="Resident baseline grid">
        <MetricCard
          label="Cells matched"
          icon={<Droplets size={15} aria-hidden="true" />}
          value={formatCount(payload.matched_rows ?? null)}
          quantity="1 km cells with a resident baseline"
          caption={`${formatCount(payload.returned ?? null)} served${
            payload.truncated === true ? " · truncated at the API limit" : ""
          }.`}
          status={status}
          modelTime={null}
        />
        <MetricCard
          label="Grid size"
          icon={<Droplets size={15} aria-hidden="true" />}
          value={formatCount(payload.grid_size_m ?? null)}
          unit="m"
          quantity="cell edge length; centroid in the analysis CRS"
          caption="x and y are EPSG:32647 easting and northing; the WGS84 point is served as POINT (lon lat)."
          status={status}
          modelTime={null}
        />
        <MetricCard
          label="Quantity"
          icon={<Droplets size={15} aria-hidden="true" />}
          value={formatText(payload.quantity)}
          quantity="the population quantity this grid represents"
          caption={formatText(payload.quantity_note)}
          status={status}
          modelTime={null}
        />
      </section>
      <DataTable
        head={["cell", "pop (weighted residents)", "x (EPSG:32647)", "y (EPSG:32647)", "lon", "lat"]}
        rows={rows}
        empty="The API served no cells for this run."
        note={`The 25 heaviest cells by weighted residents, sorted for reading only. A resident count is a baseline, not a count of people present at any hour. Served columns: ${formatText(
          (payload.columns ?? []).join(", ") || null,
        )}.`}
      />
    </div>
  );
}

/** The API serves the WGS84 point as `POINT (lon lat)`; read it, do not guess it. */
function pointWkt(wkt: string | null): [number | null, number | null] {
  if (typeof wkt !== "string") return [null, null];
  const match = /POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)/i.exec(wkt);
  if (!match) return [null, null];
  const lon = Number(match[1]);
  const lat = Number(match[2]);
  return [Number.isFinite(lon) ? lon : null, Number.isFinite(lat) ? lat : null];
}

/* ------------------------------------------------------------------ *
 * Connectivity screening under observed water
 * ------------------------------------------------------------------ */

/**
 * Every share on this screen is a share of a 0..1 quantity and the two charts
 * are drawn on the same full-height scale, so a 6% bar and a 70% bar can be
 * compared by eye. That comparison is the finding: the graph loses a few per
 * cent of its edges and several tenths of the exposed population's reachability,
 * and the two numbers must not be read as the same kind of loss.
 */
function barHeight(value: number | null | undefined): number {
  if (value === null || value === undefined || !Number.isFinite(value) || value <= 0) {
    return 0;
  }
  return Math.max(2, Math.min(100, value * 100));
}

function ShareBars({
  heading,
  ariaLabel,
  series,
  note,
}: {
  heading: string;
  ariaLabel: string;
  series: Array<{ key: string; label: string; value: number | null }>;
  note?: string;
}) {
  if (series.length === 0) return null;
  return (
    <div className="table-section">
      <h3 className="table-section-title">{heading}</h3>
      <div className="presence-chart" role="img" aria-label={ariaLabel}>
        {series.map((entry) => (
          <div key={entry.key} className="presence-bar">
            <i style={{ height: `${barHeight(entry.value)}%` }} />
            <span>{entry.label}</span>
            <em>{formatShare(entry.value)}</em>
          </div>
        ))}
      </div>
      {note ? <p className="muted">{note}</p> : null}
    </div>
  );
}

function ConnectivityView({
  record,
  detail,
  detailPhase,
  detailError,
  onReloadDetail,
  screenedYears,
  selectedYear,
  onSelectYear,
  status,
}: {
  record: ConnectivityResponse;
  detail: ConnectivityResponse | null;
  detailPhase: AsyncPhase;
  detailError: ApiError | null;
  onReloadDetail: () => void;
  screenedYears: number[];
  selectedYear: number | null;
  onSelectYear: (value: number) => void;
  status: string | null;
}) {
  const recordYears = record.years ?? [];
  const shown = detail?.years?.[0] ?? null;
  const flag = detail?.is_evacuation_simulation ?? record.is_evacuation_simulation ?? null;
  const severityNote = detail?.severity_note ?? record.severity_note ?? null;
  const destinationNote = record.destination_note ?? CONNECTIVITY_DESTINATION_FALLBACK;

  /**
   * The worst year is derived from the payload rather than named in prose: the
   * year with the most edges lost, and separately the year whose exposed
   * population can reach least far. When they agree, that agreement is shown.
   */
  const scored = recordYears.filter(
    (entry) =>
      typeof entry.closed_edge_share === "number" ||
      typeof entry.reachable_share_of_exposed === "number",
  );
  const worstClosed = scored.reduce<ConnectivityYear | null>(
    (best, entry) =>
      best === null || (entry.closed_edge_share ?? 0) > (best.closed_edge_share ?? 0)
        ? entry
        : best,
    null,
  );
  const worstReachable = scored.reduce<ConnectivityYear | null>(
    (worst, entry) =>
      worst === null ||
      (entry.reachable_share_of_exposed ?? 1) < (worst.reachable_share_of_exposed ?? 1)
        ? entry
        : worst,
    null,
  );
  const worstYear = worstClosed?.year ?? null;
  const yearsAgree = worstYear !== null && worstYear === worstReachable?.year;

  return (
    <div className="observed-stack">
      {/* The two notices are the first thing in the panel. A reader who takes
          nothing else from this screen still takes these. */}
      <p className="status-note">
        <TriangleAlert size={15} aria-hidden="true" />
        <span>
          <b>
            {flag === true
              ? "The API reports this layer as an evacuation simulation."
              : "This is not an evacuation simulation."}
          </b>{" "}
          <span className="mono">is_evacuation_simulation = {String(flag)}</span>.{" "}
          {formatText(record.measures)}. Screen an annual water classification, not an
          event: the figures below say which parts of the graph that classification cuts
          off, and nothing about how anyone would move or when.
        </span>
      </p>
      {severityNote ? (
        <p className="status-note">
          <ShieldAlert size={15} aria-hidden="true" />
          <span>
            <b>As the run recorded it:</b> {severityNote}
          </span>
        </p>
      ) : null}
      <p className="status-note">
        <Landmark size={15} aria-hidden="true" />
        <span>
          <b>The destination count is a choice, not a fact about the city.</b>{" "}
          {destinationNote}
        </span>
      </p>

      <dl className="kv">
        <div>
          <dt>Measures</dt>
          <dd>{formatText(record.measures)}</dd>
        </div>
        <div>
          <dt>Source role</dt>
          <dd className="mono">
            {formatText(record.source_role)} / hazard {formatText(record.hazard_role)}
          </dd>
        </div>
        <div>
          <dt>Years screened</dt>
          <dd>{screenedYears.length > 0 ? screenedYears.join(", ") : NOT_COMPUTED}</dd>
        </div>
        <div>
          <dt>Worst year</dt>
          <dd>
            {worstYear === null
              ? NOT_COMPUTED
              : `${worstYear} — most edges lost${
                  yearsAgree ? ", least of the exposed population able to reach one" : ""
                }`}
          </dd>
        </div>
      </dl>

      <ShareBars
        heading="Share of road edges treated as impassable, by year"
        ariaLabel={`Share of road edges treated as impassable, one bar per screened year: ${recordYears
          .map(
            (entry) =>
              `${entry.year ?? "unknown year"} ${formatShare(entry.closed_edge_share ?? null)}`,
          )
          .join(", ")}. The same figures are in the year table below.`}
        series={recordYears.map((entry) => ({
          key: `closed-${entry.year}`,
          label: entry.year === null || entry.year === undefined ? "?" : String(entry.year),
          value: propNumber(entry, "closed_edge_share"),
        }))}
        note="Water is treated as impassable at any depth, so this share is a property of that rule and not of a depth the run does not have."
      />

      <ShareBars
        heading="Share of the exposed population that can still reach a designated destination"
        ariaLabel={`Share of the exposed population that can still reach a designated destination, one bar per screened year: ${recordYears
          .map(
            (entry) =>
              `${entry.year ?? "unknown year"} ${formatShare(
                entry.reachable_share_of_exposed ?? null,
              )}`,
          )
          .join(", ")}. The same figures are in the year table below.`}
        series={recordYears.map((entry) => ({
          key: `reachable-${entry.year}`,
          label: entry.year === null || entry.year === undefined ? "?" : String(entry.year),
          value: propNumber(entry, "reachable_share_of_exposed"),
        }))}
        note="Drawn on the same full-height scale as the chart above: a few per cent of edges and several tenths of reachability are not the same size of loss."
      />

      <div className="registry-toolbar">
        <div className="rail-field">
          <label htmlFor="connectivity-year">Screened year</label>
          <Select
            value={selectedYear === null ? undefined : String(selectedYear)}
            onValueChange={(value) => onSelectYear(Number(value))}
          >
            <SelectTrigger id="connectivity-year" aria-label="Screened year">
              <SelectValue placeholder="No year screened" />
            </SelectTrigger>
            <SelectContent>
              {screenedYears.map((option) => (
                <SelectItem key={option} value={String(option)}>
                  {option}
                  {option === worstYear ? " · worst screened year" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <p className="muted">
          Both charts above hold every screened year at once; the selector chooses which
          year the numbers below describe. A year the run did not screen is not shown
          in place of one it did.
        </p>
      </div>

      {detailPhase === "loading" ? (
        <LoadingState label={`Reading the screening for ${selectedYear ?? "the selected year"}`} />
      ) : null}
      {detailPhase === "error" && detailError ? (
        <ErrorState
          error={detailError}
          onRetry={onReloadDetail}
          context={`Connectivity screening for ${selectedYear ?? "the selected year"}.`}
        />
      ) : null}
      {detailPhase === "ready" && shown === null ? (
        <AbsentLayer
          title={`No screening for ${selectedYear ?? "the selected year"}`}
          what="a per-year connectivity record"
          warnings={asWarningList(detail?.warnings)}
        />
      ) : null}

      {shown !== null ? (
        <section className="metric-grid" aria-label={`Connectivity screening for ${shown.year}`}>
          <MetricCard
            label="Edges impassable"
            icon={<Route size={15} aria-hidden="true" />}
            value={formatShare(shown.closed_edge_share ?? null)}
            quantity="share of the routing graph the year's water classification cuts"
            caption={`${formatCount(shown.closed_edges ?? null)} of ${formatCount(
              shown.total_edges ?? null,
            )} edges.`}
            status={status}
            modelTime={null}
          />
          <MetricCard
            label="Exposed population"
            icon={<Droplets size={15} aria-hidden="true" />}
            value={formatPeople(shown.exposed_population ?? null)}
            quantity="people in cells the year's classification calls water-exposed"
            caption={`${formatCount(shown.exposed_cells ?? null)} exposed cells · ${formatCount(
              shown.water_cells ?? null,
            )} classified as water.`}
            status={status}
            modelTime={null}
          />
          <MetricCard
            label="Can still reach one"
            icon={<Route size={15} aria-hidden="true" />}
            value={formatShare(shown.reachable_share_of_exposed ?? null)}
            quantity="share of the exposed population with a path to a designated destination"
            caption={`${formatPeople(shown.reachable_population ?? null)} people.`}
            status={status}
            modelTime={null}
          />
          <MetricCard
            label="Cannot reach one"
            icon={<TriangleAlert size={15} aria-hidden="true" />}
            value={formatPeople(shown.unreachable_population ?? null)}
            quantity="exposed population with no path to a designated destination under the impassable-water rule"
            caption={`${formatCount(shown.no_network_access_cells ?? null)} cells have no network access at all.`}
            status={status}
            modelTime={null}
          />
          <MetricCard
            label="Median time to a destination"
            icon={<Route size={15} aria-hidden="true" />}
            value={formatNumber(
              propNumber(shown.clearance_minutes, "p50") ??
                propNumber(shown.clearance_minutes, "median"),
              1,
            )}
            unit="min"
            quantity="p50 of the screen's own travel-time proxy, not a modelled evacuation time"
            caption={`p5 ${formatNumber(propNumber(shown.clearance_minutes, "p5"), 1)} min · p95 ${formatNumber(
              propNumber(shown.clearance_minutes, "p95"),
              1,
            )} min. No person is simulated moving.`}
            status={status}
            modelTime={null}
          />
          <MetricCard
            label="Designated destinations"
            icon={<Landmark size={15} aria-hidden="true" />}
            value={formatCount(shown.designated_destinations ?? null)}
            quantity="a scenario choice: the OSM-tagged destinations the screen was given"
            caption="Unverified tags, no capacity, no operator. Not a property of the city and not a list of shelters."
            status={status}
            modelTime={null}
          />
        </section>
      ) : null}

      <ConnectivityYearTable years={recordYears} selectedYear={selectedYear} />

      {asWarningList(record.warnings).length > 0 ? (
        <WarningList items={asWarningList(record.warnings)} />
      ) : null}
      {shown && asWarningList(shown.warnings).length > 0 ? (
        <WarningList
          items={asWarningList(shown.warnings)}
          label={`Warnings the run recorded for ${shown.year ?? "this year"}`}
        />
      ) : null}
    </div>
  );
}

function ConnectivityYearTable({
  years,
  selectedYear,
}: {
  years: ConnectivityYear[];
  selectedYear: number | null;
}) {
  const rows = years.map((entry) => [
    entry.year === null || entry.year === undefined ? NOT_COMPUTED : String(entry.year),
    formatCount(entry.water_cells ?? null),
    formatCount(entry.closed_edges ?? null),
    formatShare(entry.closed_edge_share ?? null),
    formatPeople(entry.exposed_population ?? null),
    formatShare(entry.reachable_share_of_exposed ?? null),
    formatPeople(entry.unreachable_population ?? null),
    formatNumber(
      propNumber(entry.clearance_minutes, "p50") ??
        propNumber(entry.clearance_minutes, "median"),
      1,
    ),
    formatCount(entry.designated_destinations ?? null),
    entry.year === selectedYear ? "◆ shown above" : "",
  ]);

  return (
    <DataTable
      head={[
        "year",
        "water cells",
        "edges closed",
        "share closed",
        "exposed population",
        "share reachable",
        "unreachable population",
        "median minutes",
        "destinations",
        "selector",
      ]}
      rows={rows}
      empty="The API screened no year for this run."
      note="Table equivalent of the two charts above, and the non-map view of this layer. 'Reachable' means a path to an OSM-tagged destination under an impassable-water rule; it is not an evacuation outcome."
    />
  );
}

/* ------------------------------------------------------------------ *
 * Drainage-discharge screening index
 * ------------------------------------------------------------------ */

/** Display order is fixed where the band is known, appended where it is not. */
function orderedBands(bands: Record<string, unknown> | null): string[] {
  if (!bands) return [];
  const known = DRAINAGE_BANDS.filter((name) => name in bands);
  const extra = Object.keys(bands).filter((name) => !DRAINAGE_BANDS.includes(name));
  return [...known, ...extra];
}

function DrainageView({
  index,
  cells,
  cellsPhase,
  cellsError,
  onReloadCells,
  band,
  onSelectBand,
  status,
}: {
  index: DrainageResponse;
  cells: DrainageCellsResult | null;
  cellsPhase: AsyncPhase;
  cellsError: ApiError | null;
  onReloadCells: () => void;
  band: string;
  onSelectBand: (value: string) => void;
  status: string | null;
}) {
  const summary = index.summary ?? null;
  const bands = summary?.bands ?? null;
  const shares = summary?.band_shares ?? null;
  const bandNames = orderedBands(bands);
  const declaredBands = new Map(
    (index.bands ?? [])
      .filter((entry) => typeof entry?.band === "string")
      .map((entry) => [String(entry.band), entry]),
  );
  const limitations = (index.limitations ?? []).filter(
    (item): item is string => typeof item === "string" && item.trim().length > 0,
  );
  const features = asFeatureCollection<DrainageCellProperties>(cells).features;

  return (
    <div className="observed-stack">
      <p className="status-note">
        <TriangleAlert size={15} aria-hidden="true" />
        <span>
          <b>This is not a flood depth.</b>{" "}
          <span className="mono">is_flood_depth = {String(index.is_flood_depth)}</span>.{" "}
          {formatText(index.measures)}. Read it as a position on a 0–1 scale: it says
          where mapped drainage infrastructure is thin, and it is blind to rainfall,
          river stage, tide, pumping and gate operation.
        </span>
      </p>

      <dl className="kv">
        <div>
          <dt>Index version</dt>
          <dd className="mono">{formatText(index.index_version)}</dd>
        </div>
        <div>
          <dt>Source role</dt>
          <dd className="mono">{formatText(index.source_role)}</dd>
        </div>
        <div>
          <dt>Grid</dt>
          <dd>{formatCount(index.grid_size_m ?? null)} m cells</dd>
        </div>
        <div>
          <dt>Distance cutoff</dt>
          <dd>{formatCount(index.distance_cutoff_m ?? null)} m</dd>
        </div>
      </dl>

      {limitations.length > 0 ? (
        <div className="table-section">
          <h3 className="table-section-title">
            What this index cannot do — the run&rsquo;s own list, verbatim
          </h3>
          <WarningList items={limitations} label="Stated limitations of the drainage index" />
        </div>
      ) : null}

      <section className="metric-grid" aria-label="Drainage-discharge index distribution">
        <MetricCard
          label="Cells scored"
          icon={<Waves size={15} aria-hidden="true" />}
          value={formatCount(summary?.rows_scored ?? index.rows ?? null)}
          quantity="1 km cells carrying a risk index"
          caption={`${formatCount(summary?.rows ?? null)} cells in the grid.`}
          status={status}
          modelTime={null}
        />
        <MetricCard
          label="Median risk index"
          icon={<Waves size={15} aria-hidden="true" />}
          value={formatNumber(summary?.risk_index?.median ?? null, 3)}
          quantity="middle of the 0–1 scale over this AOI only"
          caption={`min ${formatNumber(summary?.risk_index?.min ?? null, 3)} · mean ${formatNumber(
            summary?.risk_index?.mean ?? null,
            3,
          )} · max ${formatNumber(summary?.risk_index?.max ?? null, 3)}.`}
          status={status}
          modelTime={null}
        />
      </section>

      <ComponentWeights weights={index.component_weights ?? null} />

      <ShareBars
        heading="Share of cells in each band"
        ariaLabel={`Share of cells in each band: ${bandNames
          .map((name) => `${name} ${formatShare(propNumber(shares, name))}`)
          .join(", ")}. The same figures are in the band table below.`}
        series={bandNames.map((name) => ({
          key: `band-${name}`,
          label: name,
          value: propNumber(shares, name),
        }))}
        note={summary?.bands_note ?? undefined}
      />

      <DataTable
        head={["band", "declared range", "cells", "share of cells"]}
        rows={bandNames.map((name) => {
          const declared = declaredBands.get(name);
          const low = declared?.min ?? null;
          const high = declared?.max ?? null;
          return [
            name,
            typeof low === "number" && typeof high === "number"
              ? `${low} – ${high}`
              : NOT_COMPUTED,
            formatCount(propNumber(bands, name)),
            formatShare(propNumber(shares, name)),
          ];
        })}
        empty="The API reported no band distribution for this run."
        note="Counts and shares are as the run published them. The declared ranges are the artefact's own cut points; every cell's own risk_index is in the table below, so no band's membership has to be taken on trust."
      />

      <div className="registry-toolbar">
        <div className="rail-field">
          <label htmlFor="drainage-band">Band</label>
          <Select value={band} onValueChange={onSelectBand}>
            <SelectTrigger id="drainage-band" aria-label="Drainage index band">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_BANDS}>all bands</SelectItem>
              {bandNames.map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <p className="muted">
          This layer is served as a table, not as a map layer.{" "}
          {cellsPhase === "ready"
            ? `${formatCount(cells?.matched_rows ?? null)} matched, ${formatCount(
                cells?.returned ?? null,
              )} served${cells?.truncated === true ? " · truncated at the API limit" : ""}, highest risk first.`
            : "Reading the cells."}
        </p>
      </div>

      {cellsPhase === "loading" ? (
        <LoadingState label="Reading the screening cells" />
      ) : null}
      {cellsPhase === "error" && cellsError ? (
        <ErrorState error={cellsError} onRetry={onReloadCells} context="Drainage index cells." />
      ) : null}
      {cellsPhase === "ready" && cells?.available === false ? (
        <AbsentLayer
          title="No screening cells on this run"
          what="cell-level drainage susceptibility"
          warnings={asWarningList(cells?.warnings)}
        />
      ) : null}
      {asWarningList(cells?.warnings).length > 0 ? (
        <WarningList items={asWarningList(cells?.warnings)} />
      ) : null}

      <DrainageCellTable features={features} />
    </div>
  );
}

/**
 * The components are named by the artefact and weighted by it. The site does not
 * explain what each one measures beyond that, because the definition is the
 * pipeline's to state and this screen has no licence to invent one; what the
 * table adds is the weights themselves and the artefact's own admission that
 * they are a declared ordering rather than a fitted result.
 */
function ComponentWeights({ weights }: { weights: Record<string, number> | null }) {
  const names = Object.keys(weights ?? {});
  if (names.length === 0) {
    return (
      <p className="muted">
        The API published no component weights, so the index cannot be decomposed here.
        Zero is not inferred.
      </p>
    );
  }
  return (
    <div className="table-section">
      <h3 className="table-section-title">What the score is made of</h3>
      <p className="muted">
        Each cell&rsquo;s <span className="mono">risk_index</span> is a weighted sum of
        these components after they have been min–max normalised across this AOI, so it
        expresses a position within this distribution and is not comparable with another
        AOI without recomputing it. The weights are a declared ordering, not a fitted or
        calibrated result.
      </p>
      <DataTable
        head={["component", "weight"]}
        rows={names.map((name) => [name, formatNumber(weights?.[name] ?? null, 2)])}
        empty="No component was published."
        note="Component names and weights exactly as the run recorded them."
      />
    </div>
  );
}

function DrainageCellTable({
  features,
}: {
  features: Array<{ properties?: DrainageCellProperties | null }>;
}) {
  const rows = features.map((item, index) => {
    const p = item.properties ?? {};
    const components = p.index_components ?? null;
    return [
      propString(p, "cell_id") ?? `row ${index + 1}`,
      formatNumber(p.risk_index ?? null, 3),
      formatText(p.risk_band),
      formatCount(p.drainage_m ?? null),
      formatNumber(p.distance_to_drainage_m ?? null, 0),
      p.in_overflow_path === true ? "✓ yes" : p.in_overflow_path === false ? "✕ no" : "○ not reported",
      p.susceptible_village === true ? "✓ yes" : p.susceptible_village === false ? "✕ no" : "○ not reported",
      components
        ? DRAINAGE_BANDS.length > 0
          ? Object.keys(components)
              .map((name) => `${name} ${formatNumber(components[name] ?? null, 2)}`)
              .join(" · ")
          : NOT_COMPUTED
        : NOT_COMPUTED,
      formatText(p.source_role),
      p.is_flood_depth === false ? "✕ not a depth" : "○ not reported",
    ];
  });

  return (
    <DataTable
      head={[
        "cell",
        "risk index",
        "band",
        "drainage (m)",
        "distance to drainage (m)",
        "in overflow path",
        "susceptible village",
        "components",
        "source role",
        "flood depth",
      ]}
      rows={rows.slice(0, 100)}
      empty="The API served no screening cells for this band."
      note={
        rows.length > 100
          ? `Showing the 100 highest-risk of ${formatCount(rows.length)} served cells. The full list is the API response; this layer is not truncated silently.`
          : "Non-map view of the screening index, highest risk first. A risk index is a relative susceptibility score, not metres of water, and the last column says so on every row."
      }
    />
  );
}
