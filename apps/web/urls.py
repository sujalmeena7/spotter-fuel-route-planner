from django.urls import path

from apps.web.views import map_view

urlpatterns = [
    path("map/", map_view, name="map"),
    path("", map_view, name="root-map"),
]
