"""Route planning orchestration service."""

import time

from apps.planner.corridor import find_corridor_stations
from apps.routing.locations import LocationResolver
from apps.routing.providers import get_routing_provider


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
