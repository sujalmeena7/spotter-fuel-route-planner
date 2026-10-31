"""Routing and location domain exceptions."""


class RoutingError(Exception):
    """Base exception for routing and location errors."""

    status_code: int = 400
    code: str = "invalid_input"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class LocationNotFound(RoutingError):
    status_code = 422
    code = "location_not_found"


class LocationOutsideUSA(RoutingError):
    status_code = 422
    code = "location_outside_usa"


class RoadNotFound(RoutingError):
    status_code = 422
    code = "road_not_found"


class NoRoute(RoutingError):
    status_code = 422
    code = "no_route"


class UpstreamError(RoutingError):
    status_code = 502
    code = "routing_upstream_error"


class UpstreamTimeout(RoutingError):
    status_code = 503
    code = "routing_timeout"
