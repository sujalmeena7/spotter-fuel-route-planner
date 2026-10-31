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


def test_optimizer_invariant_fuel_purchased_plus_start_fuel():
    """For every successful plan, total_gallons_purchased + start_fuel >= distance/mpg - 1e-6."""
    stops = [
        Stop(mile=10.0, price=3.20),
        Stop(mile=200.0, price=3.00),
        Stop(mile=450.0, price=3.50),
        Stop(mile=700.0, price=2.80),
    ]
    for dist in [150.0, 300.0, 500.0, 850.0]:
        for start_fuel in [0.0, 5.0, 15.0, 30.0, 50.0]:
            for mode in ["cost", "practical"]:
                res = optimize_fuel(
                    stops,
                    total_miles=dist,
                    tank_gal=50.0,
                    mpg=10.0,
                    start_fuel=start_fuel,
                    optimize_for=mode,
                )
                assert res.total_gallons + start_fuel >= (dist / 10.0) - 1e-6


def test_low_starting_fuel_unreachable_both_modes():
    """Verify low starting fuel where no station is reachable raises Unreachable in both cost and practical modes."""
    stops = [
        Stop(mile=105.46, price=3.199),
        Stop(mile=128.85, price=2.799),
    ]
    total_miles = 197.03
    for fuel in [0.5, 5.0]:
        for mode in ["cost", "practical"]:
            with pytest.raises(Unreachable) as exc_info:
                optimize_fuel(
                    stops=stops,
                    total_miles=total_miles,
                    tank_gal=50.0,
                    mpg=10.0,
                    start_fuel=fuel,
                    optimize_for=mode,
                )
            assert exc_info.value.gap_start_mile == 0.0
            assert exc_info.value.gap_end_mile == 105.46


def test_dp_cross_check_200_seeded_cases():
    """Verify greedy optimizer strictly matches DP reference solver on 200 seeded random instances
    with fixed-price origin stop, and verify practical cost >= cost-mode cost."""
    random.seed(98765)
    mpg = 10
    tank_gal = 50

    for case_num in range(200):
        num_stops = random.randint(3, 15)
        stops = []
        origin_mile = random.randint(0, 2) * float(mpg)
        origin_price = round(random.uniform(2.5, 4.5), 3)
        stops.append(Stop(mile=origin_mile, price=origin_price))
        curr_mile = origin_mile

        for _ in range(num_stops - 1):
            gap_gal = random.randint(5, 45)  # 50 to 450 miles (<= 500 mi range)
            curr_mile += gap_gal * mpg
            stops.append(Stop(mile=curr_mile, price=round(random.uniform(2.5, 4.5), 3)))

        total_miles = curr_mile + (random.randint(2, 40) * mpg)

        # Supply fixed-price origin stop at mile 0
        if stops[0].mile > 0.0:
            stops.insert(0, Stop(mile=0.0, price=origin_price, is_origin=True))

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

        # Run Dynamic Programming (given fixed-price origin stop)
        dp_cost = solve_dp(stops, total_miles=total_miles, tank_gal=tank_gal, mpg=mpg)

        # Assert exact equivalence
        diff = abs(greedy_raw_cost - dp_cost)
        assert diff < 1e-6, (
            f"Case {case_num} failed: greedy={greedy_raw_cost}, dp={dp_cost}, diff={diff}"
        )

        # Verify practical cost >= cost-mode cost
        prac_res = optimize_fuel(
            stops,
            total_miles=total_miles,
            tank_gal=tank_gal,
            mpg=mpg,
            start_fuel=0.0,
            optimize_for="practical",
        )
        assert float(prac_res.total_cost_usd) >= float(res.total_cost_usd) - 1e-6, (
            f"Case {case_num}: practical={prac_res.total_cost_usd} < cost={res.total_cost_usd}"
        )


@pytest.mark.django_db
def test_practical_stop_consolidation_ny_to_la():
    """Verify practical dispatch mode on NY->LA consolidates stops within 2% of pure cost."""
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

    # In pure greedy, NY->LA has 19 stops (with origin fill)
    assert pure_stops_count == 19
    # In practical mode, stops must be consolidated to <= 9
    assert practical_stops_count <= 9, f"Expected <= 9 stops, got {practical_stops_count}"
    # Total cost must be within 2% of pure cost optimum
    assert practical_cost <= 1.02 * pure_cost
    assert practical_cost >= pure_cost

    # Every stop except possibly the last must purchase >= MIN_PURCHASE_GALLONS
    min_purchase = 10.0
    for ps in practical_plan.stops[:-1]:
        assert ps.gallons_purchased >= min_purchase - 1e-4, (
            f"NY->LA: Stop at {ps.mile} buys {ps.gallons_purchased} < {min_purchase}"
        )


@pytest.mark.django_db
def test_arrival_departure_consistency_benchmark_routes():
    """Verify arrival/departure fuel consistency for every stop on all 6 benchmark routes:
    arrival_next = departure_prev - (mile_next - mile_prev)/mpg (within 0.01)."""
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

    for name, rdata in routes.items():
        route = Route(
            coordinates=rdata["coordinates"],
            distance_m=rdata["distance_m"],
            duration_s=rdata["duration_s"],
            provider="benchmark",
        )
        corridor_stations = find_corridor_stations(route, corridor_miles=10.0)
        orig_stop = Stop(
            mile=0.0,
            price=corridor_stations[0].price_float if corridor_stations else 3.0,
            is_origin=True,
        )
        stops = [orig_stop] + [
            Stop(mile=cs.mile_marker, price=cs.price_float, ref=cs)
            for cs in corridor_stations
            if cs.mile_marker > 0.0
        ]
        for mode in ["cost", "practical"]:
            res = optimize_fuel(
                stops, total_miles=route.distance_miles, start_fuel=0.0, optimize_for=mode
            )
            assert len(res.stops) > 0, f"{name} {mode} has no stops"
            assert abs(res.stops[0].fuel_on_arrival_gallons - 0.0) < 0.01
            for i in range(1, len(res.stops)):
                prev = res.stops[i - 1]
                curr = res.stops[i]
                burn = (curr.mile - prev.mile) / 10.0
                expected_arr = prev.fuel_on_departure_gallons - burn
                diff = abs(curr.fuel_on_arrival_gallons - expected_arr)
                assert diff <= 0.01, (
                    f"{name} {mode} stop {i}: arr={curr.fuel_on_arrival_gallons}, exp={expected_arr}, diff={diff}"
                )


@pytest.mark.django_db
def test_practical_cost_ge_cost_mode_benchmark_routes():
    """Verify practical mode cost >= cost-mode cost for all 6 benchmark routes."""
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

    for name, rdata in routes.items():
        route = Route(
            coordinates=rdata["coordinates"],
            distance_m=rdata["distance_m"],
            duration_s=rdata["duration_s"],
            provider="benchmark",
        )
        corridor_stations = find_corridor_stations(route, corridor_miles=10.0)
        orig_stop = Stop(
            mile=0.0,
            price=corridor_stations[0].price_float if corridor_stations else 3.0,
            is_origin=True,
        )
        stops = [orig_stop] + [
            Stop(mile=cs.mile_marker, price=cs.price_float, ref=cs)
            for cs in corridor_stations
            if cs.mile_marker > 0.0
        ]
        c_res = optimize_fuel(
            stops, total_miles=route.distance_miles, start_fuel=0.0, optimize_for="cost"
        )
        p_res = optimize_fuel(
            stops, total_miles=route.distance_miles, start_fuel=0.0, optimize_for="practical"
        )
        assert float(p_res.total_cost_usd) >= float(c_res.total_cost_usd) - 1e-6, (
            f"{name}: practical={p_res.total_cost_usd} < cost={c_res.total_cost_usd}"
        )
        # Every stop except possibly the last must purchase >= MIN_PURCHASE_GALLONS in practical mode
        min_purchase = 10.0
        for ps in p_res.stops[:-1]:
            assert ps.gallons_purchased >= min_purchase - 1e-4, (
                f"{name}: stop at mile {ps.mile} buys {ps.gallons_purchased} < {min_purchase}"
            )
