from django.contrib import admin

from apps.stations.models import Station


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = (
        "opis_id",
        "name",
        "city",
        "state",
        "price",
        "lat",
        "lon",
        "geocode_source",
    )
    search_fields = ("opis_id", "name", "city", "address")
    list_filter = ("state", "geocode_source")
    ordering = ("opis_id",)
