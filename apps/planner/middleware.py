"""Middleware for tracking request duration."""

import time


class ResponseTimeMiddleware:
    """Adds X-Response-Time-ms header to all responses."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        t0 = time.perf_counter()
        response = self.get_response(request)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        response["X-Response-Time-ms"] = str(round(elapsed_ms, 2))
        return response
