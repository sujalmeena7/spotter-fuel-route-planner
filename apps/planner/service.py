"""Route planning orchestration service."""

import hashlib
import time
import urllib.parse
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.cache import cache

from apps.planner.corridor import CorridorStation, find_corridor_stations
from apps.planner.optimizer import Stop, optimize_fuel
from apps.routing.exceptions import NoRoute
from apps.routing.geometry import thin_geometry
from apps.routing.locations import LocationResolver
from apps.routing.providers import (
    get_call_count,
    get_routing_provider,
    reset_call_counter,
)
from apps.stations.gazetteer import is_alaska, is_hawaii
from apps.stations.index import StationIndex


class RoutePlanService:
    """Orchestrates location resolution, route generation, corridor matching, and fuel optimization."""

    @classmethod
    def preview(
        cls,
        origin_str: str,
        destination_str: str,
        corridor_miles: float = 10.0,
    ) -> dict:
        """Preview route and find corridor fuel stations with performance metrics."""
        t0 = time.perf_counter()

        origin = LocationResolver.resolve(origin_str)
        dest = LocationResolver.resolve(destination_str)
        t_resolve = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        provider = get_routing_provider()
        route = provider.get_route((origin.lat, origin.lon), (dest.lat, dest.lon))
        t_route = (time.perf_counter() - t1) * 1000

        t2 = time.perf_counter()
        corridor_stations = find_corridor_stations(route, corridor_miles=corridor_miles)
        t_match = (time.perf_counter() - t2) * 1000

        local_ms = t_resolve + t_match

        return {
            "origin": origin,
            "destination": dest,
            "route": route,
            "corridor_stations": corridor_stations,
            "timing_ms": {
                "resolve": round(t_resolve, 2),
                "route": round(t_route, 2),
                "corridor_match": round(t_match, 2),
                "local_compute": round(local_ms, 2),
            },
        }

    @classmethod
    def plan(
        cls,
        start_str: str,
        finish_str: str,
        start_fuel: float = 0.0,
        include_candidates: bool = False,
        optimize_for: str = "practical",
    ) -> dict:
        """Generate full optimal route plan, fuel stops, financials, GeoJSON, and metadata."""
        t_start = time.perf_counter()

        # Cache key based on normalized inputs and settings fingerprint
        norm_start = start_str.strip().lower()
        norm_finish = finish_str.strip().lower()
        norm_opt_for = optimize_for.strip().lower()
        tank_gal = float(getattr(settings, "TANK_GALLONS", 50))
        mpg = float(getattr(settings, "MPG", 10))
        corridor_mi = float(getattr(settings, "CORRIDOR_MILES", 10))
        origin_rad = float(getattr(settings, "ORIGIN_RADIUS_MILES", 25))
        min_purchase = float(getattr(settings, "MIN_PURCHASE_GALLONS", 10.0))
        stop_penalty = float(getattr(settings, "STOP_PENALTY_USD", 5.00))

        settings_fp = f"{tank_gal}_{mpg}_{corridor_mi}_{origin_rad}_{min_purchase}_{stop_penalty}_{norm_opt_for}"
        raw_cache_key = (
            f"plan:{norm_start}:{norm_finish}:{start_fuel:.2f}:{include_candidates}:{settings_fp}"
        )
        cache_hash = hashlib.sha256(raw_cache_key.encode("utf-8")).hexdigest()
        cache_key = f"routeplan_{cache_hash}"

        cached_payload = cache.get(cache_key)
        if cached_payload:
            # Warm hit: update compute time, set cache_hit to True, 0 external calls
            elapsed_ms = int(round((time.perf_counter() - t_start) * 1000))
            payload = dict(cached_payload)
            payload["meta"] = dict(payload["meta"])
            payload["meta"]["cache_hit"] = True
            payload["meta"]["external_api_calls"] = 0
            payload["meta"]["compute_ms"] = elapsed_ms
            payload["meta"]["local_compute_ms"] = elapsed_ms
            payload["meta"]["routing_ms"] = 0
            payload["meta"]["total_ms"] = elapsed_ms
            payload["meta"]["timing"] = {
                "routing_ms": 0,
                "local_compute_ms": elapsed_ms,
                "total_ms": elapsed_ms,
            }
            if "warnings" in cached_payload.get("meta", {}):
                payload["meta"]["warnings"] = cached_payload["meta"]["warnings"]
            return payload

        # Cold request: reset call counter
        reset_call_counter()

        # 1. Resolve locations
        origin = LocationResolver.resolve(start_str)
        dest = LocationResolver.resolve(finish_str)

        # Detect non-drivable island/disconnected states before calling routing API (0 calls)
        if is_hawaii(origin.lat, origin.lon) or is_hawaii(dest.lat, dest.lon):
            raise NoRoute("No drivable route between these locations.")
        if is_alaska(origin.lat, origin.lon) != is_alaska(dest.lat, dest.lon):
            raise NoRoute("No drivable route between these locations.")

        # 2. Routing call
        t_route_start = time.perf_counter()
        provider = get_routing_provider()
        route = provider.get_route(
            (origin.lat, origin.lon),
            (dest.lat, dest.lon),
            origin_label=origin.label,
            dest_label=dest.label,
        )
        t_routing = (time.perf_counter() - t_route_start) * 1000

        # 3. Corridor stations
        corridor_stations = find_corridor_stations(route, corridor_miles=corridor_mi)

        # 4. Handle origin fueling when start_fuel <= 0.0
        meta_warnings: list[str] = []
        origin_cs: CorridorStation | None = None
        if start_fuel <= 0.0:
            st_idx = StationIndex.get_instance()
            if len(st_idx) > 0:
                nearest_idx, dist_orig = st_idx.find_nearest(origin.lat, origin.lon)
                st_name = str(st_idx.names[nearest_idx])
                st_price_f = float(st_idx.prices[nearest_idx])
                st_price_dec = st_idx.prices_decimal[nearest_idx]
                st_id = int(st_idx.ids[nearest_idx])
                st_addr = str(st_idx.addresses[nearest_idx])
                st_city = str(st_idx.cities[nearest_idx])
                st_state = str(st_idx.states[nearest_idx])
                st_lat = float(st_idx.lats[nearest_idx])
                st_lon = float(st_idx.lons[nearest_idx])

                if dist_orig > origin_rad:
                    meta_warnings.append(
                        f"No station within {int(origin_rad)} mi of origin; origin fill priced at nearest station ({dist_orig:.1f} mi)"
                    )

                origin_cs = CorridorStation(
                    station_id=st_id,
                    name=f"Origin fill (priced at {st_name}, {dist_orig:.1f} mi away)",
                    address=st_addr,
                    city=st_city,
                    state=st_state,
                    lat=st_lat,
                    lon=st_lon,
                    price=st_price_dec,
                    price_float=st_price_f,
                    mile_marker=0.0,
                    off_route_miles=round(dist_orig, 2),
                )

        # Fuel optimization stops
        optimizer_stops: list[Stop] = []
        if origin_cs is not None:
            optimizer_stops.append(
                Stop(mile=0.0, price=origin_cs.price_float, ref=origin_cs, is_origin=True)
            )
        for cs in corridor_stations:
            if cs.mile_marker > 0.0:
                optimizer_stops.append(Stop(mile=cs.mile_marker, price=cs.price_float, ref=cs))

        plan_res = optimize_fuel(
            stops=optimizer_stops,
            total_miles=route.distance_miles,
            tank_gal=tank_gal,
            mpg=mpg,
            start_fuel=start_fuel,
            origin_radius=origin_rad,
            optimize_for=norm_opt_for,
            min_purchase_gallons=min_purchase,
            stop_penalty_usd=stop_penalty,
        )

        # 5. Financial calculations (baseline & savings)
        total_gallons = plan_res.total_gallons
        total_cost_usd_dec = plan_res.total_cost_usd

        if corridor_stations:
            mean_corridor_price = sum(cs.price_float for cs in corridor_stations) / len(
                corridor_stations
            )
            baseline_dec = (
                Decimal(str(total_gallons)) * Decimal(str(round(mean_corridor_price, 3)))
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            baseline_dec = total_cost_usd_dec

        savings_dec = max(Decimal("0.00"), baseline_dec - total_cost_usd_dec)

        cost_per_mile_dec = (
            (total_cost_usd_dec / Decimal(str(route.distance_miles))).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
            if route.distance_miles > 0
            else Decimal("0.000")
        )

        avg_price_gal_dec = (
            (total_cost_usd_dec / Decimal(str(total_gallons))).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
            if total_gallons > 0
            else Decimal("0.000")
        )

        summary = {
            "start": {"label": origin.label, "lat": origin.lat, "lon": origin.lon},
            "finish": {"label": dest.label, "lat": dest.lat, "lon": dest.lon},
            "distance_miles": route.distance_miles,
            "duration_hours": route.duration_hours,
            "total_gallons": round(total_gallons, 4),
            "total_fuel_cost_usd": f"{total_cost_usd_dec:.2f}",
            "avg_price_per_gallon": f"{avg_price_gal_dec:.3f}",
            "cost_per_mile_usd": f"{cost_per_mile_dec:.3f}",
            "fuel_stops": len(plan_res.stops),
            "baseline_cost_usd": f"{baseline_dec:.2f}",
            "savings_usd": f"{savings_dec:.2f}",
        }

        # 6. Fuel stops detail
        fuel_stops = []
        for ps in plan_res.stops:
            cs: CorridorStation = ps.ref
            fuel_stops.append(
                {
                    "sequence": ps.sequence,
                    "kind": ps.kind,
                    "station_id": cs.station_id,
                    "name": cs.name,
                    "address": cs.address,
                    "city": cs.city,
                    "state": cs.state,
                    "lat": cs.lat,
                    "lon": cs.lon,
                    "mile_marker": ps.mile,
                    "off_route_miles": cs.off_route_miles,
                    "price_per_gallon": f"{cs.price_float:.3f}",
                    "gallons_purchased": ps.gallons_purchased,
                    "cost_usd": f"{ps.cost_usd:.2f}",
                    "fuel_on_arrival_gallons": ps.fuel_on_arrival_gallons,
                    "fuel_on_departure_gallons": ps.fuel_on_departure_gallons,
                }
            )

        # 7. GeoJSON FeatureCollection
        thinned_coords = thin_geometry(route.coordinates, min_step_miles=0.1)
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": thinned_coords},
                "properties": {"kind": "route"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [origin.lon, origin.lat]},
                "properties": {"kind": "start"},
            },
        ]

        for fs in fuel_stops:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [fs["lon"], fs["lat"]]},
                    "properties": {"kind": "fuel_stop", "sequence": fs["sequence"]},
                }
            )

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [dest.lon, dest.lat]},
                "properties": {"kind": "finish"},
            }
        )

        route_geojson = {
            "type": "FeatureCollection",
            "features": features,
        }

        # 8. Query string and map URL
        map_query = urllib.parse.urlencode({"start": start_str, "finish": finish_str})
        map_url = f"/map/?{map_query}"

        # 9. Candidates (if requested)
        candidates = None
        if include_candidates:
            candidates = [
                {
                    "station_id": cs.station_id,
                    "lat": cs.lat,
                    "lon": cs.lon,
                    "price_per_gallon": f"{cs.price_float:.3f}",
                    "mile_marker": cs.mile_marker,
                }
                for cs in corridor_stations
            ]

        # 10. Metadata
        total_external_calls = get_call_count() + origin.external_calls + dest.external_calls
        t_total = (time.perf_counter() - t_start) * 1000
        routing_ms = int(round(t_routing))
        total_ms = int(round(t_total))
        local_compute_ms = max(0, total_ms - routing_ms)

        meta = {
            "routing_provider": route.provider,
            "external_api_calls": total_external_calls,
            "cache_hit": False,
            "compute_ms": local_compute_ms,
            "routing_ms": routing_ms,
            "local_compute_ms": local_compute_ms,
            "total_ms": total_ms,
            "timing": {
                "routing_ms": routing_ms,
                "local_compute_ms": local_compute_ms,
                "total_ms": total_ms,
            },
            "assumptions": [
                f"Tank {int(tank_gal)} gal, {int(mpg)} MPG",
                "Lowest listed price per station",
                f"Corridor {int(corridor_mi)} mi",
            ],
        }
        if meta_warnings:
            meta["warnings"] = meta_warnings

        payload = {
            "summary": summary,
            "fuel_stops": fuel_stops,
            "route": route_geojson,
            "map_url": map_url,
            "meta": meta,
        }
        if candidates is not None:
            payload["candidates"] = candidates

        # Cache response for 1 hour (3600 seconds)
        cache.set(cache_key, payload, timeout=3600)
        return payload
