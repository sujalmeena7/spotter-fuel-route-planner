"""Routing provider protocol, implementations for ORS and OSRM, and caching wrapper."""

import hashlib
import logging
import time
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Protocol

import requests
from django.conf import settings
from django.core.cache import cache

from apps.routing.exceptions import NoRoute, RoadNotFound, UpstreamError, UpstreamTimeout

logger = logging.getLogger(__name__)

# Thread/async safe per-request external call counter
_EXTERNAL_CALLS: ContextVar[int] = ContextVar("external_api_calls", default=0)


def get_call_count() -> int:
    return _EXTERNAL_CALLS.get()


def reset_call_counter() -> None:
    _EXTERNAL_CALLS.set(0)


def increment_call_counter() -> None:
    _EXTERNAL_CALLS.set(_EXTERNAL_CALLS.get() + 1)


@dataclass(frozen=True)
class Route:
    """Standardized route output across providers."""

    coordinates: list[list[float]]  # [[lon, lat], ...]
    distance_m: float
    duration_s: float
    provider: str

    @property
    def distance_miles(self) -> float:
        return round(self.distance_m / 1609.344, 2)

    @property
    def duration_hours(self) -> float:
        return round(self.duration_s / 3600.0, 2)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Route":
        return cls(
            coordinates=data["coordinates"],
            distance_m=float(data["distance_m"]),
            duration_s=float(data["duration_s"]),
            provider=data["provider"],
        )


class RoutingProvider(Protocol):
    """Protocol for pluggable routing providers."""

    name: str

    def get_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        origin_label: str = "",
        dest_label: str = "",
    ) -> Route: ...


class OpenRouteServiceProvider:
    """Truck profile routing provider using OpenRouteService driving-hgv."""

    name = "openrouteservice"
    BASE_URL = "https://api.openrouteservice.org/v2/directions/driving-hgv/geojson"

    def __init__(self, api_key: str, session: requests.Session | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()

    def get_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        origin_label: str = "",
        dest_label: str = "",
    ) -> Route:
        lat1, lon1 = origin
        lat2, lon2 = destination

        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, application/geo+json",
        }
        payload = {
            "coordinates": [[round(lon1, 6), round(lat1, 6)], [round(lon2, 6), round(lat2, 6)]],
            "radiuses": [5000, 5000],
        }

        # Attempt with 1 retry on 5xx or connection error
        resp = None
        for attempt in range(2):
            try:
                resp = self.session.post(
                    self.BASE_URL,
                    headers=headers,
                    json=payload,
                    timeout=(3.05, 10),
                )
                if resp.status_code < 500:
                    break
            except requests.exceptions.Timeout as e:
                if attempt == 1:
                    raise UpstreamTimeout(f"OpenRouteService timed out: {e}") from e
            except requests.exceptions.RequestException as e:
                if attempt == 1:
                    raise UpstreamError(f"OpenRouteService connection failed: {e}") from e
            time.sleep(0.5)

        if resp is None:
            raise UpstreamError("OpenRouteService failed to respond.")

        if resp.status_code == 200:
            try:
                data = resp.json()
                feat = data["features"][0]
                coords = feat["geometry"]["coordinates"]
                summary = feat["properties"]["summary"]
                return Route(
                    coordinates=coords,
                    distance_m=float(summary["distance"]),
                    duration_s=float(summary["duration"]),
                    provider=self.name,
                )
            except (KeyError, IndexError, ValueError) as e:
                raise UpstreamError(f"Malformed response from OpenRouteService: {e}") from e

        if resp.status_code in (400, 404):
            err_code = None
            err_msg = ""
            try:
                err_data = resp.json().get("error", {})
                err_code = err_data.get("code")
                err_msg = err_data.get("message", "")
            except Exception:
                pass

            logger.warning(
                f"OpenRouteService 4xx error ({resp.status_code}): code={err_code}, msg={err_msg}"
            )
            if err_code == 2010:
                if "point 0" in err_msg.lower():
                    label = origin_label or "origin location"
                elif "point 1" in err_msg.lower():
                    label = dest_label or "destination location"
                else:
                    label = origin_label or dest_label or "route location"
                raise RoadNotFound(f"Could not find a road near {label}.")

            raise NoRoute("No drivable route between these locations.")

        logger.error(f"OpenRouteService upstream error ({resp.status_code}): {resp.text}")
        raise UpstreamError(f"OpenRouteService routing error ({resp.status_code}).")


class OSRMProvider:
    """Car profile routing fallback provider using public OSRM server."""

    name = "osrm"
    BASE_URL = "http://router.project-osrm.org/route/v1/driving"

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()

    def get_route(self, origin: tuple[float, float], destination: tuple[float, float]) -> Route:
        lat1, lon1 = origin
        lat2, lon2 = destination

        url = f"{self.BASE_URL}/{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}"
        params = {"overview": "full", "geometries": "geojson"}

        resp = None
        for attempt in range(2):
            try:
                resp = self.session.get(url, params=params, timeout=(3.05, 10))
                if resp.status_code < 500:
                    break
            except requests.exceptions.Timeout as e:
                if attempt == 1:
                    raise UpstreamTimeout(f"OSRM timed out: {e}") from e
            except requests.exceptions.RequestException as e:
                if attempt == 1:
                    raise UpstreamError(f"OSRM connection failed: {e}") from e
            time.sleep(0.5)

        if resp is None:
            raise UpstreamError("OSRM failed to respond.")

        if resp.status_code == 200:
            try:
                data = resp.json()
                if data.get("code") != "Ok" or not data.get("routes"):
                    raise NoRoute("OSRM found no valid route.")
                route = data["routes"][0]
                coords = route["geometry"]["coordinates"]
                return Route(
                    coordinates=coords,
                    distance_m=float(route["distance"]),
                    duration_s=float(route["duration"]),
                    provider=self.name,
                )
            except (KeyError, IndexError, ValueError) as e:
                raise UpstreamError(f"Malformed response from OSRM: {e}") from e

        if resp.status_code in (400, 404):
            raise NoRoute(f"OSRM found no route: {resp.text}")

        raise UpstreamError(f"OSRM upstream error ({resp.status_code}): {resp.text}")


class CachedRoutingProvider:
    """Decorator that caches routes for 24 hours and manages external call counts."""

    def __init__(self, inner: RoutingProvider):
        self.inner = inner
        self.name = inner.name

    def get_route(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        origin_label: str = "",
        dest_label: str = "",
    ) -> Route:
        lat1, lon1 = origin
        lat2, lon2 = destination

        # Cache key rounded to 4 decimal places (~11 meters)
        raw_key = f"route:{self.inner.name}:{lat1:.4f},{lon1:.4f}->{lat2:.4f},{lon2:.4f}"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        cache_key = f"route_{key_hash}"

        cached = cache.get(cache_key)
        if cached:
            return Route.from_dict(cached)

        # Cold request: increment call counter and call provider
        increment_call_counter()
        route = self.inner.get_route(
            origin, destination, origin_label=origin_label, dest_label=dest_label
        )
        cache.set(cache_key, route.to_dict(), timeout=24 * 3600)
        return route


def get_routing_provider(provider_name: str | None = None) -> CachedRoutingProvider:
    """Factory creating the configured routing provider with caching."""
    target = provider_name or (
        "openrouteservice" if getattr(settings, "ORS_API_KEY", "").strip() else "osrm"
    )

    if target == "openrouteservice":
        api_key = getattr(settings, "ORS_API_KEY", "").strip()
        provider = OpenRouteServiceProvider(api_key=api_key)
    else:
        provider = OSRMProvider()

    return CachedRoutingProvider(provider)
