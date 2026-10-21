/**
 * "The flood" (BKK-055c): how big a what-if flood is, how deep, and whether
 * people can still move, at one model time of one run.
 *
 * The readings come from `/v1/runs/{id}/flood-summary`; the map reuses the
 * shared flood and road layers at the same time, with roads drawn for the mode
 * the reader picks. Past floods seen by satellite stay on the Observed & assets
 * screen until the Past tab lands (design note, section 4.1).
 */

import { useMemo, useState } from "react";
import { FloodReadings } from "@/components/FloodReadings";
import { MapStatsGate } from "@/components/MapStatsGate";
import { MapView, type LayerState, type MapBundle } from "@/components/MapView";
import { ErrorState, LoadingState, NoRunState, PageIntro, Panel } from "@/components/primitives";
import { useApi } from "@/hooks/useApi";
import type { FloodResult, FloodSummary, StudyAreaProperties, StudyAreaResponse } from "@/lib/api";
import { asFeatureCollection, floodPath, floodSummaryPath, studyAreaPath } from "@/lib/client";
import { depthRulerMarks, type RulerMark } from "@/lib/flood-summary";
import { formatModelClock, formatText } from "@/lib/format";
import { useRuns } from "@/lib/run-context";
import { RunPicker, Timeline } from "@/screens/ScenarioLab";

/** Only the flood and the roads: the two layers the readings describe. */
const FLOOD_LAYERS: LayerState = {
  population: false,
  flood: true,
  buildings: false,
  network: true,
  routes: false,
  refuges: false,
  observedWater: false,
};

/** PFLOW mode codes, as `/links?mode=` accepts them. */
const ROAD_MODES = [
  { code: "0", label: "Roads for walking" },
  { code: "3", label: "Roads for car / motorcycle" },
] as const;

const DEEPEST_LABEL = "Deepest water now";

/** The layers this screen leaves off still need a (typed) empty collection. */
const empty = () => asFeatureCollection<Record<string, unknown>>(null);

export function TheFlood({ reducedMotion }: { reducedMotion: boolean }) {
  const { activeRunId: runId, stats, hasNoRun, reloadAll } = useRuns();
  const [picked, setPicked] = useState<{ runId: string | null; time: number } | null>(null);
  const [roadMode, setRoadMode] = useState<string>(ROAD_MODES[0].code);

  // A time picked on one run means nothing on another, whose clock differs:
  // it is dropped, and the summary chooses the new run's peak.
  const selectedTime = picked !== null && picked.runId === runId ? picked.time : null;
  const setSelectedTime = (time: number) => setPicked({ runId, time });

  const summary = useApi<FloodSummary>(
    runId ? floodSummaryPath(runId, selectedTime) : null,
    [runId, selectedTime],
  );
  const activeTime = summary.data?.time_s ?? null;
  const times = summary.data?.available_times ?? [];
  const modelTime = formatModelClock(activeTime);
  const status = summary.data?.validation_status ?? stats.data?.validation_status ?? null;

  const studyArea = useApi<StudyAreaResponse>(studyAreaPath, []);
  const flood = useApi<FloodResult>(
    runId && activeTime !== null ? floodPath(runId, activeTime, 5000) : null,
    [runId, activeTime],
  );
  const links = useApi<unknown>(
    runId && activeTime !== null
      ? `/v1/runs/${encodeURIComponent(runId)}/links?time=${activeTime}&mode=${roadMode}`
      : null,
    [runId, activeTime, roadMode],
  );

  const bundle = useMemo<MapBundle>(
    () => ({
      studyArea: asFeatureCollection<StudyAreaProperties>(studyArea.data),
      mesh: empty(),
      flood: asFeatureCollection<Record<string, unknown>>(flood.data),
      links: asFeatureCollection<Record<string, unknown>>(links.data),
      buildings: empty(),
      routes: empty(),
      refuges: empty(),
      observedWater: empty(),
    }),
    [studyArea.data, flood.data, links.data],
  );

  return (
    <div className="page flood-page">
      <PageIntro
        kicker="The flood"
        title="How big, how deep, and can people still move?"
        lead={
          <>
            A what-if flood: a declared scenario, not a forecast and not an observation.
            Depth spreads out from mapped waterways; roads close at the project&rsquo;s declared
            depths. Past floods seen by satellite are on the Observed &amp; assets screen.
          </>
        }
      />

      <div className="flood-controls">
        <RunPicker />
        <div className="flood-mode" role="group" aria-label="Roads drawn on the map">
          {ROAD_MODES.map((mode) => (
            <button
              key={mode.code}
              type="button"
              className={roadMode === mode.code ? "active" : ""}
              aria-pressed={roadMode === mode.code}
              onClick={() => setRoadMode(mode.code)}
            >
              {mode.label}
            </button>
          ))}
        </div>
      </div>

      {hasNoRun ? <NoRunState what="flood readings" onReload={reloadAll} /> : null}
      {summary.phase === "error" && summary.error ? (
        <ErrorState error={summary.error} onRetry={summary.reload} context="Flood summary for this run." />
      ) : null}
      {summary.phase === "loading" && !summary.data ? (
        <LoadingState label="Reading the flood summary" />
      ) : null}

      {summary.data ? (
        <>
          <Timeline
            times={times}
            activeTime={activeTime}
            onChange={setSelectedTime}
            modelTime={modelTime}
            status={status}
          />
          <FloodReadings summary={summary.data} status={status} modelTime={modelTime} />
          <Panel
            title="Depth ruler"
            description={`Depths at which each mode stops, from the declared threshold set ${formatText(
              summary.data.threshold_set_version,
            )}, against the deepest water at ${modelTime}.`}
          >
            <DepthRuler marks={depthRulerMarks(summary.data)} />
          </Panel>
          <MapStatsGate stats={stats} runId={runId}>
            <MapView
              bundle={bundle}
              layers={FLOOD_LAYERS}
              modelTime={activeTime === null ? null : modelTime}
              areaName={formatText(stats.data?.geography?.name ?? "the pilot area")}
              reducedMotion={reducedMotion}
            />
          </MapStatsGate>
        </>
      ) : null}
    </div>
  );
}

function DepthRuler({ marks }: { marks: RulerMark[] }) {
  if (marks.length === 0) {
    return <p className="muted">This run has no depth to measure against.</p>;
  }
  // Scale to the deeper of 0.6 m and the deepest mark, so ticks never overflow.
  const top = Math.max(0.6, ...marks.map((mark) => mark.depthM));
  return (
    <div className="depth-ruler">
      <div className="depth-track" aria-hidden="true">
        {marks.map((mark) => (
          <span
            key={mark.label}
            className={`depth-tick${mark.label === DEEPEST_LABEL ? " now" : ""}`}
            style={{ left: `${(mark.depthM / top) * 100}%` }}
          />
        ))}
      </div>
      <ol className="depth-marks">
        {marks.map((mark) => (
          <li key={mark.label}>
            <b>{mark.depthM.toFixed(2)} m</b> {mark.label}
          </li>
        ))}
      </ol>
    </div>
  );
}
