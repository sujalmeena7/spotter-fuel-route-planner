import json
import socket

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command

from apps.routing.providers import OpenRouteServiceProvider, Route
from apps.stations.index import StationIndex
from apps.stations.models import Station

_ORIGINAL_CONNECT = socket.socket.connect


@pytest.fixture(autouse=True)
def block_external_sockets(monkeypatch):
    """Prevent any external network calls during tests."""

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        # Allow local loopback connections if needed by test servers
        if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
            return _ORIGINAL_CONNECT(self, address)
        raise RuntimeError(
            f"Blocked external network access to {address} during test execution. "
            "Use recorded fixtures or mock the network call."
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


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

    def mock_get_route(self, origin, destination, *args, **kwargs):
        lat1, _ = origin
        if abs(lat1 - 29.78) < 1.0:
            return houston_route
        return dallas_route

    monkeypatch.setattr(OpenRouteServiceProvider, "get_route", mock_get_route)
    return dallas_route
