/**
 * The flood screen's Past tab (BKK-055c part 2): water seen by satellite in a
 * past year, or everywhere ever seen as water in 1984-2021.
 *
 * Observed water lives only in the citywide run, so this tab reads the newest
 * citywide run on its own and names it, whatever pilot run is selected for the
 * what-if view (North, 22 October 2026). Extent only: depth is Unknown and
 * movement waits for an admitted citywide run (BKK-040).
 *
 * `useApi` keeps the last answer while the next one loads, so every response
 * is checked against the run and layer it was asked for before it is shown.
 */

import { useMemo } from "react";
import { PastReadings } from "@/components/PastReadings";
import { MapView, type LayerState, type MapBundle } from "@/components/MapView";
import { ErrorState, LoadingState } from "@/components/primitives";
import { useApi } from "@/hooks/useApi";
import type {
  EverWater,
  ObservedWaterResponse,
  StudyAreaProperties,
  StudyAreaResponse,
} from "@/lib/api";
import { asFeatureCollection, observedWaterPath, studyAreaPath } from "@/lib/client";
import { formatText } from "@/lib/format";
import {
  cellsMatch,
  EVER,
  forRun,
  newestCityRun,
  pastCellsPath,
  pastYears,
  resolvePastChoice,
  type PastChoice,
} from "@/lib/past-flood";
import { useRuns } from "@/lib/run-context";

/** Only the observed-water cells: never mixed with a scenario layer. */
const PAST_LAYERS: LayerState = {
  population: false,
  flood: false,
  buildings: false,
  network: false,
  routes: false,
  refuges: false,
  observedWater: true,
};

const empty = () => asFeatureCollection<Record<string, unknown>>(null);
const choiceLabel = (choice: PastChoice) => (choice === EVER ? "1984–2021" : String(choice));

function warningMessages(payload: unknown): string[] {
  const warnings = (payload as { warnings?: unknown } | null)?.warnings;
  if (!Array.isArray(warnings)) return [];
  return warnings.flatMap((warning) => {
    const message = (warning as { message?: unknown } | null)?.message;
    return typeof message === "string" && message ? [message] : [];
  });
}

export function PastFlood({
  reducedMotion,
  picked,
  onPick,
}: {
  reducedMotion: boolean;
  picked: PastChoice | null;
  onPick: (choice: PastChoice) => void;
}) {
  const { runs } = useRuns();
  const cityRun = newestCityRun(runs.data);
  const cityId = cityRun?.run_id ?? null;
  const status = cityRun?.validation_status ?? null;

  const observedState = useApi<ObservedWaterResponse>(cityId ? observedWaterPath(cityId) : null, [cityId]);
  const observed = forRun(observedState.data, cityId);
  const years = pastYears(observed);
  const recordPending = cityId !== null && observed === null && observedState.phase === "loading";
  const choice = resolvePastChoice(picked, years, { pending: recordPending });

  // The extent's totals and cells come in one response, asked for only when shown.
  const everState = useApi<EverWater>(
    cityId && choice === EVER ? pastCellsPath(cityId, EVER) : null,
    [cityId, choice === EVER],
  );
  const ever = forRun(everState.data, cityId);
  const yearCells = useApi<unknown>(
    cityId && choice !== null && choice !== EVER ? pastCellsPath(cityId, choice) : null,
    [cityId, choice],
  );
  const studyArea = useApi<StudyAreaResponse>(studyAreaPath, []);

  // cellsMatch checks the run as well as the layer, so the raw responses suffice.
  const cellsPayload = choice === EVER ? everState.data : yearCells.data;
  const cells = choice !== null && cellsMatch(cellsPayload, cityId, choice) ? cellsPayload : null;
  const bundle = useMemo<MapBundle>(
    () => ({
      studyArea: asFeatureCollection<StudyAreaProperties>(studyArea.data),
      mesh: empty(),
      flood: empty(),
      links: empty(),
      buildings: empty(),
      routes: empty(),
      refuges: empty(),
      observedWater: asFeatureCollection<Record<string, unknown>>(cells),
    }),
    [studyArea.data, cells],
  );

  const yearEntry =
    choice !== null && choice !== EVER ? (observed?.years ?? []).find((entry) => entry.year === choice) ?? null : null;
  const layerState = choice === EVER ? everState : yearCells;
  const loading = runs.phase === "loading" || observedState.phase === "loading" || layerState.phase === "loading";
  const notes = [...new Set([...warningMessages(observed), ...warningMessages(cells)])];

  return (
    <div className="flood-view" aria-busy={loading}>
      <p className="flood-source">
        Past floods seen by satellite (JRC Global Surface Water): where water was, not how deep,
        and a yearly layer is not one flood event. Read from citywide run{" "}
        <span className="mono">{cityId ? cityId.slice(0, 8) : "none"}</span>
        {status ? ` (${status})` : ""}, whatever run is selected for the what-if view.
      </p>

      {runs.phase === "loading" ? <LoadingState label="Reading the run list" /> : null}
      {runs.phase === "error" && runs.error ? (
        <ErrorState error={runs.error} onRetry={runs.reload} context="The run list." />
      ) : null}
      {runs.phase === "ready" && !cityRun ? (
        <p className="muted" role="status">
          No citywide run is listed, so there is no observed-water record to show.
        </p>
      ) : null}
      {observedState.phase === "error" && observedState.error ? (
        <ErrorState error={observedState.error} onRetry={observedState.reload} context="Observed water for the citywide run." />
      ) : null}
      {observedState.phase === "missing" ? (
        <p className="muted" role="status">This citywide run has no observed-water record.</p>
      ) : null}
      {observed && years.length === 0 ? (
        <p className="muted" role="status">
          This citywide run records no past years; only the 1984–2021 extent can be shown.
        </p>
      ) : null}

      {cityId && choice !== null ? (
        <>
          <div className="flood-mode" role="group" aria-label="Which past layer">
            {[...years, EVER].map((option) => (
              <button
                key={String(option)}
                type="button"
                className={choice === option ? "active" : ""}
                aria-pressed={choice === option}
                aria-label={option === EVER ? "Ever seen as water, 1984–2021" : `Water seen in ${option}`}
                onClick={() => onPick(option)}
              >
                {choiceLabel(option)}
              </button>
            ))}
          </div>
          <PastReadings
            choice={choice}
            label={choiceLabel(choice)}
            year={yearEntry}
            ever={ever}
            everLoading={choice === EVER && everState.phase === "loading"}
            status={status}
          />
          {notes.length > 0 ? (
            <ul className="reading-notes" aria-label="Notes from the data">
              {notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ) : null}
          {layerState.phase === "missing" ? (
            <p className="muted" role="status">
              The map cells for this layer are unavailable, so the map shows none; that is not
              an absence of water.
            </p>
          ) : null}
          {layerState.phase === "error" && layerState.error ? (
            <ErrorState
              error={layerState.error}
              onRetry={layerState.reload}
              context={choice === EVER ? "The 1984–2021 extent." : "Observed water cells for the map."}
            />
          ) : null}
          <MapView
            bundle={bundle}
            layers={PAST_LAYERS}
            modelTime={null}
            areaName={formatText("Bangkok")}
            reducedMotion={reducedMotion}
          />
        </>
      ) : null}
    </div>
  );
}
