/**
 * Main application coordinator for FuelRoute web application.
 */

import { fetchRoutePlan } from './api.js';
import { setupAutocomplete } from './autocomplete.js';
import { setupMap } from './map.js';
import { setupPanel } from './panel.js';

document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const panelEl = document.getElementById('floating-panel');
    const formEl = document.getElementById('route-form');
    const originInput = document.getElementById('input-origin');
    const destInput = document.getElementById('input-dest');
    const originDropdown = document.getElementById('dropdown-origin');
    const destDropdown = document.getElementById('dropdown-dest');
    const fuelSlider = document.getElementById('input-fuel');
    const fuelGaugeLabel = document.getElementById('fuel-gauge-label');
    const swapBtn = document.getElementById('btn-swap');
    const kpiSection = document.getElementById('section-kpis');
    const timelineSection = document.getElementById('section-timeline');
    const chartSection = document.getElementById('section-chart');
    const perfBadge = document.getElementById('perf-badge');
    const progressBar = document.getElementById('panel-progress');
    const errorBanner = document.getElementById('error-banner');
    const themeToggleBtn = document.getElementById('btn-theme-toggle');
    const corridorToggleBtn = document.getElementById('btn-corridor-toggle');

    // 1. Initialize Autocomplete
    setupAutocomplete(originInput, originDropdown);
    setupAutocomplete(destInput, destDropdown);

    // 2. Initialize Map
    let panelController;
    const mapController = setupMap({
        containerId: 'map-container',
        themeToggleBtn,
        corridorToggleBtn,
        onStopHover: (seq, isHovered) => {
            if (panelController) panelController.highlightTimelineStop(seq, isHovered);
        },
        onStopClick: (seq) => {
            if (panelController) panelController.highlightTimelineStop(seq, true);
        },
    });

    // 3. Plan submission handler
    async function executePlan({ start, finish, start_fuel_gallons }) {
        panelController.setLoading(true);

        // Update URL state seamlessly
        const url = new URL(window.location);
        url.searchParams.set('start', start);
        url.searchParams.set('finish', finish);
        url.searchParams.set('fuel', String(start_fuel_gallons));
        window.history.replaceState({}, '', url);

        try {
            const data = await fetchRoutePlan({
                start,
                finish,
                start_fuel_gallons,
                include_candidates: true,
            });
            panelController.renderResults(data);
            mapController.renderRoute(data, true);
        } catch (err) {
            console.error('Plan error:', err);
            panelController.showError(err.message || 'Failed to calculate route.');
        } finally {
            panelController.setLoading(false);
        }
    }

    // 4. Initialize Panel Controller
    panelController = setupPanel({
        panelEl,
        formEl,
        originInput,
        destInput,
        fuelSlider,
        fuelGaugeLabel,
        swapBtn,
        kpiSection,
        timelineSection,
        chartSection,
        perfBadge,
        progressBar,
        errorBanner,
        onPlanSubmit: executePlan,
        onStopHover: (seq, isHovered) => {
            mapController.highlightMarker(seq, isHovered);
        },
        onStopClick: (seq) => {
            mapController.flyToStop(seq);
        },
    });

    // 5. Read Initial URL Query Parameters (Auto-plan on load)
    const params = new URLSearchParams(window.location.search);
    const initialStart = params.get('start');
    const initialFinish = params.get('finish');
    const initialFuel = params.get('fuel');

    if (initialFuel !== null) {
        fuelSlider.value = initialFuel;
        fuelSlider.dispatchEvent(new Event('input'));
    }

    if (initialStart && initialFinish) {
        originInput.value = initialStart;
        destInput.value = initialFinish;
        // Wait for map style to be ready before firing initial plan
        if (mapController.map.loaded()) {
            executePlan({
                start: initialStart,
                finish: initialFinish,
                start_fuel_gallons: parseFloat(fuelSlider.value),
            });
        } else {
            mapController.map.once('load', () => {
                executePlan({
                    start: initialStart,
                    finish: initialFinish,
                    start_fuel_gallons: parseFloat(fuelSlider.value),
                });
            });
        }
    }
});
