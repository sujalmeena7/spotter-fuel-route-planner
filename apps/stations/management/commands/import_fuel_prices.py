import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.stations.models import Station

US_50_STATES_AND_DC = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}


class Command(BaseCommand):
    help = "Import and clean fuel prices CSV, dropping Canadian rows and resolving duplicate IDs to lowest price."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            type=str,
            default=str(settings.BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"),
            help="Path to the fuel prices CSV file.",
        )

    def handle(self, *args, **options):
        file_path = Path(options["path"])
        if not file_path.exists():
            self.stderr.write(self.style.ERROR(f"CSV file not found at {file_path}"))
            return

        read_count = 0
        dropped_non_us_count = 0
        merged_duplicates_count = 0
        station_map: dict[int, dict] = {}

        with open(file_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                read_count += 1
                state = row["State"].strip().upper()
                if state not in US_50_STATES_AND_DC:
                    dropped_non_us_count += 1
                    continue

                try:
                    opis_id = int(row["OPIS Truckstop ID"].strip())
                    price = Station.quantize_price(row["Retail Price"].strip())
                    rack_id = int(row["Rack ID"].strip())
                except (ValueError, KeyError) as e:
                    self.stderr.write(f"Skipping malformed row: {row} ({e})")
                    continue

                name = " ".join(row["Truckstop Name"].strip().split())
                address = " ".join(row["Address"].strip().split())
                city = " ".join(row["City"].strip().split())

                station_data = {
                    "opis_id": opis_id,
                    "name": name,
                    "address": address,
                    "city": city,
                    "state": state,
                    "rack_id": rack_id,
                    "price": price,
                }

                if opis_id in station_map:
                    merged_duplicates_count += 1
                    # Keep the lowest price per ID
                    if price < station_map[opis_id]["price"]:
                        station_map[opis_id] = station_data
                else:
                    station_map[opis_id] = station_data

        instances = [Station(**data) for data in station_map.values()]
        Station.objects.bulk_create(
            instances,
            batch_size=1000,
            update_conflicts=True,
            update_fields=["name", "address", "city", "state", "rack_id", "price"],
            unique_fields=["opis_id"],
        )

        saved_count = len(instances)

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete: read={read_count}, "
                f"dropped_non_us={dropped_non_us_count}, "
                f"merged_duplicates={merged_duplicates_count}, "
                f"saved={saved_count}"
            )
        )
