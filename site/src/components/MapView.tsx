/**
 * The map. MapLibre GL, fed exclusively by GeoJSON that the API serves for the
 * selected run. There is no basemap tile dependency: the style is a plain
 * background so the site renders with no external tile service and no key.
 *
 * Contract rules implemented here:
 *  - observed / modelled / scenario flood are three separate layers with
 *    different fill ramps and different outline dash patterns, and the legend
 *    names the difference in words;
 *  - the population layer states which population quantity it represents;
 *  - building height never implies shelter: refuges are a separate layer and
 *    an unverified refuge record is drawn hollow with a dashed ring;
 *  - every visible layer has a table equivalent.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  GeoJSONSource,
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { Layers, Table2, Map as MapIcon } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  BuildingProperties,
  EvacuationProperties,
  Feature,
  FeatureCollection,
  LinkProperties,
  MeshProperties,
} from "@/lib/api";
import {
  formatCount,
  formatNumber,
  formatText,
  prop,
  propBoolean,
  propNumber,
  propString,
} from "@/lib/format";

/* ------------------------------------------------------------------ *
 * Layer model
 * ------------------------------------------------------------------ */

export type LayerId =
  | "population"
  | "flood"
  | "buildings"
  | "network"
  | "routes"
  | "refuges";

export const LAYER_IDS: readonly LayerId[] = [
  "population",
  "flood",
  "buildings",
  "network",
  "routes",
  "refuges",
] as const;

export type LayerState = Record<LayerId, boolean>;

export const DEFAULT_LAYERS: LayerState = {
  population: true,
  flood: true,
  buildings: false,
  network: true,
  routes: true,
  refuges: true,
};

export const LAYER_LABELS: Record<LayerId, { name: string; quantity: string }> = {
  population: {
    name: "Population",
    quantity:
      "People present — PFLOW mesh total (stationary + travelling) at the selected model time",
  },
  flood: {
    name: "Flood depth",
    quantity: "Flood depth in metres, by source role (observed / modelled / scenario)",
  },
  buildings: {
    name: "Buildings",
    quantity: "Building footprints with maximum modelled flood depth at the footprint",
  },
  network: {
    name: "Network state",
    quantity: "Road and path edges with flood-impedance state at the selected model time",
  },
  routes: {
    name: "Evacuation routes",
    quantity: "Simulated evacuation trajectories, weighted synthetic agents",
  },
  refuges: {
    name: "Refuges",
    quantity: "Destination records. A record is a shelter only when refuge_verified is true",
  },
};

export type MapBundle = {
  mesh: FeatureCollection<MeshProperties>;
  links: FeatureCollection<LinkProperties>;
  buildings: FeatureCollection<BuildingProperties>;
  routes: FeatureCollection<EvacuationProperties>;
  /** Derived from the building records; the contract serves no refuge endpoint. */
  refuges: FeatureCollection<BuildingProperties>;
};

export const EMPTY_BUNDLE: MapBundle = {
  mesh: { type: "FeatureCollection", features: [] },
  links: { type: "FeatureCollection", features: [] },
  buildings: { type: "FeatureCollection", features: [] },
  routes: { type: "FeatureCollection", features: [] },
  refuges: { type: "FeatureCollection", features: [] },
};

/** Records that the API presents as a destination of some kind. */
export function extractRefuges(
  buildings: FeatureCollection<BuildingProperties>,
): FeatureCollection<BuildingProperties> {
  const features = buildings.features.filter((feature) => {
    const properties = feature.properties ?? {};
    return (
      prop(properties, "refuge_id") !== null ||
      prop(properties, "refuge_verified") !== null ||
      prop(properties, "refuge_name") !== null
    );
  });
  return { type: "FeatureCollection", features };
}

/* ------------------------------------------------------------------ *
 * Style and paint
 * ------------------------------------------------------------------ */

const BLANK_STYLE: StyleSpecification = {
  version: 8,
  name: "bkkflow-no-basemap",
  sources: {},
  layers: [
    { id: "background", type: "background", paint: { "background-color": "#dfe7e2" } },
  ],
};

/** Depth ramps are separated by hue *and* lightness so they survive greyscale. */
const DEPTH_STOPS_OBSERVED: [number, string][] = [
  [0, "#cfe6ef"],
  [0.15, "#74b9d5"],
  [0.3, "#2a7fa6"],
  [0.6, "#0f4b66"],
];
const DEPTH_STOPS_MODELLED: [number, string][] = [
  [0, "#ccd6e8"],
  [0.15, "#8296c4"],
  [0.3, "#47609c"],
  [0.6, "#26356b"],
];
const DEPTH_STOPS_SCENARIO: [number, string][] = [
  [0, "#f7e2c6"],
  [0.15, "#eab473"],
  [0.3, "#dc8443"],
  [0.6, "#a3511d"],
];

function depthExpression(stops: [number, string][]): unknown[] {
  return [
    "interpolate",
    ["linear"],
    ["coalesce", ["to-number", ["get", "depth_m"]], 0],
    ...stops.flatMap(([value, colour]) => [value, colour]),
  ];
}

const NUM = (key: string) => ["coalesce", ["to-number", ["get", key]], 0] as unknown[];
const STR = (key: string) => [
  "match",
  ["to-string", ["get", key]],
  "observed",
  "observed",
  "modelled",
  "modelled",
  "modelled",
  "scenario",
  "scenario",
] as unknown[];

const CLOSED = [
  "any",
  ["==", ["get", "closed"], true],
  ["==", ["to-string", ["get", "closed"]], "true"],
] as unknown[];

const SLOWED = [
  "all",
  ["!", CLOSED],
  ["<=", ["to-number", ["coalesce", ["get", "speed_multiplier"], 1]], 0.95],
] as unknown[];

const OPEN = ["all", ["!", CLOSED], ["!", SLOWED]] as unknown[];

const VERIFIED = [
  "any",
  ["==", ["get", "refuge_verified"], true],
  ["==", ["to-string", ["get", "refuge_verified"]], "true"],
] as unknown[];

const NOT_VERIFIED = ["!", VERIFIED] as unknown[];

const EXPOSED_BUILDING = [">", NUM("max_depth_m"), 0] as unknown[];

const POP_FILL = [
  "interpolate",
  ["linear"],
  NUM("total_pop"),
  0,
  "#e7f0ec",
  25,
  "#a8ccc1",
  100,
  "#4e9184",
  400,
  "#124b48",
] as unknown[];

const POP_RADIUS = [
  "interpolate",
  ["linear"],
  NUM("total_pop"),
  0,
  2,
  400,
  16,
] as unknown[];

const SOURCES = ["mesh", "links", "buildings", "routes"] as const;

/**
 * Refuge status has to survive greyscale and colour-blind viewing, and a circle
 * layer cannot be dashed. Both states are therefore drawn as distinct glyphs
 * generated on a canvas at start-up: a filled disc with a check for a verified
 * refuge record, a dashed ring with a cross for anything unverified.
 */
function refugeGlyph(kind: "verified" | "unverified"): ImageData | null {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.lineCap = "round";

  if (kind === "verified") {
    ctx.beginPath();
    ctx.arc(32, 32, 26, 0, Math.PI * 2);
    ctx.fillStyle = "#2f7d5c";
    ctx.fill();
    ctx.lineWidth = 5;
    ctx.strokeStyle = "#0f2a24";
    ctx.stroke();
    ctx.strokeStyle = "#f2f7ee";
    ctx.lineWidth = 7;
    ctx.beginPath();
    ctx.moveTo(20, 33);
    ctx.lineTo(29, 42);
    ctx.lineTo(45, 23);
    ctx.stroke();
  } else {
    ctx.beginPath();
    ctx.arc(32, 32, 28, 0, Math.PI * 2);
    ctx.setLineDash([8, 6]);
    ctx.lineWidth = 5;
    ctx.strokeStyle = "#e7654d";
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.lineWidth = 7;
    ctx.beginPath();
    ctx.moveTo(23, 23);
    ctx.lineTo(41, 41);
    ctx.moveTo(41, 23);
    ctx.lineTo(23, 41);
    ctx.stroke();
  }
  return ctx.getImageData(0, 0, size, size);
}

function isPolygonal(features: Array<Feature<unknown>>): boolean {
  return features.some((feature) => {
    const type = feature.geometry?.type;
    return type === "Polygon" || type === "MultiPolygon";
  });
}

/* ------------------------------------------------------------------ *
 * Component
 * ------------------------------------------------------------------ */

export type MapViewProps = {
  bundle: MapBundle;
  layers: LayerState;
  modelTime: string | null;
  center?: [number, number];
  zoom?: number;
  /** Named so the map can be labelled and described for assistive tech. */
  areaName: string;
  reducedMotion: boolean;
};

export function MapView({
  bundle,
  layers,
  modelTime,
  center = [100.5014, 13.75],
  zoom = 11,
  areaName,
  reducedMotion,
}: MapViewProps) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<MapLibreMap | null>(null);
  const [ready, setReady] = useState(false);
  const [mode, setMode] = useState<"map" | "table">("map");
  const [failure, setFailure] = useState<string | null>(null);

  const geometryKind = useMemo(
    () => ({
      mesh: isPolygonal(bundle.mesh.features),
      routes: isPolygonal(bundle.routes.features),
    }),
    [bundle.mesh, bundle.routes],
  );

  const dataFor = useMemo(
    () => ({
      mesh: bundle.mesh as unknown as GeoJSON.FeatureCollection,
      links: bundle.links as unknown as GeoJSON.FeatureCollection,
      buildings: bundle.buildings as unknown as GeoJSON.FeatureCollection,
      routes: bundle.routes as unknown as GeoJSON.FeatureCollection,
    }),
    [bundle],
  );

  // Initialise once.
  useEffect(() => {
    if (!container.current || map.current) return;
    let instance: MapLibreMap;
    try {
      instance = new MapLibreMap({
        container: container.current,
        style: BLANK_STYLE,
        center,
        zoom,
        attributionControl: false,
        dragRotate: false,
        // Reduced motion: no inertial easing and no automatic fly animation.
        fadeDuration: reducedMotion ? 0 : 200,
        interactive: true,
      });
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "WebGL is unavailable.");
      return;
    }
    map.current = instance;
    instance.addControl(new NavigationControl({ showCompass: false }), "top-left");
    instance.addControl(new ScaleControl({ maxWidth: 110, unit: "metric" }), "bottom-left");

    const onLoad = () => {
      for (const id of SOURCES) {
        instance.addSource(id, {
          type: "geojson",
          data: dataFor[id] as GeoJSON.FeatureCollection,
        });
      }

      // --- Flood: three role-specific layers, never merged. -------------
      const roles: Array<[string, string, [number, string][], number[]]> = [
        ["flood-observed", "observed", DEPTH_STOPS_OBSERVED, []],
        ["flood-modelled", "modelled", DEPTH_STOPS_MODELLED, [3, 2]],
        ["flood-scenario", "scenario", DEPTH_STOPS_SCENARIO, [1, 2.2]],
      ];
      for (const [id, role, stops, dash] of roles) {
        instance.addLayer({
          id: `${id}-fill`,
          type: "fill",
          source: "mesh",
          filter: ["==", STR("source_role"), role] as never,
          layout: { visibility: "visible" },
          paint: {
            "fill-color": depthExpression(stops) as never,
            "fill-opacity": 0.62,
          },
        });
        instance.addLayer({
          id: `${id}-line`,
          type: "line",
          source: "mesh",
          filter: ["==", STR("source_role"), role] as never,
          layout: { visibility: "visible", "line-join": "round" },
          paint: {
            "line-color": stops[stops.length - 1][1],
            "line-width": role === "observed" ? 1.8 : 1.4,
            ...(dash.length ? { "line-dasharray": dash } : {}),
          },
        });
      }

      // --- Population -------------------------------------------------
      if (geometryKind.mesh) {
        instance.addLayer({
          id: "population-fill",
          type: "fill",
          source: "mesh",
          layout: { visibility: "visible" },
          paint: {
            "fill-color": POP_FILL as never,
            "fill-opacity": 0.7,
            "fill-outline-color": "#0d403c",
          },
        });
      } else {
        instance.addLayer({
          id: "population-circle",
          type: "circle",
          source: "mesh",
          layout: { visibility: "visible" },
          paint: {
            "circle-color": POP_FILL as never,
            "circle-radius": POP_RADIUS as never,
            "circle-opacity": 0.8,
            "circle-stroke-color": "#0d403c",
            "circle-stroke-width": 0.8,
          },
        });
      }

      // --- Buildings: footprint exposure only, never shelter ----------
      instance.addLayer({
        id: "buildings-fill",
        type: "fill",
        source: "buildings",
        layout: { visibility: "visible" },
        paint: {
          "fill-color": [
            "case",
            EXPOSED_BUILDING,
            "#c97a63",
            "#9aa8a2",
          ] as never,
          "fill-opacity": 0.55,
          "fill-outline-color": "#3f4d49",
        },
      });

      // --- Network state ---------------------------------------------
      instance.addLayer({
        id: "network-open",
        type: "line",
        source: "links",
        filter: OPEN as never,
        layout: { visibility: "visible" },
        paint: { "line-color": "#7f8f89", "line-width": 1.1, "line-opacity": 0.75 },
      });
      instance.addLayer({
        id: "network-slowed",
        type: "line",
        source: "links",
        filter: SLOWED as never,
        layout: { visibility: "visible" },
        paint: {
          "line-color": "#c98a2e",
          "line-width": 2.4,
          "line-dasharray": [3, 1.6],
        },
      });
      instance.addLayer({
        id: "network-closed",
        type: "line",
        source: "links",
        filter: CLOSED as never,
        layout: { visibility: "visible" },
        paint: { "line-color": "#b03a2b", "line-width": 3.4 },
      });

      // --- Routes ----------------------------------------------------
      if (geometryKind.routes) {
        instance.addLayer({
          id: "routes-line",
          type: "fill",
          source: "routes",
          layout: { visibility: "visible" },
          paint: { "fill-color": "#ef9b43", "fill-opacity": 0.35 },
        });
      } else {
        instance.addLayer({
          id: "routes-line",
          type: "line",
          source: "routes",
          layout: { visibility: "visible" },
          paint: { "line-color": "#ef9b43", "line-width": 2.2, "line-opacity": 0.9 },
        });
      }

      // --- Refuges: verified and unverified are drawn differently ----
      const verifiedIcon = refugeGlyph("verified");
      const unverifiedIcon = refugeGlyph("unverified");
      if (verifiedIcon) {
        instance.addImage("refuge-verified-icon", verifiedIcon, { pixelRatio: 2 });
        instance.addLayer({
          id: "refuge-verified",
          type: "symbol",
          source: "buildings",
          filter: VERIFIED as never,
          layout: {
            "icon-image": "refuge-verified-icon",
            "icon-allow-overlap": true,
            "icon-size": 0.42,
            visibility: "visible",
          },
        });
      }
      if (unverifiedIcon) {
        instance.addImage("refuge-unverified-icon", unverifiedIcon, { pixelRatio: 2 });
        instance.addLayer({
          id: "refuge-unverified",
          type: "symbol",
          source: "buildings",
          filter: NOT_VERIFIED as never,
          layout: {
            "icon-image": "refuge-unverified-icon",
            "icon-allow-overlap": true,
            "icon-size": 0.42,
            visibility: "visible",
          },
        });
      }

      setReady(true);
    };

    if (instance.loaded()) onLoad();
    else instance.on("load", onLoad);

    return () => {
      map.current = null;
      instance.remove();
    };
    // Intentionally mounted once; data and visibility are applied by effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push new data into the existing sources.
  useEffect(() => {
    if (!ready || !map.current) return;
    for (const id of SOURCES) {
      const source = map.current.getSource(id) as GeoJSONSource | undefined;
      source?.setData(dataFor[id] as GeoJSON.FeatureCollection);
    }
  }, [ready, dataFor]);

  // Apply layer visibility.
  useEffect(() => {
    if (!ready || !map.current) return;
    const set = (id: string, visible: boolean) => {
      if (map.current?.getLayer(id)) {
        map.current.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
      }
    };
    set("population-fill", layers.population);
    set("population-circle", layers.population);
    set("flood-observed-fill", layers.flood);
    set("flood-observed-line", layers.flood);
    set("flood-modelled-fill", layers.flood);
    set("flood-modelled-line", layers.flood);
    set("flood-scenario-fill", layers.flood);
    set("flood-scenario-line", layers.flood);
    set("buildings-fill", layers.buildings);
    set("network-open", layers.network);
    set("network-slowed", layers.network);
    set("network-closed", layers.network);
    set("routes-line", layers.routes);
    set("refuge-verified", layers.refuges);
    set("refuge-unverified", layers.refuges);
  }, [ready, layers]);

  const totalFeatures =
    bundle.mesh.features.length +
    bundle.links.features.length +
    bundle.buildings.features.length +
    bundle.routes.features.length;

  return (
    <div className="map-shell">
      <div className="map-toolbar">
        <Tabs value={mode} onValueChange={(value) => setMode(value as "map" | "table")}>
          <TabsList>
            <TabsTrigger value="map">
              <MapIcon size={14} aria-hidden="true" /> Map
            </TabsTrigger>
            <TabsTrigger value="table">
              <Table2 size={14} aria-hidden="true" /> Table
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <p className="map-toolbar-note">
          <Layers size={14} aria-hidden="true" />
          {totalFeatures === 0
            ? "no features served for this run"
            : `${totalFeatures} features served at model time ${modelTime ?? "not available"}`}
        </p>
      </div>

      {mode === "map" ? (
        <div className="map-body">
          <div
            ref={container}
            className="map-canvas"
            role="img"
            aria-label={`Map of ${areaName}. Flood, population, network, route and refuge layers. All values are in the table view.`}
            tabIndex={0}
          />
          {failure ? (
            <p className="map-failure" role="alert">
              The map could not start ({failure}). Every layer is still available in the
              table view.
            </p>
          ) : null}
          {totalFeatures === 0 ? (
            <p className="map-empty" role="status">
              This run served no map geometry at the selected model time. Use the table
              view for the metrics the run does report.
            </p>
          ) : null}
          <MapLegend layers={layers} />
        </div>
      ) : (
        <MapTables bundle={bundle} layers={layers} modelTime={modelTime} />
      )}

      <LayerFooterNote modelTime={modelTime} />
    </div>
  );
}

function LayerFooterNote({ modelTime }: { modelTime: string | null }) {
  return (
    <p className="layer-legend-note">
      Model time for every layer above: {modelTime ?? "not available"} · flood source
      legend names observed, modelled and scenario separately · building height is
      never presented as shelter · unverified refuge records are marked, not hidden.
    </p>
  );
}

/* ------------------------------------------------------------------ *
 * Legend
 * ------------------------------------------------------------------ */

function MapLegend({ layers }: { layers: LayerState }) {
  return (
    <aside className="map-legend" aria-label="Map legend">
      <p className="legend-title">Legend</p>

      {layers.flood ? (
        <div className="legend-group">
          <p className="legend-name">Flood — three separate sources, never merged</p>
          <ul>
            <li>
              <span className="swatch flood-observed" aria-hidden="true" />
              <b>Observed</b> flood extent — measured footprint. Outline is solid.
              Depth is not observed.
            </li>
            <li>
              <span className="swatch flood-modelled" aria-hidden="true" />
              <b>Modelled</b> flood depth — solver output. Outline is dashed.
            </li>
            <li>
              <span className="swatch flood-scenario" aria-hidden="true" />
              <b>Scenario</b> flood — assumed forcing, not a prediction. Outline is
              finely dotted.
            </li>
          </ul>
        </div>
      ) : null}

      {layers.population ? (
        <div className="legend-group">
          <p className="legend-name">Population</p>
          <p className="legend-ramp" aria-hidden="true">
            <i className="pop-0" />
            <i className="pop-25" />
            <i className="pop-100" />
            <i className="pop-400" />
          </p>
          <p>
            <b>People present</b> — PFLOW mesh total (stationary + travelling) at the
            selected model time. <b>People exposed</b> is a different quantity and is
            never drawn from this layer.
          </p>
        </div>
      ) : null}

      {layers.network ? (
        <div className="legend-group">
          <p className="legend-name">Network state</p>
          <ul>
            <li>
              <span className="swatch net-open" aria-hidden="true" /> Open
            </li>
            <li>
              <span className="swatch net-slowed" aria-hidden="true" /> Reduced speed
              (dashed)
            </li>
            <li>
              <span className="swatch net-closed" aria-hidden="true" /> Closed (heavy
              solid)
            </li>
          </ul>
        </div>
      ) : null}

      {layers.buildings ? (
        <div className="legend-group">
          <p className="legend-name">Buildings</p>
          <p>
            Footprint with maximum modelled depth at the footprint. <b>Height is never
            a shelter claim.</b>
          </p>
        </div>
      ) : null}

      {layers.refuges ? (
        <div className="legend-group">
          <p className="legend-name">Refuges</p>
          <ul>
            <li>
              <span className="swatch refuge-verified" aria-hidden="true" /> Verified
              refuge record
            </li>
            <li>
              <span className="swatch refuge-unverified" aria-hidden="true" /> Unverified
              — not a shelter
            </li>
          </ul>
        </div>
      ) : null}
    </aside>
  );
}

/* ------------------------------------------------------------------ *
 * Table equivalents — one per visible layer
 * ------------------------------------------------------------------ */

type Row = { id: string; cells: string[] };

function featureId(feature: Feature<unknown>, index: number): string {
  const properties = feature.properties ?? {};
  return (
    propString(properties, "cell_id") ??
    propString(properties, "edge_id") ??
    propString(properties, "building_id") ??
    propString(properties, "refuge_id") ??
    propString(properties, "gcode") ??
    propString(properties, "trip_id") ??
    (feature.id != null ? String(feature.id) : `#${index + 1}`)
  );
}

function meshRows(features: Array<Feature<MeshProperties>>): Row[] {
  return features.map((feature, index) => {
    const p = feature.properties ?? {};
    return {
      id: featureId(feature, index),
      cells: [
        featureId(feature, index),
        formatText(propString(p, "gcode")),
        formatNumber(propNumber(p, "stationary_pop"), 1),
        formatNumber(propNumber(p, "travelling_pop"), 1),
        formatNumber(propNumber(p, "total_pop"), 1),
        formatNumber(propNumber(p, "exposed_pop"), 1),
        formatText(propString(p, "source_role")),
      ],
    };
  });
}

function floodRows(features: Array<Feature<MeshProperties>>): Row[] {
  return features.map((feature, index) => {
    const p = feature.properties ?? {};
    return {
      id: featureId(feature, index),
      cells: [
        featureId(feature, index),
        formatText(propString(p, "source_role")),
        formatNumber(propNumber(p, "depth_m"), 2),
        formatText(propString(p, "confidence")),
      ],
    };
  });
}

function linkRows(features: Array<Feature<LinkProperties>>): Row[] {
  return features.map((feature, index) => {
    const p = feature.properties ?? {};
    const closed = propBoolean(p, "closed");
    const state = closed === null ? "not reported" : closed ? "closed" : "open";
    return {
      id: featureId(feature, index),
      cells: [
        featureId(feature, index),
        state,
        formatNumber(propNumber(p, "depth_m"), 2),
        formatNumber(propNumber(p, "speed_multiplier"), 2),
        formatNumber(propNumber(p, "capacity_multiplier"), 2),
        formatCount(propNumber(p, "volume")),
        formatText(propString(p, "reason_code")),
      ],
    };
  });
}

function buildingRows(features: Array<Feature<BuildingProperties>>): Row[] {
  return features.map((feature, index) => {
    const p = feature.properties ?? {};
    const verified = propBoolean(p, "refuge_verified");
    return {
      id: featureId(feature, index),
      cells: [
        featureId(feature, index),
        formatNumber(propNumber(p, "height_m"), 1),
        formatText(propString(p, "height_source")),
        formatNumber(propNumber(p, "max_depth_m"), 2),
        verified === null ? "no refuge record" : verified ? "verified refuge" : "unverified — not a shelter",
        formatCount(propNumber(p, "refuge_capacity")),
      ],
    };
  });
}

function routeRows(features: Array<Feature<EvacuationProperties>>): Row[] {
  return features.map((feature, index) => {
    const p = feature.properties ?? {};
    return {
      id: featureId(feature, index),
      cells: [
        featureId(feature, index),
        formatText(propString(p, "state")),
        formatText(propString(p, "dest_id")),
        formatNumber(propNumber(p, "weight"), 1),
        formatNumber(propNumber(p, "event_time_s"), 0),
        formatText(propString(p, "reason")),
      ],
    };
  });
}

function MapTables({
  bundle,
  layers,
  modelTime,
}: {
  bundle: MapBundle;
  layers: LayerState;
  modelTime: string | null;
}) {
  const sections = [
    layers.population && {
      key: "population" as const,
      title: `Population — ${LAYER_LABELS.population.quantity}`,
      head: ["cell", "gcode", "stationary", "travelling", "total present", "exposed", "source role"],
      rows: meshRows(bundle.mesh.features),
    },
    layers.flood && {
      key: "flood" as const,
      title: `Flood — ${LAYER_LABELS.flood.quantity}`,
      head: ["cell", "source role", "depth (m)", "confidence"],
      rows: floodRows(bundle.mesh.features),
    },
    layers.network && {
      key: "network" as const,
      title: `Network — ${LAYER_LABELS.network.quantity}`,
      head: ["edge", "state", "depth (m)", "speed ×", "capacity ×", "volume", "reason"],
      rows: linkRows(bundle.links.features),
    },
    layers.buildings && {
      key: "buildings" as const,
      title: `Buildings — ${LAYER_LABELS.buildings.quantity}`,
      head: ["building", "height (m)", "height source", "max depth (m)", "refuge status", "capacity"],
      rows: buildingRows(bundle.buildings.features),
    },
    layers.refuges && {
      key: "refuges" as const,
      title: `Refuges — ${LAYER_LABELS.refuges.quantity}`,
      head: ["refuge", "height (m)", "height source", "max depth (m)", "refuge status", "capacity"],
      rows: buildingRows(bundle.refuges.features),
    },
    layers.routes && {
      key: "routes" as const,
      title: `Routes — ${LAYER_LABELS.routes.quantity}`,
      head: ["record", "state", "destination", "weight", "event time (s)", "reason"],
      rows: routeRows(bundle.routes.features),
    },
  ].filter(Boolean) as Array<{
    key: LayerId;
    title: string;
    head: string[];
    rows: Row[];
  }>;

  return (
    <div className="map-tables">
      <p className="tables-note">
        Table equivalent of every visible map layer, at model time{" "}
        {modelTime ?? "not available"}. Sorted rows are not ranked; the order is the
        order the API served.
      </p>
      {sections.length === 0 ? (
        <p className="muted">No layers are switched on, so there is nothing to list.</p>
      ) : null}
      {sections.map((section) => (
        <section key={section.key} className="table-section">
          <h3>{section.title}</h3>
          <p className="muted">
            {section.rows.length === 0
              ? "This run served no rows for this layer."
              : `${section.rows.length} row${section.rows.length === 1 ? "" : "s"}.`}
          </p>
          <Table>
            <TableHeader>
              <TableRow>
                {section.head.map((cell) => (
                  <TableHead key={cell} scope="col">
                    {cell}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {section.rows.slice(0, 400).map((row) => (
                <TableRow key={row.id}>
                  {row.cells.map((cell, index) => (
                    <TableCell key={`${row.id}-${index}`}>{cell}</TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {section.rows.length > 400 ? (
            <p className="muted">
              Showing the first 400 of {section.rows.length} rows for browser
              performance. Export the run bundle for the full set.
            </p>
          ) : null}
        </section>
      ))}
    </div>
  );
}
