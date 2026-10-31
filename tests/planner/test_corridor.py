import json
import time
from decimal import Decimal

import numpy as np
import pytest
from django.conf import settings

from apps.planner.corridor import find_corridor_stations
from apps.routing.geometry import (
    compute_cumulative_miles,
    thin_geometry,
)
from apps.routing.providers import Route
from apps.stations.index import StationIndex
from apps.stations.models import Station


def test_geometry_cumulative_and_thinning():
    """Verify cumulative miles calculation and geometry thinning."""
    # 100 points along meridian from 30.0N to 31.0N (-97.0W)
    lats = np.linspace(30.0, 31.0, 101)
    coords = [[-97.0, float(lat)] for lat in lats]

    seg_miles, cum_miles = compute_cumulative_miles(coords)
    assert len(cum_miles) == 101
    assert cum_miles[0] == 0.0
    total_dist = cum_miles[-1]
    # 1 degree of latitude is ~69.1 miles
    assert 68.8 <= total_dist <= 69.3

    thinned = thin_geometry(coords, min_step_miles=1.0)
    assert len(thinned) < len(coords)
    assert thinned[0] == coords[0]
    assert thinned[-1] == coords[-1]


def test_corridor_matching_synthetic():
    """Verify corridor matching with synthetic route and mock station index."""
    # Straight north route from 30.0N to 32.0N (~138.2 miles)
    lats = np.linspace(30.0, 32.0, 201)
    route_coords = [[-97.0, float(lat)] for lat in lats]
    route = Route(
        coordinates=route_coords,
        distance_m=138.2 * 1609.344,
        duration_s=7200.0,
        provider="synthetic",
    )

    # Create mock StationIndex
    mock_idx = StationIndex()
    # 4 stations:
    # 1: Exactly on route at 30.5N (~34.5 mi)
    # 2: 3.0 mi west of route at 31.0N (within 10 mi corridor)
    # 3: 30.0 mi west of route at 31.0N (outside 10 mi corridor)
    # 4: Far north at 40.0N (outside bbox)
    mock_idx.ids = np.array([1, 2, 3, 4], dtype=np.int32)
    mock_idx.lats = np.array([30.5, 31.0, 31.0, 40.0], dtype=np.float64)
    # At lat 31, 1 deg lon is ~59.3 mi, so 0.05 deg is ~3 mi, 0.5 deg is ~30 mi
    mock_idx.lons = np.array([-97.0, -97.05, -97.5, -97.0], dtype=np.float64)
    mock_idx.prices = np.array([3.10, 3.20, 2.90, 3.00], dtype=np.float64)
    mock_idx.prices_decimal = [
        Decimal("3.100"),
        Decimal("3.200"),
        Decimal("2.900"),
        Decimal("3.000"),
    ]
    mock_idx.names = ["Station 1", "Station 2", "Station 3", "Station 4"]
    mock_idx.addresses = ["Addr 1", "Addr 2", "Addr 3", "Addr 4"]
    mock_idx.cities = ["City 1", "City 2", "City 3", "City 4"]
    mock_idx.states = ["TX", "TX", "TX", "WY"]
    mock_idx.rack_ids = [1, 2, 3, 4]
    from apps.routing.geometry import lat_lon_to_unit_vectors

    mock_idx.unit_vectors = lat_lon_to_unit_vectors(mock_idx.lats, mock_idx.lons)

    stations = find_corridor_stations(route, corridor_miles=10.0, index=mock_idx)

    # Stations 1 and 2 must be included; 3 (too far) and 4 (outside bbox) excluded
    station_ids = [s.station_id for s in stations]
    assert station_ids == [1, 2]

    # Mile marker accuracy within 0.5 mi
    s1 = stations[0]
    assert abs(s1.mile_marker - 34.55) < 0.5
    assert s1.off_route_miles < 0.2

    s2 = stations[1]
    assert abs(s2.mile_marker - 69.1) < 0.5
    assert 2.5 <= s2.off_route_miles <= 3.5

    # Check sorted by mile marker
    assert stations[0].mile_marker <= stations[1].mile_marker


@pytest.mark.django_db
def test_corridor_matching_dallas_to_denver_performance():
    """Verify corridor matching against real database stations completes in under 50 ms."""
    from django.core.management import call_command

    if not Station.objects.filter(lat__isnull=False).exists():
        call_command("import_fuel_prices")
        call_command("load_stations")
        StationIndex.refresh()

    fixture_path = settings.BASE_DIR / "tests" / "fixtures" / "ors_dallas_denver.json"
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    feat = data["features"][0]
    coords = feat["geometry"]["coordinates"]
    summary = feat["properties"]["summary"]
    route = Route(
        coordinates=coords,
        distance_m=float(summary["distance"]),
        duration_s=float(summary["duration"]),
        provider="openrouteservice",
    )

    t0 = time.perf_counter()
    stations = find_corridor_stations(route, corridor_miles=10.0)
    match_ms = (time.perf_counter() - t0) * 1000

    # Ensure stations were found along the 780+ mile corridor
    assert len(stations) > 10
    # Must run in under 50 ms
    assert match_ms < 50.0

    # Verify sorted order
    markers = [s.mile_marker for s in stations]
    assert markers == sorted(markers)

    # Off-route distance must all be <= 10.0 mi
    for s in stations:
        assert s.off_route_miles <= 10.0
