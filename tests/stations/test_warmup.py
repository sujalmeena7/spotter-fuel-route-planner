import sys

import pytest
from django.test import Client

from apps.stations.apps import _is_server_process, _should_skip, _warmup_worker
from apps.stations.gazetteer import GazetteerIndex
from apps.stations.index import StationIndex


@pytest.mark.django_db
def test_warmup_worker_populates_indexes():
    """Verify _warmup_worker() loads GazetteerIndex and StationIndex."""
    # Reset singletons
    GazetteerIndex.reset()
    StationIndex._instance = None

    _warmup_worker()

    assert GazetteerIndex._instance is not None
    assert GazetteerIndex.get_instance()._loaded is True
    assert StationIndex._instance is not None
    assert StationIndex.get_instance()._loaded is True


@pytest.mark.django_db
def test_first_request_local_compute_under_100ms(mock_ors_route):
    """With warmup completed, the first route plan request must have local_compute_ms < 100."""
    # Ensure warmup state
    GazetteerIndex.get_instance().load()
    StationIndex.get_instance().load()

    client = Client()
    resp = client.get("/api/v1/route-plan/?start=Dallas,TX&finish=Denver,CO")
    assert resp.status_code == 200

    data = resp.json()
    local_ms = data["meta"]["timing"]["local_compute_ms"]
    assert local_ms < 100, f"Expected local_compute_ms < 100, got {local_ms}"


def test_warmup_skipped_for_management_commands():
    """Verify _is_server_process and _should_skip logic."""
    original_argv = sys.argv[:]
    try:
        sys.argv = ["manage.py", "migrate"]
        assert _should_skip() is True

        sys.argv = ["manage.py", "collectstatic"]
        assert _should_skip() is True

        sys.argv = ["manage.py", "runserver"]
        assert _should_skip() is False

        sys.argv = ["manage.py", "runserver", "--noreload"]
        assert _should_skip() is False
        assert _is_server_process() is True
    finally:
        sys.argv = original_argv
