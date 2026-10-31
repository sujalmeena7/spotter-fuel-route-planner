# Architecture & Engineering Decisions (DECISIONS.md)

This log documents all architectural choices, version selections, external URL verifications, and deviations from `plan.md`.

---

## 1. Dependency Versions & Environment

- **Django**: `6.1.2` (Verified on PyPI as latest stable release).
- **Django REST Framework (DRF)**: `3.18.3` (Verified on PyPI for full Django 6.1 support).
- **drf-spectacular**: `0.30.0` (Verified on PyPI; provides OpenAPI 3.0 schema generation for Django 6.1 and DRF 3.18).
- **Requests**: `2.32.3`.
- **NumPy**: `2.2.3` / `~2.2`.
- **SciPy**: `1.15.2` / `~1.15`.
- **python-dotenv**: `1.0.1`.
- **WhiteNoise**: `6.9.0`.
- **Gunicorn**: `23.0.0`.
- **Pytest**: `8.3.5`.
- **pytest-django**: `4.10.0`.
- **Ruff**: `0.9.10`.

---

## 2. External Services & Basemaps

- **Census Gazetteer**: Places national file pattern `https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/2026_Gaz_place_national.zip` (with fallback to 2025/2024 if 2026 is not yet published on census FTP).
- **MapLibre GL JS**: Pinned version `v4.7.1` / `v5.1.0` with verified SRI hash for zero-build frontend.
- **Basemaps**:
  - Light mode: OpenFreeMap Positron vector style (`https://tiles.openfreemap.org/styles/positron`).
  - Dark mode: CARTO Dark Matter GL style (`https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json`).

---

## 3. Deviations from PLAN.md

*(None so far; everything adheres strictly to plan.md.)*
