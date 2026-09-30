import type { FeatureCollection, Geometry } from "./api";

export type GeographicBounds = [number, number, number, number];

function extendWithCoordinates(
  value: unknown,
  bounds: GeographicBounds,
): void {
  if (!Array.isArray(value)) return;
  if (
    value.length >= 2 &&
    typeof value[0] === "number" &&
    typeof value[1] === "number" &&
    Number.isFinite(value[0]) &&
    Number.isFinite(value[1])
  ) {
    const [lon, lat] = value as [number, number];
    if (lon < -180 || lon > 180 || lat < -90 || lat > 90) return;
    bounds[0] = Math.min(bounds[0], lon);
    bounds[1] = Math.min(bounds[1], lat);
    bounds[2] = Math.max(bounds[2], lon);
    bounds[3] = Math.max(bounds[3], lat);
    return;
  }
  for (const child of value) extendWithCoordinates(child, bounds);
}

/** Return [west, south, east, north] for valid WGS84 GeoJSON coordinates. */
export function geoJsonBounds(
  collection: FeatureCollection<unknown>,
): GeographicBounds | null {
  const bounds: GeographicBounds = [Infinity, Infinity, -Infinity, -Infinity];
  for (const feature of collection.features) {
    const geometry = feature.geometry as
      | (Geometry & { geometries?: Geometry[] })
      | null
      | undefined;
    if (!geometry) continue;
    if (geometry.type === "GeometryCollection") {
      for (const member of geometry.geometries ?? []) {
        extendWithCoordinates(member.coordinates, bounds);
      }
    } else {
      extendWithCoordinates(geometry.coordinates, bounds);
    }
  }
  return bounds.every(Number.isFinite) ? bounds : null;
}
