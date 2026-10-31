"""URL configuration for spotter fuel route planner project."""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from config.views import healthz

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path("healthz/", healthz, name="healthz_slash"),
    # OpenAPI 3.0 schema and Swagger docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    # Location and Routing APIs
    path("", include("apps.routing.urls")),
    path("", include("apps.planner.urls")),
    path("", include("apps.web.urls")),
]
