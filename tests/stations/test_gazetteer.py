import csv
import io
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.stations.gazetteer import GazetteerIndex, is_within_usa, normalize_city_name
from apps.stations.management.commands.build_gazetteer import parse_gazetteer_text
from apps.stations.models import GeocodeSource, Station


def test_city_normalization():
    """Verify city name normalization handles abbreviations, casing, accents, and spacing."""
    assert normalize_city_name("MC DERMITT") == "mcdermitt"
    assert normalize_city_name("St. Louis") == "saint louis"
    assert normalize_city_name("New Castle                              ") == "new castle"
    assert normalize_city_name("Ft. Wayne") == "fort wayne"
    assert normalize_city_name("Mt. Vernon") == "mount vernon"
    assert normalize_city_name("Dallas") == "dallas"
    assert normalize_city_name("Abbeville") == "abbeville"
    assert normalize_city_name("Boise City") == "boise city"
    assert normalize_city_name("Lake Village") == "lake village"
    assert normalize_city_name("Winston-Salem") == "winston salem"
    assert normalize_city_name("Cañon City") == "canon city"


def test_gazetteer_lookup_plausible_coordinates():
    """Verify spot check coordinates for known cities are accurate and plausible."""
    idx = GazetteerIndex.get_instance()
    res = idx.lookup("Big Cabin", "OK")
    assert res is not None
    lat, lon, source = res
    assert 36.4 <= lat <= 36.6
    assert -95.3 <= lon <= -95.1
    assert source in ("gazetteer_place", "gazetteer_cousub")

    res_dallas = idx.lookup("Dallas", "TX")
    assert res_dallas is not None
    lat_d, lon_d, _ = res_dallas
    assert 32.6 <= lat_d <= 32.9
    assert -96.9 <= lon_d <= -96.7

    res_denver = idx.lookup("Denver", "CO")
    assert res_denver is not None
    lat_den, lon_den, _ = res_denver
    assert 39.6 <= lat_den <= 39.9
    assert -105.1 <= lon_den <= -104.8

    res_lv = idx.lookup("Lake Village", "AR")
    assert res_lv is not None
    lat_lv, lon_lv, _ = res_lv
    assert 33.2 <= lat_lv <= 33.4
    assert -91.4 <= lon_lv <= -91.2

    res_lc = idx.lookup("Lake City", "AR")
    assert res_lc is not None
    lat_lc, lon_lc, _ = res_lc
    assert 35.7 <= lat_lc <= 35.9
    assert -90.5 <= lon_lc <= -90.4


def test_cousub_parser_header_mapping():
    """Verify 2026 cousub header mapping places lat and lon in correct fields without offset."""
    # Real 2026 header line for cousubs (notice GEOIDFQ column and lack of LSAD)
    cousub_fixture = (
        "USPS|GEOID|GEOIDFQ|ANSICODE|NAME|FUNCSTAT|ALAND|AWATER|ALAND_SQMI|AWATER_SQMI|INTPTLAT|INTPTLONG\n"
        "AL|0100190184|0600000US0100190184|00023405|Autaugaville CCD|S|478151747|13897843|184.615|5.366|32.457413|-86.729003\n"
    )
    records, rejected = parse_gazetteer_text(cousub_fixture, kind="cousub")

    assert rejected == 0
    assert len(records) == 1
    rec = records[0]
    assert rec["name"] == "Autaugaville CCD"
    assert rec["state"] == "AL"
    # Lat must be 32.457413 (not 5.366 AWATER_SQMI)
    assert rec["lat"] == "32.457413"
    # Lon must be -86.729003 (not 32.457413 INTPTLAT)
    assert rec["lon"] == "-86.729003"
    assert is_within_usa(float(rec["lat"]), float(rec["lon"]))


def test_data_integrity_all_geocoded_stations_within_us_bounds():
    """Assert every row in data/stations_geocoded.csv is valid and strictly within US bounds."""
    csv_path = Path(settings.BASE_DIR) / "data" / "stations_geocoded.csv"
    assert csv_path.exists(), "stations_geocoded.csv must exist"

    with open(csv_path, encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    assert len(reader) == 6626
    outside_bounds = []

    for row in reader:
        assert row["lat"], f"Missing lat for opis_id {row['opis_id']}"
        assert row["lon"], f"Missing lon for opis_id {row['opis_id']}"
        lat = float(row["lat"])
        lon = float(row["lon"])
        if not is_within_usa(lat, lon):
            outside_bounds.append((row["opis_id"], lat, lon, row["geocode_source"]))

    assert len(outside_bounds) == 0, (
        f"Found {len(outside_bounds)} stations outside US bounds: {outside_bounds[:5]}"
    )


@pytest.mark.django_db
def test_geocode_priority_and_overrides(tmp_path):
    """Verify gazetteer priority: place -> cousub -> override."""
    Station.objects.create(
        opis_id=99901,
        name="OVERRIDE STOP",
        address="100 HYPOTHETICAL WAY",
        city="NowhereVilleXyz",
        state="WY",
        rack_id=1,
        price=3.500,
    )
    Station.objects.create(
        opis_id=99902,
        name="BIG CABIN STOP",
        address="I-44",
        city="Big Cabin",
        state="OK",
        rack_id=2,
        price=3.100,
    )

    overrides_file = tmp_path / "test_overrides.json"
    overrides_file.write_text(
        '{"nowherevillexyz,WY": {"lat": 43.1234, "lon": -107.5678, "source": "override"}}',
        encoding="utf-8",
    )
    output_file = tmp_path / "test_geocoded.csv"

    out = io.StringIO()
    call_command(
        "geocode_stations",
        output=str(output_file),
        overrides=str(overrides_file),
        stdout=out,
    )

    s1 = Station.objects.get(opis_id=99901)
    assert s1.lat == 43.1234
    assert s1.lon == -107.5678
    assert s1.geocode_source == GeocodeSource.OVERRIDE

    s2 = Station.objects.get(opis_id=99902)
    assert s2.lat is not None
    assert s2.geocode_source in (GeocodeSource.GAZETTEER_PLACE, GeocodeSource.GAZETTEER_COUSUB)


@pytest.mark.django_db
def test_load_stations_from_csv(tmp_path):
    """Verify load_stations updates coordinates from CSV without network access."""
    s = Station.objects.create(
        opis_id=88888,
        name="TEST LOAD STOP",
        address="1 MAIN ST",
        city="SampleCity",
        state="TX",
        rack_id=1,
        price=3.250,
    )
    csv_file = tmp_path / "test_stations_geocoded.csv"
    csv_file.write_text(
        "opis_id,lat,lon,geocode_source\n88888,31.555555,-98.444444,gazetteer_place\n",
        encoding="utf-8",
    )

    out = io.StringIO()
    call_command("load_stations", path=str(csv_file), stdout=out)

    s.refresh_from_db()
    assert s.lat == 31.555555
    assert s.lon == -98.444444
    assert s.geocode_source == "gazetteer_place"


@pytest.mark.django_db
def test_load_stations_zero_null_coordinates_in_db():
    """Assert DB has 6,626 stations with 0 null coordinates and 0 outside US bounds after load_stations."""
    call_command("import_fuel_prices")
    call_command("load_stations")

    stations = Station.objects.all()
    assert stations.count() == 6626
    assert Station.objects.filter(lat__isnull=True).count() == 0
    assert Station.objects.filter(lon__isnull=True).count() == 0

    outside = [s.opis_id for s in stations if not is_within_usa(s.lat, s.lon)]
    assert len(outside) == 0, f"Found stations outside US bounds: {outside}"


@pytest.mark.django_db
def test_all_checkable_stations_within_25_miles_of_city_centroid(
    ensure_db_stations_and_clean_cache,
):
    """Verify all checkable stations in data/stations_geocoded.csv are within 25 mi of city centroid."""
    import math

    def haversine(lat1, lon1, lat2, lon2):
        R = 3958.8
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    idx = GazetteerIndex.get_instance()

    raw_cities = {}
    fuel_csv = settings.BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"
    with open(fuel_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw_cities[row["OPIS Truckstop ID"]] = (
                row["City"].strip(),
                row["State"].strip().upper(),
            )

    geocoded_csv = settings.BASE_DIR / "data" / "stations_geocoded.csv"
    checked_count = 0
    with open(geocoded_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row["lat"] or not row["lon"]:
                continue
            sid = row["opis_id"]
            lat = float(row["lat"])
            lon = float(row["lon"])
            city, state = raw_cities.get(sid, ("", ""))
            res = idx.lookup(city, state)
            if res:
                checked_count += 1
                c_lat, c_lon, _ = res
                dist = haversine(lat, lon, c_lat, c_lon)
                assert dist <= 25.0, (
                    f"Station #{sid} ({city}, {state}) at ({lat}, {lon}) is {dist:.1f} mi "
                    f"from gazetteer centroid ({c_lat}, {c_lon}) (> 25 mi)"
                )

    assert checked_count > 6000, f"Expected > 6000 checkable stations, got {checked_count}"

    # Specifically verify station #70495 in Lake Village, AR
    s70495 = Station.objects.get(opis_id=70495)
    assert s70495.city == "Lake Village"
    assert s70495.state == "AR"
    assert 33.2 <= s70495.lat <= 33.4
    assert -91.4 <= s70495.lon <= -91.2
