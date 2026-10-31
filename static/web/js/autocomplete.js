/**
 * Accessible location autocomplete component.
 */

import { fetchAutocomplete } from './api.js';

export function setupAutocomplete(inputEl, dropdownEl, onSelect) {
    let debounceTimer = null;
    let selectedIndex = -1;
    let currentResults = [];

    function closeDropdown() {
        dropdownEl.innerHTML = '';
        dropdownEl.classList.remove('active');
        inputEl.setAttribute('aria-expanded', 'false');
        selectedIndex = -1;
        currentResults = [];
    }

    function renderDropdown(items, query) {
        currentResults = items;
        selectedIndex = -1;
        if (!items || items.length === 0) {
            closeDropdown();
            return;
        }

        const qLower = query.toLowerCase();
        const html = items
            .map((item, idx) => {
                const label = item.label;
                const matchIndex = label.toLowerCase().indexOf(qLower);
                let highlighted = label;
                if (matchIndex >= 0) {
                    const before = label.slice(0, matchIndex);
                    const matched = label.slice(matchIndex, matchIndex + qLower.length);
                    const after = label.slice(matchIndex + qLower.length);
                    highlighted = `${before}<strong>${matched}</strong>${after}`;
                }
                return `
                <div class="autocomplete-item" role="option" id="auto-opt-${idx}" data-index="${idx}" tabindex="-1">
                    <span class="auto-pin">📍</span>
                    <span class="auto-label">${highlighted}</span>
                </div>
            `;
            })
            .join('');

        dropdownEl.innerHTML = html;
        dropdownEl.classList.add('active');
        inputEl.setAttribute('aria-expanded', 'true');

        // Item click listeners
        dropdownEl.querySelectorAll('.autocomplete-item').forEach((el) => {
            el.addEventListener('mousedown', (e) => {
                e.preventDefault();
                const idx = parseInt(el.getAttribute('data-index'), 10);
                selectItem(idx);
            });
        });
    }

    function selectItem(idx) {
        if (idx >= 0 && idx < currentResults.length) {
            const item = currentResults[idx];
            inputEl.value = item.label;
            closeDropdown();
            if (onSelect) onSelect(item);
        }
    }

    function highlightItem(newIdx) {
        const items = dropdownEl.querySelectorAll('.autocomplete-item');
        items.forEach((el, i) => {
            if (i === newIdx) {
                el.classList.add('selected');
                el.scrollIntoView({ block: 'nearest' });
                inputEl.setAttribute('aria-activedescendant', el.id);
            } else {
                el.classList.remove('selected');
            }
        });
        selectedIndex = newIdx;
    }

    inputEl.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        const query = inputEl.value.trim();
        if (query.length < 2) {
            closeDropdown();
            return;
        }

        debounceTimer = setTimeout(async () => {
            try {
                const items = await fetchAutocomplete(query, 8);
                renderDropdown(items, query);
            } catch (err) {
                console.error('Autocomplete error:', err);
                closeDropdown();
            }
        }, 150);
    });

    inputEl.addEventListener('keydown', (e) => {
        if (!dropdownEl.classList.contains('active')) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            const nextIdx = (selectedIndex + 1) % currentResults.length;
            highlightItem(nextIdx);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            const prevIdx = (selectedIndex - 1 + currentResults.length) % currentResults.length;
            highlightItem(prevIdx);
        } else if (e.key === 'Enter') {
            if (selectedIndex >= 0) {
                e.preventDefault();
                selectItem(selectedIndex);
            }
        } else if (e.key === 'Escape') {
            e.preventDefault();
            closeDropdown();
        }
    });

    inputEl.addEventListener('blur', () => {
        // Small delay to permit click events on dropdown items
        setTimeout(closeDropdown, 200);
    });
}
