"""Patch observed_evac to decide closures from the 30 m water mask.

Aggregating water to 1 km before testing which roads are affected closed 87%
of the city, which is an artefact of the aggregation. The source 30 m
classification is the only resolution at which "is this road wet" is a
meaningful question.
"""

from pathlib import Path

P = Path("pipeline/bkkflow/observed_evac.py")
src = P.read_text(encoding="utf-8")

MARKER = "def _water_cell_geometries(year: int) -> gpd.GeoDataFrame:"

HELPERS = '''WATER_MASK_CACHE: dict[int, Any] = {}


def water_mask(year: int):
    """Return (mask, transform, crs) for a year at the SOURCE 30 m resolution.

    Aggregating water to 1 km before testing which roads are affected destroys
    the very thing the test needs: inside a 1 km cell the water may be a canal
    with dry roads either side of it. Deciding closures from cell centres closed
    87% of the city, which is an artefact of the aggregation rather than a
    finding. The 30 m classification is the resolution at which "is this road
    wet" is a meaningful question.
    """
    if year in WATER_MASK_CACHE:
        return WATER_MASK_CACHE[year]

    from pathlib import Path as _Path
    from rasterio.mask import mask as rio_mask

    from .aoi import load_aoi
    from .sources import gsw as gsw_module

    aoi = load_aoi("bangkok-bma")
    bounds = tuple(float(value) for value in aoi.geometry.union_all().bounds)
    path = _Path("data/staged/gsw") / gsw_module.tile_name_for(year, bounds)
    if not path.is_file():
        WATER_MASK_CACHE[year] = None
        return None
    with rasterio.open(path) as dataset:
        data, transform = rio_mask(
            dataset,
            [aoi.geometry.union_all()],
            crop=True,
            filled=True,
            nodata=gsw_module.CODE_NO_DATA_LAND,
        )
        crs = dataset.crs
    result = (data[0] == gsw_module.CODE_WATER, transform, crs)
    WATER_MASK_CACHE[year] = result
    return result


def edges_in_water(
    edges: gpd.GeoDataFrame, year: int, samples_per_edge: int = 5
) -> np.ndarray:
    """Flag edges that pass through observed water, sampled along their length.

    Several samples per edge catch a short flooded section that the endpoints
    alone would miss. Returns a boolean array aligned with ``edges``.
    """
    import shapely
    from rasterio.transform import rowcol

    masked = water_mask(year)
    if masked is None:
        return np.zeros(len(edges), dtype=bool)
    mask, transform, crs = masked

    from pyproj import Transformer

    source_crs = str(edges.crs) if edges.crs is not None else "EPSG:32647"
    to_mask = Transformer.from_crs(source_crs, crs, always_xy=True)

    geometries = np.asarray(edges.geometry.values, dtype=object)
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    for fraction in np.linspace(0.0, 1.0, samples_per_edge):
        points = shapely.get_coordinates(
            shapely.line_interpolate_point(geometries, fraction)
        )
        xs.append(points[:, 0])
        ys.append(points[:, 1])
    mask_x, mask_y = to_mask.transform(np.concatenate(xs), np.concatenate(ys))
    rows, cols = rowcol(transform, mask_x, mask_y)
    rows = np.clip(np.asarray(rows, dtype="int64"), 0, mask.shape[0] - 1)
    cols = np.clip(np.asarray(cols, dtype="int64"), 0, mask.shape[1] - 1)
    wet = mask[rows, cols].reshape(len(edges), samples_per_edge)
    return wet.any(axis=1)


'''

assert src.count(MARKER) == 1, src.count(MARKER)
src = src.replace(MARKER, HELPERS + MARKER, 1)

OLD_CLOSURE = """    closed_mask = np.zeros(len(edges), dtype=bool)
    if not water.empty and "geometry_wkt" in edges.columns:
        from shapely import wkt as shapely_wkt
        from shapely.strtree import STRtree

        edge_geoms = np.asarray(
            [shapely_wkt.loads(text) for text in edges["geometry_wkt"]], dtype=object
        )
        tree = STRtree(edge_geoms)
        # A 1 km cell is represented by its centre point, and a centre point
        # does not intersect a road. Ask which edges pass near the cell instead,
        # using half a cell diagonal as the tolerance.
        hits = tree.query(
            water.geometry.values, predicate="dwithin", distance=707.0
        )
        if len(hits):
            closed_mask[np.unique(hits[1])] = True
    closed_edges = int(closed_mask.sum())"""

NEW_CLOSURE = """    if not water.empty and "geometry_wkt" in edges.columns:
        from shapely import wkt as shapely_wkt

        edges = edges.copy()
        edges["geometry"] = edges["geometry_wkt"].map(shapely_wkt.loads)
        edges = gpd.GeoDataFrame(edges, geometry="geometry", crs="EPSG:32647")
        closed_mask = edges_in_water(edges, year)
    else:
        closed_mask = np.zeros(len(edges), dtype=bool)
    closed_edges = int(closed_mask.sum())"""

assert src.count(OLD_CLOSURE) == 1, src.count(OLD_CLOSURE)
src = src.replace(OLD_CLOSURE, NEW_CLOSURE, 1)

P.write_text(src, encoding="utf-8")
print("patched: closures now decided at 30 m")
