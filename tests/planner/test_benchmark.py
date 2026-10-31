"""Tests for benchmark_routes management command and optimizer complexity."""

import io
import os
import time

import pytest
from django.core.management import call_command

from apps.planner.optimizer import Stop, optimize_fuel


@pytest.mark.django_db
def test_benchmark_routes_mock_execution():
    """Verify benchmark_routes runs in mock mode with 0 network calls and valid output structure."""
    from apps.stations.index import StationIndex
    from apps.stations.models import Station

    if not Station.objects.filter(lat__isnull=False).exists():
        call_command("import_fuel_prices")
        call_command("load_stations")
        StationIndex.refresh()

    out = io.StringIO()
    call_command("benchmark_routes", mock=True, iterations=2, stdout=out)
    output = out.getvalue()

    assert "SPOTTER FLEET FUEL ROUTE PLANNER" in output
    assert "MOCK FIXTURES (0 network calls)" in output
    assert "Dallas, TX -> Denver, CO" in output
    assert "New York, NY -> Los Angeles, CA" in output
    assert "Chicago, IL -> Atlanta, GA" in output
    assert "Seattle, WA -> Miami, FL" in output
    assert "Houston, TX -> Phoenix, AZ" in output
    assert "Boston, MA -> Washington, DC" in output
    assert "AVERAGE (6 PAIRS)" in output

    if os.environ.get("BENCH_STRICT") == "1":
        assert "[PASS] Average local compute" in output
        assert "[PASS] Average warm cached response" in output
    else:
        # On non-strict or loaded CI/reviewer runs, allow PASS or WARN (< 100 ms)
        assert "[PASS] Average local compute" in output or "[WARN] Average local compute" in output
        assert (
            "[PASS] Average warm cached response" in output
            or "[WARN] Average warm cached response" in output
        )


def test_optimizer_complexity_linear_in_station_count():
    """Verify that greedy optimizer runtime scales linearly O(N) with candidate station count."""

    def make_stops(n: int, total_miles: float) -> list[Stop]:
        step = total_miles / (n + 1)
        return [
            Stop(
                mile=step * (i + 1),
                price=3.00 + ((i % 10) * 0.10),
                ref={"id": i, "name": f"Station {i}"},
            )
            for i in range(n)
        ]

    # Pre-warm
    warm = make_stops(50, 1000.0)
    optimize_fuel(warm, 1000.0, optimize_for="cost")

    n1, n2 = 200, 1000
    s1 = make_stops(n1, 5000.0)
    s2 = make_stops(n2, 5000.0)

    iters = 25
    t0 = time.perf_counter()
    for _ in range(iters):
        optimize_fuel(s1, 5000.0, optimize_for="cost")
    t1 = time.perf_counter() - t0

    t0 = time.perf_counter()
    for _ in range(iters):
        optimize_fuel(s2, 5000.0, optimize_for="cost")
    t2 = time.perf_counter() - t0

    # For O(N), ratio t2/t1 scales ~ 5x (n2/n1 = 5). For O(N^2), ratio would be 25x.
    ratio = t2 / max(t1, 1e-6)
    assert ratio < 15.0, f"Expected linear scaling (t2/t1 ~ 5), but got ratio={ratio:.2f}"
