/**
 * The Past tab's three readings (BKK-055c part 2): how big the water seen by
 * satellite was, how deep (Unknown: observations have no depth), and whether
 * people could move (Not yet: needs an admitted citywide run).
 *
 * Observed numbers carry no model time, so the stamp says so, as on the
 * Observed & assets screen.
 */

import { Footprints, Gauge, Satellite } from "lucide-react";
import { MetricCard } from "@/components/primitives";
import type { EverWater, ObservedWaterYear } from "@/lib/api";
import type { Reading } from "@/lib/flood-summary";
import {
  EVER,
  everReading,
  PAST_DEPTH,
  PAST_MOVEMENT,
  yearReading,
  type PastChoice,
} from "@/lib/past-flood";

function Caption({ reading }: { reading: Reading }) {
  return (
    <>
      {reading.detail}
      {reading.reason ? <span className="reading-reason">{reading.reason}</span> : null}
    </>
  );
}

export function PastReadings({
  choice,
  label,
  year,
  ever,
  status,
}: {
  choice: PastChoice;
  /** "2011" or "1984–2021": what the tiles describe. */
  label: string;
  year: ObservedWaterYear | null;
  ever: Pick<EverWater, "available" | "ever_water_km2" | "reason" | "no_data_km2" | "ever_water_share_of_observed"> | null;
  status: string | null;
}) {
  const big = choice === EVER ? everReading(ever) : yearReading(year);
  return (
    <section className="metric-grid flood-readings" aria-label={`Observed water, ${label}`}>
      <MetricCard
        label="How big"
        icon={<Satellite size={15} aria-hidden="true" />}
        value={big.value}
        unit={big.unit}
        quantity={`water seen by satellite, ${label}`}
        caption={<Caption reading={big} />}
        status={status}
        modelTime={null}
      />
      <MetricCard
        label="How deep"
        icon={<Gauge size={15} aria-hidden="true" />}
        value={PAST_DEPTH.value}
        caption={<Caption reading={PAST_DEPTH} />}
        status={status}
        modelTime={null}
      />
      <MetricCard
        label="Can people move?"
        icon={<Footprints size={15} aria-hidden="true" />}
        value={PAST_MOVEMENT.value}
        caption={<Caption reading={PAST_MOVEMENT} />}
        status={status}
        modelTime={null}
      />
    </section>
  );
}
