/**
 * Observed & assets — the one screen that carries an observation.
 *
 * Everything else in this prototype is a model output at a stated model time.
 * The JRC Global Surface Water annual classification is a measurement of
 * *extent*: a cell is classified as water or not, for one year, with no depth,
 * no duration and no direction. The four rules at the top of this screen are
 * not disclaimers bolted on afterwards; they are the reading instructions for
 * every figure below, and they are also what makes the absence of 2011 and the
 * absence of any verified destination legible rather than invisible.
 *
 * A pilot run has none of the city layers. Each of the five routes then answers
 * `available: false` with a `warnings` array, and this screen says so instead of
 * drawing an empty map or a zero.
 */

import { useMemo, useState, type ReactNode } from "react";
import { CircleDashed, Droplets, Landmark, Network, Satellite, ShieldAlert } from "lucide-react";
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
import { useApi } from "@/hooks/useApi";
import { useRuns } from "@/lib/run-context";
import {
  asFeatureCollection,
  asWarningList,
  destinationsPath,
  networkPath,
  observedWaterCellsPath,
  observedWaterPath,
  populationGridPath,
} from "@/lib/client";
import {
  DESTINATION_CLASSES,
  type DestinationResult,
  type FeatureCollection,
  type NetworkResult,
  type ObservedWaterCellsResult,
  type ObservedWaterCellProperties,
  type ObservedWaterResponse,
  type ObservedWaterYear,
  type PopulationGridResponse,
} from "@/lib/api";
import {
  formatCount,
  formatNumber,
  formatShare,
  formatSigned,
  formatText,
  NOT_COMPUTED,
  propNumber,
  propString,
} from "@/lib/format";

/** Cells below this water share are not listed on the map. Stated on screen. */
const MIN_SHARE = 0.05;

const ALL_CLASSES = "all";

export function ObservedAssets({ reducedMotion }: { reducedMotion: boolean }) {
  const { activeRunId, stats, hasNoRun, reloadAll } = useRuns();
  const runId = activeRunId;

  const [year, setYear] = useState<number | null>(null);
  const [destinationClass, setDestinationClass] = useState<string>(ALL_CLASSES);

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
      observedWater: asFeatureCollection<ObservedWaterCellProperties>(
        cells.phase === "ready" ? cells.data : null,
      ),
    }),
    [cells.phase, cells.data],
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
            <h3>Every year is a lower bound</h3>
            <p>
              Water under cloud, shadow or dense vegetation is not classified. Each
              area below is a floor for its year, and the series is not a trend. The
              API&rsquo;s own note on 2011 is printed in full in the panel below.
            </p>
          </li>
          <li>
            <h3>2011 is classified, not resolved</h3>
            <p>
              The 2011 Bangkok flood is in the annual record, but an annual Landsat
              composite barely captures it. The 2011 row is a floor on extent, not a
              measurement of the flood peak, and it must not be read as one. The
              API&rsquo;s own interpretation notes are printed verbatim in the panel
              below.
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

function WarningList({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="warning-list" aria-label="API warnings">
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
      note="Water area is a lower bound for its year: unclassified water is not counted. The state column carries a glyph as well as a colour, and the baseline year is named."
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
