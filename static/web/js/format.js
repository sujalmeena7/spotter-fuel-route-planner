/**
 * Formatting and utility helpers for FuelRoute.
 */

const CURRENCY_FMT = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
});

const NUMBER_FMT = new Intl.NumberFormat('en-US', {
    maximumFractionDigits: 1,
});

export function formatMoney(val) {
    const num = typeof val === 'number' ? val : parseFloat(val);
    return isNaN(num) ? '$0.00' : CURRENCY_FMT.format(num);
}

export function formatPrice(val) {
    const num = typeof val === 'number' ? val : parseFloat(val);
    return isNaN(num) ? '$0.000' : `$${num.toFixed(3)}`;
}

export function formatMiles(val) {
    const num = typeof val === 'number' ? val : parseFloat(val);
    return isNaN(num) ? '0 mi' : `${NUMBER_FMT.format(num)} mi`;
}

export function formatGallons(val) {
    const num = typeof val === 'number' ? val : parseFloat(val);
    return isNaN(num) ? '0 gal' : `${NUMBER_FMT.format(num)} gal`;
}

export function formatHours(val) {
    const num = typeof val === 'number' ? val : parseFloat(val);
    if (isNaN(num)) return '0h';
    const totalMinutes = Math.round(num * 60);
    const hrs = Math.floor(totalMinutes / 60);
    const mins = totalMinutes % 60;
    return mins > 0 ? `${hrs}h ${mins}m` : `${hrs}h`;
}

/**
 * Categorize station price into low (green), mid (amber), high (red) tier relative to corridor min/max.
 */
export function getPriceTier(price, minPrice, maxPrice) {
    if (maxPrice <= minPrice) return { class: 'tier-low', label: 'Cheapest' };
    const ratio = (price - minPrice) / (maxPrice - minPrice);
    if (ratio <= 0.33) {
        return { class: 'tier-low', label: 'Low price', color: '#16A34A' };
    }
    if (ratio <= 0.66) {
        return { class: 'tier-mid', label: 'Average', color: '#D97706' };
    }
    return { class: 'tier-high', label: 'High price', color: '#DC2626' };
}
