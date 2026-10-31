"""Corridor matching engine using vectorized unit-sphere cKDTree."""

from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from scipy.spatial import cKDTree

from apps.routing.geometry import (
    chord_to_great_circle_miles,
    compute_cumulative_miles,
    lat_lon_to_unit_vectors,
)
from apps.routing.providers import Route
from apps.stations.index import StationIndex


@dataclass(frozen=True)
class CorridorStation:
    """Station located within the route corridor."""

    station_id: int
    name: str
    address: str
    city: str
    state: str
    lat: float
    lon: float
    price: Decimal
    price_float: float
    mile_marker: float
    off_route_miles: float


def find_corridor_stations(
    route: Route,
    corridor_miles: float = 10.0,
    index: StationIndex | None = None,
) -> list[CorridorStation]:
    """Find all fuel stations within corridor_miles of the route.

    1. Bounding box pre-filter.
    2. cKDTree search on 3D unit sphere vectors.
    3. Chord to great-circle conversion.
    4. Sorted by mile marker along route.
    """
    if not route.coordinates:
        return []

    idx = index or StationIndex.get_instance()
    if len(idx) == 0:
        return []

    route_arr = np.asarray(route.coordinates, dtype=np.float64)  # [[lon, lat], ...]
    route_lons = route_arr[:, 0]
    route_lats = route_arr[:, 1]

    # Compute cumulative miles along the full route geometry
    _, cum_miles = compute_cumulative_miles(route_arr)

    # 1. Bounding box pre-filter
    min_lat = np.min(route_lats)
    max_lat = np.max(route_lats)
    min_lon = np.min(route_lons)
    max_lon = np.max(route_lons)

    # 1 degree of latitude is ~69 miles
    pad_lat = corridor_miles / 69.0
    mean_lat = (min_lat + max_lat) / 2.0
    cos_lat = max(0.1, np.cos(np.radians(mean_lat)))
    pad_lon = (corridor_miles / 69.0) / cos_lat

    bbox_mask = (
        (idx.lats >= min_lat - pad_lat)
        & (idx.lats <= max_lat + pad_lat)
        & (idx.lons >= min_lon - pad_lon)
        & (idx.lons <= max_lon + pad_lon)
    )

    cand_indices = np.where(bbox_mask)[0]
    if len(cand_indices) == 0:
        return []

    cand_unit_vectors = idx.unit_vectors[cand_indices]

    # 2. Build cKDTree on route 3D unit vectors
    route_unit_vectors = lat_lon_to_unit_vectors(route_lats, route_lons)
    tree = cKDTree(route_unit_vectors)

    # 3. Query nearest route vertex for each candidate
    chords, nearest_vertices = tree.query(cand_unit_vectors, k=1)

    # 4. Convert chord distances to great-circle miles
    dist_miles = chord_to_great_circle_miles(chords)

    # 5. Filter stations within corridor_miles
    within_corridor = np.where(dist_miles <= corridor_miles)[0]
    if len(within_corridor) == 0:
        return []

    results: list[CorridorStation] = []
    for rel_idx in within_corridor:
        orig_idx = cand_indices[rel_idx]
        v_idx = nearest_vertices[rel_idx]
        marker = round(float(cum_miles[v_idx]), 2)
        off_route = round(float(dist_miles[rel_idx]), 2)

        results.append(
            CorridorStation(
                station_id=int(idx.ids[orig_idx]),
                name=idx.names[orig_idx],
                address=idx.addresses[orig_idx],
                city=idx.cities[orig_idx],
                state=idx.states[orig_idx],
                lat=round(float(idx.lats[orig_idx]), 5),
                lon=round(float(idx.lons[orig_idx]), 5),
                price=idx.prices_decimal[orig_idx],
                price_float=float(idx.prices[orig_idx]),
                mile_marker=marker,
                off_route_miles=off_route,
            )
        )

    # Sort strictly by mile_marker
    results.sort(key=lambda s: s.mile_marker)
    return results
