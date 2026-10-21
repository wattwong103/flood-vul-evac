/**
 * The flood screen's three readings (BKK-055c): how big, how deep, can people
 * move. Kept free of the map so it can be rendered and tested on its own.
 *
 * A missing value renders as "not available" with the API's reason beside it,
 * never as zero; a dry run's zero carries its "declared dry scenario" label.
 */

import { Footprints, Gauge, Waves } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { MetricCard, ValidationStamp } from "@/components/primitives";
import type { FloodSummary } from "@/lib/api";
import {
  howBigReading,
  howDeepReading,
  movementReason,
  movementRows,
  type MovementRow,
  type Reading,
} from "@/lib/flood-summary";
import { formatNumber, formatShare } from "@/lib/format";

/** The same open / slowed / closed colours the map uses for roads. */
const SEGMENTS: Array<{ key: "open" | "slowed" | "closed" | "unknown"; label: string; colour: string }> = [
  { key: "open", label: "open", colour: "#7f8f89" },
  { key: "slowed", label: "slowed", colour: "#c98a2e" },
  { key: "closed", label: "closed", colour: "#b03a2b" },
  { key: "unknown", label: "no state", colour: "#d5dcd8" },
];

function Caption({ reading }: { reading: Reading }) {
  return (
    <>
      {reading.detail}
      {reading.reason ? <span className="reading-reason">{reading.reason}</span> : null}
    </>
  );
}

function MovementBar({ row }: { row: MovementRow }) {
  if (row.closed === null) {
    return <p className="reading-reason">{row.reason ?? "Road states are not available."}</p>;
  }
  const parts = SEGMENTS.filter(({ key }) => (row[key] ?? 0) > 0);
  return (
    <>
      <div className="move-bar" role="img" aria-label={`${row.label}: ${describe(row)}`}>
        {parts.map(({ key, colour }) => (
          <span key={key} style={{ width: `${(row[key] ?? 0) * 100}%`, background: colour }} />
        ))}
      </div>
      <p className="move-text">{describe(row)}</p>
    </>
  );
}

/** Closed first: it is the answer to "can people move?". */
const READING_ORDER = ["closed", "slowed", "open", "unknown"] as const;

function describe(row: MovementRow): string {
  const shares = READING_ORDER.filter((key) => key !== "unknown" || (row.unknown ?? 0) > 0).map(
    (key) => `${formatShare(row[key])} ${SEGMENTS.find((segment) => segment.key === key)?.label}`,
  );
  return `${shares.join(" · ")} of ${formatNumber(row.totalKm, 1)} km`;
}

export function FloodReadings({
  summary,
  status,
  modelTime,
}: {
  summary: FloodSummary;
  status: string | null;
  modelTime: string | null;
}) {
  const big = howBigReading(summary);
  const deep = howDeepReading(summary);
  const rows = movementRows(summary);
  const noMovement = movementReason(summary);

  return (
    <section className="metric-grid flood-readings" aria-label="How big, how deep, can people move">
      <MetricCard
        label="How big"
        icon={<Waves size={15} aria-hidden="true" />}
        value={big.value}
        unit={big.unit}
        caption={<Caption reading={big} />}
        status={status}
        modelTime={modelTime}
      />
      <MetricCard
        label="How deep"
        icon={<Gauge size={15} aria-hidden="true" />}
        value={deep.value}
        unit={deep.unit}
        caption={<Caption reading={deep} />}
        status={status}
        modelTime={modelTime}
      />
      <Card className="metric-card movement-card">
        <CardHeader className="metric-head">
          <CardTitle className="metric-label">
            <span aria-hidden="true" className="metric-icon">
              <Footprints size={15} />
            </span>
            Can people move?
          </CardTitle>
        </CardHeader>
        <CardContent>
          {rows.length === 0 ? (
            <p className="reading-reason">{noMovement ?? "Road states are not available."}</p>
          ) : (
            rows.map((row) => (
              <div key={row.mode} className="move-row">
                <p className="move-label">{row.label}</p>
                <MovementBar row={row} />
              </div>
            ))
          )}
          <p className="metric-caption">Share of the road length each mode may use.</p>
          <ValidationStamp status={status} modelTime={modelTime} compact />
        </CardContent>
      </Card>
    </section>
  );
}
