"""Serializers for route planning inputs and outputs."""

from rest_framework import serializers


class RoutePlanInputSerializer(serializers.Serializer):
    """Input parameters for fuel-optimized route planning."""

    start = serializers.CharField(
        required=True,
        help_text="Origin location ('lat,lon' or 'City, ST')",
    )
    finish = serializers.CharField(
        required=True,
        help_text="Destination location ('lat,lon' or 'City, ST')",
    )
    start_fuel_gallons = serializers.FloatField(
        required=False,
        default=0.0,
        min_value=0.0,
        max_value=50.0,
        help_text="Initial fuel level in tank (0 to 50 gallons)",
    )
    include_candidates = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether to include all corridor candidate stations for map display",
    )
    optimize_for = serializers.ChoiceField(
        choices=["practical", "cost"],
        default="practical",
        required=False,
        help_text="Optimization strategy: 'practical' consolidates short stops; 'cost' gives pure mathematical optimum",
    )


class LocationCoordinateSerializer(serializers.Serializer):
    label = serializers.CharField()
    lat = serializers.FloatField()
    lon = serializers.FloatField()


class RoutePlanSummarySerializer(serializers.Serializer):
    start = LocationCoordinateSerializer()
    finish = LocationCoordinateSerializer()
    distance_miles = serializers.FloatField()
    duration_hours = serializers.FloatField()
    total_gallons = serializers.FloatField()
    total_fuel_cost_usd = serializers.CharField()
    avg_price_per_gallon = serializers.CharField()
    cost_per_mile_usd = serializers.CharField()
    fuel_stops = serializers.IntegerField()
    baseline_cost_usd = serializers.CharField()
    savings_usd = serializers.CharField()


class FuelStopSerializer(serializers.Serializer):
    sequence = serializers.IntegerField()
    station_id = serializers.IntegerField()
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    lat = serializers.FloatField()
    lon = serializers.FloatField()
    mile_marker = serializers.FloatField()
    off_route_miles = serializers.FloatField()
    price_per_gallon = serializers.CharField()
    gallons_purchased = serializers.FloatField()
    cost_usd = serializers.CharField()
    fuel_on_arrival_gallons = serializers.FloatField()
    fuel_on_departure_gallons = serializers.FloatField()


class CandidateStationSerializer(serializers.Serializer):
    station_id = serializers.IntegerField()
    lat = serializers.FloatField()
    lon = serializers.FloatField()
    price_per_gallon = serializers.CharField()
    mile_marker = serializers.FloatField()


class RoutePlanMetaSerializer(serializers.Serializer):
    routing_provider = serializers.CharField()
    external_api_calls = serializers.IntegerField()
    cache_hit = serializers.BooleanField()
    compute_ms = serializers.IntegerField()
    assumptions = serializers.ListField(child=serializers.CharField())


class RoutePlanResponseSerializer(serializers.Serializer):
    summary = RoutePlanSummarySerializer()
    fuel_stops = FuelStopSerializer(many=True)
    route = serializers.DictField(
        help_text="GeoJSON FeatureCollection representing route and waypoints"
    )
    candidates = CandidateStationSerializer(many=True, required=False)
    map_url = serializers.CharField()
    meta = RoutePlanMetaSerializer()
