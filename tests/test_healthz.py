import pytest
from django.test import Client


@pytest.mark.django_db
def test_healthz_endpoint():
    """Verify GET /healthz returns 200 with status ok."""
    client = Client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_openapi_schema_endpoint():
    """Verify OpenAPI 3 schema endpoint returns 200."""
    client = Client()
    response = client.get("/api/schema/")
    assert response.status_code == 200
