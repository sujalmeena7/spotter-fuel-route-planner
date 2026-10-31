import pytest
from django.apps import apps
from django.test import Client

from apps.stations.apps import StationsConfig
from apps.stations.gazetteer import GazetteerIndex
from apps.stations.index import StationIndex


@pytest.mark.django_db
def test_warmup_in_ready_populates_indexes(monkeypatch):
    """Verify ready() triggers warmup when RUN_MAIN is set."""
    monkeypatch.setenv("RUN_MAIN", "true")

    config = apps.get_app_config("stations")
    assert isinstance(config, StationsConfig)

    # Reset singletons to verify ready() loads them
    GazetteerIndex.reset()
    StationIndex._instance = None

    config.ready()

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
