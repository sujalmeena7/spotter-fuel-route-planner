/**
 * MapLibre GL JS Map Controller for FuelRoute.
 */

import { formatGallons, formatMoney, formatPrice, getPriceTier } from './format.js';

const STYLES = {
    light: 'https://tiles.openfreemap.org/styles/positron',
    dark: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
};

export function setupMap({
    containerId,
    themeToggleBtn,
    corridorToggleBtn,
    onStopHover,
    onStopClick,
}) {
    // 1. Theme determination
    const urlParams = new URLSearchParams(window.location.search);
    const urlTheme = urlParams.get('theme');
    const savedTheme = localStorage.getItem('fuelroute_theme');
    const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    let currentTheme = (urlTheme === 'light' || urlTheme === 'dark')
        ? urlTheme
        : (savedTheme || (systemPrefersDark ? 'dark' : 'light'));

    document.documentElement.setAttribute('data-theme', currentTheme);

    const map = new maplibregl.Map({
        container: containerId,
        style: STYLES[currentTheme],
        center: [-98.5795, 39.8283], // Geographic center of USA
        zoom: 3.8,
        attributionControl: false,
    });
    window.mapInstance = map;

    // Add navigation and fullscreen controls
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'top-right');
    map.addControl(new maplibregl.FullscreenControl(), 'top-right');
    map.addControl(
        new maplibregl.AttributionControl({
            compact: true,
        }),
        'bottom-right'
    );

    let activeMarkers = [];
    let currentPlanData = null;
    let showCandidates = false;
    let drawInAnimFrame = null;

    // 2. Theme Switching & UI State
    function updateThemeBtn(theme) {
        if (!themeToggleBtn) return;
        const icon = theme === 'dark' ? '☀️' : '🌙';
        const label = theme === 'dark' ? ' Light' : ' Dark';
        themeToggleBtn.innerHTML = `<span class="btn-icon">${icon}</span><span class="btn-text">${label}</span>`;
    }

    function setTheme(theme) {
        currentTheme = theme;
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('fuelroute_theme', theme);
        updateThemeBtn(theme);
        map.setStyle(STYLES[theme]);
    }

    // Re-add custom route casing, route line, and candidate layers whenever a style loads
    function reapplyRouteLayers() {
        if (!currentPlanData) return;
        if (map.getSource('route-source')) return;

        const routeFeature = currentPlanData.route.features.find((f) => f.properties.kind === 'route');
        if (!routeFeature) return;
        const coords = routeFeature.geometry.coordinates;

        try {
            // Double-layer Route Line Source
            map.addSource('route-source', {
                type: 'geojson',
                data: {
                    type: 'Feature',
                    geometry: {
                        type: 'LineString',
                        coordinates: coords,
                    },
                },
            });

            // Casing layer (9px wide)
            map.addLayer({
                id: 'route-casing',
                type: 'line',
                source: 'route-source',
                layout: { 'line-join': 'round', 'line-cap': 'round' },
                paint: {
                    'line-color': currentTheme === 'dark' ? '#0F172A' : '#CBD5E1',
                    'line-width': 9,
                    'line-opacity': 0.9,
                },
            });

            // Brand line layer (5px wide)
            map.addLayer({
                id: 'route-line',
                type: 'line',
                source: 'route-source',
                layout: { 'line-join': 'round', 'line-cap': 'round' },
                paint: {
                    'line-color': '#2563EB',
                    'line-width': 5,
                },
            });

            // Corridor Candidates Circle Layer (if candidates provided)
            if (currentPlanData.candidates && currentPlanData.candidates.length > 0) {
                if (!map.getSource('corridor-candidates-source')) {
                    const candGeojson = {
                        type: 'FeatureCollection',
                        features: currentPlanData.candidates.map((c) => ({
                            type: 'Feature',
                            geometry: { type: 'Point', coordinates: [c.lon, c.lat] },
                            properties: {
                                station_id: c.station_id,
                                price: parseFloat(c.price_per_gallon) || 3.50,
                                mile_marker: c.mile_marker,
                            },
                        })),
                    };

                    map.addSource('corridor-candidates-source', {
                        type: 'geojson',
                        data: candGeojson,
                    });
                }

                if (!map.getLayer('corridor-candidates-layer')) {
                    map.addLayer({
                        id: 'corridor-candidates-layer',
                        type: 'circle',
                        source: 'corridor-candidates-source',
                        layout: {
                            visibility: showCandidates ? 'visible' : 'none',
                        },
                        paint: {
                            'circle-radius': 4.5,
                            'circle-color': [
                                'interpolate',
                                ['linear'],
                                ['get', 'price'],
                                2.80, '#16A34A',
                                3.50, '#D97706',
                                4.20, '#DC2626',
                            ],
                            'circle-opacity': 0.85,
                            'circle-stroke-width': 1,
                            'circle-stroke-color': '#FFFFFF',
                        },
                    });
                }
            }
        } catch (err) {
            // Style not ready yet; will retry on styledata / style.load / idle
        }
    }

    map.on('style.load', reapplyRouteLayers);
    map.on('styledata', reapplyRouteLayers);
    map.on('idle', reapplyRouteLayers);

    updateThemeBtn(currentTheme);
    themeToggleBtn.addEventListener('click', () => {
        setTheme(currentTheme === 'dark' ? 'light' : 'dark');
    });

    // 3. Corridor Candidates Toggle
    function updateCorridorBtn() {
        if (!corridorToggleBtn) return;
        const text = showCandidates ? ' Hide Corridor Stations' : ' Show Corridor Stations';
        corridorToggleBtn.innerHTML = `<span class="btn-icon">📍</span><span class="btn-text">${text}</span>`;
    }

    updateCorridorBtn();
    corridorToggleBtn.addEventListener('click', () => {
        showCandidates = !showCandidates;
        corridorToggleBtn.classList.toggle('active', showCandidates);
        updateCorridorBtn();
        if (map.getLayer('corridor-candidates-layer')) {
            map.setLayoutProperty(
                'corridor-candidates-layer',
                'visibility',
                showCandidates ? 'visible' : 'none'
            );
        }
    });

    // 4. Render Route, Layers, and Markers
    function renderRoute(planData, animate = true) {
        currentPlanData = planData;
        clearLayersAndMarkers();

        const routeFeature = planData.route.features.find((f) => f.properties.kind === 'route');
        if (!routeFeature) return;

        const coords = routeFeature.geometry.coordinates;

        // Double-layer Route Line Source
        map.addSource('route-source', {
            type: 'geojson',
            data: {
                type: 'Feature',
                geometry: {
                    type: 'LineString',
                    coordinates: animate ? [coords[0]] : coords,
                },
            },
        });

        // Casing layer (9px wide)
        map.addLayer({
            id: 'route-casing',
            type: 'line',
            source: 'route-source',
            layout: { 'line-join': 'round', 'line-cap': 'round' },
            paint: {
                'line-color': currentTheme === 'dark' ? '#0F172A' : '#CBD5E1',
                'line-width': 9,
                'line-opacity': 0.9,
            },
        });

        // Brand line layer (5px wide)
        map.addLayer({
            id: 'route-line',
            type: 'line',
            source: 'route-source',
            layout: { 'line-join': 'round', 'line-cap': 'round' },
            paint: {
                'line-color': '#2563EB',
                'line-width': 5,
            },
        });

        // Corridor Candidates Circle Layer (if candidates provided)
        if (planData.candidates && planData.candidates.length > 0) {
            const candGeojson = {
                type: 'FeatureCollection',
                features: planData.candidates.map((c) => ({
                    type: 'Feature',
                    geometry: { type: 'Point', coordinates: [c.lon, c.lat] },
                    properties: {
                        station_id: c.station_id,
                        price: parseFloat(c.price_per_gallon) || 3.50,
                        mile_marker: c.mile_marker,
                    },
                })),
            };

            map.addSource('corridor-candidates-source', {
                type: 'geojson',
                data: candGeojson,
            });

            map.addLayer({
                id: 'corridor-candidates-layer',
                type: 'circle',
                source: 'corridor-candidates-source',
                layout: {
                    visibility: showCandidates ? 'visible' : 'none',
                },
                paint: {
                    'circle-radius': 4.5,
                    'circle-color': [
                        'interpolate',
                        ['linear'],
                        ['get', 'price'],
                        2.80, '#16A34A',
                        3.50, '#D97706',
                        4.20, '#DC2626'
                    ],
                    'circle-opacity': 0.85,
                    'circle-stroke-width': 1,
                    'circle-stroke-color': '#FFFFFF',
                },
            });

            // Hover tooltip on candidate dot
            const candPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
            map.on('mouseenter', 'corridor-candidates-layer', (e) => {
                map.getCanvas().style.cursor = 'pointer';
                const f = e.features[0];
                const pt = f.geometry.coordinates;
                candPopup
                    .setLngLat(pt)
                    .setHTML(`<strong>Station #${f.properties.station_id}</strong><br/>${formatPrice(f.properties.price)} · Mile ${f.properties.mile_marker}`)
                    .addTo(map);
            });
            map.on('mouseleave', 'corridor-candidates-layer', () => {
                map.getCanvas().style.cursor = '';
                candPopup.remove();
            });
        }

        // Animated draw-in over ~900 ms
        if (animate) {
            const totalPoints = coords.length;
            const startTime = performance.now();
            const duration = 900;

            function animateLine(now) {
                const progress = Math.min((now - startTime) / duration, 1.0);
                const currentCount = Math.max(2, Math.floor(progress * totalPoints));
                const currentSegment = coords.slice(0, currentCount);

                const src = map.getSource('route-source');
                if (src) {
                    src.setData({
                        type: 'Feature',
                        geometry: { type: 'LineString', coordinates: currentSegment },
                    });
                }

                if (progress < 1.0) {
                    drawInAnimFrame = requestAnimationFrame(animateLine);
                } else {
                    addWaypointsAndMarkers(planData);
                }
            }
            drawInAnimFrame = requestAnimationFrame(animateLine);
        } else {
            addWaypointsAndMarkers(planData);
        }

        // Fit Bounds with padding for floating panel on desktop
        const bounds = coords.reduce(
            (b, coord) => b.extend(coord),
            new maplibregl.LngLatBounds(coords[0], coords[0])
        );

        const isDesktop = window.innerWidth >= 1024;
        map.fitBounds(bounds, {
            padding: {
                top: 80,
                bottom: isDesktop ? 80 : Math.round(window.innerHeight * 0.52),
                left: isDesktop ? 460 : 36,
                right: 70,
            },
            duration: 1200,
        });
    }

    function addWaypointsAndMarkers(planData) {
        const { summary, fuel_stops: stops } = planData;

        // Origin fill check
        const originFillStop = stops.find((s) => s.kind === 'origin_fill' || s.sequence === 0);
        const regularStops = stops.filter((s) => s.kind !== 'origin_fill' && s.sequence !== 0);

        // 1. Start Marker (Green Dot with Ring, or Fuel Badge if origin_fill)
        const startEl = document.createElement('div');
        startEl.className = 'custom-marker start-marker';
        startEl.id = 'map-marker-0';
        startEl.setAttribute('data-sequence', '0');

        let startPopupHtml = `<strong>Origin:</strong> ${summary.start.label}`;
        if (originFillStop) {
            startEl.classList.add('has-origin-fill');
            startEl.innerHTML = '<div class="marker-dot green-dot origin-fill-dot"><span class="origin-pump-icon">⛽</span></div>';
            const tier = getPriceTier(parseFloat(originFillStop.price_per_gallon), 2.8, 4.2);
            startPopupHtml = `
                <div class="marker-popup-card">
                    <div class="popup-title">⛽ Origin Fill</div>
                    <div class="popup-sub">${originFillStop.name}</div>
                    <div class="popup-sub">${originFillStop.city}, ${originFillStop.state} · Mile 0.0</div>
                    <div class="popup-stats">
                        <span class="popup-price ${tier.class}">${formatPrice(originFillStop.price_per_gallon)}</span>
                        <span>${formatGallons(originFillStop.gallons_purchased)} · ${formatMoney(originFillStop.cost_usd)}</span>
                    </div>
                </div>
            `;
        } else {
            startEl.innerHTML = '<div class="marker-dot green-dot"></div>';
        }

        const startMarker = new maplibregl.Marker({ element: startEl })
            .setLngLat([summary.start.lon, summary.start.lat])
            .setPopup(new maplibregl.Popup({ offset: 15 }).setHTML(startPopupHtml))
            .addTo(map);
        activeMarkers.push(startMarker);

        if (originFillStop) {
            startEl.addEventListener('mouseenter', () => {
                if (onStopHover) onStopHover(0, true);
            });
            startEl.addEventListener('mouseleave', () => {
                if (onStopHover) onStopHover(0, false);
            });
            startEl.addEventListener('click', () => {
                if (onStopClick) onStopClick(0);
            });
        }

        // 2. Fuel Stop Markers (Numbered Price-Colored Circles, excluding origin_fill)
        const prices = regularStops.map((s) => parseFloat(s.price_per_gallon));
        const minPrice = prices.length ? Math.min(...prices) : 3.0;
        const maxPrice = prices.length ? Math.max(...prices) : 4.0;

        regularStops.forEach((s, idx) => {
            const tier = getPriceTier(parseFloat(s.price_per_gallon), minPrice, maxPrice);
            const stopEl = document.createElement('div');
            stopEl.className = `custom-marker fuel-stop-marker ${tier.class}`;
            stopEl.id = `map-marker-${s.sequence}`;
            stopEl.setAttribute('data-sequence', s.sequence);
            stopEl.innerHTML = `<span>${s.sequence}</span>`;

            // Calculate offset if within ~12px / ~0.003 deg of an earlier stop
            let offset = [0, 0];
            for (let i = 0; i < idx; i++) {
                const prev = regularStops[i];
                if (Math.abs(s.lat - prev.lat) < 0.003 && Math.abs(s.lon - prev.lon) < 0.003) {
                    offset = [14, -8];
                    stopEl.classList.add('clustered-offset');
                    break;
                }
            }

            const popupContent = `
                <div class="marker-popup-card">
                    <div class="popup-title">Stop ${s.sequence}: ${s.name}</div>
                    <div class="popup-sub">${s.city}, ${s.state} · Mile ${s.mile_marker.toFixed(1)}</div>
                    <div class="popup-stats">
                        <span class="popup-price ${tier.class}">${formatPrice(s.price_per_gallon)}</span>
                        <span>${formatGallons(s.gallons_purchased)} · ${formatMoney(s.cost_usd)}</span>
                    </div>
                </div>
            `;
            const popup = new maplibregl.Popup({ offset: 18 }).setHTML(popupContent);

            const marker = new maplibregl.Marker({ element: stopEl, offset })
                .setLngLat([s.lon, s.lat])
                .setPopup(popup)
                .addTo(map);

            activeMarkers.push(marker);

            // Two-way interaction
            stopEl.addEventListener('mouseenter', () => {
                if (onStopHover) onStopHover(s.sequence, true);
            });
            stopEl.addEventListener('mouseleave', () => {
                if (onStopHover) onStopHover(s.sequence, false);
            });
            stopEl.addEventListener('click', () => {
                if (onStopClick) onStopClick(s.sequence);
            });
        });

        // 3. Finish Marker (Red Pin with Shadow)
        const finishEl = document.createElement('div');
        finishEl.className = 'custom-marker finish-marker';
        finishEl.innerHTML = '<div class="marker-dot red-dot"></div>';
        const finishMarker = new maplibregl.Marker({ element: finishEl })
            .setLngLat([summary.finish.lon, summary.finish.lat])
            .setPopup(new maplibregl.Popup({ offset: 15 }).setHTML(`<strong>Destination:</strong> ${summary.finish.label}`))
            .addTo(map);
        activeMarkers.push(finishMarker);
    }

    function clearLayersAndMarkers() {
        if (drawInAnimFrame) {
            cancelAnimationFrame(drawInAnimFrame);
            drawInAnimFrame = null;
        }
        activeMarkers.forEach((m) => m.remove());
        activeMarkers = [];

        if (map.getLayer('corridor-candidates-layer')) map.removeLayer('corridor-candidates-layer');
        if (map.getSource('corridor-candidates-source')) map.removeSource('corridor-candidates-source');
        if (map.getLayer('route-line')) map.removeLayer('route-line');
        if (map.getLayer('route-casing')) map.removeLayer('route-casing');
        if (map.getSource('route-source')) map.removeSource('route-source');
    }

    function flyToStop(sequence) {
        if (!currentPlanData) return;
        const stop = currentPlanData.fuel_stops.find((s) => s.sequence === sequence);
        if (stop) {
            map.flyTo({
                center: [stop.lon, stop.lat],
                zoom: 12.5,
                duration: 1400,
                essential: true,
            });
            const marker = activeMarkers.find((m) => {
                const el = m.getElement();
                return el && el.getAttribute('data-sequence') === String(sequence);
            });
            if (marker) marker.togglePopup();
        }
    }

    function highlightMarker(sequence, isHighlighted) {
        const el = document.getElementById(`map-marker-${sequence}`);
        if (el) {
            if (isHighlighted) {
                el.classList.add('active-highlight');
            } else {
                el.classList.remove('active-highlight');
            }
        }
    }

    return {
        map,
        renderRoute,
        flyToStop,
        highlightMarker,
    };
}
