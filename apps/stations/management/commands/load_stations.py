"""Load station coordinates from committed data/stations_geocoded.csv into database (offline, zero-network)."""

import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.stations.gazetteer import is_within_usa
from apps.stations.models import GeocodeSource, Station


class Command(BaseCommand):
    help = "Load station coordinates from committed data/stations_geocoded.csv into database (offline, zero-network)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            type=str,
            default=str(settings.BASE_DIR / "data" / "stations_geocoded.csv"),
            help="Path to stations_geocoded.csv file.",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["path"])
        if not csv_path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {csv_path}"))
            return

        # Map opis_id -> (lat, lon, geocode_source)
        geocode_data: dict[int, tuple[float | None, float | None, str]] = {}
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    opis_id = int(row["opis_id"])
                    lat = float(row["lat"]) if row.get("lat") else None
                    lon = float(row["lon"]) if row.get("lon") else None
                    source = row.get("geocode_source") or GeocodeSource.NONE

                    # Enforce US bounds
                    if lat is not None and lon is not None:
                        if not is_within_usa(lat, lon):
                            lat = None
                            lon = None
                            source = GeocodeSource.NONE

                    geocode_data[opis_id] = (lat, lon, source)
                except (ValueError, KeyError):
                    continue

        stations = list(Station.objects.all())
        updated = 0
        outside_bounds_count = 0
        unmatched = []

        for s in stations:
            if s.opis_id in geocode_data:
                lat, lon, source = geocode_data[s.opis_id]
                s.lat = lat
                s.lon = lon
                s.geocode_source = source
                if lat is not None and lon is not None:
                    updated += 1
                else:
                    unmatched.append(s)
            else:
                unmatched.append(s)

        Station.objects.bulk_update(
            stations,
            ["lat", "lon", "geocode_source"],
            batch_size=1000,
        )

        null_count = Station.objects.filter(lat__isnull=True).count()
        match_rate = (updated / len(stations) * 100) if stations else 0
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded coordinates for {updated}/{len(stations)} stations ({match_rate:.2f}%).\n"
                f"  Stations with null lat/lon: {null_count}\n"
                f"  Stations outside US bounds: {outside_bounds_count}"
            )
        )
