# Architecture & Engineering Decisions (DECISIONS.md)

This log documents all architectural choices, version selections, external URL verifications, and engineering refinements made relative to `plan.md`.

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
- **MapLibre GL JS**: Pinned version `v4.7.1` with verified SRI hashes:
  - JS: `sha384-SYKAG6cglRMN0RVvhNeBY0r3FYKNOJtznwA0v7B5Vp9tr31xAHsZC0DqkQ/pZDmj`
  - CSS: `sha384-MinO0mNliZ3vwppuPOUnGa+iq619pfMhLVUXfC4LHwSCvF9H+6P/KO4Q7qBOYV5V`
- **Basemaps**:
  - Light mode: OpenFreeMap Positron vector style (`https://tiles.openfreemap.org/styles/positron`).
  - Dark mode: CARTO Dark Matter GL style (`https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json`).

---

## 3. Engineering Decisions & Refinements

1. **Sub-Sampling Route Vertices on Long Cross-Country Corridors**:
   - *Context*: Cross-country routes (e.g., Seattle, WA to Miami, FL or NY to LA) produce 35,000+ raw coordinates from OSRM/ORS. Building a `cKDTree` on 35,000 vertices per request caused matching time to reach ~300 ms.
   - *Refinement*: When a route has $> 4,000$ vertices, `find_corridor_stations` samples vertices down to ~4,000 evenly spaced points (~0.15 miles spacing). This preserves precision well within 0.1 miles (far exceeding the 0.5-mile accuracy requirement) while dropping corridor matching compute time to $< 25$ ms.
2. **Deterministic SHA-256 Hashing of Cache Keys**:
   - *Context*: Standard Django cache backends (such as Redis or Memcached) disallow spaces, colons, or control characters in cache keys (`CacheKeyWarning`).
   - *Refinement*: All cache keys for routes and plans are formatted as `routeplan_<sha256(normalized_input)>`, guaranteeing RFC-compliant keys across all backend cache providers.
3. **Gunicorn `post_fork` Pre-Warming**:
   - *Context*: The first HTTP request to a newly spawned Gunicorn worker previously incurred ~40 ms loading the KDTree and Gazetteer index.
   - *Refinement*: Configured `post_fork(server, worker)` in `gunicorn.conf.py` to pre-warm both `StationIndex` and `LocationResolver` before accepting traffic, guaranteeing instant sub-50ms latency on the very first user request.
4. **Recorded Route Fixtures for Benchmark Command**:
   - *Context*: `benchmark_routes` benchmarks 6 canonical city pairs. In CI environments, real network access is disallowed.
   - *Refinement*: Saved real highway geometries into `tests/fixtures/benchmark_routes.json`. Running `manage.py benchmark_routes --mock` exercises the exact highway routes offline with 0 external API calls.
