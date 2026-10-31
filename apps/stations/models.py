from decimal import ROUND_HALF_UP, Decimal

from django.db import models


class GeocodeSource(models.TextChoices):
    GAZETTEER_PLACE = "gazetteer_place", "Gazetteer Place"
    GAZETTEER_COUSUB = "gazetteer_cousub", "Gazetteer County Sub"
    OVERRIDE = "override", "Manual Override"
    NOMINATIM = "nominatim", "Nominatim"
    NONE = "none", "None"


class Station(models.Model):
    """Retail truck stop fuel station."""

    opis_id = models.IntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.IntegerField()
    price = models.DecimalField(max_digits=6, decimal_places=3)
    lat = models.FloatField(null=True, blank=True, db_index=True)
    lon = models.FloatField(null=True, blank=True)
    geocode_source = models.CharField(
        max_length=32,
        choices=GeocodeSource.choices,
        default=GeocodeSource.NONE,
    )

    class Meta:
        ordering = ["opis_id"]
        verbose_name = "Station"
        verbose_name_plural = "Stations"

    def __str__(self) -> str:
        return f"#{self.opis_id} {self.name} ({self.city}, {self.state}) - ${self.price}"

    @staticmethod
    def quantize_price(raw: float | str | Decimal) -> Decimal:
        """Quantize retail price to 3 decimal places using ROUND_HALF_UP."""
        return Decimal(str(raw)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
