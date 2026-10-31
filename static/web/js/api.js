/**
 * API client for FuelRoute backend endpoints.
 */

export async function fetchAutocomplete(query, limit = 8) {
    if (!query || !query.trim()) return [];
    const params = new URLSearchParams({ q: query.trim(), limit: String(limit) });
    const resp = await fetch(`/api/v1/locations/autocomplete/?${params.toString()}`);
    if (!resp.ok) return [];
    return await resp.json();
}

export async function fetchRoutePlan({ start, finish, start_fuel_gallons = 0, include_candidates = true }) {
    const params = new URLSearchParams({
        start: start.trim(),
        finish: finish.trim(),
        start_fuel_gallons: String(start_fuel_gallons),
        include_candidates: String(include_candidates),
    });

    const resp = await fetch(`/api/v1/route-plan/?${params.toString()}`);
    const data = await resp.json();

    if (!resp.ok) {
        const errorInfo = data.error || {
            code: 'unknown_error',
            message: 'Failed to plan route. Please try again.',
        };
        const err = new Error(errorInfo.message);
        err.code = errorInfo.code;
        err.details = errorInfo.details || {};
        throw err;
    }

    return data;
}
