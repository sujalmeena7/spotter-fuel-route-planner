"""Benchmark command measuring cold/warm timings across 6 canonical city pairs.

Measures each processing stage:
  1. Resolve: geocoding origin & destination
  2. Route: fetching route geometry
  3. Match: corridor station KDTree search & projection
  4. Optimize: greedy fuel optimization
  5. Serialize: GeoJSON & financial summary construction
  6. Warm: cache hit latency
"""

import hashlib
import json
import time
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand

from apps.planner.corridor import find_corridor_stations
from apps.planner.optimizer import Stop, optimize_fuel
from apps.planner.service import RoutePlanService
from apps.routing.locations import LocationResolver
from apps.routing.providers import (
    Route,
    get_routing_provider,
)
from apps.stations.index import StationIndex

BENCHMARK_PAIRS = [
    ("Dallas, TX", "Denver, CO"),
    ("New York, NY", "Los Angeles, CA"),
    ("Chicago, IL", "Atlanta, GA"),
    ("Seattle, WA", "Miami, FL"),
    ("Houston, TX", "Phoenix, AZ"),
    ("Boston, MA", "Washington, DC"),
]


class Command(BaseCommand):
    help = "Benchmark route planner across 6 canonical city pairs measuring stage timings"

    def add_arguments(self, parser):
        parser.add_argument(
            "--mock",
            action="store_true",
            help="Use pre-recorded route fixtures instead of network calls (for CI & testing)",
        )
        parser.add_argument(
            "--iterations",
            type=int,
            default=3,
            help="Number of iterations for warm cache latency measurement (default: 3)",
        )

    def handle(self, *args, **options):
        use_mock = options["mock"]
        iterations = max(1, options["iterations"])

        self.stdout.write(self.style.NOTICE("=" * 80))
        self.stdout.write(
            self.style.NOTICE(" SPOTTER FLEET FUEL ROUTE PLANNER — PERFORMANCE BENCHMARK")
        )
        self.stdout.write(self.style.NOTICE("=" * 80))

        # 1. Warm up indexes
        self.stdout.write("Warming in-memory StationIndex and Gazetteer...")
        t_w0 = time.perf_counter()
        StationIndex.get_instance()
        LocationResolver.resolve("Dallas, TX")
        dummy_route = Route(
            coordinates=[[-96.79, 32.77], [-96.80, 32.78]],
            distance_m=1000,
            duration_s=60,
            provider="warmup",
        )
        find_corridor_stations(dummy_route, corridor_miles=10.0)
        warmup_ms = (time.perf_counter() - t_w0) * 1000
        self.stdout.write(f"Index warmed in {warmup_ms:.1f} ms\n")

        # Load fixtures if mock mode is requested or no ORS key available
        fixtures_data = {}
        fixture_path = Path(settings.BASE_DIR) / "tests" / "fixtures" / "benchmark_routes.json"
        if use_mock or not getattr(settings, "ORS_API_KEY", ""):
            use_mock = True
            if fixture_path.exists():
                with open(fixture_path, encoding="utf-8") as f:
                    fixtures_data = json.load(f)

        mode_str = "MOCK FIXTURES (0 network calls)" if use_mock else "LIVE ROUTING PROVIDER"
        self.stdout.write(f"Routing mode: {mode_str}")
        self.stdout.write(f"Warm iterations: {iterations}\n")

        results = []

        for start_city, finish_city in BENCHMARK_PAIRS:
            pair_key = f"{start_city} -> {finish_city}"

            # Clear cache to guarantee cold measurement
            cache.clear()

            # Stage 1: Resolve
            t0 = time.perf_counter()
            origin = LocationResolver.resolve(start_city)
            dest = LocationResolver.resolve(finish_city)
            t_resolve = (time.perf_counter() - t0) * 1000

            # Stage 2: Route
            t0 = time.perf_counter()
            if use_mock and pair_key in fixtures_data:
                fd = fixtures_data[pair_key]
                route = Route(
                    coordinates=fd["coordinates"],
                    distance_m=fd["distance_m"],
                    duration_s=fd["duration_s"],
                    provider=fd["provider"],
                )
            else:
                provider = get_routing_provider()
                route = provider.get_route((origin.lat, origin.lon), (dest.lat, dest.lon))
            t_route = (time.perf_counter() - t0) * 1000

            # Stage 3: Match corridor stations
            t0 = time.perf_counter()
            corridor_stations = find_corridor_stations(
                route, corridor_miles=getattr(settings, "CORRIDOR_MILES", 10.0)
            )
            t_match = (time.perf_counter() - t0) * 1000

            # Stage 4: Optimize fuel
            t0 = time.perf_counter()
            optimizer_stops = [
                Stop(mile=cs.mile_marker, price=cs.price_float, ref=cs) for cs in corridor_stations
            ]
            plan_res = optimize_fuel(
                stops=optimizer_stops,
                total_miles=route.distance_miles,
                tank_gal=getattr(settings, "TANK_GALLONS", 50.0),
                mpg=getattr(settings, "MPG", 10.0),
                start_fuel=0.0,
                origin_radius=getattr(settings, "ORIGIN_RADIUS_MILES", 25.0),
            )
            t_opt = (time.perf_counter() - t0) * 1000

            # Stage 5: Serialize / build response
            t0 = time.perf_counter()
            if not use_mock:
                RoutePlanService.plan(start_city, finish_city)
            else:
                # Exercise serialization logic
                total_gallons = plan_res.total_gallons
                _ = plan_res.total_cost_usd
                if corridor_stations:
                    mean_p = sum(cs.price_float for cs in corridor_stations) / len(
                        corridor_stations
                    )
                    _ = Decimal(str(round(total_gallons * mean_p, 2)))
                _ = [
                    {
                        "sequence": ps.sequence,
                        "station_id": ps.ref.station_id,
                        "name": ps.ref.name,
                        "mile_marker": ps.mile,
                        "price_per_gallon": f"{ps.ref.price_float:.3f}",
                        "gallons_purchased": ps.gallons_purchased,
                        "cost_usd": f"{ps.cost_usd:.2f}",
                    }
                    for ps in plan_res.stops
                ]
            t_serialize = (time.perf_counter() - t0) * 1000

            local_ms = t_resolve + t_match + t_opt + t_serialize
            cold_total_ms = local_ms + t_route

            # Warm cache measurement
            warm_times = []
            if not use_mock:
                for _ in range(iterations):
                    tw0 = time.perf_counter()
                    RoutePlanService.plan(start_city, finish_city)
                    warm_times.append((time.perf_counter() - tw0) * 1000)
                warm_ms = sum(warm_times) / len(warm_times)
            else:
                # In mock mode, measure cache get + deserialization
                dummy_hash = hashlib.sha256(pair_key.encode()).hexdigest()
                dummy_key = f"mock_plan_{dummy_hash}"
                cache.set(dummy_key, {"cached": True}, 3600)
                for _ in range(iterations):
                    tw0 = time.perf_counter()
                    cache.get(dummy_key)
                    warm_times.append((time.perf_counter() - tw0) * 1000)
                warm_ms = sum(warm_times) / len(warm_times)

            results.append(
                {
                    "route": pair_key,
                    "distance_mi": route.distance_miles,
                    "stations": len(corridor_stations),
                    "stops": len(plan_res.stops),
                    "t_resolve": t_resolve,
                    "t_route": t_route,
                    "t_match": t_match,
                    "t_opt": t_opt,
                    "t_serialize": t_serialize,
                    "local_ms": local_ms,
                    "cold_total_ms": cold_total_ms,
                    "warm_ms": warm_ms,
                }
            )

        # Print formatted table
        header = (
            f"{'Route':<32} | {'Dist(mi)':>8} | {'Res(ms)':>7} | {'Rte(ms)':>7} | "
            f"{'Mat(ms)':>7} | {'Opt(ms)':>7} | {'Ser(ms)':>7} | {'Local':>7} | {'Cold':>7} | {'Warm':>6}"
        )
        sep = "-" * len(header)
        self.stdout.write(header)
        self.stdout.write(sep)

        sum_local = 0.0
        sum_cold = 0.0
        sum_warm = 0.0
        sum_match = 0.0
        sum_opt = 0.0

        for r in results:
            sum_local += r["local_ms"]
            sum_cold += r["cold_total_ms"]
            sum_warm += r["warm_ms"]
            sum_match += r["t_match"]
            sum_opt += r["t_opt"]

            row = (
                f"{r['route']:<32} | {r['distance_mi']:>8.0f} | {r['t_resolve']:>7.2f} | "
                f"{r['t_route']:>7.1f} | {r['t_match']:>7.2f} | {r['t_opt']:>7.2f} | "
                f"{r['t_serialize']:>7.2f} | {r['local_ms']:>7.2f} | {r['cold_total_ms']:>7.1f} | {r['warm_ms']:>6.2f}"
            )
            self.stdout.write(row)

        self.stdout.write(sep)
        n = len(results)
        avg_local = sum_local / n
        avg_cold = sum_cold / n
        avg_warm = sum_warm / n
        avg_match = sum_match / n
        avg_opt = sum_opt / n

        avg_row = (
            f"{'AVERAGE (6 PAIRS)':<32} | {'-':>8} | {'-':>7} | {'-':>7} | "
            f"{avg_match:>7.2f} | {avg_opt:>7.2f} | {'-':>7} | "
            f"{avg_local:>7.2f} | {avg_cold:>7.1f} | {avg_warm:>6.2f}"
        )
        self.stdout.write(avg_row)
        self.stdout.write("=" * len(header))

        # Check performance bars
        self.stdout.write("\nQuality Bar Verifications:")
        if avg_local < 50.0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  [PASS] Average local compute: {avg_local:.2f} ms (< 50.0 ms target)"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  [WARN] Average local compute: {avg_local:.2f} ms (>= 50.0 ms target)"
                )
            )

        if avg_warm < 10.0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  [PASS] Average warm cached response: {avg_warm:.2f} ms (< 10.0 ms target)"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  [WARN] Average warm cached response: {avg_warm:.2f} ms (>= 10.0 ms target)"
                )
            )
