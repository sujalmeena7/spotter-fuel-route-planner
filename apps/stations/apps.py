import os
import sys

from django.apps import AppConfig


class StationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.stations"
    verbose_name = "Stations"

    def ready(self) -> None:
        """Warm up StationIndex and GazetteerIndex on server startup."""
        # Warm up if running inside Django's runserver worker process or under gunicorn
        is_runserver_worker = os.environ.get("RUN_MAIN") == "true"
        is_gunicorn = any("gunicorn" in arg for arg in sys.argv) or "gunicorn" in sys.modules

        # Avoid executing warmup during migrations, schema setup, static collection, etc.
        ignored_commands = {
            "migrate",
            "makemigrations",
            "collectstatic",
            "flush",
            "inspectdb",
        }
        if any(cmd in sys.argv for cmd in ignored_commands):
            return

        if is_runserver_worker or is_gunicorn:
            try:
                from apps.stations.gazetteer import GazetteerIndex
                from apps.stations.index import StationIndex

                GazetteerIndex.get_instance().load()
                StationIndex.get_instance().load()
            except Exception:
                # Silently proceed if database tables are not yet created
                pass
