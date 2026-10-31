import json
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client

from apps.planner.optimizer import NoFuelNearOrigin, Unreachable
from apps.routing.exceptions import (
    NoRoute,
    UpstreamError,
    UpstreamTimeout,
)
from apps.routing.providers import OpenRouteServiceProvider, Route
from apps.stations.index import StationIndex
from apps.stations.models import Station


@pytest.fixture(autouse=True)
def ensure_db_stations_and_clean_cache():
    cache.clear()
    if not Station.objects.filter(lat__isnull=False).exists():
        call_command("import_fuel_prices")
        call_command("load_stations")
        StationIndex.refresh()
    yield
    cache.clear()


@pytest.fixture
def mock_ors_route(monkeypatch):
    """Mocks OpenRouteServiceProvider to return recorded fixtures without network."""
    dallas_path = settings.BASE_DIR / "tests" / "fixtures" / "ors_dallas_denver.json"
    with open(dallas_path, encoding="utf-8") as f:
        dallas_data = json.load(f)
    d_feat = dallas_data["features"][0]
    dallas_route = Route(
        coordinates=d_feat["geometry"]["coordinates"],
        distance_m=float(d_feat["properties"]["summary"]["distance"]),
        duration_s=float(d_feat["properties"]["summary"]["duration"]),
        provider="openrouteservice",
    )

    houston_path = settings.BASE_DIR / "tests" / "fixtures" / "ors_houston_san_antonio.json"
    with open(houston_path, encoding="utf-8") as f:
        houston_data = json.load(f)
    h_feat = houston_data["features"][0]
    houston_route = Route(
        coordinates=h_feat["geometry"]["coordinates"],
        distance_m=float(h_feat["properties"]["summary"]["distance"]),
        duration_s=float(h_feat["properties"]["summary"]["duration"]),
        provider="openrouteservice",
    )

    def mock_get_route(self, origin, destination):
        lat1, _ = origin
        if abs(lat1 - 29.78) < 1.0:
            return houston_route
        return dallas_route

    monkeypatch.setattr(OpenRouteServiceProvider, "get_route", mock_get_route)
    return dallas_route


@pytest.mark.django_db
def test_cold_and_warm_request_call_counts(mock_ors_route):
    """A cold request makes exactly 1 external routing call; warm request makes 0 calls."""
    client = Client()

    # 1. Cold request
    resp_cold = client.get(
        "/api/v1/route-plan/?start=Dallas,TX&finish=Denver,CO&start_fuel_gallons=0"
    )
    assert resp_cold.status_code == 200
    data_cold = resp_cold.json()

    assert data_cold["meta"]["external_api_calls"] == 1
    assert data_cold["meta"]["cache_hit"] is False
    assert "X-Response-Time-ms" in resp_cold.headers
    assert "routing_ms" in data_cold["meta"]
    assert "local_compute_ms" in data_cold["meta"]
    assert "total_ms" in data_cold["meta"]
    assert "timing" in data_cold["meta"]
    assert "routing_ms" in data_cold["meta"]["timing"]
    assert "local_compute_ms" in data_cold["meta"]["timing"]
    assert "total_ms" in data_cold["meta"]["timing"]

    # 2. Warm request
    resp_warm = client.get(
        "/api/v1/route-plan/?start=Dallas,TX&finish=Denver,CO&start_fuel_gallons=0"
    )
    assert resp_warm.status_code == 200
    data_warm = resp_warm.json()

    assert data_warm["meta"]["external_api_calls"] == 0
    assert data_warm["meta"]["cache_hit"] is True

    # Validate output structure
    assert "summary" in data_warm
    assert "fuel_stops" in data_warm
    assert "route" in data_warm
    assert data_warm["route"]["type"] == "FeatureCollection"
    assert len(data_warm["fuel_stops"]) > 0


@pytest.mark.django_db
def test_get_and_post_bodies_are_identical(mock_ors_route):
    """GET and POST endpoints must return identical bodies for identical inputs."""
    client = Client()

    # Clear cache before GET
    cache.clear()
    get_resp = client.get(
        "/api/v1/route-plan/?start=Dallas%2C+TX&finish=Denver%2C+CO&start_fuel_gallons=10&include_candidates=true"
    )

    # Clear cache before POST so both are evaluated under identical cache conditions
    cache.clear()
    post_resp = client.post(
        "/api/v1/route-plan/",
        data={
            "start": "Dallas, TX",
            "finish": "Denver, CO",
            "start_fuel_gallons": 10.0,
            "include_candidates": True,
        },
        content_type="application/json",
    )

    assert get_resp.status_code == 200
    assert post_resp.status_code == 200

    get_data = get_resp.json()
    post_data = post_resp.json()

    # Strip timing fields as microsecond timing can vary
    for d in (get_data, post_data):
        d["meta"]["compute_ms"] = 0
        d["meta"]["local_compute_ms"] = 0
        d["meta"]["routing_ms"] = 0
        d["meta"]["total_ms"] = 0
        if "timing" in d["meta"]:
            d["meta"]["timing"]["local_compute_ms"] = 0
            d["meta"]["timing"]["routing_ms"] = 0
            d["meta"]["timing"]["total_ms"] = 0

    assert get_data == post_data


@pytest.mark.django_db
def test_include_candidates_flag(mock_ors_route):
    """Verify include_candidates adds candidates list when True and omits when False."""
    client = Client()

    # False: candidates omitted
    resp_no_cand = client.get(
        "/api/v1/route-plan/?start=Dallas,TX&finish=Denver,CO&include_candidates=false"
    )
    assert resp_no_cand.status_code == 200
    assert "candidates" not in resp_no_cand.json()

    cache.clear()

    # True: candidates present
    resp_with_cand = client.get(
        "/api/v1/route-plan/?start=Dallas,TX&finish=Denver,CO&include_candidates=true"
    )
    assert resp_with_cand.status_code == 200
    data = resp_with_cand.json()
    assert "candidates" in data
    assert isinstance(data["candidates"], list)
    assert len(data["candidates"]) > 0


@pytest.mark.django_db
def test_error_invalid_input_400():
    """Verify missing required fields return 400 invalid_input."""
    client = Client()
    resp = client.get("/api/v1/route-plan/?start=Dallas,TX")
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "invalid_input"
    assert "finish" in err["details"]


@pytest.mark.django_db
def test_error_location_not_found_422(settings):
    """Verify unresolvable location returns 422 location_not_found."""
    settings.ORS_API_KEY = ""
    client = Client()
    resp = client.get("/api/v1/route-plan/?start=NonexistentXyzCity,TX&finish=Denver,CO")
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "location_not_found"


@pytest.mark.django_db
def test_error_location_outside_usa_422():
    """Verify coordinates outside USA return 422 location_outside_usa."""
    client = Client()
    # Paris, France
    resp = client.get("/api/v1/route-plan/?start=48.8566,2.3522&finish=Denver,CO")
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "location_outside_usa"


@pytest.mark.django_db
def test_error_no_route_422(monkeypatch):
    """Verify provider NoRoute returns 422 no_route."""

    def mock_raise_no_route(*args, **kwargs):
        raise NoRoute("No route exists between waypoints.")

    monkeypatch.setattr(OpenRouteServiceProvider, "get_route", mock_raise_no_route)

    client = Client()
    resp = client.get("/api/v1/route-plan/?start=Dallas,TX&finish=Denver,CO")
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "no_route"


@pytest.mark.django_db
def test_error_unreachable_422(monkeypatch, mock_ors_route):
    """Verify optimizer Unreachable gap returns 422 unreachable with gap details."""
    with patch("apps.planner.service.optimize_fuel", side_effect=Unreachable(200.0, 750.0)):
        client = Client()
        resp = client.get("/api/v1/route-plan/?start=Dallas,TX&finish=Denver,CO")
        assert resp.status_code == 422
        err = resp.json()["error"]
        assert err["code"] == "unreachable"
        assert err["details"]["gap_start_mile"] == 200.0
        assert err["details"]["gap_end_mile"] == 750.0


@pytest.mark.django_db
def test_error_no_fuel_near_origin_422(monkeypatch, mock_ors_route):
    """Verify optimizer NoFuelNearOrigin returns 422 no_fuel_near_origin."""
    with patch(
        "apps.planner.service.optimize_fuel", side_effect=NoFuelNearOrigin("No fuel near origin")
    ):
        client = Client()
        resp = client.get("/api/v1/route-plan/?start=Dallas,TX&finish=Denver,CO")
        assert resp.status_code == 422
        err = resp.json()["error"]
        assert err["code"] == "no_fuel_near_origin"


@pytest.mark.django_db
def test_error_upstream_502(monkeypatch):
    """Verify provider 5xx returns 502 routing_upstream_error."""

    def mock_raise_upstream(*args, **kwargs):
        raise UpstreamError("Upstream server failed")

    monkeypatch.setattr(OpenRouteServiceProvider, "get_route", mock_raise_upstream)

    client = Client()
    resp = client.get("/api/v1/route-plan/?start=Dallas,TX&finish=Denver,CO")
    assert resp.status_code == 502
    err = resp.json()["error"]
    assert err["code"] == "routing_upstream_error"


@pytest.mark.django_db
def test_error_timeout_503(monkeypatch):
    """Verify provider timeout returns 503 routing_timeout."""

    def mock_raise_timeout(*args, **kwargs):
        raise UpstreamTimeout("Connection timed out")

    monkeypatch.setattr(OpenRouteServiceProvider, "get_route", mock_raise_timeout)

    client = Client()
    resp = client.get("/api/v1/route-plan/?start=Dallas,TX&finish=Denver,CO")
    assert resp.status_code == 503
    err = resp.json()["error"]
    assert err["code"] == "routing_timeout"


@pytest.mark.django_db
def test_low_starting_fuel_unreachable_api_both_modes(mock_ors_route):
    """GET /api/v1/route-plan/ with low starting fuel on Houston -> San Antonio returns 422 unreachable."""
    client = Client()
    for fuel in [5.0, 0.5]:
        for mode in ["cost", "practical"]:
            resp = client.get(
                f"/api/v1/route-plan/?start=Houston, TX&finish=San Antonio, TX&start_fuel_gallons={fuel}&optimize_for={mode}"
            )
            assert resp.status_code == 422
            data = resp.json()
            assert data["error"]["code"] == "unreachable"
            assert data["error"]["details"]["gap_start_mile"] == 0.0
            assert data["error"]["details"]["gap_end_mile"] == 105.46
