"""API views for route planning."""

import logging

from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.planner.serializers import (
    RoutePlanInputSerializer,
    RoutePlanResponseSerializer,
)
from apps.planner.service import RoutePlanService

logger = logging.getLogger("planner")


class RoutePlanView(APIView):
    """Calculates fuel-optimized route, stops, and financial summary between two US locations."""

    @extend_schema(
        summary="Plan Fuel-Optimized Route (GET)",
        description="Calculate optimal refueling stops for a 500-mile range truck at 10 MPG.",
        parameters=[
            OpenApiParameter(
                name="start",
                description="Origin location ('lat,lon' or 'City, ST')",
                required=True,
                type=str,
            ),
            OpenApiParameter(
                name="finish",
                description="Destination location ('lat,lon' or 'City, ST')",
                required=True,
                type=str,
            ),
            OpenApiParameter(
                name="start_fuel_gallons",
                description="Initial fuel in tank (0 to 50 gallons, default 0)",
                required=False,
                type=float,
            ),
            OpenApiParameter(
                name="include_candidates",
                description="Include all candidate stations in route corridor",
                required=False,
                type=bool,
            ),
        ],
        responses={200: RoutePlanResponseSerializer},
        examples=[
            OpenApiExample(
                "Dallas to Denver Example",
                value={
                    "start": "Dallas, TX",
                    "finish": "Denver, CO",
                    "start_fuel_gallons": 0.0,
                    "include_candidates": False,
                },
                request_only=True,
            )
        ],
    )
    def get(self, request):
        serializer = RoutePlanInputSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return self._handle_plan(serializer.validated_data)

    @extend_schema(
        summary="Plan Fuel-Optimized Route (POST)",
        description="Calculate optimal refueling stops for a 500-mile range truck at 10 MPG.",
        request=RoutePlanInputSerializer,
        responses={200: RoutePlanResponseSerializer},
    )
    def post(self, request):
        serializer = RoutePlanInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._handle_plan(serializer.validated_data)

    def _handle_plan(self, data: dict) -> Response:
        start = data["start"]
        finish = data["finish"]
        start_fuel = float(data.get("start_fuel_gallons", 0.0))
        include_candidates = bool(data.get("include_candidates", False))

        payload = RoutePlanService.plan(
            start_str=start,
            finish_str=finish,
            start_fuel=start_fuel,
            include_candidates=include_candidates,
        )

        meta = payload.get("meta", {})
        logger.info(
            f"Route plan: {start} -> {finish} | "
            f"{meta.get('compute_ms')}ms | "
            f"calls={meta.get('external_api_calls')} | "
            f"cache_hit={meta.get('cache_hit')}"
        )

        return Response(payload, status=status.HTTP_200_OK)
