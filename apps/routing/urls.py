"""URLs for routing app."""

from django.urls import path

from apps.routing.views import LocationAutocompleteView

urlpatterns = [
    path(
        "api/v1/locations/autocomplete/",
        LocationAutocompleteView.as_view(),
        name="location-autocomplete",
    ),
]
