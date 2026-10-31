"""Serializers for routing and location endpoints."""

from rest_framework import serializers


class LocationSuggestionSerializer(serializers.Serializer):
    """Schema for individual city autocomplete suggestions."""

    label = serializers.CharField(help_text="Formatted city and state label, e.g. 'Dallas, TX'")
    city = serializers.CharField(help_text="City name")
    state = serializers.CharField(help_text="2-letter US state code")
    lat = serializers.FloatField(help_text="Centroid latitude")
    lon = serializers.FloatField(help_text="Centroid longitude")
    aland = serializers.IntegerField(help_text="Land area in square meters", required=False)
