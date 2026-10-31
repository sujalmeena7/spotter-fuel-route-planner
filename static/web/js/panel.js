/**
 * Panel and Bottom-Sheet UX controller for FuelRoute.
 */

import { formatGallons, formatHours, formatMiles, formatMoney, formatPrice, getPriceTier } from './format.js';
import { renderFuelChart } from './chart.js';

export function setupPanel({
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
    onPlanSubmit,
    onStopHover,
    onStopClick,
}) {
    // 1. Starting fuel slider sync
    function updateFuelSlider() {
        const val = parseFloat(fuelSlider.value);
        let label = `${val} gal · ${Math.round(val * 10)} mi`;
        if (val === 0) label = 'Empty (0 gal)';
        else if (val === 50) label = 'Full (50 gal · 500 mi)';
        fuelGaugeLabel.textContent = label;
    }
    fuelSlider.addEventListener('input', updateFuelSlider);
    updateFuelSlider();

    // 2. Origin/Destination swap with 180deg rotation
    let rotation = 0;
    swapBtn.addEventListener('click', () => {
        rotation += 180;
        swapBtn.style.transform = `rotate(${rotation}deg)`;
        const temp = originInput.value;
        originInput.value = destInput.value;
        destInput.value = temp;
        if (originInput.value && destInput.value) {
            formEl.dispatchEvent(new Event('submit'));
        }
    });

    // 3. Form submission
    formEl.addEventListener('submit', (e) => {
        e.preventDefault();
        const start = originInput.value.trim();
        const finish = destInput.value.trim();
        const startFuel = parseFloat(fuelSlider.value);

        if (!start) {
            originInput.focus();
            showError('Please enter an origin location.');
            return;
        }
        if (!finish) {
            destInput.focus();
            showError('Please enter a destination location.');
            return;
        }

        clearError();
        if (onPlanSubmit) {
            onPlanSubmit({ start, finish, start_fuel_gallons: startFuel });
        }
    });

    // 4. Example chips click handling
    document.querySelectorAll('.example-chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            const start = chip.getAttribute('data-start');
            const finish = chip.getAttribute('data-finish');
            originInput.value = start;
            destInput.value = finish;
            formEl.dispatchEvent(new Event('submit'));
        });
    });

    // 4b. Collapsible route input summary handling
    const summaryBar = document.getElementById('route-summary-bar');
    const editBtn = document.getElementById('btn-edit-route');
    const inputCard = document.querySelector('.route-input-card');
    const exampleChips = document.querySelector('.example-chips-wrap');

    function toggleInputCollapse() {
        if (!inputCard) return;
        const isCollapsed = inputCard.classList.toggle('collapsed');
        if (exampleChips) {
            exampleChips.style.display = isCollapsed ? 'none' : 'block';
        }
        if (editBtn) {
            editBtn.textContent = isCollapsed ? 'Edit' : 'Done';
        }
    }

    if (editBtn) {
        editBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleInputCollapse();
        });
    }
    if (summaryBar) {
        summaryBar.addEventListener('click', toggleInputCollapse);
    }

    // 5. Loading skeletons & progress bar
    function setLoading(isLoading) {
        if (isLoading) {
            progressBar.classList.add('active');
            formEl.querySelector('button[type="submit"]').classList.add('loading');
            renderSkeletons();
        } else {
            progressBar.classList.remove('active');
            formEl.querySelector('button[type="submit"]').classList.remove('loading');
        }
    }

    function renderSkeletons() {
        kpiSection.innerHTML = `
            <div class="kpi-grid">
                <div class="kpi-card hero skeleton" style="height: 90px;"></div>
                <div class="kpi-card savings skeleton" style="height: 70px;"></div>
                <div class="kpi-card skeleton" style="height: 60px;"></div>
                <div class="kpi-card skeleton" style="height: 60px;"></div>
                <div class="kpi-card skeleton" style="height: 60px;"></div>
                <div class="kpi-card skeleton" style="height: 60px;"></div>
            </div>
        `;
        timelineSection.innerHTML = `
            <div class="timeline-skeleton">
                <div class="card skeleton" style="height: 75px; margin-bottom: 12px;"></div>
                <div class="card skeleton" style="height: 75px; margin-bottom: 12px;"></div>
            </div>
        `;
        chartSection.innerHTML = '';
        perfBadge.style.display = 'none';
    }

    // 6. Error handling
    function showError(msg) {
        errorBanner.textContent = msg;
        errorBanner.style.display = 'block';
    }

    function clearError() {
        errorBanner.textContent = '';
        errorBanner.style.display = 'none';
    }

    // 7. Render Route Results
    function renderResults(planData) {
        clearError();
        const { summary, fuel_stops: stops, meta, map_url } = planData;

        // Route Summary Bar (collapsed on mobile when results load)
        const summaryText = document.getElementById('route-summary-text');
        if (summaryBar && summaryText && inputCard) {
            summaryText.textContent = `${summary.start.label} → ${summary.finish.label}`;
            summaryBar.style.display = 'flex';
            if (window.innerWidth <= 900) {
                inputCard.classList.add('collapsed');
                if (exampleChips) exampleChips.style.display = 'none';
                if (editBtn) editBtn.textContent = 'Edit';
            }
        }

        // Performance badge
        if (meta) {
            const localMs = meta.local_compute_ms ?? (meta.timing ? meta.timing.local_compute_ms : meta.compute_ms) ?? 0;
            const routingMs = meta.routing_ms ?? (meta.timing ? meta.timing.routing_ms : 0) ?? 0;
            const calls = meta.external_api_calls ?? 0;
            const callsText = meta.cache_hit
                ? 'cached · 0 calls'
                : `${calls} call${calls === 1 ? '' : 's'}`;
            perfBadge.textContent = `⚡ ${localMs} ms compute · ${routingMs} ms routing · ${callsText}`;
            perfBadge.style.display = 'inline-flex';
        }

        // Animate counter helper
        const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        function animateCounter(el, target, isCurrency = true, decimals = 2) {
            if (prefersReducedMotion) {
                el.textContent = isCurrency ? formatMoney(target) : target.toFixed(decimals);
                return;
            }
            const duration = 700;
            const startVal = 0;
            const startTime = performance.now();

            function tick(now) {
                const elapsed = now - startTime;
                const progress = Math.min(elapsed / duration, 1);
                // easeOutQuad
                const ease = 1 - (1 - progress) * (1 - progress);
                const current = startVal + (target - startVal) * ease;
                el.textContent = isCurrency ? formatMoney(current) : current.toFixed(decimals);
                if (progress < 1) {
                    requestAnimationFrame(tick);
                }
            }
            requestAnimationFrame(tick);
        }

        // Render KPI Grid
        const totalCostNum = parseFloat(summary.total_fuel_cost_usd);
        const savingsNum = parseFloat(summary.savings_usd);

        kpiSection.innerHTML = `
            <div class="kpi-grid">
                <div class="kpi-card hero">
                    <span class="kpi-label">Total Fuel Cost</span>
                    <span class="kpi-value hero-cost" id="kpi-total-cost">$0.00</span>
                    <span class="kpi-meta">${summary.fuel_stops} stop${summary.fuel_stops === 1 ? '' : 's'} · ${summary.total_gallons.toFixed(1)} gal total</span>
                </div>
                <div class="kpi-card savings">
                    <span class="kpi-label">Corridor Savings</span>
                    <span class="kpi-value savings-val" id="kpi-savings">$0.00</span>
                    <span class="kpi-sub">vs. corridor average ($${summary.baseline_cost_usd})</span>
                </div>
                <div class="kpi-card">
                    <span class="kpi-label">Distance</span>
                    <span class="kpi-value">${formatMiles(summary.distance_miles)}</span>
                </div>
                <div class="kpi-card">
                    <span class="kpi-label">Drive Time</span>
                    <span class="kpi-value">${formatHours(summary.duration_hours)}</span>
                </div>
                <div class="kpi-card">
                    <span class="kpi-label">Avg $/Gal</span>
                    <span class="kpi-value">${formatPrice(summary.avg_price_per_gallon)}</span>
                </div>
                <div class="kpi-card">
                    <span class="kpi-label">Cost / Mile</span>
                    <span class="kpi-value">${formatPrice(summary.cost_per_mile_usd)}</span>
                </div>
            </div>
        `;

        animateCounter(document.getElementById('kpi-total-cost'), totalCostNum, true);
        animateCounter(document.getElementById('kpi-savings'), savingsNum, true);

        // Render Sawtooth Fuel Chart
        renderFuelChart(chartSection, planData);

        // Render Itinerary Timeline
        const prices = stops.map((s) => parseFloat(s.price_per_gallon));
        const minPrice = prices.length ? Math.min(...prices) : 3.0;
        const maxPrice = prices.length ? Math.max(...prices) : 4.0;

        const warningsHtml = (meta.warnings && meta.warnings.length) ? `
            <div class="warning-banner" style="background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.35); border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 12px; color: var(--color-warning, #d97706); display: flex; align-items: center; gap: 8px;">
                <span>⚠️</span>
                <span>${meta.warnings.join(' · ')}</span>
            </div>
        ` : '';

        let timelineHtml = `
            ${warningsHtml}
            <div class="itinerary-header">
                <h3>Trip Itinerary</h3>
                <span class="badge-stops">${stops.length} Refueling Stop${stops.length === 1 ? '' : 's'}</span>
            </div>
            <div class="timeline-stepper">
                <!-- Start Waypoint -->
                <div class="timeline-step start">
                    <div class="step-marker-col">
                        <div class="step-dot start-dot"></div>
                        <div class="step-line"></div>
                    </div>
                    <div class="step-card origin-card">
                        <div class="step-title-row">
                            <span class="step-name">Trip Origin</span>
                            <span class="step-mile">Mile 0.0</span>
                        </div>
                        <div class="step-address">${summary.start.label}</div>
                    </div>
                </div>
        `;

        let lastMile = 0.0;
        stops.forEach((s) => {
            const distFromLast = Math.round(s.mile_marker - lastMile);
            const tier = getPriceTier(parseFloat(s.price_per_gallon), minPrice, maxPrice);
            const isOriginFill = s.kind === 'origin_fill' || s.sequence === 0;

            timelineHtml += `
                <!-- Inter-stop Distance Indicator -->
                ${distFromLast > 0 ? `
                <div class="timeline-gap">
                    <span class="gap-label">— ${distFromLast} miles —</span>
                </div>` : ''}

                <!-- Stop Card -->
                <div class="timeline-step ${isOriginFill ? 'origin-fill-step' : 'fuel-stop-step'}" id="timeline-stop-${s.sequence}" data-sequence="${s.sequence}">
                    <div class="step-marker-col">
                        <div class="stop-badge ${isOriginFill ? 'origin-badge' : tier.class}">${s.sequence}</div>
                        <div class="step-line"></div>
                    </div>
                    <div class="step-card stop-card ${isOriginFill ? 'origin-fill-card' : ''}">
                        <div class="step-title-row">
                            <span class="step-name">${isOriginFill ? `⛽ ${s.name}` : s.name}</span>
                            <span class="price-chip ${tier.class}">${formatPrice(s.price_per_gallon)} · ${tier.label}</span>
                        </div>
                        <div class="step-address">${s.address ? s.address + ', ' : ''}${s.city}, ${s.state}</div>
                        
                        <div class="stop-metrics-row">
                            <span class="metric-item"><strong>Mile:</strong> ${s.mile_marker.toFixed(1)}</span>
                            <span class="metric-item"><strong>Off-route:</strong> ${s.off_route_miles.toFixed(1)} mi</span>
                            <span class="metric-item"><strong>Purchase:</strong> ${s.gallons_purchased.toFixed(1)} gal</span>
                            <span class="metric-item cost"><strong>Cost:</strong> ${formatMoney(s.cost_usd)}</span>
                        </div>

                        <!-- Mini Fuel Level Progression Bar -->
                        <div class="mini-fuel-bar-wrap">
                            <div class="fuel-labels">
                                <span>Arr: ${s.fuel_on_arrival_gallons.toFixed(1)}g</span>
                                <span>Dep: ${s.fuel_on_departure_gallons.toFixed(1)}g</span>
                            </div>
                            <div class="fuel-track">
                                <div class="fuel-fill" style="left: ${(s.fuel_on_arrival_gallons / 50) * 100}%; width: ${(s.gallons_purchased / 50) * 100}%;"></div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            lastMile = s.mile_marker;
        });

        const finalDist = Math.round(summary.distance_miles - lastMile);
        timelineHtml += `
                <!-- Final Gap to Destination -->
                <div class="timeline-gap">
                    <span class="gap-label">— ${finalDist} miles —</span>
                </div>

                <!-- Destination Waypoint -->
                <div class="timeline-step finish">
                    <div class="step-marker-col">
                        <div class="step-dot finish-dot"></div>
                    </div>
                    <div class="step-card dest-card">
                        <div class="step-title-row">
                            <span class="step-name">Trip Destination</span>
                            <span class="step-mile">Mile ${summary.distance_miles.toFixed(1)}</span>
                        </div>
                        <div class="step-address">${summary.finish.label}</div>
                    </div>
                </div>
            </div>

            <!-- Action Buttons -->
            <div class="action-footer">
                <button type="button" class="btn btn-secondary action-share" id="btn-share-link">
                    🔗 Copy Share Link
                </button>
                <button type="button" class="btn btn-secondary action-geojson" id="btn-download-geojson">
                    📥 Download GeoJSON
                </button>
                <a href="/api/docs/" target="_blank" class="btn btn-secondary action-swagger">
                    📖 Swagger Docs
                </a>
            </div>
            <div id="toast" class="toast"></div>
        `;

        timelineSection.innerHTML = timelineHtml;

        // Wire Action Buttons
        const toastEl = document.getElementById('toast');
        function showToast(msg) {
            toastEl.textContent = msg;
            toastEl.classList.add('show');
            setTimeout(() => toastEl.classList.remove('show'), 2500);
        }

        document.getElementById('btn-share-link').addEventListener('click', () => {
            navigator.clipboard.writeText(window.location.href);
            showToast('Share link copied to clipboard!');
        });

        document.getElementById('btn-download-geojson').addEventListener('click', () => {
            const blob = new Blob([JSON.stringify(planData.route, null, 2)], {
                type: 'application/json',
            });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `fuel_route_${summary.start.label}_to_${summary.finish.label}.geojson`;
            a.click();
            URL.revokeObjectURL(url);
            showToast('GeoJSON downloaded!');
        });

        // Two-way interaction listeners on stop cards
        document.querySelectorAll('.fuel-stop-step').forEach((el) => {
            const seq = parseInt(el.getAttribute('data-sequence'), 10);
            el.addEventListener('mouseenter', () => {
                if (onStopHover) onStopHover(seq, true);
            });
            el.addEventListener('mouseleave', () => {
                if (onStopHover) onStopHover(seq, false);
            });
            el.addEventListener('click', () => {
                if (onStopClick) onStopClick(seq);
            });
        });
    }

    // 8. Mobile Bottom-Sheet Gesture Implementation (Pointer events, 3 snap points)
    setupBottomSheet(panelEl);

    return {
        setLoading,
        showError,
        clearError,
        renderResults,
        highlightTimelineStop: (seq, isHighlighted) => {
            const el = document.getElementById(`timeline-stop-${seq}`);
            if (el) {
                if (isHighlighted) {
                    el.classList.add('highlighted');
                    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                } else {
                    el.classList.remove('highlighted');
                }
            }
        },
    };
}

/**
 * Mobile Bottom Sheet drag controller with 3 snap points (peek, half, full).
 */
function setupBottomSheet(sheetEl) {
    let startY = 0;
    let currentY = 0;
    let isDragging = false;
    const handleEl = sheetEl.querySelector('.drag-handle');
    if (!handleEl) return;

    // Snap heights: peek (18vh), half (50vh), full (90vh)
    const getSnapHeights = () => {
        const vh = window.innerHeight;
        return {
            peek: vh * 0.20,
            half: vh * 0.52,
            full: vh * 0.90,
        };
    };

    function setSheetHeight(heightPx, animate = true) {
        if (animate) {
            sheetEl.style.transition = 'height 250ms cubic-bezier(0.16, 1, 0.3, 1)';
        } else {
            sheetEl.style.transition = 'none';
        }
        sheetEl.style.height = `${heightPx}px`;
    }

    handleEl.addEventListener('pointerdown', (e) => {
        if (window.innerWidth >= 1024) return;
        isDragging = true;
        startY = e.clientY;
        currentY = sheetEl.getBoundingClientRect().height;
        handleEl.setPointerCapture(e.pointerId);
    });

    handleEl.addEventListener('pointermove', (e) => {
        if (!isDragging) return;
        const delta = startY - e.clientY;
        const newHeight = Math.max(120, currentY + delta);
        setSheetHeight(newHeight, false);
    });

    handleEl.addEventListener('pointerup', (e) => {
        if (!isDragging) return;
        isDragging = false;
        handleEl.releasePointerCapture(e.pointerId);

        const currentHeight = sheetEl.getBoundingClientRect().height;
        const snaps = getSnapHeights();

        // Find closest snap point
        const diffPeek = Math.abs(currentHeight - snaps.peek);
        const diffHalf = Math.abs(currentHeight - snaps.half);
        const diffFull = Math.abs(currentHeight - snaps.full);

        if (diffPeek <= diffHalf && diffPeek <= diffFull) {
            setSheetHeight(snaps.peek, true);
        } else if (diffHalf <= diffPeek && diffHalf <= diffFull) {
            setSheetHeight(snaps.half, true);
        } else {
            setSheetHeight(snaps.full, true);
        }
    });
}
