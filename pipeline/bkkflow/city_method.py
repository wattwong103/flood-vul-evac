"""Shared city screening assumptions; changing these changes the method.

Grid origins may differ, so exposure compares full footprints rather than IDs.
These are scenario assumptions, not calibrated Bangkok evacuation parameters.
"""

PUBLIC_GRID_M = 1000.0
SNAP_TOLERANCE_M = 400.0
ROUTING_CUTOFF_MINUTES = 180


def cell_footprints(x, y):
    """Square public cells about projected metre coordinates."""
    import shapely
    half = PUBLIC_GRID_M / 2
    return shapely.box(x - half, y - half, x + half, y + half)
