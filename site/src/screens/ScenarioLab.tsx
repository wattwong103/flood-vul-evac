/**
 * Scenario Lab — the primary screen.
 *
 * Two things are deliberately kept apart here:
 *  1. the flood *composition* the analyst is thinking about, which contract
 *     bkkflow-run-v0.1 cannot yet submit (there is no run-creation endpoint),
 *     so it is labelled as unsubmitted and never alters the figures below; and
 *  2. the immutable run artefact that every number on this screen comes from.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  CircleAlert,
  Clock3,
  Gauge,
  Map as MapIcon,
  Route,
  Users,
  Waves,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DEFAULT_LAYERS,
  LAYER_LABELS,
  MapView,
  SCENARIO_LAYER_IDS,
  extractRefuges,
  type LayerId,
  type LayerState,
  type MapBundle,
} from "@/components/MapView";
import {
  ErrorState,
  LoadingState,
  MetricCard,
  NoRunState,
  Panel,
  ValidationStamp,
  ValidationStatusNote,
} from "@/components/primitives";
import { useApi } from "@/hooks/useApi";
import { useRuns } from "@/lib/run-context";
import { availableModelTimes, shouldLoadStaticFallback } from "@/lib/map-copy";
import {
  API_BASE_URL,
  asFeatureCollection,
  floodPath,
  networkPath,
  populationGridPath,
  routesPath,
  studyAreaPath,
} from "@/lib/client";
import {
  isFloodSourceRole,
  evacuationReason,
  floodReason,
  floodStatus,
  type FloodResult,
  type MeshResult,
  type NetworkResult,
  type PopulationGridResponse,
  type RunStats,
  type StudyAreaProperties,
  type StudyAreaResponse,
} from "@/lib/api";
import {
  formatCount,
  formatModelClock,
  formatNumber,
  formatPeople,
  formatShare,
  formatSigned,
  formatText,
  formatTimestamp,
  NOT_COMPUTED,
  propNumber,
} from "@/lib/format";

const UNSUBMITTED_NOTE =
  "Contract bkkflow-run-v0.1 exposes no run-creation endpoint, so these values are not submitted and do not change the run shown. A changed input must produce a new immutable run, never a cosmetic update.";

type TideSeverity = "normal" | "rising" | "high";

export function ScenarioLab({ reducedMotion }: { reducedMotion: boolean }) {
  const { activeRunId, stats, detail, hasNoRun, reloadAll } = useRuns();

  const [layers, setLayers] = useState<LayerState>(DEFAULT_LAYERS);
  const [selectedTime, setSelectedTime] = useState<number | null>(null);
  const [profile, setProfile] = useState<string>("reported");
  const studyArea = useApi<StudyAreaResponse>(studyAreaPath, []);

  // --- Local, unsubmitted scenario composition -------------------------
  const [rainfall, setRainfall] = useState(150);
  const [river, setRiver] = useState(1.0);
  const [tide, setTide] = useState<TideSeverity>("normal");

  const runId = activeRunId;
  const encoded = runId ? encodeURIComponent(runId) : null;
  const isCity = stats.data?.scale === "city";

  // The unfiltered mesh response is the only place the run's own model times
  // are discoverable, so it drives the timeline.
  const meshAll = useApi<MeshResult>(encoded ? `/v1/runs/${encoded}/mesh` : null, [runId]);
  const floodIndex = useApi<FloodResult>(
    runId ? floodPath(runId, null, 1) : null,
    [runId],
  );

  const times = useMemo(() => {
    if (Array.isArray(meshAll.data?.available_times)) {
      return availableModelTimes(
        meshAll.data.available_times,
        floodIndex.data?.available_times,
      );
    }
    const collection = asFeatureCollection<{ time_s?: number | null }>(meshAll.data);
    const set = new Set<number>();
    for (const feature of collection.features) {
      const value = propNumber(feature.properties, "time_s");
      if (value !== null) set.add(value);
    }
    return availableModelTimes([...set], floodIndex.data?.available_times);
  }, [meshAll.data, floodIndex.data]);

  const activeTime = useMemo(() => {
    if (times.length === 0) return null;
    if (selectedTime !== null && times.includes(selectedTime)) return selectedTime;
    const peakFloodTime = floodIndex.data?.peak_time_s;
    if (typeof peakFloodTime === "number" && times.includes(peakFloodTime)) {
      return peakFloodTime;
    }
    return times[times.length - 1];
  }, [times, selectedTime, floodIndex.data]);

  useEffect(() => {
    if (selectedTime !== null && times.length > 0 && !times.includes(selectedTime)) {
      setSelectedTime(null);
    }
  }, [times, selectedTime]);

  const slicedMesh = useApi<unknown>(
    encoded && activeTime !== null
      ? `/v1/runs/${encoded}/mesh?time=${encodeURIComponent(String(activeTime))}`
      : null,
    [runId, activeTime],
  );

  const links = useApi<unknown>(
    encoded
      ? `/v1/runs/${encoded}/links${activeTime !== null ? `?time=${encodeURIComponent(String(activeTime))}` : ""}`
      : null,
    [runId, activeTime],
  );

  const buildings = useApi<unknown>(encoded && stats.phase === "ready" && !isCity ? `/v1/runs/${encoded}/buildings` : null, [runId, isCity, stats.phase]);

  // City runs publish a resident grid and a bounded network sample through
  // dedicated endpoints. Fetch those large fallbacks only after the primary
  // PFLOW layer is known to be empty.
  const primaryMeshData = activeTime !== null ? slicedMesh.data : meshAll.data;
  const primaryMeshPhase = activeTime !== null ? slicedMesh.phase : meshAll.phase;
  const primaryMeshCount = asFeatureCollection(primaryMeshData).features.length;
  const primaryLinkCount = asFeatureCollection(links.data).features.length;
  const cityPopulation = useApi<PopulationGridResponse>(
    runId && shouldLoadStaticFallback(primaryMeshPhase, primaryMeshCount)
      ? populationGridPath(runId)
      : null,
    [runId, primaryMeshPhase, primaryMeshCount],
  );
  const cityNetwork = useApi<NetworkResult>(
    runId && stats.phase === "ready" && !isCity && shouldLoadStaticFallback(links.phase, primaryLinkCount)
      ? networkPath(runId, 5000)
      : null,
    [runId, links.phase, primaryLinkCount, isCity, stats.phase],
  );

  const flood = useApi<FloodResult>(
    runId ? floodPath(runId, activeTime, 5000) : null,
    [runId, activeTime],
  );

  const evacuationRoutes = useApi<unknown>(
    runId ? routesPath(runId) : null,
    [runId],
  );

  const validation = useApi<unknown>(
    encoded ? `/v1/runs/${encoded}/validation` : null,
    [runId],
  );

  const modelTime = formatModelClock(activeTime);
  const payload: RunStats | null = stats.data ?? null;

  const status = payload?.validation_status ?? detail.data?.validation_status ?? null;
  const reportedProfile = payload?.population?.time_profile ?? null;

  const bundle = useMemo<MapBundle>(() => {
    const buildingCollection = asFeatureCollection<Record<string, unknown>>(
      buildings.data,
    );
    const routeCollection = asFeatureCollection<Record<string, unknown>>(
      evacuationRoutes.data,
    );
    const meshCollection = asFeatureCollection<Record<string, unknown>>(
      primaryMeshData,
    );
    const cityPopulationCollection = asFeatureCollection<Record<string, unknown>>(
      cityPopulation.data,
    );
    const linkCollection = asFeatureCollection<Record<string, unknown>>(links.data);
    const cityNetworkCollection = asFeatureCollection<Record<string, unknown>>(
      cityNetwork.data,
    );
    const floodCollection = asFeatureCollection<Record<string, unknown>>(flood.data);
    return {
      studyArea: asFeatureCollection<StudyAreaProperties>(studyArea.data),
      mesh:
        meshCollection.features.length > 0 ? meshCollection : cityPopulationCollection,
      links:
        linkCollection.features.length > 0 ? linkCollection : cityNetworkCollection,
      flood: floodCollection,
      buildings: buildingCollection,
      routes: routeCollection,
      refuges: extractRefuges(buildingCollection),
      // Observed extent is served per year on its own screen, never mixed into
      // the model-time bundle above.
      observedWater: { type: "FeatureCollection", features: [] },
    };
  }, [studyArea.data, primaryMeshData, links, cityPopulation, cityNetwork, flood, buildings, evacuationRoutes]);

  const sourceRoles = useMemo(() => {
    const roles = new Set<string>();
    for (const feature of bundle.flood.features) {
      const value = feature.properties?.source_role;
      if (typeof value === "string") roles.add(value);
    }
    const declared = payload?.flood?.source_role;
    if (declared) roles.add(declared);
    return [...roles].sort();
  }, [bundle.flood, payload]);

  const toggleLayer = useCallback((id: LayerId) => {
    setLayers((current) => ({ ...current, [id]: !current[id] }));
  }, []);

  // The run's reported profile drives the figure; any other profile is absent.
  const profileIsReported = profile === "reported" || profile === reportedProfile;
  const presentValue = profileIsReported
    ? (payload?.population?.people_present ?? null)
    : null;

  const anyLoading =
    stats.phase === "loading" ||
    meshAll.phase === "loading" ||
    slicedMesh.phase === "loading" ||
    floodIndex.phase === "loading" ||
    flood.phase === "loading" ||
    links.phase === "loading" ||
    buildings.phase === "loading" ||
    cityPopulation.phase === "loading" ||
    cityNetwork.phase === "loading" ||
    evacuationRoutes.phase === "loading";

  // A city run does not compute a flood depth: `max_depth_m` and `edges_closed`
  // are null and the state of the computation is reported separately. Pilot
  // runs carry a depth and the earlier `status` / `reason` keys. Both shapes are
  // read through the resolvers, and a null always renders as "not computed".
  const depthValue = payload?.flood?.max_depth_m ?? null;
  const depthComputed = depthValue !== null;
  const depthState = floodStatus(payload?.flood);
  const depthReason = floodReason(payload?.flood);
  const closedValue = payload?.flood?.edges_closed ?? null;

  return (
    <div className="scenario-lab">
      <aside className="lab-rail" aria-label="Scenario controls and layers">
        <p className="eyebrow">01 · Scenario Lab</p>
        <h1>Where can people still move?</h1>
        <p className="lead">
          The map always opens on the full Bangkok Metropolitan Administration
          boundary. Population and network data cover the city when a city run is
          selected; flood depth and evacuation remain visibly limited to the scope
          of the selected run. The observed JRC surface-water extent is on the
          Observed &amp; assets screen.
        </p>

        <RunPicker />

        <Card className="rail-card">
          <CardHeader>
            <CardTitle className="rail-title">
              <Waves size={15} aria-hidden="true" /> Flood conditions
            </CardTitle>
            <p className="rail-desc">{UNSUBMITTED_NOTE}</p>
          </CardHeader>
          <CardContent className="rail-body">
            <SliderField
              id="rainfall"
              label="Rainfall total"
              value={rainfall}
              min={0}
              max={300}
              step={5}
              suffix=" mm"
              onChange={setRainfall}
            />
            <SliderField
              id="river"
              label="River stage anomaly"
              value={river}
              min={-1}
              max={3}
              step={0.1}
              format={(value) => formatSigned(value, 1, "m")}
              onChange={setRiver}
            />
            <fieldset className="rail-field">
              <legend>Tide severity</legend>
              <div className="chip-row">
                {(["normal", "rising", "high"] as TideSeverity[]).map((option) => (
                  <Button
                    key={option}
                    type="button"
                    size="sm"
                    variant={tide === option ? "default" : "outline"}
                    aria-pressed={tide === option}
                    onClick={() => setTide(option)}
                  >
                    {option}
                  </Button>
                ))}
              </div>
            </fieldset>
            <p className="rail-note">
              Composed locally: {rainfall} mm rainfall · {formatSigned(river, 1, "m")}{" "}
              river · {tide} tide. Not submitted.
            </p>
          </CardContent>
        </Card>

        <Card className="rail-card">
          <CardHeader>
            <CardTitle className="rail-title">
              <CircleAlert size={15} aria-hidden="true" /> Flood source in this run
            </CardTitle>
          </CardHeader>
          <CardContent className="rail-body">
            <p className="rail-headline">
              {isFloodSourceRole(payload?.flood?.source_role)
                ? payload?.flood?.source_role
                : "not reported"}
            </p>
            <p className="rail-note">
              Model {formatText(payload?.flood?.model?.name)} · version{" "}
              {formatText(payload?.flood?.model?.version)}
            </p>
            <p className="rail-note">
              Depth computation: {floodStatus(payload?.flood) ?? "not reported"}
              {floodReason(payload?.flood) ? ` — ${floodReason(payload?.flood)}` : ""}
            </p>
            <ul className="role-list">
              {(["observed", "modelled", "scenario"] as const).map((role) => {
                const present = sourceRoles.includes(role);
                return (
                  <li key={role} className={present ? "present" : "absent"}>
                    <span aria-hidden="true" className="role-glyph">
                      {present ? "■" : "□"}
                    </span>
                    <b>{role}</b>
                    <span className="role-state">{present ? "present in this run" : "absent"}</span>
                  </li>
                );
              })}
            </ul>
            <p className="rail-note">
              Observed extent is a footprint, not a depth. Modelled and scenario depth
              are different products and are drawn separately.
            </p>
          </CardContent>
        </Card>

        <Card className="rail-card">
          <CardHeader>
            <CardTitle className="rail-title">
              <Clock3 size={15} aria-hidden="true" /> Time of day
            </CardTitle>
            <p className="rail-desc">
              The time-of-day profile changes how many people are present. It is a
              different quantity from how many are exposed.
            </p>
          </CardHeader>
          <CardContent className="rail-body">
            <Select value={profile} onValueChange={setProfile}>
              <SelectTrigger aria-label="Time-of-day profile">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="reported">
                  reported by this run{reportedProfile ? ` — ${reportedProfile}` : ""}
                </SelectItem>
                <SelectItem value="day">day</SelectItem>
                <SelectItem value="evening">evening</SelectItem>
                <SelectItem value="night">night</SelectItem>
              </SelectContent>
            </Select>
            <p className="rail-note">
              {profileIsReported
                ? `This run reports the "${reportedProfile ?? "unspecified"}" profile.`
                : `This run reports only the "${reportedProfile ?? "unspecified"}" profile, so people present for the selected period is not available. The model has not been run for it.`}
            </p>
          </CardContent>
        </Card>

        <Card className="rail-card">
          <CardHeader>
            <CardTitle className="rail-title">
              <MapIcon size={15} aria-hidden="true" /> Layers
            </CardTitle>
            <p className="rail-desc">Each layer names the quantity it represents.</p>
          </CardHeader>
          <CardContent className="rail-body">
            <ul className="layer-toggles">
              {SCENARIO_LAYER_IDS.map((id) => (
                <li key={id}>
                  <label>
                    <Switch
                      checked={layers[id]}
                      onCheckedChange={() => toggleLayer(id)}
                      aria-label={`Toggle ${LAYER_LABELS[id].name} layer`}
                    />
                    <span>
                      <b>{LAYER_LABELS[id].name}</b>
                      <small>{LAYER_LABELS[id].quantity}</small>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </aside>

      <div className="lab-main">
        {hasNoRun ? (
          <NoRunState
            what="scenario results"
            onReload={reloadAll}
            detail={
              <p className="muted">
                Start the API and publish a completed run, or check the Data registry for
                the sources that will produce one.
              </p>
            }
          />
        ) : null}

        {stats.phase === "error" && stats.error ? (
          <ErrorState error={stats.error} onRetry={stats.reload} context="Run statistics." />
        ) : null}

        {!hasNoRun && stats.phase === "error" ? null : (
          <>
            <Timeline
            times={times}
            activeTime={activeTime}
            onChange={setSelectedTime}
            modelTime={modelTime}
            status={status}
            />

            <div className="lab-map">
              {meshAll.phase === "error" && meshAll.error ? (
                <ErrorState
                  error={meshAll.error}
                  onRetry={meshAll.reload}
                  context="Mesh time slices for this run."
                />
              ) : null}
              {anyLoading ? <LoadingState label="Reading run artefacts from the API" /> : null}
              <MapView
                bundle={bundle}
                spatialRunId={isCity ? runId : null}
                layers={layers}
                modelTime={activeTime === null ? null : modelTime}
                areaName={formatText(payload?.geography?.name ?? "the pilot area")}
                reducedMotion={reducedMotion}
              />
            </div>

            <section className="metric-grid" aria-label="Headline metrics">
              <MetricCard
                label="People present"
                icon={<Users size={15} aria-hidden="true" />}
                value={formatPeople(presentValue)}
                quantity="PFLOW people present at the reported time-of-day profile"
                caption="Synthetic weighted agents inside the area. Not observed occupancy."
                status={status}
                modelTime={modelTime}
              />
              <MetricCard
                label="People exposed"
                icon={<Waves size={15} aria-hidden="true" />}
                value={formatPeople(payload?.population?.people_exposed ?? null)}
                quantity="PFLOW people exposed to modelled or scenario flood depth"
                caption={
                  <>
                    A different quantity from people present. These two are never summed
                    into a single figure.
                  </>
                }
                status={status}
                modelTime={modelTime}
              />
              <MetricCard
                label="Exposed share of present"
                icon={<Activity size={15} aria-hidden="true" />}
                value={formatShare(payload?.population?.exposed_share_of_present ?? null)}
                quantity="people exposed ÷ people present"
                caption="Undefined when either quantity is missing; not shown as 0%."
                status={status}
                modelTime={modelTime}
              />
              <MetricCard
                label="Maximum flood depth"
                icon={<Waves size={15} aria-hidden="true" />}
                value={depthComputed ? formatNumber(depthValue, 2) : NOT_COMPUTED}
                unit="m"
                quantity={`${
                  isFloodSourceRole(payload?.flood?.source_role ?? payload?.flood?.depth_source_role)
                    ? (payload?.flood?.source_role ?? payload?.flood?.depth_source_role)
                    : "unspecified"
                } flood source`}
                caption={
                  depthComputed ? (
                    "Depth comes from the model. Observed extent alone has no depth."
                  ) : (
                    <>
                      This run reports no depth: {depthState ?? "no status published"}
                      {depthReason ? ` — ${depthReason}` : ""}. A missing depth is
                      never shown as 0 m.
                    </>
                  )
                }
                status={status}
                modelTime={modelTime}
              />
              <MetricCard
                label="Road capacity loss"
                icon={<Route size={15} aria-hidden="true" />}
                value={formatShare(payload?.flood?.road_capacity_loss_share ?? null)}
                quantity="network capacity multiplier against the dry baseline"
                caption={
                  closedValue === null ? (
                    <>
                      Closed edges: {NOT_COMPUTED}
                      {depthReason ? ` — ${depthReason}` : ""}.
                    </>
                  ) : (
                    `${formatCount(closedValue)} of ${formatCount(
                      payload?.flood?.edges_total ?? null,
                    )} edges closed.`
                  )
                }
                status={status}
                modelTime={modelTime}
              />
              <MetricCard
                label="Clearance time, median"
                icon={<Gauge size={15} aria-hidden="true" />}
                value={formatNumber(payload?.evacuation?.clearance_time_minutes?.median ?? null, 0)}
                unit="min"
                quantity="weighted synthetic agents that reached a destination"
                caption={`p5 ${formatNumber(
                  payload?.evacuation?.clearance_time_minutes?.p5 ?? null,
                  0,
                )} min · p95 ${formatNumber(
                  payload?.evacuation?.clearance_time_minutes?.p95 ?? null,
                  0,
                )} min.`}
                status={status}
                modelTime={modelTime}
                emphasis
              />
              <MetricCard
                label="Evacuation cohort"
                icon={<Users size={15} aria-hidden="true" />}
                value={formatPeople(payload?.evacuation?.cohort_weighted ?? null)}
                quantity="agents the scenario marked eligible for evacuation"
                caption={`${formatPeople(
                  payload?.evacuation?.arrived_weighted ?? null,
                )} arrived · ${formatPeople(
                  payload?.evacuation?.unserved_weighted ?? null,
                )} unserved.`}
                status={status}
                modelTime={modelTime}
              />
              <MetricCard
                label="Flooded area"
                icon={<Waves size={15} aria-hidden="true" />}
                value={formatNumber(payload?.flood?.flooded_area_km2 ?? null, 2)}
                unit="km²"
                quantity={`area of ${
                  formatText(payload?.geography?.name ?? null)
                } (${formatNumber(payload?.geography?.area_km2 ?? null, 2)} km²)`}
                caption={`Analysis CRS ${formatText(payload?.geography?.analysis_crs ?? null)}.`}
                status={status}
                modelTime={modelTime}
              />
            </section>

            <section className="lab-footer" aria-label="Run provenance and validation">
              <Panel
                title="What this run is"
                description="A run is immutable. Changing an input produces a new run id."
              >
                <dl className="kv">
                  <div>
                    <dt>Run</dt>
                    <dd className="mono">{activeRunId ?? "none"}</dd>
                  </div>
                  <div>
                    <dt>Created</dt>
                    <dd>{formatTimestamp(payload?.created_at ?? detail.data?.created_at ?? null)}</dd>
                  </div>
                  <div>
                    <dt>Area of interest</dt>
                    <dd>{formatText(payload?.geography?.name ?? null)}</dd>
                  </div>
                  <div>
                    <dt>Population version</dt>
                    <dd>{formatText(payload?.population?.population_version ?? null)}</dd>
                  </div>
                  <div>
                    <dt>Flood depth</dt>
                    <dd>
                      {depthComputed
                        ? `${formatNumber(depthValue, 2)} m`
                        : `${NOT_COMPUTED}${depthReason ? ` — ${depthReason}` : ""}`}
                    </dd>
                  </div>
                  <div>
                    <dt>Evacuation reason</dt>
                    <dd>
                      {evacuationReason(payload?.evacuation) ??
                        "no run-level reason published"}
                    </dd>
                  </div>
                  <div>
                    <dt>Warnings</dt>
                    <dd>{(payload?.warnings ?? []).length || "none recorded"}</dd>
                  </div>
                </dl>
                <ValidationStatusNote status={status} />
                <ValidationStamp status={status} modelTime={modelTime} />
              </Panel>

              <Panel
                title="Validation checks"
                description="From the run's validation report. Thresholds are published, not tuned per viewer."
                actions={
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      window.open(
                        `${API_BASE_URL}/v1/runs/${encoded}/validation`,
                        "_blank",
                      )
                    }
                  >
                    Raw JSON
                  </Button>
                }
              >
                {validation.phase === "loading" ? <LoadingState label="Reading validation report" /> : null}
                {validation.phase === "error" && validation.error ? (
                  <ErrorState error={validation.error} onRetry={validation.reload} />
                ) : null}
                {validation.phase === "ready" ? (
                  <ValidationSummary report={validation.data} />
                ) : null}
                {validation.phase === "missing" ? (
                  <p className="muted">
                    This run published no validation report. Absence of a report is not a
                    passing result.
                  </p>
                ) : null}
              </Panel>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ *
 * Pieces
 * ------------------------------------------------------------------ */

function RunPicker() {
  const { runs, activeRunId, setActiveRunId } = useRuns();
  const list = Array.isArray(runs.data) ? runs.data : [];

  return (
    <div className="run-picker">
      <label htmlFor="run-select">Run</label>
      {list.length === 0 ? (
        <p className="muted" id="run-select">
          No runs listed. {runs.phase === "loading" ? "Asking the API…" : ""}
        </p>
      ) : (
        <Select value={activeRunId ?? undefined} onValueChange={setActiveRunId}>
          <SelectTrigger id="run-select" aria-label="Select a run">
            <SelectValue placeholder="Select a run" />
          </SelectTrigger>
          <SelectContent>
            {list.map((run) => (
              <SelectItem key={run.run_id} value={run.run_id}>
                {run.run_id.slice(0, 8)} · {formatTimestamp(run.created_at)}
                {run.status ? ` · ${run.status}` : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      {runs.phase === "error" && runs.error ? (
        <p className="muted" role="status">
          The run list is unavailable: {runs.error.message}
        </p>
      ) : null}
    </div>
  );
}

function SliderField({
  id,
  label,
  value,
  min,
  max,
  step,
  suffix,
  format,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix?: string;
  format?: (value: number) => string;
  onChange: (value: number) => void;
}) {
  return (
    <div className="rail-field">
      <div className="rail-field-head">
        <label htmlFor={id}>{label}</label>
        <output htmlFor={id}>{format ? format(value) : `${value}${suffix ?? ""}`}</output>
      </div>
      <Slider
        id={id}
        value={[value]}
        min={min}
        max={max}
        step={step}
        onValueChange={(next) => onChange(next[0] ?? value)}
        aria-label={label}
      />
    </div>
  );
}

function Timeline({
  times,
  activeTime,
  onChange,
  modelTime,
  status,
}: {
  times: number[];
  activeTime: number | null;
  onChange: (value: number) => void;
  modelTime: string;
  status: string | null;
}) {
  const index = activeTime === null ? -1 : times.indexOf(activeTime);
  return (
    <div className="timeline-bar">
      <div className="timeline-clock">
        <Clock3 size={15} aria-hidden="true" />
        <div>
          <p className="timeline-label">Model time</p>
          <p className="timeline-value">
            {activeTime === null ? "not available" : modelTime}
            {activeTime !== null ? (
              <span className="muted"> · {activeTime} s into the run</span>
            ) : null}
          </p>
        </div>
        <ValidationStamp status={status} modelTime={modelTime} compact />
      </div>
      {times.length <= 1 ? (
        <p className="muted timeline-hint">
          {times.length === 0
            ? "This run published no model time steps, so there is nothing to scrub."
            : "This run published a single model time step."}
        </p>
      ) : (
        <div className="rail-field timeline-slider">
          <label htmlFor="model-time">
            Scrub {times.length} served model times ({formatModelClock(times[0])} –{" "}
            {formatModelClock(times[times.length - 1])})
          </label>
          <Slider
            id="model-time"
            value={[Math.max(0, index)]}
            min={0}
            max={times.length - 1}
            step={1}
            onValueChange={(next) => {
              const position = next[0] ?? 0;
              const value = times[position];
              if (value !== undefined) onChange(value);
            }}
            aria-label="Model time step"
          />
        </div>
      )}
    </div>
  );
}

function ValidationSummary({ report }: { report: unknown }) {
  const checks = Array.isArray((report as { checks?: unknown })?.checks)
    ? ((report as { checks: Array<Record<string, unknown>> }).checks)
    : [];

  if (checks.length === 0) {
    return <p className="muted">The report contains no individual checks.</p>;
  }

  return (
    <ul className="check-list">
      {checks.map((check, index) => {
        const name = String(check.name ?? check.check ?? `check ${index + 1}`);
        const passed =
          typeof check.passed === "boolean"
            ? check.passed
            : String(check.status ?? "").toLowerCase() === "pass";
        const result = check.result ?? null;
        const threshold = check.threshold ?? null;
        return (
          <li key={`${name}-${index}`}>
            <span aria-hidden="true" className={`check-glyph ${passed ? "pass" : "fail"}`}>
              {passed ? "✓" : "✕"}
            </span>
            <span className="check-name">
              {name}
              {check.notes ? <small>{String(check.notes)}</small> : null}
            </span>
            <span className="check-values">
              <span>result {result === null ? "not available" : String(result)}</span>
              <span>threshold {threshold === null ? "not available" : String(threshold)}</span>
            </span>
            <Badge variant="outline">{passed ? "pass" : "fail"}</Badge>
          </li>
        );
      })}
    </ul>
  );
}
