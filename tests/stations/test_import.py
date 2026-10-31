import io
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.stations.models import Station


@pytest.mark.django_db
def test_import_fuel_prices_synthetic(tmp_path):
    """Test fuel price import logic with synthetic data covering whitespace, duplicates, and Canadian rows."""
    csv_content = (
        "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"
        '101,  TA TEST 1  ,"  100 MAIN ST  ",New Castle                              ,DE,243,3.459\n'
        '101,TA TEST 1 CHEAPER,"100 MAIN ST",New Castle,DE,243,3.199\n'
        '101,TA TEST 1 PRICIER,"100 MAIN ST",New Castle,DE,243,3.899\n'
        '202,ONTARIO TRUCK STOP,"HWY 401",London,ON,999,3.500\n'
        '203,ALBERTA FUEL,"CALGARY TRAIL",Edmonton,AB,998,3.200\n'
        '303,CHICAGO EXPRESS,"95TH ST",Chicago,IL,100,3.650\n'
    )
    csv_file = tmp_path / "test_prices.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    out = io.StringIO()
    call_command("import_fuel_prices", path=str(csv_file), stdout=out)
    output = out.getvalue()

    assert "read=6" in output
    assert "dropped_non_us=2" in output
    assert "merged_duplicates=2" in output
    assert "saved=2" in output

    # Check non-US dropped
    assert not Station.objects.filter(state__in=["ON", "AB"]).exists()

    # Check whitespace trimmed
    station_de = Station.objects.get(opis_id=101)
    assert station_de.city == "New Castle"
    assert station_de.state == "DE"
    assert station_de.address == "100 MAIN ST"

    # Check duplicate resolved to lowest price (3.199 vs 3.459 vs 3.899)
    assert station_de.price == Decimal("3.199")

    # Check second US station
    station_il = Station.objects.get(opis_id=303)
    assert station_il.price == Decimal("3.650")
    assert station_il.city == "Chicago"

    # Verify idempotency
    call_command("import_fuel_prices", path=str(csv_file), stdout=out)
    assert Station.objects.count() == 2


@pytest.mark.django_db
def test_import_real_dataset():
    """Verify importing the real dataset produces valid US stations and no Canadian provinces."""
    out = io.StringIO()
    call_command("import_fuel_prices", stdout=out)
    output = out.getvalue()

    assert "read=8151" in output
    assert "dropped_non_us=620" in output
    assert "merged_duplicates=905" in output
    assert "saved=6626" in output

    total = Station.objects.count()
    assert total == 6626

    # Canadian provinces must not exist
    canadian_provinces = ["AB", "ON", "BC", "QC", "MB", "SK", "NB", "NS", "PE", "NL", "YT", "NT"]
    assert not Station.objects.filter(state__in=canadian_provinces).exists()

    # Verify specific duplicate station 105 has lowest price
    station_105 = Station.objects.get(opis_id=105)
    assert station_105.city == "Bridgeport"
    assert station_105.state == "MI"
    # Bridgeport ID 105 has prices 3.269, 3.299, etc. Min is <= 3.269
    assert station_105.price <= Decimal("3.269")
