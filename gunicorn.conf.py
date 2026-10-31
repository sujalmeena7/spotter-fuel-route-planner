"""Gunicorn configuration for Spotter Fuel Route Planner.

Configures 3 worker processes with post_fork pre-warming of in-memory KDTree
and Gazetteer to guarantee sub-50ms latency on the very first user request.
"""

import os

bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")
workers = int(os.getenv("GUNICORN_WORKERS", "3"))
worker_class = "sync"
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")


def post_fork(server, worker):
    """Warm up StationIndex and Gazetteer in each worker process immediately after fork.

    Eliminates first-request lazy-load latency, ensuring instant sub-50ms responses.
    """
    server.log.info(
        "Worker spawned (pid: %s) — pre-warming StationIndex and Gazetteer...", worker.pid
    )
    try:
        import django

        django.setup()
        from apps.planner.corridor import StationIndex
        from apps.routing.locations import LocationResolver

        # Warm gazetteer place lookups
        LocationResolver.resolve("Dallas, TX")
        # Warm numpy arrays & spatial index
        StationIndex.get_instance()
        server.log.info("Worker (pid: %s) pre-warming complete. Ready for traffic.", worker.pid)
    except Exception as exc:  # noqa: BLE001
        server.log.warning("Worker pre-warm skipped or failed: %s", exc)
