"""Geocode all fuel stations using Gazetteer places, cousubs, overrides.json, and optional Nominatim.

Validates that all coordinates fall strictly within US bounds (lower 48, AK, HI).
Rejects any result outside bounds and reports source breakdown and rejected count.
"""

import csv
import json
import time
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.stations.gazetteer import GazetteerIndex, is_within_usa, normalize_city_name
from apps.stations.models import GeocodeSource, Station

NOMINATIM_USER_AGENT = "SpotterFuelRoutePlanner/1.0 (assessment@spotter.ai)"


class Command(BaseCommand):
    help = "Geocode all stations using Gazetteer places, cousubs, overrides.json, and optional Nominatim fallback."

    def add_arguments(self, parser):
        parser.add_argument(
            "--nominatim",
            action="store_true",
            help="Enable 1 req/s Nominatim geocoding fallback for remaining unmatched stations.",
        )
        parser.add_argument(
            "--output",
            type=str,
            default=str(settings.BASE_DIR / "data" / "stations_geocoded.csv"),
            help="Path to export geocoded stations CSV.",
        )
        parser.add_argument(
            "--overrides",
            type=str,
            default=str(settings.BASE_DIR / "data" / "overrides.json"),
            help="Path to manual overrides JSON file.",
        )

    def handle(self, *args, **options):
        output_path = Path(options["output"])
        overrides_path = Path(options["overrides"])
        use_nominatim = options["nominatim"]

        # Reset GazetteerIndex singleton to guarantee newly built file is reloaded
        GazetteerIndex.reset()
        idx = GazetteerIndex.get_instance()

        # Load overrides if file exists
        overrides: dict[str, dict] = {}
        if overrides_path.exists():
            with open(overrides_path, encoding="utf-8") as f:
                try:
                    overrides = json.load(f)
                except json.JSONDecodeError:
                    self.stderr.write(
                        "Failed to parse overrides.json, starting with empty overrides."
                    )

        stations = list(Station.objects.all().order_by("opis_id"))
        total = len(stations)

        matched_count = 0
        rejected_bounds_count = 0
        unmatched_stations = []
        geocoded_rows = []
        source_counts: dict[str, int] = {}

        nominatim_session = requests.Session()
        nominatim_session.headers.update({"User-Agent": NOMINATIM_USER_AGENT})

        self.stdout.write(f"Geocoding {total} stations with US bounds checking...")

        for station in stations:
            norm_city = normalize_city_name(station.city)
            key = f"{norm_city},{station.state}"
            raw_key = f"{station.city.strip()},{station.state}"

            lat = None
            lon = None
            source = GeocodeSource.NONE

            # 1. Try Gazetteer place & cousub
            res = idx.lookup(station.city, station.state)
            if res:
                cand_lat, cand_lon, src_str = res
                if is_within_usa(cand_lat, cand_lon):
                    lat = cand_lat
                    lon = cand_lon
                    source = (
                        GeocodeSource.GAZETTEER_PLACE
                        if src_str == "gazetteer_place"
                        else GeocodeSource.GAZETTEER_COUSUB
                    )
                else:
                    rejected_bounds_count += 1

            # 2. Try overrides.json
            if lat is None and (key in overrides or raw_key in overrides):
                entry = overrides.get(key) or overrides.get(raw_key)
                cand_lat = float(entry["lat"])
                cand_lon = float(entry["lon"])
                if is_within_usa(cand_lat, cand_lon):
                    lat = cand_lat
                    lon = cand_lon
                    source = entry.get("source", GeocodeSource.OVERRIDE)
                else:
                    rejected_bounds_count += 1

            # 3. Optional Nominatim fallback
            if lat is None and use_nominatim:
                self.stdout.write(f"Querying Nominatim for {station.city}, {station.state}...")
                try:
                    query = f"{station.city}, {station.state}, USA"
                    resp = nominatim_session.get(
                        "https://nominatim.openstreetmap.org/search",
                        params={"q": query, "format": "json", "limit": 1},
                        timeout=10,
                    )
                    time.sleep(1.0)  # Respect 1 req/s rate limit
                    if resp.status_code == 200 and resp.json():
                        first = resp.json()[0]
                        cand_lat = float(first["lat"])
                        cand_lon = float(first["lon"])
                        if is_within_usa(cand_lat, cand_lon):
                            lat = cand_lat
                            lon = cand_lon
                            source = GeocodeSource.NOMINATIM
                            overrides[key] = {
                                "lat": lat,
                                "lon": lon,
                                "source": GeocodeSource.NOMINATIM,
                                "city": station.city,
                                "state": station.state,
                            }
                        else:
                            rejected_bounds_count += 1
                except Exception as e:
                    self.stderr.write(
                        f"Nominatim lookup failed for {station.city}, {station.state}: {e}"
                    )

            if lat is not None and lon is not None:
                matched_count += 1
                station.lat = round(lat, 6)
                station.lon = round(lon, 6)
                station.geocode_source = source
                source_counts[source] = source_counts.get(source, 0) + 1
                geocoded_rows.append(
                    {
                        "opis_id": station.opis_id,
                        "lat": station.lat,
                        "lon": station.lon,
                        "geocode_source": station.geocode_source,
                    }
                )
            else:
                station.lat = None
                station.lon = None
                station.geocode_source = GeocodeSource.NONE
                unmatched_stations.append(station)
                geocoded_rows.append(
                    {
                        "opis_id": station.opis_id,
                        "lat": "",
                        "lon": "",
                        "geocode_source": GeocodeSource.NONE,
                    }
                )

        # Write updated overrides if changed
        if use_nominatim:
            with open(overrides_path, mode="w", encoding="utf-8") as f:
                json.dump(overrides, f, indent=2)

        # Bulk update stations in database
        Station.objects.bulk_update(
            stations,
            ["lat", "lon", "geocode_source"],
            batch_size=1000,
        )

        # Export CSV
        with open(output_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["opis_id", "lat", "lon", "geocode_source"])
            writer.writeheader()
            writer.writerows(geocoded_rows)

        match_rate = (matched_count / total * 100) if total else 0
        self.stdout.write(
            self.style.SUCCESS(
                f"\nGeocoding Results:\n"
                f"  Total Stations: {total}\n"
                f"  Matched: {matched_count}/{total} ({match_rate:.2f}%)\n"
                f"  Unmatched: {len(unmatched_stations)}\n"
                f"  Rejected Outside US Bounds: {rejected_bounds_count}\n"
                f"  Source Breakdown: {dict(source_counts)}"
            )
        )

        if unmatched_stations:
            sample = [f"{s.opis_id}: {s.city}, {s.state}" for s in unmatched_stations[:10]]
            self.stdout.write(f"Sample unmatched stations: {', '.join(sample)}")
