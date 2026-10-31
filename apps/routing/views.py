"""Location autocomplete and routing views."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.routing.serializers import LocationSuggestionSerializer
from apps.stations.gazetteer import GazetteerIndex


class LocationAutocompleteView(APIView):
    """Offline city autocomplete endpoint powered by Census Gazetteer."""

    @extend_schema(
        summary="City Autocomplete",
        description="Search US cities offline from in-memory Census Gazetteer. Makes 0 external calls.",
        parameters=[
            OpenApiParameter(
                name="q",
                description="City search prefix or 'City, ST'",
                required=True,
                type=str,
            ),
            OpenApiParameter(
                name="limit",
                description="Maximum number of suggestions (default 8)",
                required=False,
                type=int,
            ),
        ],
        responses={200: LocationSuggestionSerializer(many=True)},
    )
    def get(self, request):
        query = request.query_params.get("q", "").strip()
        try:
            limit = int(request.query_params.get("limit", 8))
        except (ValueError, TypeError):
            limit = 8
        limit = max(1, min(limit, 50))

        if not query:
            return Response([])

        idx = GazetteerIndex.get_instance()
        results = idx.search_autocomplete(query=query, limit=limit)
        return Response(results)
