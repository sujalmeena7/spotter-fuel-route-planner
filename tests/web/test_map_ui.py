import pytest
from django.test import Client


@pytest.mark.django_db
def test_map_page_renders():
    """Verify /map/ returns 200 and uses map.html with pinned MapLibre SRI."""
    client = Client()
    resp = client.get("/map/")
    assert resp.status_code == 200
    assert "text/html" in resp["Content-Type"]

    content = resp.content.decode("utf-8")
    assert "FuelRoute" in content
    assert "maplibre-gl@4.7.1" in content
    assert "sha384-SYKAG6cglRMN0RVvhNeBY0r3FYKNOJtznwA0v7B5Vp9tr31xAHsZC0DqkQ/pZDmj" in content
    assert "/static/web/css/app.css" in content
    assert "/static/web/js/main.js" in content


@pytest.mark.django_db
def test_static_files_resolve():
    """Verify WhiteNoise static files for CSS and JavaScript resolve correctly."""
    client = Client()

    # CSS
    resp_css = client.get("/static/web/css/app.css")
    assert resp_css.status_code == 200
    css_content = b"".join(resp_css.streaming_content).decode("utf-8")
    assert "--brand" in css_content

    # JS
    for js_file in [
        "main.js",
        "api.js",
        "map.js",
        "panel.js",
        "chart.js",
        "autocomplete.js",
        "format.js",
    ]:
        resp_js = client.get(f"/static/web/js/{js_file}")
        assert resp_js.status_code == 200, f"Failed to resolve /static/web/js/{js_file}"


@pytest.mark.django_db
def test_openapi_schema_endpoint():
    """Verify /api/schema/ and /api/docs/ return 200."""
    client = Client()
    resp_schema = client.get("/api/schema/")
    assert resp_schema.status_code == 200

    resp_docs = client.get("/api/docs/")
    assert resp_docs.status_code == 200
