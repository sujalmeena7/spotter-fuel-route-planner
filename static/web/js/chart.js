/**
 * Pure SVG Sawtooth Fuel-Level Profile Chart.
 * Displays fuel gallons (Y-axis 0..50) against trip miles (X-axis 0..total_miles).
 */

export function renderFuelChart(container, planData) {
    if (!container || !planData || !planData.summary) {
        if (container) container.innerHTML = '';
        return;
    }

    const summary = planData.summary;
    const stops = planData.fuel_stops || [];
    const totalMiles = summary.distance_miles;
    const tankCapacity = 50.0;
    const mpg = 10.0;

    if (totalMiles <= 0) {
        container.innerHTML = '';
        return;
    }

    // Chart dimensions
    const width = 360;
    const height = 140;
    const padLeft = 34;
    const padRight = 14;
    const padTop = 16;
    const padBottom = 26;

    const plotW = width - padLeft - padRight;
    const plotH = height - padTop - padBottom;

    const scaleX = (mile) => padLeft + (mile / totalMiles) * plotW;
    const scaleY = (gal) => padTop + plotH - (Math.max(0, Math.min(gal, tankCapacity)) / tankCapacity) * plotH;

    // Build sawtooth trajectory points
    // Array of { mile, fuel, isPurchase, stopRef }
    const points = [];
    const startFuel = planData.start_fuel_gallons !== undefined ? planData.start_fuel_gallons : 0.0;

    if (stops.length === 0) {
        // Direct trip without stops
        points.push({ mile: 0, fuel: startFuel });
        const endFuel = Math.max(0, startFuel - (totalMiles / mpg));
        points.push({ mile: totalMiles, fuel: endFuel });
    } else {
        // Starts at origin
        let currentMile = 0.0;
        let currentFuel = startFuel;
        points.push({ mile: 0, fuel: currentFuel });

        stops.forEach((s) => {
            // Slope down to arrival fuel at stop
            points.push({ mile: s.mile_marker, fuel: s.fuel_on_arrival_gallons });
            // Vertical jump to departure fuel
            points.push({
                mile: s.mile_marker,
                fuel: s.fuel_on_departure_gallons,
                isStop: true,
                sequence: s.sequence,
                purchased: s.gallons_purchased,
                name: s.name,
            });
            currentMile = s.mile_marker;
            currentFuel = s.fuel_on_departure_gallons;
        });

        // Final slope to destination
        const finishFuel = Math.max(0, currentFuel - ((totalMiles - currentMile) / mpg));
        points.push({ mile: totalMiles, fuel: finishFuel });
    }

    // SVG path strings
    let pathD = `M ${scaleX(points[0].mile)} ${scaleY(points[0].fuel)}`;
    for (let i = 1; i < points.length; i++) {
        pathD += ` L ${scaleX(points[i].mile)} ${scaleY(points[i].fuel)}`;
    }

    const areaD = `${pathD} L ${scaleX(totalMiles)} ${scaleY(0)} L ${scaleX(0)} ${scaleY(0)} Z`;

    // Stop markers on chart
    const stopDots = points
        .filter((p) => p.isStop)
        .map(
            (p) => `
        <circle cx="${scaleX(p.mile)}" cy="${scaleY(p.fuel)}" r="4" 
                class="chart-stop-dot" data-sequence="${p.sequence}"
                fill="#2563EB" stroke="#ffffff" stroke-width="2"/>
    `
        )
        .join('');

    container.innerHTML = `
        <div class="chart-header">
            <span class="chart-title">Fuel Level Profile</span>
            <span class="chart-subtitle">Sawtooth Refueling Trajectory (50 gal tank)</span>
        </div>
        <div class="chart-svg-wrap">
            <svg viewBox="0 0 ${width} ${height}" class="fuel-chart-svg" aria-label="Fuel level sawtooth chart">
                <defs>
                    <linearGradient id="fuelAreaGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#3B82F6" stop-opacity="0.32" />
                        <stop offset="100%" stop-color="#3B82F6" stop-opacity="0.02" />
                    </linearGradient>
                </defs>
                <!-- Grid Lines -->
                <line x1="${padLeft}" y1="${scaleY(0)}" x2="${width - padRight}" y2="${scaleY(0)}" stroke="var(--border)" stroke-width="1"/>
                <line x1="${padLeft}" y1="${scaleY(25)}" x2="${width - padRight}" y2="${scaleY(25)}" stroke="var(--border)" stroke-width="1" stroke-dasharray="3 3"/>
                <line x1="${padLeft}" y1="${scaleY(50)}" x2="${width - padRight}" y2="${scaleY(50)}" stroke="var(--border)" stroke-width="1"/>

                <!-- Y-Axis Labels -->
                <text x="${padLeft - 6}" y="${scaleY(50) + 4}" class="chart-axis-label" text-anchor="end">50g</text>
                <text x="${padLeft - 6}" y="${scaleY(25) + 4}" class="chart-axis-label" text-anchor="end">25g</text>
                <text x="${padLeft - 6}" y="${scaleY(0) + 4}" class="chart-axis-label" text-anchor="end">0g</text>

                <!-- X-Axis Labels -->
                <text x="${padLeft}" y="${height - 6}" class="chart-axis-label" text-anchor="start">0 mi</text>
                <text x="${width - padRight}" y="${height - 6}" class="chart-axis-label" text-anchor="end">${Math.round(totalMiles)} mi</text>

                <!-- Area & Line -->
                <path d="${areaD}" fill="url(#fuelAreaGrad)"/>
                <path d="${pathD}" fill="none" stroke="#2563EB" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>

                <!-- Fuel Stop Dots -->
                ${stopDots}

                <!-- Crosshair Group (dynamic hover) -->
                <g class="chart-crosshair" style="display: none;">
                    <line class="crosshair-line" y1="${padTop}" y2="${height - padBottom}" stroke="#94A3B8" stroke-width="1" stroke-dasharray="2 2"/>
                    <circle class="crosshair-point" r="3.5" fill="#2563EB" stroke="#ffffff" stroke-width="1.5"/>
                </g>
            </svg>
            <div class="chart-tooltip" style="display: none;"></div>
        </div>
    `;

    // Interactive crosshair & tooltip
    const svg = container.querySelector('.fuel-chart-svg');
    const tooltip = container.querySelector('.chart-tooltip');
    const crosshair = container.querySelector('.chart-crosshair');
    const crosshairLine = container.querySelector('.crosshair-line');
    const crosshairPoint = container.querySelector('.crosshair-point');

    svg.addEventListener('mousemove', (e) => {
        const rect = svg.getBoundingClientRect();
        const svgX = ((e.clientX - rect.left) / rect.width) * width;
        if (svgX < padLeft || svgX > width - padRight) {
            crosshair.style.display = 'none';
            tooltip.style.display = 'none';
            return;
        }

        const mileRatio = (svgX - padLeft) / plotW;
        const currentM = mileRatio * totalMiles;

        // Find fuel level at currentM along points trajectory
        let estimatedFuel = 0.0;
        for (let i = 0; i < points.length - 1; i++) {
            const p1 = points[i];
            const p2 = points[i + 1];
            if (currentM >= p1.mile && currentM <= p2.mile) {
                if (Math.abs(p2.mile - p1.mile) < 1e-4) {
                    estimatedFuel = p2.fuel;
                } else {
                    const t = (currentM - p1.mile) / (p2.mile - p1.mile);
                    estimatedFuel = p1.fuel + t * (p2.fuel - p1.fuel);
                }
                break;
            }
        }

        const plotX = scaleX(currentM);
        const plotY = scaleY(estimatedFuel);

        crosshair.style.display = 'block';
        crosshairLine.setAttribute('x1', plotX);
        crosshairLine.setAttribute('x2', plotX);
        crosshairPoint.setAttribute('cx', plotX);
        crosshairPoint.setAttribute('cy', plotY);

        tooltip.style.display = 'block';
        tooltip.style.left = `${(plotX / width) * 100}%`;
        tooltip.style.top = `${(plotY / height) * 100}%`;
        tooltip.innerHTML = `<strong>Mile ${Math.round(currentM)}</strong> · ${estimatedFuel.toFixed(1)} gal`;
    });

    svg.addEventListener('mouseleave', () => {
        crosshair.style.display = 'none';
        tooltip.style.display = 'none';
    });
}
