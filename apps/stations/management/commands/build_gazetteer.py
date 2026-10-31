"""Download and parse US Census Gazetteer Places and County Subdivisions files.

Uses csv.DictReader with header names (USPS, NAME, ALAND, INTPTLAT, INTPTLONG),
strips header and value whitespace, and enforces US bounding box validation.
"""

import csv
import io
import zipfile
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.stations.gazetteer import is_within_usa

PLACES_URL_2026 = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/2026_Gaz_place_national.zip"
PLACES_URL_2025 = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_place_national.zip"
COUSUBS_URL_2026 = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/2026_Gaz_cousubs_national.zip"
COUSUBS_URL_2025 = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_cousubs_national.zip"


def parse_gazetteer_text(text_content: str, kind: str) -> tuple[list[dict], int]:
    """Parse a pipe-delimited Census Gazetteer file using header names and US bounds validation.

    Returns (valid_records, rejected_bounds_count).
    """
    records: list[dict] = []
    rejected_count = 0

    f = io.StringIO(text_content)
    reader = csv.DictReader(f, delimiter="|")
    if reader.fieldnames:
        reader.fieldnames = [name.strip() for name in reader.fieldnames]

    required_headers = {"USPS", "NAME", "ALAND", "INTPTLAT", "INTPTLONG"}
    missing = required_headers - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"Gazetteer file missing required headers: {missing}")

    for row in reader:
        state = (row.get("USPS") or "").strip()
        name = (row.get("NAME") or "").strip()
        aland = (row.get("ALAND") or "").strip() or "0"
        lat_str = (row.get("INTPTLAT") or "").strip()
        lon_str = (row.get("INTPTLONG") or "").strip()

        if not (state and name and lat_str and lon_str):
            continue

        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError:
            continue

        if not is_within_usa(lat, lon):
            rejected_count += 1
            continue

        records.append(
            {
                "name": name,
                "state": state,
                "lat": str(round(lat, 6)),
                "lon": str(round(lon, 6)),
                "aland": aland,
                "kind": kind,
            }
        )

    return records, rejected_count


class Command(BaseCommand):
    help = "Download US Census Gazetteer Places and County Subdivisions and build trimmed CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=str,
            default=str(settings.BASE_DIR / "data" / "gazetteer_places_trimmed.csv"),
            help="Path to output trimmed gazetteer CSV.",
        )

    def _download_zip(self, primary_url: str, fallback_url: str) -> zipfile.ZipFile:
        self.stdout.write(f"Downloading {primary_url}...")
        try:
            resp = requests.get(primary_url, timeout=30)
            resp.raise_for_status()
            return zipfile.ZipFile(io.BytesIO(resp.content))
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"Primary failed ({e}), falling back to {fallback_url}")
            )
            resp = requests.get(fallback_url, timeout=30)
            resp.raise_for_status()
            return zipfile.ZipFile(io.BytesIO(resp.content))

    def handle(self, *args, **options):
        output_path = Path(options["output"])
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Download and parse places
        z_places = self._download_zip(PLACES_URL_2026, PLACES_URL_2025)
        places_file_name = z_places.namelist()[0]
        places_text = z_places.open(places_file_name).read().decode("utf-8", errors="replace")
        place_records, place_rejected = parse_gazetteer_text(places_text, kind="place")
        self.stdout.write(
            f"Parsed {len(place_records)} places (rejected {place_rejected} outside US bounds)"
        )

        # 2. Download and parse cousubs
        z_cousubs = self._download_zip(COUSUBS_URL_2026, COUSUBS_URL_2025)
        cousubs_file_name = z_cousubs.namelist()[0]
        cousubs_text = z_cousubs.open(cousubs_file_name).read().decode("utf-8", errors="replace")
        cousub_records, cousub_rejected = parse_gazetteer_text(cousubs_text, kind="cousub")
        self.stdout.write(
            f"Parsed {len(cousub_records)} cousubs (rejected {cousub_rejected} outside US bounds)"
        )

        all_records = place_records + cousub_records
        total_rejected = place_rejected + cousub_rejected

        with open(output_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "state", "lat", "lon", "aland", "kind"])
            writer.writeheader()
            writer.writerows(all_records)

        self.stdout.write(
            self.style.SUCCESS(
                f"Saved {len(all_records)} trimmed gazetteer records to {output_path} "
                f"(total rejected outside US bounds: {total_rejected})"
            )
        )
