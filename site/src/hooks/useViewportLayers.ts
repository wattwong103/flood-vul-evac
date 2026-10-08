import { useEffect, useMemo, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { MapBundle } from "@/components/MapView";
import { loadViewportLayer, type ViewportBounds, type ViewportResult } from "@/lib/client";
import { isRefugeRecord } from "@/lib/map-refuges";

const EMPTY = { type: "FeatureCollection" as const, features: [] };

/** Cancel obsolete viewport/run requests; never keep details from the previous run. */
export function useViewportLayers(
  map: MapLibreMap | null, runId: string | null, source: MapBundle,
  network: boolean, buildings: boolean,
) {
  const [viewport, setViewport] = useState<{ bounds: ViewportBounds; zoom: number } | null>(null);
  const [loaded, setLoaded] = useState<{ key: string; network?: ViewportResult; buildings?: ViewportResult; note: string } | null>(null);
  useEffect(() => {
    if (!map || !runId) return;
    const update = () => {
      const b = map.getBounds();
      setViewport({ bounds: [Math.max(-180, b.getWest()), Math.max(-90, b.getSouth()),
        Math.min(180, b.getEast()), Math.min(90, b.getNorth())], zoom: map.getZoom() });
    };
    update();
    map.on("moveend", update);
    return () => { map.off("moveend", update); };
  }, [map, runId]);
  const key = JSON.stringify([runId, viewport, network, buildings]);
  const detailed = !!viewport && viewport.zoom >= 13;
  useEffect(() => {
    if (!runId || !viewport || !detailed || (!network && !buildings)) return;
    const controller = new AbortController();
    Promise.all([
      network ? loadViewportLayer(runId, "network", viewport.bounds, controller.signal) : undefined,
      buildings ? loadViewportLayer(runId, "buildings", viewport.bounds, controller.signal) : undefined,
    ]).then(([roads, footprints]) => {
      if (!controller.signal.aborted) setLoaded({ key, network: roads, buildings: footprints,
        note: [roads?.note, footprints?.note].filter(Boolean).join(" ") });
    }).catch(error => {
      if (!controller.signal.aborted) setLoaded({ key, note: `Map details unavailable: ${error instanceof Error ? error.message : String(error)}` });
    });
    return () => controller.abort();
  }, [key, runId, viewport, detailed, network, buildings]);
  const current = loaded?.key === key ? loaded : null;
  const footprints = current?.buildings ?? EMPTY;
  const bundle = useMemo(() => !runId ? source : {
      ...source, links: current?.network ?? EMPTY, buildings: footprints,
      refuges: { ...EMPTY, features: footprints.features.filter(f => isRefugeRecord(f.properties)) } },
    [runId, source, current?.network, footprints]);
  return {
    bundle,
    note: !runId || (!network && !buildings) ? null : !detailed
      ? "Road and building details are hidden at this scale. Zoom in to level 13 to load them."
      : current?.note ?? "Loading roads and buildings in this viewport…",
  };
}
