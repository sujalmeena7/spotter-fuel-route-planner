"""Offline-first location resolution and geocoding."""

import hashlib
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
from apps.stations.gazetteer import GazetteerIndex, is_within_usa

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

CANADIAN_PROVINCE_CODES = {
    "AB",
    "BC",
    "MB",
    "NB",
    "NL",
    "NS",
    "NT",
    "NU",
    "ON",
    "PE",
    "QC",
    "SK",
    "YT",
}

CANADIAN_PROVINCES = {
    "alberta",
    "british columbia",
    "manitoba",
    "new brunswick",
    "newfoundland",
    "newfoundland and labrador",
    "nova scotia",
    "northwest territories",
    "nunavut",
    "ontario",
    "prince edward island",
    "quebec",
    "saskatchewan",
    "yukon",
    "canada",
}

NON_US_COUNTRIES = {
    "canada",
    "mexico",
    "france",
    "germany",
    "united kingdom",
    "uk",
    "england",
    "scotland",
    "wales",
    "ireland",
    "spain",
    "italy",
    "china",
    "japan",
    "australia",
    "brazil",
    "india",
    "russia",
    "netherlands",
    "belgium",
    "switzerland",
    "sweden",
    "norway",
    "denmark",
    "finland",
    "poland",
    "austria",
    "portugal",
    "greece",
    "turkey",
    "egypt",
    "south africa",
    "argentina",
    "chile",
    "colombia",
    "peru",
    "new zealand",
    "south korea",
}

LAT_LON_REGEX = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*$")


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

        query_lower = query.lower()
        if (
            query_lower in NON_US_COUNTRIES
            or query_lower in CANADIAN_PROVINCES
            or query.upper() in CANADIAN_PROVINCE_CODES
        ):
            raise LocationOutsideUSA(f"Location '{query}' is outside the United States.")

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
        state_code = None
        if "," in query:
            parts = [p.strip() for p in query.split(",", 1)]
            city_part, state_part = parts[0], parts[1]
            state_upper = state_part.upper()
            state_lower = state_part.lower()

            # If suffix is a Canadian province or non-US country, reject immediately without calling API
            if (
                state_upper in CANADIAN_PROVINCE_CODES
                or state_lower in CANADIAN_PROVINCES
                or state_lower in NON_US_COUNTRIES
            ):
                raise LocationOutsideUSA(f"Location '{query}' is outside the United States.")

            if state_upper in US_STATE_CODES:
                state_code = state_upper
            elif state_lower in US_STATE_NAMES:
                state_code = US_STATE_NAMES[state_lower]
            elif len(state_part) == 2 and state_part.isalpha():
                # Invalid 2-letter state code not in standard 50 US states + DC (e.g. Springfield, ZZ)
                raise LocationNotFound(
                    f"Location '{query}' could not be resolved (invalid US state code '{state_part}')."
                )

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

        query_hash = hashlib.sha1(query.lower().strip().encode("utf-8")).hexdigest()
        cache_key = f"geocode_{query_hash}"
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
            import logging

            logging.getLogger(__name__).error(
                f"ORS geocoding upstream error ({resp.status_code}): {resp.text}"
            )
            raise UpstreamError(f"ORS geocoding service error ({resp.status_code}).")

        data = resp.json()
        features = data.get("features", [])
        if not features:
            raise LocationNotFound(f"Location '{query}' could not be resolved.")

        first_feat = features[0]
        props = first_feat.get("properties", {})
        layer = (props.get("layer") or "").lower()
        allowed_layers = {
            "locality",
            "localadmin",
            "borough",
            "neighbourhood",
            "address",
            "street",
            "venue",
            "postalcode",
        }
        if layer and layer not in allowed_layers:
            raise LocationNotFound(
                f"Location '{query}' could not be resolved (coarse layer '{layer}')."
            )
        props = first_feat.get("properties", {})
        ors_state_code = (props.get("region_a") or "").upper()
        ors_state_name = (props.get("region") or "").lower()

        # If user typed a specific US state, assert that ORS result matches that state
        if state_code:
            if ors_state_code and ors_state_code != state_code:
                raise LocationNotFound(
                    f"Location '{query}' not found in {state_code} (resolved to {ors_state_code})."
                )
            if (
                ors_state_name
                and US_STATE_NAMES.get(ors_state_name)
                and US_STATE_NAMES.get(ors_state_name) != state_code
            ):
                raise LocationNotFound(
                    f"Location '{query}' not found in {state_code} (resolved to {ors_state_name})."
                )

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
