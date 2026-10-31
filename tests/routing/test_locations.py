import pytest
from django.core.cache import cache
from django.test import Client

from apps.routing.exceptions import LocationNotFound, LocationOutsideUSA
from apps.routing.locations import LocationResolver


@pytest.fixture(autouse=True)
def clear_django_cache():
    cache.clear()
    yield
    cache.clear()


def test_resolve_lat_lon_coordinates():
    """Verify coordinate strings are resolved offline with 0 external calls."""
    loc = LocationResolver.resolve("32.7767, -96.7970")
    assert loc.lat == 32.7767
    assert loc.lon == -96.7970
    assert loc.source == "coordinates"
    assert loc.external_calls == 0


def test_resolve_coordinates_outside_usa():
    """Verify coordinates outside the US bounding boxes raise LocationOutsideUSA."""
    # Paris, France
    with pytest.raises(LocationOutsideUSA):
        LocationResolver.resolve("48.8566, 2.3522")

    # London, UK
    with pytest.raises(LocationOutsideUSA):
        LocationResolver.resolve("51.5074, -0.1278")


def test_resolve_city_state_code():
    """Verify City, ST is resolved offline from Census Gazetteer with 0 external calls."""
    loc = LocationResolver.resolve("Dallas, TX")
    assert 32.6 <= loc.lat <= 32.9
    assert -96.9 <= loc.lon <= -96.7
    assert loc.source == "gazetteer"
    assert loc.external_calls == 0
    assert "Dallas" in loc.label


def test_resolve_city_full_state_name():
    """Verify City, Full State Name resolves to state code and offline coordinates."""
    loc = LocationResolver.resolve("Denver, Colorado")
    assert 39.6 <= loc.lat <= 39.9
    assert -105.1 <= loc.lon <= -104.8
    assert loc.source == "gazetteer"
    assert loc.external_calls == 0
    assert "Denver, CO" in loc.label


def test_resolve_unknown_city_no_ors_key(settings):
    """Verify unknown city with no ORS key raises LocationNotFound."""
    settings.ORS_API_KEY = ""
    with pytest.raises(LocationNotFound):
        LocationResolver.resolve("NonexistentFantasyCityXYZ, WY")


def test_resolve_ors_fallback_mocked(settings, monkeypatch):
    """Verify ORS geocoding fallback when key is set, plus caching behavior."""
    settings.ORS_API_KEY = "mock-key-for-test"

    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "features": [
                    {
                        "geometry": {"coordinates": [-98.4936, 29.4241]},
                        "properties": {"label": "San Antonio, TX, USA"},
                    }
                ]
            }

    calls = 0

    def mock_get(url, params=None, timeout=None):
        nonlocal calls
        calls += 1
        return MockResponse()

    monkeypatch.setattr("requests.get", mock_get)

    # First call (cold) makes 1 external call
    loc1 = LocationResolver.resolve("SomeUnlistedPlace, TX")
    assert loc1.external_calls == 1
    assert loc1.lat == 29.4241
    assert loc1.lon == -98.4936
    assert calls == 1

    # Second call (warm) hits cache and makes 0 external calls
    loc2 = LocationResolver.resolve("SomeUnlistedPlace, TX")
    assert loc2.external_calls == 0
    assert loc2.lat == 29.4241
    assert calls == 1


@pytest.mark.django_db
def test_autocomplete_endpoint():
    """Verify autocomplete endpoint returns ranked city suggestions with 0 external calls."""
    client = Client()
    resp = client.get("/api/v1/locations/autocomplete/?q=dal&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    labels = [item["label"] for item in data]
    assert any("Dallas, TX" in lbl for lbl in labels)

    # Empty query returns empty list
    empty_resp = client.get("/api/v1/locations/autocomplete/?q=")
    assert empty_resp.status_code == 200
    assert empty_resp.json() == []
