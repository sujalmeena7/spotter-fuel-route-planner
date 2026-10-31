"""Tests for benchmark_routes management command."""

import io

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_benchmark_routes_mock_execution():
    """Verify benchmark_routes runs in mock mode with 0 network calls and meets < 50ms bar."""
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
    assert "Seattle, WA -> Miami, FL" in output
    assert "AVERAGE (6 PAIRS)" in output
    assert "[PASS] Average local compute" in output
    assert "[PASS] Average warm cached response" in output
