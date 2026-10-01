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
  setWorkerUrl,
  type StyleSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
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
  FloodProperties,
  LinkProperties,
  MeshProperties,
  ObservedWaterCellProperties,
  StudyAreaProperties,
} from "@/lib/api";
import {
  formatCount,
  formatNumber,
  formatShare,
  formatText,
  propBoolean,
  propNumber,
  propString,
} from "@/lib/format";
import { stringPropertyExpression } from "@/lib/map-expressions";
import { geoJsonBounds } from "@/lib/map-bounds";
import { layerFooterText } from "@/lib/map-copy";
import { useViewportLayers } from "@/hooks/useViewportLayers";
import { updateMapSources } from "@/lib/map-sources";
import { isRefugeRecord } from "@/lib/map-refuges";
import { MapPanel } from "@/components/MapPanel";

setWorkerUrl(maplibreWorkerUrl);

/* ------------------------------------------------------------------ *
 * Layer model
 * ------------------------------------------------------------------ */

export type LayerId =
  | "population"
  | "flood"
  | "buildings"
  | "network"
  | "routes"
  | "refuges"
  | "observedWater";

export const LAYER_IDS: readonly LayerId[] = [
  "population",
  "flood",
  "buildings",
  "network",
  "routes",
  "refuges",
  "observedWater",
] as const;

/**
 * The layers the Scenario Lab offers as toggles. The observed-water layer is
 * served by its own route and is only drawn on the Observed & assets screen,
 * where the year it belongs to is always stated.
 */
export const SCENARIO_LAYER_IDS: readonly LayerId[] = LAYER_IDS.filter(
  (id) => id !== "observedWater",
);

export type LayerState = Record<LayerId, boolean>;

export const DEFAULT_LAYERS: LayerState = {
  population: true,
  flood: true,
  buildings: false,
  network: true,
  routes: true,
  refuges: true,
  observedWater: false,
};

export const LAYER_LABELS: Record<LayerId, { name: string; quantity: string }> = {
  population: {
    name: "Population",
    quantity:
      "Quantity declared per feature: PFLOW people present or city resident baseline",
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
    name: "Evacuation bottlenecks",
    quantity: "Aggregate weighted flow on the run's top evacuation bottleneck edges",
  },
  refuges: {
    name: "Refuges",
    quantity: "Destination records. A record is a shelter only when refuge_verified is true",
  },
  observedWater: {
    name: "Observed water extent",
    quantity:
      "JRC Global Surface Water: share of each cell classified as water in the selected year. Extent, not depth",
  },
};

export type MapBundle = {
  studyArea: FeatureCollection<StudyAreaProperties>;
  mesh: FeatureCollection<MeshProperties>;
  flood: FeatureCollection<FloodProperties>;
  links: FeatureCollection<LinkProperties>;
  buildings: FeatureCollection<BuildingProperties>;
  routes: FeatureCollection<EvacuationProperties>;
  /** Derived from the building records; the contract serves no refuge endpoint. */
  refuges: FeatureCollection<BuildingProperties>;
  /** Served by `/observed-water/cells` for one selected year. */
  observedWater: FeatureCollection<ObservedWaterCellProperties>;
};

export const EMPTY_BUNDLE: MapBundle = {
  studyArea: { type: "FeatureCollection", features: [] },
  mesh: { type: "FeatureCollection", features: [] },
  flood: { type: "FeatureCollection", features: [] },
  links: { type: "FeatureCollection", features: [] },
  buildings: { type: "FeatureCollection", features: [] },
  routes: { type: "FeatureCollection", features: [] },
  refuges: { type: "FeatureCollection", features: [] },
  observedWater: { type: "FeatureCollection", features: [] },
};

/** Records that the API presents as a destination of some kind. */
export function extractRefuges(
  buildings: FeatureCollection<BuildingProperties>,
): FeatureCollection<BuildingProperties> {
  const features = buildings.features.filter((feature) => isRefugeRecord(feature.properties));
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
const STR = stringPropertyExpression;

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

const SOURCES = [
  "study-area",
  "mesh",
  "flood",
  "links",
  "buildings",
  "refuges",
  "routes",
  "observed-water",
] as const;

/**
 * Observed extent is a single ramp, deliberately unlike the three flood-depth
 * ramps above: it carries one observation, not one observation per source role.
 * Depth is separated from it by the wording of the legend, never by a hue.
 */
const WATER_SHARE_FILL = [
  "interpolate",
  ["linear"],
  NUM("water_share"),
  0,
  "#e8f1f4",
  0.05,
  "#a9cfe0",
  0.25,
  "#4b93b8",
  0.5,
  "#1d5f85",
  1,
  "#0b3550",
] as unknown[];

const WATER_SHARE_RADIUS = [
  "interpolate",
  ["linear"],
  NUM("water_share"),
  0,
  3,
  1,
  16,
] as unknown[];

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
  spatialRunId?: string | null;
};

export function MapView({
  bundle: suppliedBundle,
  layers,
  modelTime,
  center = [100.6333, 13.5872],
  zoom = 9.1,
  areaName,
  reducedMotion,
  spatialRunId = null,
}: MapViewProps) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<MapLibreMap | null>(null);
  const uploadedFeatures = useRef(new Map<string, unknown>());
  const hasFittedStudyArea = useRef(false);
  const [ready, setReady] = useState(false);
  const [mode, setMode] = useState<"map" | "table">("map");
  const [failure, setFailure] = useState<string | null>(null);
  const { bundle, note: viewportNote } = useViewportLayers(ready ? map.current : null,
    spatialRunId, suppliedBundle, layers.network, layers.buildings || layers.refuges);

  const dataFor = useMemo(
    () => ({
      "study-area": bundle.studyArea as unknown as GeoJSON.FeatureCollection,
      mesh: bundle.mesh as unknown as GeoJSON.FeatureCollection,
      flood: bundle.flood as unknown as GeoJSON.FeatureCollection,
      links: bundle.links as unknown as GeoJSON.FeatureCollection,
      buildings: bundle.buildings as unknown as GeoJSON.FeatureCollection,
      refuges: bundle.refuges as unknown as GeoJSON.FeatureCollection,
      routes: bundle.routes as unknown as GeoJSON.FeatureCollection,
      "observed-water": bundle.observedWater as unknown as GeoJSON.FeatureCollection,
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

      // --- Study area: always the full Bangkok administrative extent. ---
      instance.addLayer({
        id: "study-area-fill",
        type: "fill",
        source: "study-area",
        paint: {
          "fill-color": "#f7fbf9",
          "fill-opacity": 0.18,
        },
      });
      instance.addLayer({
        id: "study-area-outline",
        type: "line",
        source: "study-area",
        paint: {
          "line-color": "#173f3b",
          "line-width": 2.2,
          "line-opacity": 0.95,
        },
      });

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
          source: "flood",
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
          source: "flood",
          filter: ["==", STR("source_role"), role] as never,
          layout: { visibility: "visible", "line-join": "round" },
          paint: {
            "line-color": stops[stops.length - 1][1],
            "line-width": role === "observed" ? 1.8 : 1.4,
            ...(dash.length ? { "line-dasharray": dash } : {}),
          },
        });
        instance.addLayer({
          id: `${id}-circle`,
          type: "circle",
          source: "flood",
          filter: ["==", STR("source_role"), role] as never,
          layout: { visibility: "visible" },
          paint: {
            "circle-color": depthExpression(stops) as never,
            "circle-radius": [
              "interpolate",
              ["linear"],
              ["coalesce", ["to-number", ["get", "depth_m"]], 0],
              0,
              3,
              0.6,
              11,
            ] as never,
            "circle-opacity": 0.72,
            "circle-stroke-color": stops[stops.length - 1][1],
            "circle-stroke-width": role === "observed" ? 1.4 : 0.8,
          },
        });
      }

      // --- Population -------------------------------------------------
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
      instance.addLayer({
        id: "routes-fill",
        type: "fill",
        source: "routes",
        layout: { visibility: "visible" },
        paint: { "fill-color": "#ef9b43", "fill-opacity": 0.35 },
      });
      instance.addLayer({
        id: "routes-line",
        type: "line",
        source: "routes",
        layout: { visibility: "visible" },
        paint: {
          "line-color": "#ef9b43",
          "line-width": [
            "interpolate",
            ["linear"],
            NUM("traversal_weight"),
            0,
            1.5,
            1000,
            7,
          ] as never,
          "line-opacity": 0.9,
        },
      });

      // --- Refuges: verified and unverified are drawn differently ----
      const verifiedIcon = refugeGlyph("verified");
      const unverifiedIcon = refugeGlyph("unverified");
      if (verifiedIcon) {
        instance.addImage("refuge-verified-icon", verifiedIcon, { pixelRatio: 2 });
        instance.addLayer({
          id: "refuge-verified",
          type: "symbol",
          source: "refuges",
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
          source: "refuges",
          filter: NOT_VERIFIED as never,
          layout: {
            "icon-image": "refuge-unverified-icon",
            "icon-allow-overlap": true,
            "icon-size": 0.42,
            visibility: "visible",
          },
        });
      }

      // --- Observed surface water: extent only, for the selected year --
      instance.addLayer({
        id: "observed-water-cell",
        type: "circle",
        source: "observed-water",
        layout: { visibility: "visible" },
        paint: {
          "circle-color": WATER_SHARE_FILL as never,
          "circle-radius": WATER_SHARE_RADIUS as never,
          "circle-opacity": 0.85,
          "circle-stroke-color": "#0b3550",
          "circle-stroke-width": 0.6,
        },
      });

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
    const instance = map.current;
    updateMapSources({ getSource: id => instance.getSource(id) as GeoJSONSource | undefined }, dataFor, uploadedFeatures.current);
  }, [ready, dataFor]);

  // Fit the initial view to all of Bangkok once the city boundary arrives.
  // Timeline changes update layers without repeatedly moving the user's map.
  useEffect(() => {
    if (!ready || !map.current || hasFittedStudyArea.current) return;
    const bounds = geoJsonBounds(bundle.studyArea);
    if (!bounds) return;
    map.current.fitBounds(
      [
        [bounds[0], bounds[1]],
        [bounds[2], bounds[3]],
      ],
      {
        padding: { top: 40, right: 40, bottom: 40, left: 40 },
        duration: reducedMotion ? 0 : 450,
        maxZoom: 11,
      },
    );
    hasFittedStudyArea.current = true;
  }, [ready, bundle.studyArea, reducedMotion]);

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
    set("flood-observed-circle", layers.flood);
    set("flood-modelled-fill", layers.flood);
    set("flood-modelled-line", layers.flood);
    set("flood-modelled-circle", layers.flood);
    set("flood-scenario-fill", layers.flood);
    set("flood-scenario-line", layers.flood);
    set("flood-scenario-circle", layers.flood);
    set("buildings-fill", layers.buildings);
    set("network-open", layers.network);
    set("network-slowed", layers.network);
    set("network-closed", layers.network);
    set("routes-fill", layers.routes);
    set("routes-line", layers.routes);
    set("refuge-verified", layers.refuges);
    set("refuge-unverified", layers.refuges);
    set("observed-water-cell", layers.observedWater);
  }, [ready, layers]);

  const totalFeatures =
    bundle.mesh.features.length +
    bundle.flood.features.length +
    bundle.links.features.length +
    bundle.buildings.features.length +
    bundle.routes.features.length +
    bundle.observedWater.features.length;

  useEffect(() => {
    if (mode === "map") map.current?.resize();
  }, [mode]);

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
          Full Bangkok extent · {" "}
          {totalFeatures === 0
            ? "no features served for this run"
            : modelTime === null
              ? `${totalFeatures} static or observed features served · no model time`
              : `${totalFeatures} features served at model time ${modelTime}`}
        </p>
      </div>

        <MapPanel visible={mode === "map"}>
          <div
            ref={container}
            className="map-canvas"
            role="img"
            aria-label={`Map of the full Bangkok Metropolitan Administration extent, showing ${areaName}. Flood, population, network, route, refuge and observed-water layers. All values are in the table view.`}
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
        </MapPanel>
      {mode === "table" ? (
        <MapTables bundle={bundle} layers={layers} modelTime={modelTime} />
      ) : null}

      {viewportNote ? <p className="layer-legend-note" role="status">{viewportNote}</p> : null}
      <LayerFooterNote modelTime={modelTime} />
    </div>
  );
}

function LayerFooterNote({ modelTime }: { modelTime: string | null }) {
  return <p className="layer-legend-note">{layerFooterText(modelTime)}</p>;
}

/* ------------------------------------------------------------------ *
 * Legend
 * ------------------------------------------------------------------ */

function MapLegend({ layers }: { layers: LayerState }) {
  return (
    <aside className="map-legend" aria-label="Map legend">
      <p className="legend-title">Legend</p>

      <div className="legend-group">
        <p className="legend-name">Study area</p>
        <ul>
          <li>
            <span className="swatch study-area" aria-hidden="true" />
            <b>Bangkok boundary</b> — the full 1,643.5 km² Metropolitan
            Administration extent. Detailed layers may cover only part of it.
          </li>
        </ul>
      </div>

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
            The map states its population quantity per feature: <b>people present</b>
            for time-specific PFLOW mesh totals, or <b>resident baseline</b> for the
            city population grid. <b>People exposed</b> is a separate result and is
            never inferred from this layer.
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

      {layers.observedWater ? (
        <div className="legend-group">
          <p className="legend-name">Observed surface water</p>
          <p className="legend-ramp" aria-hidden="true">
            <i className="water-0" />
            <i className="water-05" />
            <i className="water-25" />
            <i className="water-1" />
          </p>
          <p>
            Share of each cell classified as water in the selected year. Marker
            size rises with the share as well as colour. <b>Extent only:</b> the
            classification carries no depth, duration or direction, and no year
            here is a forecast.
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
        formatText(propString(p, "population_quantity")),
      ],
    };
  });
}

function floodRows(features: Array<Feature<FloodProperties>>): Row[] {
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
        formatNumber(propNumber(p, "traversal_weight"), 1),
        formatText(propString(p, "route_quantity")),
      ],
    };
  });
}

function observedWaterRows(
  features: Array<Feature<ObservedWaterCellProperties>>,
): Row[] {
  return features.map((feature, index) => {
    const p = feature.properties ?? {};
    return {
      id: featureId(feature, index),
      cells: [
        propString(p, "cell_id") ?? featureId(feature, index),
        formatCount(propNumber(p, "year")),
        formatShare(propNumber(p, "water_share")),
        formatNumber(propNumber(p, "water_km2"), 2),
        formatText(propString(p, "source_role")),
        formatText(propString(p, "measures")),
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
      head: ["cell", "gcode", "stationary", "travelling", "population", "exposed", "quantity"],
      rows: meshRows(bundle.mesh.features),
    },
    layers.flood && {
      key: "flood" as const,
      title: `Flood — ${LAYER_LABELS.flood.quantity}`,
      head: ["cell", "source role", "depth (m)", "confidence"],
      rows: floodRows(bundle.flood.features),
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
    layers.observedWater && {
      key: "observedWater" as const,
      title: `Observed water — ${LAYER_LABELS.observedWater.quantity}`,
      head: ["cell", "year", "water share", "water (km²)", "source role", "measures"],
      rows: observedWaterRows(bundle.observedWater.features),
    },
    layers.routes && {
      key: "routes" as const,
      title: `Routes — ${LAYER_LABELS.routes.quantity}`,
      head: ["edge", "weighted traversals", "quantity"],
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
