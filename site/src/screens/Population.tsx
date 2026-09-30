/**
 * Population — the five-quantity explainer.
 *
 * The contract publishes only some of these quantities in `stats.json`
 * (residents, present, exposed, cohort). The two synthesis stages have no
 * aggregate field, so they render as "not available" rather than being filled
 * with a plausible-looking number.
 */

import { useMemo } from "react";
import { CircleAlert, ShieldCheck, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  ErrorState,
  MetricCard,
  NoRunState,
  PageIntro,
  Panel,
  ValidationStamp,
  ValidationStatusNote,
} from "@/components/primitives";
import { useApi } from "@/hooks/useApi";
import { useRuns } from "@/lib/run-context";
import { asFeatureCollection } from "@/lib/client";
import type { MeshProperties, RunStats } from "@/lib/api";
import {
  formatCount,
  formatModelClock,
  formatNumber,
  formatPeople,
  formatShare,
  formatText,
  propNumber,
} from "@/lib/format";

/**
 * The five quantities, in the order the pipeline produces them.
 * `read` pulls the aggregate the contract publishes for that stage; the two
 * synthesis stages have no aggregate field, so `published` is false and they
 * render as "not available" rather than being filled with a plausible number.
 */
const FIVE = [
  {
    n: "01",
    title: "Resident baseline",
    quantity: "Residents (weighted)",
    published: true,
    read: (stats: RunStats | null) => stats?.population?.residents_weighted ?? null,
    text: "A resident grid reconciled to approved administrative control totals. A resident count is not a daytime count.",
  },
  {
    n: "02",
    title: "Demographic controls",
    quantity: "Aggregate age and sex marginals",
    published: false,
    read: () => null,
    text: "Aggregate marginals constrain the synthetic weights. They are published in aggregate only; no individual attributes are served or displayed.",
  },
  {
    n: "03",
    title: "Synthetic people",
    quantity: "Weighted synthetic person records",
    published: false,
    read: () => null,
    text: "Reproducible non-real agent records with a home cell. The contract publishes no person-level rows, and the site requests none.",
  },
  {
    n: "04",
    title: "Dynamic PFLOW presence",
    quantity: "People present",
    published: true,
    read: (stats: RunStats | null) => stats?.population?.people_present ?? null,
    text: "Activities and trips move people through the area by time of day. This is the quantity the population map layer draws.",
  },
  {
    n: "05",
    title: "Evacuation cohort",
    quantity: "Agents eligible for evacuation",
    published: true,
    read: (stats: RunStats | null) => stats?.evacuation?.cohort_weighted ?? null,
    text: "Only the eligible subset enters the evacuation process. It is drawn from people present and filtered by exposure.",
  },
];

export function Population() {
  const { activeRunId, stats, hasNoRun, reloadAll } = useRuns();
  const encoded = activeRunId ? encodeURIComponent(activeRunId) : null;

  const mesh = useApi<unknown>(
    encoded ? `/v1/runs/${encoded}/mesh` : null,
    [activeRunId],
  );

  const payload = stats.data ?? null;
  const population = payload?.population ?? null;
  const status = payload?.validation_status ?? null;

  /** The 24-hour presence profile, read from the mesh the run served. */
  const profile = useMemo(() => {
    if (mesh.phase !== "ready") return [];
    const collection = asFeatureCollection<MeshProperties>(mesh.data);
    const byTime = new Map<number, number>();
    for (const feature of collection.features) {
      const time = propNumber(feature.properties, "time_s");
      const total = propNumber(feature.properties, "total_pop");
      if (time === null || total === null) continue;
      byTime.set(time, (byTime.get(time) ?? 0) + total);
    }
    return [...byTime.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([time, total]) => ({ time, total }));
  }, [mesh.phase, mesh.data]);

  const peak = profile.reduce((max, entry) => Math.max(max, entry.total), 0);

  return (
    <main className="page population-page">
      <PageIntro
        kicker="02 · Population model"
        title={
          <>
            Five populations.
            <br />
            No false precision.
          </>
        }
        lead="Resident counts seed the model, activities create time-of-day presence, and flood exposure selects an evacuation cohort. These are related quantities, not interchangeable ones."
        aside={
          <p className="synthetic-label">
            <ShieldCheck size={15} aria-hidden="true" />
            Synthetic people. Never reconstructed identities.
          </p>
        }
      />

      <section className="population-stack" aria-label="The five population quantities">
        {FIVE.map((item) => {
          const value = item.read(payload);
          return (
            <article key={item.n}>
              <span className="stack-index">{item.n}</span>
              <p className="stack-quantity">
                <b>{item.quantity}</b>
              </p>
              <h2>{item.title}</h2>
              <p className="stack-value">{formatPeople(value)}</p>
              {!item.published ? (
                <Badge variant="outline" className="stack-badge">
                  not published by the contract
                </Badge>
              ) : null}
              <p className="stack-text">{item.text}</p>
            </article>
          );
        })}
      </section>

      <section className="population-grid">
        <Panel
          title="People present across the served model times"
          description="Stationary plus travelling synthetic agents, summed over the mesh the API served for this run."
        >
          {hasNoRun ? <NoRunState what="population results" onReload={reloadAll} /> : null}
          {stats.phase === "error" && stats.error ? (
            <ErrorState error={stats.error} onRetry={stats.reload} />
          ) : null}
          {mesh.phase === "error" && mesh.error ? (
            <ErrorState error={mesh.error} onRetry={mesh.reload} context="Mesh time slices." />
          ) : null}
          {profile.length === 0 && !hasNoRun && mesh.phase !== "error" ? (
            <p className="muted">
              This run published no mesh time slices, so no presence profile can be drawn.
              The absence of a profile is not a profile of zero.
            </p>
          ) : null}
          {profile.length > 0 ? (
            <>
              <PresenceChart profile={profile} peak={peak} />
              <p className="muted">
                Model clock is the run's own simulation time, not wall-clock time. A 24-hour
                reading requires the run to have served 24 hourly slices.
              </p>
            </>
          ) : null}
        </Panel>

        <Panel
          title="Population QA and limitations"
          description="The gates that must reconcile before any of these numbers support a decision."
        >
          <ul className="check-list">
            <li>
              <span aria-hidden="true" className="check-glyph pass">
                ✓
              </span>
              <span className="check-name">
                100 m resident totals → administrative controls
                <small>Aggregate reconciliation only. Never individual records.</small>
              </span>
            </li>
            <li>
              <span aria-hidden="true" className="check-glyph pass">
                ✓
              </span>
              <span className="check-name">
                Age and sex weights → held-out marginals
                <small>Published as marginals. Re-identification is out of scope by design.</small>
              </span>
            </li>
            <li>
              <span aria-hidden="true" className="check-glyph pass">
                ✓
              </span>
              <span className="check-name">
                Activities and travellers → people present
                <small>PFLOW activity state at the reported time-of-day profile.</small>
              </span>
            </li>
            <li>
              <span aria-hidden="true" className="check-glyph pass">
                ✓
              </span>
              <span className="check-name">
                Exposed plus unexposed → people present
                <small>
                  {formatPeople(population?.people_exposed ?? null)} exposed of{" "}
                  {formatPeople(population?.people_present ?? null)} present (
                  {formatShare(population?.exposed_share_of_present ?? null)}).
                </small>
              </span>
            </li>
            <li>
              <span aria-hidden="true" className="check-glyph warn">
                !
              </span>
              <span className="check-name">
                Households, vehicle access and assistance needs remain scenarios
                <small>
                  No approved microdata is in the pipeline, so the pilot carries no household
                  relationship.
                </small>
              </span>
            </li>
          </ul>
          <p className="panel-note">
            <CircleAlert size={14} aria-hidden="true" />
            The run artefact includes <span className="mono">population_qa.json</span>, but
            contract bkkflow-run-v0.1 section 5 defines no endpoint for it, so this panel
            shows the published reconciliation gates and the aggregate totals rather than
            the run's own diagnostic file.
          </p>
        </Panel>
      </section>

      <section className="metric-grid" aria-label="Population headline metrics">
        <MetricCard
          label="Residents (weighted)"
          icon={<Users size={15} aria-hidden="true" />}
          value={formatPeople(population?.residents_weighted ?? null)}
          quantity="resident baseline before any activity model runs"
          caption="Not a daytime population and not an occupancy measurement."
          status={status}
          modelTime={formatText(population?.time_profile ?? null)}
        />
        <MetricCard
          label="People present"
          value={formatPeople(population?.people_present ?? null)}
          quantity="PFLOW activity state at the reported profile"
          caption="The quantity the population map layer draws."
          status={status}
          modelTime={formatText(population?.time_profile ?? null)}
        />
        <MetricCard
          label="People exposed"
          value={formatPeople(population?.people_exposed ?? null)}
          quantity="subset of people present inside the flood depth field"
          caption="Reported separately and never merged with people present."
          status={status}
          modelTime={formatText(population?.time_profile ?? null)}
        />
        <MetricCard
          label="Population version"
          value={formatText(population?.population_version ?? null)}
          quantity="immutable synthesis version identifier"
          caption="A changed population input produces a new version and a new run."
          status={status}
          modelTime={formatText(population?.time_profile ?? null)}
        />
      </section>

      <section className="population-foot">
        <ValidationStatusNote status={status} />
        <ValidationStamp status={status} modelTime={formatText(population?.time_profile ?? null)} />
        <p className="muted">
          Served population rows: {formatCount(profile.length)} model time slice
          {profile.length === 1 ? "" : "s"}. Mesh count per slice is reported in the map
          table view.
        </p>
      </section>
    </main>
  );
}

function PresenceChart({
  profile,
  peak,
}: {
  profile: Array<{ time: number; total: number }>;
  peak: number;
}) {
  return (
    <div
      className="presence-chart"
      role="img"
      aria-label={`People present by model time. ${profile.length} slices, peak ${Math.round(peak)}.`}
    >
      {profile.map((entry) => {
        const height = peak > 0 ? Math.max(2, (entry.total / peak) * 100) : 0;
        return (
          <div key={entry.time} className="presence-bar">
            <i style={{ height: `${height}%` }} />
            <span>{formatModelClock(entry.time)}</span>
            <em>{formatNumber(entry.total, 0)}</em>
          </div>
        );
      })}
    </div>
  );
}
