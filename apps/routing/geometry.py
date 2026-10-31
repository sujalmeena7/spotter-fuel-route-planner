"""Vectorized spherical geometry and route thinning."""

import numpy as np

EARTH_RADIUS_MILES = 3958.8


def compute_cumulative_miles(
    coords: list[list[float]] | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute segment distances and cumulative miles along route coordinates [[lon, lat], ...].

    Returns (segment_miles, cumulative_miles).
    """
    arr = np.asarray(coords, dtype=np.float64)
    if len(arr) == 0:
        return np.array([]), np.array([])
    if len(arr) == 1:
        return np.array([0.0]), np.array([0.0])

    lons = np.radians(arr[:, 0])
    lats = np.radians(arr[:, 1])

    dlat = lats[1:] - lats[:-1]
    dlon = lons[1:] - lons[:-1]

    a = np.sin(dlat / 2.0) ** 2 + np.cos(lats[:-1]) * np.cos(lats[1:]) * np.sin(dlon / 2.0) ** 2
    c = 2.0 * np.arcsin(np.clip(np.sqrt(a), 0.0, 1.0))
    seg_miles = EARTH_RADIUS_MILES * c

    cum_miles = np.empty(len(arr), dtype=np.float64)
    cum_miles[0] = 0.0
    cum_miles[1:] = np.cumsum(seg_miles)

    return seg_miles, cum_miles


def thin_geometry(coords: list[list[float]], min_step_miles: float = 0.1) -> list[list[float]]:
    """Thin response geometry by keeping vertex if >= min_step_miles from previous kept vertex.

    Always keeps the first and last vertex.
    """
    if len(coords) <= 2:
        return coords

    _, cum_miles = compute_cumulative_miles(coords)
    thinned = [coords[0]]
    last_kept_mile = cum_miles[0]

    for i in range(1, len(coords) - 1):
        if (cum_miles[i] - last_kept_mile) >= min_step_miles:
            thinned.append(coords[i])
            last_kept_mile = cum_miles[i]

    # Always keep last vertex
    thinned.append(coords[-1])
    return thinned


def lat_lon_to_unit_vectors(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Convert arrays of latitudes and longitudes (in degrees) to 3D unit vectors on sphere."""
    lats_r = np.radians(lats)
    lons_r = np.radians(lons)

    x = np.cos(lats_r) * np.cos(lons_r)
    y = np.cos(lats_r) * np.sin(lons_r)
    z = np.sin(lats_r)

    return np.column_stack((x, y, z))


def chord_to_great_circle_miles(chord_dist: np.ndarray) -> np.ndarray:
    """Convert 3D Euclidean chord distance on unit sphere to great-circle miles."""
    theta = 2.0 * np.arcsin(np.clip(chord_dist / 2.0, 0.0, 1.0))
    return EARTH_RADIUS_MILES * theta
