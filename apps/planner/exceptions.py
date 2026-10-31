"""Unified exception handler formatting errors to standard shape."""

from rest_framework import status
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from apps.planner.optimizer import NoFuelNearOrigin, Unreachable
from apps.routing.exceptions import (
    LocationNotFound,
    LocationOutsideUSA,
    NoRoute,
    RoutingError,
    UpstreamError,
    UpstreamTimeout,
)


def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    """DRF exception handler producing standard Spotter error envelope:

    {"error": {"code": "...", "message": "...", "details": {...}}}
    """
    # 1. Custom domain exceptions from optimizer and routing
    if isinstance(exc, NoFuelNearOrigin):
        return Response(
            {
                "error": {
                    "code": "no_fuel_near_origin",
                    "message": str(exc),
                    "details": {},
                }
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if isinstance(exc, Unreachable):
        return Response(
            {
                "error": {
                    "code": "unreachable",
                    "message": str(exc),
                    "details": {
                        "gap_start_mile": exc.gap_start_mile,
                        "gap_end_mile": exc.gap_end_mile,
                    },
                }
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if isinstance(exc, LocationNotFound):
        return Response(
            {
                "error": {
                    "code": "location_not_found",
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if isinstance(exc, LocationOutsideUSA):
        return Response(
            {
                "error": {
                    "code": "location_outside_usa",
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if isinstance(exc, NoRoute):
        return Response(
            {
                "error": {
                    "code": "no_route",
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if isinstance(exc, UpstreamTimeout):
        return Response(
            {
                "error": {
                    "code": "routing_timeout",
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if isinstance(exc, UpstreamError):
        return Response(
            {
                "error": {
                    "code": "routing_upstream_error",
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if isinstance(exc, RoutingError):
        return Response(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            status=exc.status_code,
        )

    # 2. Standard DRF exceptions (Throttled, ValidationError, etc.)
    if isinstance(exc, Throttled):
        return Response(
            {
                "error": {
                    "code": "throttled",
                    "message": f"Request limit exceeded. Available in {int(exc.wait or 60)} seconds.",
                    "details": {"wait_seconds": exc.wait},
                }
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    if isinstance(exc, ValidationError):
        return Response(
            {
                "error": {
                    "code": "invalid_input",
                    "message": "Input validation failed.",
                    "details": exc.detail
                    if isinstance(exc.detail, dict)
                    else {"non_field_errors": exc.detail},
                }
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # 3. Default DRF exception handling fallback
    response = exception_handler(exc, context)
    if response is not None:
        return Response(
            {
                "error": {
                    "code": getattr(exc, "default_code", "error"),
                    "message": str(exc),
                    "details": response.data if isinstance(response.data, dict) else {},
                }
            },
            status=response.status_code,
        )

    return None
