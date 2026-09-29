/**
 * Method — plain-language pipeline, assumptions, uncertainty, validation.
 *
 * The prose is the product's own explanation. Every status claim on this page
 * is read from the API, not asserted here.
 */

import { ArrowRight, CircleAlert, Compass, Waves } from "lucide-react";
import {
  ErrorState,
  LoadingState,
  PageIntro,
  Panel,
  ValidationStamp,
  ValidationStatusNote,
} from "@/components/primitives";
import { useApi } from "@/hooks/useApi";
import { useRuns } from "@/lib/run-context";
import { isFloodSourceRole, VALIDATION_STATUSES } from "@/lib/api";
import { formatNumber, formatText } from "@/lib/format";

const STAGES = [
  {
    n: "01",
    title: "Sources and licence gate",
    text: "Every input is checked for public access and explicit reuse permission before it can enter the pipeline. A dataset that is merely public is held at verify.",
  },
  {
    n: "02",
    title: "People and activities",
    text: "Weighted synthetic people are generated from an approved resident baseline, then given Bangkok activity chains. Japan-side population and behaviour parameters are not transferred.",
  },
  {
    n: "03",
    title: "Trips and trajectories",
    text: "Mode-labelled trips are routed on a dated OpenStreetMap graph. PFLOW-compatible trip and waypoint records are kept so downstream PFLOW tooling still works.",
  },
  {
    n: "04",
    title: "Flood intervention",
    text: "Observed extent and modelled depth become time-varying edge impedance, building exposure and explicit destination constraints. The three flood sources stay separate.",
  },
  {
    n: "05",
    title: "Evacuation and aggregation",
    text: "Agents respond on the dynamic graph, then mesh volumes, link volumes, clearance distributions and bottlenecks are published with their uncertainty.",
  },
];

/** Reads a loosely-typed config field without asserting its runtime type. */
function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

const ASSUMPTIONS = [  {
    title: "Drainage is a scenario, not a measurement",
    text: "Bangkok's canals, pumps and gates are major determinants of flood extent. Where no open, licensed operational data exists, drainage capacity is an explicit scenario assumption and is labelled as one.",
  },
  {
    title: "Observed extent is not depth",
    text: "A satellite or agency footprint records where water was seen, not how deep it was. Depth comes from the model and carries its own source role.",
  },
  {
    title: "Height is an estimate, not a survey",
    text: "Building height prefers measured values, then explicit OSM tags, then a remote-sensing estimate. A remote-sensing height is a modelled surface, not a surveyed building.",
  },
  {
    title: "A tall building is not a shelter",
    text: "Refuge status is a separate verified record covering access, capacity, operation and structural suitability. A destination that is not verified is drawn as unverified and must not be treated as safe.",
  },
  {
    title: "Residents are not daytime presence",
    text: "People present comes from the activity model, not from the resident grid. The two are reported as separate quantities and never substituted for one another.",
  },
  {
    title: "Behaviour is not shortest-path choice",
    text: "Departure delay, compliance, assistance needs and household grouping are social and institutional questions. They are modelled as scenarios with stated parameters, not solved.",
  },
];

export function Method() {
  const { activeRunId, stats, detail, hasNoRun } = useRuns();
  const encoded = activeRunId ? encodeURIComponent(activeRunId) : null;

  const config = useApi<Record<string, unknown>>("/v1/config", []);
  const validation = useApi<Record<string, unknown>>(
    encoded ? `/v1/runs/${encoded}/validation` : null,
    [activeRunId],
  );

  const status =
    stats.data?.validation_status ?? detail.data?.validation_status ?? null;
  const checks = Array.isArray(validation.data?.checks)
    ? (validation.data.checks as Array<Record<string, unknown>>)
    : [];

  return (
    <main className="page method-page">
      <PageIntro
        kicker="04 · Method"
        title={
          <>
            Keep the contract.
            <br />
            Rebuild the evidence.
          </>
        }
        lead="PFLOW supplies the research spine — people, activities, trips, trajectories, mesh and link volumes. Bangkok brings new open inputs, a flood intervention, an evacuation response and a validation contract. Contract compatibility is not behavioural validity."
      />

      <section className="method-flow" aria-label="Pipeline stages">
        {STAGES.map((stage, index) => (
          <article key={stage.n}>
            <p className="method-number">{stage.n}</p>
            <h2>{stage.title}</h2>
            <p>{stage.text}</p>
            {index < STAGES.length - 1 ? (
              <ArrowRight className="method-arrow" size={18} aria-hidden="true" />
            ) : null}
          </article>
        ))}
      </section>

      <section className="method-grid">
        <Panel
          title={
            <>
              <Compass size={16} aria-hidden="true" /> Assumptions
            </>
          }
          description="Each of these is a modelling choice, not a discovered fact."
        >
          <ul className="assumption-list">
            {ASSUMPTIONS.map((item) => (
              <li key={item.title}>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel
          title="Uncertainty position"
          description="What this prototype does and does not claim."
        >
          <p>
            A run is a single stochastic draw from a fixed seed. Point outputs are
            therefore one sample, not a best estimate with an interval around it. Clearance
            time is published as a p5, median and p95 distribution rather than an average,
            and bottleneck locations are the ones that bind, not the fastest routes.
          </p>
          <p>
            Repeated runs with different seeds quantify sampling variability. Repeat runs
            with the same seed and the same manifest reproduce identical outputs, which is
            a reproducibility property and not evidence of correctness.
          </p>
          <p className="panel-note">
            <CircleAlert size={14} aria-hidden="true" />
            Because the pilot is at demonstration status, no interval, score or map on
            this site may be quoted as an operational forecast.
          </p>
        </Panel>
      </section>

      <section className="validation-band">
        <div>
          <p className="eyebrow">Validation status</p>
          <h2>What has to be true before launch</h2>
          <ValidationStatusNote status={status} />
          <ValidationStamp
            status={status}
            modelTime={formatText(stats.data?.created_at ?? null)}
          />
          {!hasNoRun ? (
            <p className="muted">
              Reported for the selected run. The API copies this from the manifest; the
              site never infers it.
            </p>
          ) : (
            <p className="muted">No run is selected, so no status can be reported.</p>
          )}
        </div>

        <div>
          <ol className="gate-list">
            <li>
              <b>Population and behaviour.</b> Fit the synthetic people, activity chains,
              trip rates and modes to held-out Bangkok evidence.
            </li>
            <li>
              <b>Flood accuracy.</b> Validate extent against held-out observation and depth
              against licensed local measurement.
            </li>
            <li>
              <b>Building height.</b> Compare remote-sensing height against a representative
              Bangkok sample. Published non-Thailand error is not local accuracy.
            </li>
            <li>
              <b>Refuge truth.</b> Never infer safety from height. Capacity, access,
              operation and structural suitability each need a verified record.
            </li>
            <li>
              <b>Latency and ownership.</b> Operational use additionally requires signed
              operating procedures, a data-latency budget and institutional ownership.
            </li>
          </ol>
        </div>
      </section>

      <section className="status-scale" aria-label="Validation status vocabulary">
        <h2>Status vocabulary</h2>
        <p className="muted">
          The API exposes one of these four values. A run starts and, in the pilot, stays
          at the first.
        </p>
        <ul>
          {VALIDATION_STATUSES.map((value) => (
            <li key={value} className={value === status ? "current" : ""}>
              <span aria-hidden="true" className="status-glyph">
                {value === status ? "◆" : "○"}
              </span>
              <b>{value}</b>
              {value === status ? <em>this run</em> : null}
            </li>
          ))}
        </ul>
      </section>

      <section className="method-foot">
        <Panel title="Pilot configuration" description="From GET /v1/config.">
          {config.phase === "loading" ? <LoadingState label="Reading configuration" /> : null}
          {config.phase === "error" && config.error ? (
            <ErrorState error={config.error} onRetry={config.reload} />
          ) : null}
          {config.phase === "ready" && config.data ? (
            <dl className="kv">
              <div>
                <dt>Area of interest</dt>
                <dd>{formatText(asString(config.data.aoi_name ?? config.data.name))}</dd>
              </div>
              <div>
                <dt>Area (km²)</dt>
                <dd>{formatNumber(asNumber(config.data.area_km2), 2)}</dd>
              </div>
              <div>
                <dt>CRS</dt>
                <dd>{formatText(asString(config.data.crs ?? config.data.analysis_crs))}</dd>
              </div>
              <div>
                <dt>Declared scenario status</dt>
                <dd>
                  {formatText(
                    asString(config.data.scenario_status ?? config.data.declared_scenario_status),
                  )}
                </dd>
              </div>
              <div>
                <dt>Contract version</dt>
                <dd>{formatText(asString(config.data.contract_version))}</dd>
              </div>
            </dl>
          ) : null}
        </Panel>

        <Panel
          title={
            <>
              <Waves size={16} aria-hidden="true" /> Flood source in use
            </>
          }
          description="Observed, modelled and scenario flood are different products."
        >
          <p className="source-role-line">
            This run declares:{" "}
            <b>
              {isFloodSourceRole(stats.data?.flood?.source_role)
                ? stats.data?.flood?.source_role
                : "not reported"}
            </b>
          </p>
          <ul className="role-explainer">
            <li>
              <b>Observed</b> — where water was seen, at an acquisition time. No depth.
            </li>
            <li>
              <b>Modelled</b> — depth from a solver, with a model name and version.
            </li>
            <li>
              <b>Scenario</b> — assumed forcing for exploration. Not a prediction.
            </li>
          </ul>
          <p className="muted">
            Model {formatText(stats.data?.flood?.model?.name ?? null)} · version{" "}
            {formatText(stats.data?.flood?.model?.version ?? null)}
          </p>
        </Panel>

        <Panel
          title="Published checks"
          description={
            checks.length > 0
              ? `${checks.length} check${checks.length === 1 ? "" : "s"} in the run's validation report.`
              : "No checks have been published for the selected run."
          }
        >
          {validation.phase === "loading" ? <LoadingState label="Reading validation report" /> : null}
          {validation.phase === "error" && validation.error ? (
            <ErrorState error={validation.error} onRetry={validation.reload} />
          ) : null}
          {validation.phase === "ready" ? (
            <ul className="check-list">
              {checks.length === 0 ? (                <li>
                  <span aria-hidden="true" className="check-glyph warn">
                    !
                  </span>
                  <span className="check-name">
                    The report is empty. An empty report is not a passing result.
                  </span>
                </li>
              ) : (
                checks.map((check, index) => {
                  const name = String(check.name ?? check.check ?? `check ${index + 1}`);
                  const passed =
                    typeof check.passed === "boolean"
                      ? check.passed
                      : String(check.status ?? "").toLowerCase() === "pass";
                  return (
                    <li key={`${name}-${index}`}>
                      <span
                        aria-hidden="true"
                        className={`check-glyph ${passed ? "pass" : "fail"}`}
                      >
                        {passed ? "✓" : "✕"}
                      </span>
                      <span className="check-name">
                        {name}
                        <small>
                          result {formatText(check.result as string | null)} · threshold{" "}
                          {formatText(check.threshold as string | null)}
                        </small>
                      </span>
                    </li>
                  );
                })
              )}
            </ul>
          ) : null}
        </Panel>
      </section>
    </main>
  );
}
