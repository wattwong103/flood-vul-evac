import type { ReactNode } from "react";

/** Keep MapLibre's container mounted while its accessible table is shown. */
export function MapPanel({ visible, children }: { visible: boolean; children: ReactNode }) {
  return <div className="map-body" style={{ display: visible ? undefined : "none" }}>{children}</div>;
}
