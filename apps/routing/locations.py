"""Offline-first location resolution and geocoding."""

import re
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from apps.routing.exceptions import (
    LocationNotFound,
    LocationOutsideUSA,
    UpstreamError,
    UpstreamTimeout,
)
from apps.stations.gazetteer import GazetteerIndex

US_STATE_NAMES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "district of columbia": "DC",
}

US_STATE_CODES = set(US_STATE_NAMES.values())

LAT_LON_REGEX = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*$")


def is_within_usa(lat: float, lon: float) -> bool:
    """Validate that coordinates fall within US bounding boxes (Lower 48, AK, HI)."""
    # Lower 48 + DC
    if (24.0 <= lat <= 50.0) and (-125.5 <= lon <= -66.5):
        return True
    # Alaska
    if (51.0 <= lat <= 72.0) and ((-180.0 <= lon <= -129.0) or (170.0 <= lon <= 180.0)):
        return True
    # Hawaii
    if (18.5 <= lat <= 29.0) and (-161.5 <= lon <= -154.0):
        return True
    return False


@dataclass(frozen=True)
class ResolvedLocation:
    """Resolved geographic coordinate with metadata."""

    lat: float
    lon: float
    label: str
    source: str
    external_calls: int = 0


class LocationResolver:
    """Resolves arbitrary user location strings to validated US coordinates."""

    @classmethod
    def resolve(cls, text: str) -> ResolvedLocation:
        query = text.strip()
        if not query:
            raise LocationNotFound("Location string cannot be empty.")

        # 1. Check for lat, lon coordinate pattern
        match = LAT_LON_REGEX.match(query)
        if match:
            lat = float(match.group(1))
            lon = float(match.group(2))
            if not is_within_usa(lat, lon):
                raise LocationOutsideUSA(
                    f"Coordinates ({lat}, {lon}) fall outside the United States."
                )
            return ResolvedLocation(
                lat=round(lat, 5),
                lon=round(lon, 5),
                label=f"{lat:.4f}, {lon:.4f}",
                source="coordinates",
                external_calls=0,
            )

        # 2. Check for 'City, ST' or 'City, State' pattern
        if "," in query:
            parts = [p.strip() for p in query.split(",", 1)]
            city_part, state_part = parts[0], parts[1]
            state_code = None

            state_upper = state_part.upper()
            if state_upper in US_STATE_CODES:
                state_code = state_upper
            elif state_part.lower() in US_STATE_NAMES:
                state_code = US_STATE_NAMES[state_part.lower()]

            if state_code:
                idx = GazetteerIndex.get_instance()
                res = idx.lookup(city_part, state_code)
                if res:
                    lat, lon, _ = res
                    if not is_within_usa(lat, lon):
                        raise LocationOutsideUSA(
                            f"Location '{query}' resolved outside the United States."
                        )
                    return ResolvedLocation(
                        lat=round(lat, 5),
                        lon=round(lon, 5),
                        label=f"{city_part.title()}, {state_code}",
                        source="gazetteer",
                        external_calls=0,
                    )

        # 3. Fallback to OpenRouteService geocoding (restricted to US)
        ors_key = getattr(settings, "ORS_API_KEY", "").strip()
        if not ors_key:
            raise LocationNotFound(
                f"Location '{query}' could not be resolved offline and no ORS API key is configured."
            )

        import hashlib

        query_hash = hashlib.sha256(query.lower().encode("utf-8")).hexdigest()
        cache_key = f"ors_geocode_{query_hash}"
        cached_result = cache.get(cache_key)
        if cached_result:
            return ResolvedLocation(
                lat=cached_result["lat"],
                lon=cached_result["lon"],
                label=cached_result["label"],
                source="ors_geocode_cached",
                external_calls=0,
            )

        try:
            resp = requests.get(
                "https://api.openrouteservice.org/geocode/search",
                params={
                    "api_key": ors_key,
                    "text": query,
                    "boundary.country": "US",
                    "size": 1,
                },
                timeout=(3.05, 10),
            )
        except requests.exceptions.Timeout as e:
            raise UpstreamTimeout(f"ORS geocoding timed out: {e}") from e
        except requests.exceptions.RequestException as e:
            raise UpstreamError(f"ORS geocoding connection failed: {e}") from e

        if resp.status_code != 200:
            raise UpstreamError(f"ORS geocoding upstream error ({resp.status_code}): {resp.text}")

        data = resp.json()
        features = data.get("features", [])
        if not features:
            raise LocationNotFound(f"Location '{query}' could not be resolved.")

        first_feat = features[0]
        coords = first_feat.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            raise LocationNotFound(f"Location '{query}' returned invalid coordinates.")

        lon, lat = float(coords[0]), float(coords[1])
        if not is_within_usa(lat, lon):
            raise LocationOutsideUSA(
                f"Location '{query}' resolved to coordinates outside the United States ({lat}, {lon})."
            )

        label = first_feat.get("properties", {}).get("label") or query
        resolved = ResolvedLocation(
            lat=round(lat, 5),
            lon=round(lon, 5),
            label=label,
            source="ors_geocode",
            external_calls=1,
        )

        # Cache for 7 days
        cache.set(
            cache_key,
            {"lat": resolved.lat, "lon": resolved.lon, "label": resolved.label},
            timeout=7 * 86400,
        )
        return resolved
