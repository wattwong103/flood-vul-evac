/**
 * The flood screen's Past tab (BKK-055c part 2): water seen by satellite in a
 * past year, or everywhere ever seen as water in 1984-2021.
 *
 * Observed water lives only in the citywide run, so this tab reads the newest
 * citywide run on its own and names it, whatever pilot run is selected for the
 * what-if view (North, 22 October 2026). Extent only: depth is Unknown and
 * movement waits for an admitted citywide run (BKK-040).
 */

import { useMemo, useState, type ReactNode } from "react";
import { PastReadings } from "@/components/PastReadings";
import { MapView, type LayerState, type MapBundle } from "@/components/MapView";
import { ErrorState, LoadingState, PageIntro } from "@/components/primitives";
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
  EVER,
  newestCityRun,
  pastCellsPath,
  pastYears,
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

/** 2011 is the flood readers look for first, when the record has it. */
const PREFERRED_YEAR = 2011;

const empty = () => asFeatureCollection<Record<string, unknown>>(null);

const choiceLabel = (choice: PastChoice) => (choice === EVER ? "1984–2021" : String(choice));

export function PastFlood({ reducedMotion, switcher }: { reducedMotion: boolean; switcher: ReactNode }) {
  const { runs } = useRuns();
  const cityRun = newestCityRun(runs.data);
  const cityId = cityRun?.run_id ?? null;

  const observed = useApi<ObservedWaterResponse>(cityId ? observedWaterPath(cityId) : null, [cityId]);
  const years = pastYears(observed.data);
  const [picked, setPicked] = useState<PastChoice | null>(null);
  const choice: PastChoice | null =
    picked ?? (years.includes(PREFERRED_YEAR) ? PREFERRED_YEAR : (years[years.length - 1] ?? null));

  const ever = useApi<EverWater>(cityId ? pastCellsPath(cityId, EVER) : null, [cityId]);
  const yearCells = useApi<unknown>(
    cityId && choice !== null && choice !== EVER ? pastCellsPath(cityId, choice) : null,
    [cityId, choice],
  );
  const studyArea = useApi<StudyAreaResponse>(studyAreaPath, []);

  const cells = choice === EVER ? ever.data : yearCells.data;
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
    choice !== null && choice !== EVER
      ? (observed.data?.years ?? []).find((entry) => entry.year === choice) ?? null
      : null;
  const status = cityRun?.validation_status ?? null;

  return (
    <div className="page flood-page">
      <PageIntro
        kicker="The flood"
        title="How big, how deep, and can people still move?"
        lead={
          <>
            Past floods seen by satellite (JRC Global Surface Water): where water was, not how
            deep, and a yearly layer is not one flood event. Read from citywide run{" "}
            <span className="mono">{cityId ? cityId.slice(0, 8) : "none"}</span>
            {status ? ` (${status})` : ""}, whatever run is selected for the what-if view.
          </>
        }
      />

      {switcher}

      {runs.phase === "ready" && !cityRun ? (
        <p className="muted" role="status">
          No citywide run is published, so there is no observed-water record to show.
        </p>
      ) : null}
      {observed.phase === "error" && observed.error ? (
        <ErrorState error={observed.error} onRetry={observed.reload} context="Observed water for the citywide run." />
      ) : null}
      {observed.phase === "loading" ? <LoadingState label="Reading the observed-water record" /> : null}

      {cityId && choice !== null ? (
        <>
          <div className="flood-mode" role="group" aria-label="Which past layer">
            {[...years, EVER].map((option) => (
              <button
                key={String(option)}
                type="button"
                className={choice === option ? "active" : ""}
                aria-pressed={choice === option}
                onClick={() => setPicked(option)}
              >
                {choiceLabel(option)}
              </button>
            ))}
          </div>
          <PastReadings
            choice={choice}
            label={choiceLabel(choice)}
            year={yearEntry}
            ever={ever.data}
            status={status}
          />
          {[ever, yearCells].map((layer, index) =>
            layer.phase === "error" && layer.error ? (
              <ErrorState
                key={index === 0 ? "ever" : "year"}
                error={layer.error}
                onRetry={layer.reload}
                context={index === 0 ? "The 1984–2021 extent." : "Observed water cells for the map."}
              />
            ) : null,
          )}
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
