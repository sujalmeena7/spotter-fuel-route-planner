import json
import random
from decimal import Decimal

import pytest
from django.conf import settings

from apps.planner.corridor import find_corridor_stations
from apps.planner.optimizer import (
    NoFuelNearOrigin,
    Stop,
    Unreachable,
    optimize_fuel,
)
from apps.routing.providers import Route
from tests.planner.dp_reference import solve_dp


def test_scenario_cheaper_station_ahead_partial_buy():
    """Truck buys only enough fuel to reach the cheaper station ahead."""
    stops = [
        Stop(mile=0.0, price=3.50),
        Stop(mile=200.0, price=3.00),  # Cheaper!
    ]
    # Total trip 300 miles
    res = optimize_fuel(stops, total_miles=300.0, tank_gal=50.0, mpg=10.0, start_fuel=0.0)

    assert len(res.stops) == 2
    # Stop 1 (mile 0): buys 20 gal (to cover 200 mi to Stop 2)
    s1 = res.stops[0]
    assert s1.mile == 0.0
    assert s1.gallons_purchased == 20.0
    assert s1.fuel_on_departure_gallons == 20.0

    # Stop 2 (mile 200): arrives with 0 gal, buys 10 gal (to cover remaining 100 mi)
    s2 = res.stops[1]
    assert s2.mile == 200.0
    assert s2.fuel_on_arrival_gallons == 0.0
    assert s2.gallons_purchased == 10.0
    assert s2.fuel_on_departure_gallons == 10.0

    assert res.total_gallons == 30.0  # 300 / 10


def test_scenario_all_stations_ahead_pricier_fill_up():
    """When all stations ahead in reach are pricier, truck fills to full tank."""
    stops = [
        Stop(mile=0.0, price=2.80),  # Cheapest!
        Stop(mile=300.0, price=3.90),  # Pricier
        Stop(mile=600.0, price=3.80),
    ]
    res = optimize_fuel(stops, total_miles=700.0, tank_gal=50.0, mpg=10.0, start_fuel=0.0)

    # Stop 1 fills to 50 gal
    s1 = res.stops[0]
    assert s1.mile == 0.0
    assert s1.gallons_purchased == 50.0
    assert s1.fuel_on_departure_gallons == 50.0

    # Arrives at stop 2 (mile 300) with 20 gal left, fills to 50 gal (buys 30 gal) or reaches finish
    assert res.total_gallons == 70.0


def test_scenario_trip_under_500_miles():
    """Short trip under 500 miles buys only exact needed fuel."""
    stops = [Stop(mile=10.0, price=3.20)]
    res = optimize_fuel(stops, total_miles=250.0, tank_gal=50.0, mpg=10.0, start_fuel=0.0)

    assert len(res.stops) == 1
    # 250 miles / 10 = 25 gallons total
    assert res.total_gallons == 25.0
    assert res.stops[0].gallons_purchased == 25.0


def test_scenario_start_fuel_covers_whole_trip():
    """When starting fuel alone covers the whole trip, 0 purchases are made."""
    stops = [Stop(mile=50.0, price=3.10)]
    res = optimize_fuel(stops, total_miles=200.0, tank_gal=50.0, mpg=10.0, start_fuel=25.0)

    assert res.total_gallons == 0.0
    assert res.total_cost_usd == Decimal("0.00")
    assert len(res.stops) == 0


def test_scenario_unreachable_gap():
    """Route gap exceeding 500 miles raises Unreachable with exact gap coordinates."""
    stops = [
        Stop(mile=0.0, price=3.00),
        Stop(mile=200.0, price=3.10),
        Stop(mile=750.0, price=3.20),  # Gap of 550 miles from mile 200
    ]
    with pytest.raises(Unreachable) as exc:
        optimize_fuel(stops, total_miles=1000.0, tank_gal=50.0, mpg=10.0, start_fuel=0.0)

    assert exc.value.gap_start_mile == 200.0
    assert exc.value.gap_end_mile == 750.0


def test_scenario_no_fuel_near_origin():
    """Empty truck with first station beyond 500 miles raises NoFuelNearOrigin."""
    stops = [Stop(mile=550.0, price=3.00)]
    with pytest.raises(NoFuelNearOrigin):
        optimize_fuel(stops, total_miles=800.0, tank_gal=50.0, mpg=10.0, start_fuel=0.0)


def test_scenario_price_ties_picks_farther_stop():
    """When all stops in reach are pricier and tie for cheapest, greedy picks the farther stop."""
    stops = [
        Stop(mile=0.0, price=3.00),  # Current stop cheaper than all ahead
        Stop(mile=150.0, price=3.50),  # Equal price
        Stop(mile=300.0, price=3.50),  # Equal price, but farther!
        Stop(mile=600.0, price=3.20),
    ]
    res = optimize_fuel(stops, total_miles=800.0, tank_gal=50.0, mpg=10.0, start_fuel=0.0)

    # First stop (mile 0) fills to 50 gal and travels to mile 300, skipping mile 150
    stop_miles = [s.mile for s in res.stops]
    assert 300.0 in stop_miles
    assert 150.0 not in stop_miles


def test_optimizer_invariants():
    """Assert invariants: total gallons, capacity limits, and near-zero arrival fuel."""
    stops = [
        Stop(mile=5.0, price=3.30),
        Stop(mile=180.0, price=3.10),
        Stop(mile=420.0, price=3.60),
        Stop(mile=680.0, price=2.90),
    ]
    total_miles = 850.0
    res = optimize_fuel(stops, total_miles=total_miles, tank_gal=50.0, mpg=10.0, start_fuel=0.0)

    # Invariant 1: Total gallons = total_miles / mpg
    assert abs(res.total_gallons - (total_miles / 10.0)) < 1e-4

    # Invariant 2: Fuel never goes below 0 or above tank_gal
    for s in res.stops:
        assert 0.0 <= s.fuel_on_arrival_gallons <= 50.0
        assert 0.0 <= s.fuel_on_departure_gallons <= 50.0

    # Invariant 3: Zero fuel at finish
    last_stop = res.stops[-1]
    dist_from_last = total_miles - last_stop.mile
    fuel_at_finish = last_stop.fuel_on_departure_gallons - (dist_from_last / 10.0)
    assert abs(fuel_at_finish) < 1e-4


def test_dp_cross_check_200_seeded_cases():
    """Verify greedy optimizer strictly matches DP reference solver on 200 seeded random instances."""
    random.seed(98765)
    mpg = 10
    tank_gal = 50

    for case_num in range(200):
        num_stops = random.randint(3, 15)
        stops = []
        origin_mile = random.randint(0, 2) * float(mpg)
        stops.append(Stop(mile=origin_mile, price=round(random.uniform(2.5, 4.5), 3)))
        curr_mile = origin_mile

        for _ in range(num_stops - 1):
            gap_gal = random.randint(5, 45)  # 50 to 450 miles (<= 500 mi range)
            curr_mile += gap_gal * mpg
            stops.append(Stop(mile=curr_mile, price=round(random.uniform(2.5, 4.5), 3)))

        total_miles = curr_mile + (random.randint(2, 40) * mpg)

        # Run Greedy in pure cost mode
        res = optimize_fuel(
            stops,
            total_miles=total_miles,
            tank_gal=tank_gal,
            mpg=mpg,
            start_fuel=0.0,
            optimize_for="cost",
        )
        greedy_raw_cost = sum(s.gallons_purchased * s.price_per_gallon for s in res.stops)

        # Run Dynamic Programming
        dp_cost = solve_dp(stops, total_miles=total_miles, tank_gal=tank_gal, mpg=mpg)

        # Assert exact equivalence
        diff = abs(greedy_raw_cost - dp_cost)
        assert diff < 1e-6, (
            f"Case {case_num} failed: greedy={greedy_raw_cost}, dp={dp_cost}, diff={diff}"
        )


@pytest.mark.django_db
def test_practical_stop_consolidation_ny_to_la():
    """Verify practical dispatch mode on NY->LA consolidates to <= 9 stops within 2% of pure cost."""
    from django.core.management import call_command

    from apps.stations.index import StationIndex
    from apps.stations.models import Station

    if not Station.objects.filter(lat__isnull=False).exists():
        call_command("import_fuel_prices")
        call_command("load_stations")
        StationIndex.refresh()

    fixture_path = settings.BASE_DIR / "tests" / "fixtures" / "benchmark_routes.json"
    with open(fixture_path, encoding="utf-8") as f:
        routes = json.load(f)

    ny_la = routes["New York, NY -> Los Angeles, CA"]
    route = Route(
        coordinates=ny_la["coordinates"],
        distance_m=ny_la["distance_m"],
        duration_s=ny_la["duration_s"],
        provider="benchmark",
    )
    corridor_stations = find_corridor_stations(route, corridor_miles=10.0)
    stops = [Stop(mile=cs.mile_marker, price=cs.price_float, ref=cs) for cs in corridor_stations]

    pure_plan = optimize_fuel(
        stops=stops,
        total_miles=route.distance_miles,
        tank_gal=50.0,
        mpg=10.0,
        start_fuel=0.0,
        optimize_for="cost",
    )
    practical_plan = optimize_fuel(
        stops=stops,
        total_miles=route.distance_miles,
        tank_gal=50.0,
        mpg=10.0,
        start_fuel=0.0,
        optimize_for="practical",
    )

    pure_stops_count = len(pure_plan.stops)
    practical_stops_count = len(practical_plan.stops)
    pure_cost = float(pure_plan.total_cost_usd)
    practical_cost = float(practical_plan.total_cost_usd)

    # In pure greedy, NY->LA had 17 stops
    assert pure_stops_count == 17
    # In practical mode, stops must be <= 9
    assert practical_stops_count <= 9
    # Total cost must be within 2% of pure cost optimum
    assert practical_cost <= 1.02 * pure_cost
    assert practical_cost >= pure_cost
