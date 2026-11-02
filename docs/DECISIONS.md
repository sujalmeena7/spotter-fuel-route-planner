# Architecture & Engineering Decisions (DECISIONS.md)

This log documents the architectural choices, version selections, external URL verifications, and engineering refinements made while building the project.

---

## 1. Dependency Versions & Environment

Exact pins are in `requirements.txt` and `requirements-dev.txt`:

- **Django**: `6.1.2` (latest stable release on PyPI, requires Python 3.12+).
- **Django REST Framework**: `3.18.3` (supports Django 6.1).
- **drf-spectacular**: `0.30.0` (OpenAPI schema and Swagger UI).
- **Requests**: `2.34.2`.
- **NumPy**: `2.5.4`.
- **SciPy**: `1.18.1`.
- **python-dotenv**: `1.2.4`.
- **WhiteNoise**: `6.12.0`.
- **Gunicorn**: `26.2.0`.
- **Development**: pytest `9.2.0`, pytest-django `4.14.0`, ruff `0.17.3`.

---

## 2. External Services & Basemaps

- **Census Gazetteer**: Places and County Subdivisions national files from `https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2026_Gazetteer/` (the build command falls back to the 2025 files if the 2026 files are unavailable). The trimmed result is committed as `data/gazetteer_places_trimmed.csv`, so a fresh clone needs no download.
- **MapLibre GL JS**: Pinned version `v4.7.1` with verified SRI hashes:
  - JS: `sha384-SYKAG6cglRMN0RVvhNeBY0r3FYKNOJtznwA0v7B5Vp9tr31xAHsZC0DqkQ/pZDmj`
  - CSS: `sha384-MinO0mNliZ3vwppuPOUnGa+iq619pfMhLVUXfC4LHwSCvF9H+6P/KO4Q7qBOYV5V`
- **Basemaps**:
  - Light mode: OpenFreeMap Positron vector style (`https://tiles.openfreemap.org/styles/positron`).
  - Dark mode: CARTO Dark Matter GL style (`https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json`).
- **Routing**: OpenRouteService (`driving-hgv`, truck profile) when `ORS_API_KEY` is set; otherwise the public OSRM server (car profile), so the project runs with no key.

---

## 3. Engineering Decisions & Refinements

1. **Sub-sampling route vertices on long cross-country corridors**:
   - *Context*: Cross-country routes (for example Seattle to Miami or New York to Los Angeles) return about 35,000 raw coordinates. Building a `cKDTree` on all of them per request made corridor matching noticeably slower.
   - *Refinement*: When a route has more than 4,000 vertices, `find_corridor_stations` keeps about 4,000 evenly spaced points. Measured spacing between kept points is about 0.07 to 0.25 miles on routes under 1,200 miles and about 0.65 to 0.75 miles on 2,800 to 3,300 mile routes. A station's mile marker and off-route distance can therefore be off by up to roughly 0.4 miles on the longest routes. That is small compared with the 10-mile corridor and the city-centroid station coordinates, and it keeps corridor matching at roughly 5 to 45 ms across the benchmark routes (see the README benchmark table).
2. **Deterministic SHA-256 hashing of cache keys**:
   - *Context*: Cache backends such as Memcached reject keys with spaces or control characters (`CacheKeyWarning`).
   - *Refinement*: Route and plan cache keys are formatted as `routeplan_<sha256(normalized input and settings)>`, which is valid on every backend.
3. **Warming the station index at server startup**:
   - *Context*: Loading the station index and the gazetteer takes about 1 second. Paid on the first request, it made that request slow.
   - *Refinement*: `apps/stations/apps.py` starts a background warm-up thread when the server starts (`runserver`, with or without `--noreload`, or gunicorn), and skips management commands and tests. `gunicorn.conf.py` also warms each worker in `post_fork`. The first request after startup then pays only normal request cost.
4. **Recorded route fixtures for the benchmark command**:
   - *Context*: `benchmark_routes` measures 6 canonical city pairs, and CI must not use the network.
   - *Refinement*: Real route geometries are saved in `tests/fixtures/benchmark_routes.json`. `manage.py benchmark_routes --mock` runs the same routes offline with 0 external API calls.
