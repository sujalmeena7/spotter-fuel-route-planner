import logging
import os
import sys
import threading

from django.apps import AppConfig

logger = logging.getLogger(__name__)

_warmup_event = threading.Event()
_warmup_thread: threading.Thread | None = None


def _is_server_process() -> bool:
    """Return True when running under runserver (with or without --noreload) or gunicorn."""
    if "gunicorn" in sys.modules or any("gunicorn" in arg for arg in sys.argv):
        return True
    is_runserver = any("runserver" in arg for arg in sys.argv)
    if is_runserver:
        # If --noreload is used, warm up in this single process
        if any("--noreload" in arg for arg in sys.argv):
            return True
        # If reloader is active, only warm up in the reloader child worker process
        return os.environ.get("RUN_MAIN") == "true"
    return False


def _should_skip() -> bool:
    """Skip warmup for management commands that don't serve requests."""
    skip_commands = {
        "migrate",
        "makemigrations",
        "collectstatic",
        "flush",
        "inspectdb",
        "spectacular",
        "test",
        "check",
        "showmigrations",
        "shell",
        "dbshell",
        "createsuperuser",
        "build_gazetteer",
        "geocode_stations",
        "load_stations",
        "import_fuel_prices",
        "benchmark_routes",
    }
    if len(sys.argv) >= 2 and sys.argv[1] in skip_commands:
        return True
    return False


def _warmup_worker() -> None:
    """Background thread that pre-warms scipy, gazetteer, station index, and services."""
    try:
        # Pre-import heavy scientific & routing modules off the request path
        import scipy.spatial  # noqa: F401

        import apps.planner.corridor  # noqa: F401
        import apps.planner.service  # noqa: F401
        from apps.stations.gazetteer import GazetteerIndex
        from apps.stations.index import StationIndex

        GazetteerIndex.get_instance().load()
        StationIndex.get_instance().load()

        from django.db import connection

        connection.close()

        logger.info("Warmup complete: scipy, gazetteer, and station index loaded.")
    except Exception:
        logger.warning("Warmup failed (tables or files may not exist yet).", exc_info=True)
    finally:
        _warmup_event.set()


def wait_for_warmup(timeout: float = 15.0) -> bool:
    """Wait for background warmup to finish if it was started."""
    if _warmup_thread is not None:
        return _warmup_event.wait(timeout=timeout)
    return True


class StationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.stations"
    verbose_name = "Stations"

    def ready(self) -> None:
        """Start background warmup thread for server processes only.

        Does NOT access the database in ready() itself — the DB access
        happens in the background thread, avoiding RuntimeWarning.
        """
        global _warmup_thread

        if _should_skip():
            return
        if not _is_server_process():
            return
        if "pytest" in sys.modules:
            return

        _warmup_event.clear()
        _warmup_thread = threading.Thread(target=_warmup_worker, daemon=True, name="warmup")
        _warmup_thread.start()
