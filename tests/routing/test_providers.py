import json

import pytest
import requests
from django.conf import settings
from django.core.cache import cache

from apps.routing.exceptions import NoRoute, UpstreamError, UpstreamTimeout
from apps.routing.providers import (
    CachedRoutingProvider,
    OpenRouteServiceProvider,
    OSRMProvider,
    get_call_count,
    reset_call_counter,
)

FIXTURES_DIR = settings.BASE_DIR / "tests" / "fixtures"


@pytest.fixture(autouse=True)
def clean_cache_and_counter():
    cache.clear()
    reset_call_counter()
    yield
    cache.clear()
    reset_call_counter()


class MockSession:
    """Mock requests session for replaying recorded responses or error states."""

    def __init__(self, status_code: int = 200, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self.json_data = json_data
        self.text = text

    def post(self, url, headers=None, json=None, timeout=None):
        return self

    def get(self, url, params=None, timeout=None):
        return self

    def json(self):
        return self.json_data


def test_openrouteservice_provider_parsing():
    """Verify ORS driving-hgv GeoJSON response is parsed accurately from recorded fixture."""
    fixture_path = FIXTURES_DIR / "ors_dallas_denver.json"
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    provider = OpenRouteServiceProvider(
        api_key="mock-key",
        session=MockSession(status_code=200, json_data=data),
    )
    route = provider.get_route(
        origin=(32.79333, -96.76651),
        destination=(39.73924, -104.98486),
    )

    assert route.provider == "openrouteservice"
    assert 780 <= route.distance_miles <= 795
    assert 12 <= route.duration_hours <= 20
    assert len(route.coordinates) > 1000
    # First point near Dallas, last point near Denver
    assert round(route.coordinates[0][1], 1) == 32.8
    assert round(route.coordinates[-1][1], 1) == 39.7


def test_osrm_provider_parsing():
    """Verify public OSRM GeoJSON response is parsed accurately from recorded fixture."""
    fixture_path = FIXTURES_DIR / "osrm_dallas_denver.json"
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    provider = OSRMProvider(
        session=MockSession(status_code=200, json_data=data),
    )
    route = provider.get_route(
        origin=(32.79333, -96.76651),
        destination=(39.73924, -104.98486),
    )

    assert route.provider == "osrm"
    assert 780 <= route.distance_miles <= 820
    assert len(route.coordinates) > 1000


def test_provider_error_mapping():
    """Verify upstream HTTP error codes map to typed exceptions."""
    # 404 No Route
    ors_no_route = OpenRouteServiceProvider(
        api_key="mock-key",
        session=MockSession(status_code=404, text="No route found"),
    )
    with pytest.raises(NoRoute):
        ors_no_route.get_route((32.0, -96.0), (39.0, -104.0))

    # 500 Upstream Error
    osrm_500 = OSRMProvider(
        session=MockSession(status_code=500, text="Internal Server Error"),
    )
    with pytest.raises(UpstreamError):
        osrm_500.get_route((32.0, -96.0), (39.0, -104.0))


def test_provider_timeout_mapping(monkeypatch):
    """Verify connection timeout maps to UpstreamTimeout."""

    class TimeoutSession:
        def post(self, *args, **kwargs):
            raise requests.exceptions.Timeout("Connection timed out")

    ors = OpenRouteServiceProvider(api_key="mock-key", session=TimeoutSession())
    with pytest.raises(UpstreamTimeout):
        ors.get_route((32.0, -96.0), (39.0, -104.0))


def test_cached_provider_call_counting():
    """Verify cold request makes 1 call and warm request makes 0 calls."""
    fixture_path = FIXTURES_DIR / "ors_dallas_denver.json"
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    inner = OpenRouteServiceProvider(
        api_key="mock-key",
        session=MockSession(status_code=200, json_data=data),
    )
    cached = CachedRoutingProvider(inner)

    assert get_call_count() == 0

    # Cold request: exactly 1 call
    route1 = cached.get_route((32.7933, -96.7665), (39.7392, -104.9848))
    assert get_call_count() == 1
    assert route1.distance_miles > 700

    # Reset counter and verify warm request makes 0 calls
    reset_call_counter()
    route2 = cached.get_route((32.7933, -96.7665), (39.7392, -104.9848))
    assert get_call_count() == 0
    assert route2.distance_miles == route1.distance_miles
