"""Census Gazetteer index and city name normalization."""

import csv
import re
import threading
import unicodedata
from pathlib import Path
from typing import Any

from django.conf import settings

# Suffixes to strip during normalization
SUFFIX_PATTERN = re.compile(
    r"\s*\b(city|town|village|borough|cdp|municipality|township|ccd|urban county|metropolitan government|balance)\b\s*$",
    re.IGNORECASE,
)


def is_hawaii(lat: float, lon: float) -> bool:
    """Check if coordinates fall within Hawaii bounding box."""
    return (18.5 <= lat <= 29.0) and (-161.5 <= lon <= -154.0)


def is_alaska(lat: float, lon: float) -> bool:
    """Check if coordinates fall within Alaska bounding box."""
    return (51.0 <= lat <= 72.0) and ((-180.0 <= lon <= -129.0) or (170.0 <= lon <= 180.0))


def is_within_usa(lat: float, lon: float) -> bool:
    """Validate that coordinates fall within US bounding boxes (Lower 48, AK, HI)."""
    # Lower 48 + DC
    if (24.0 <= lat <= 50.0) and (-125.5 <= lon <= -66.5):
        return True
    if is_alaska(lat, lon) or is_hawaii(lat, lon):
        return True
    return False


def normalize_city_name(name: str) -> str:
    """Normalize a city/place name for gazetteer lookup.

    Expands common abbreviations (st, ft, mt, mc), replaces hyphens with spaces,
    removes punctuation, collapses whitespace. Preserves multi-word city names.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    # Replace hyphens and slashes with space
    s = re.sub(r"[-/]", " ", s)
    # Expand cardinal directions at start if followed by word
    s = re.sub(r"^(s\.|s)\s+", "south ", s)
    s = re.sub(r"^(n\.|n)\s+", "north ", s)
    s = re.sub(r"^(e\.|e)\s+", "east ", s)
    s = re.sub(r"^(w\.|w)\s+", "west ", s)
    # Expand saint, fort, mount
    s = re.sub(r"\b(st\.|st|ste\.|ste|sainte)\b", "saint", s)
    s = re.sub(r"\b(ft\.|ft)\b", "fort", s)
    s = re.sub(r"\b(mt\.|mt)\b", "mount", s)
    # Join Mc names (e.g. 'mc dermitt' -> 'mcdermitt')
    s = re.sub(r"\bmc\s+", "mc", s)
    # Remove non-alphanumeric except space
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return " ".join(s.split())


CITY_ALIASES = {
    ("honolulu", "HI"): "urban honolulu",
    ("boise", "ID"): "boise city",
    ("amite", "LA"): "amite city",
    ("moapa", "NV"): "moapa town",
    ("bridgewater", "MA"): "bridgewater town",
}


class GazetteerIndex:
    """In-memory index of Census Gazetteer places and county subdivisions."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self, csv_path: Path | None = None):
        self.csv_path = csv_path or (settings.BASE_DIR / "data" / "gazetteer_places_trimmed.csv")
        self.places: dict[tuple[str, str], tuple[float, float, int]] = {}
        self.cousubs: dict[tuple[str, str], tuple[float, float, int]] = {}
        # List of records for autocomplete: (display_label, norm_name, state, lat, lon, aland)
        self.autocomplete_records: list[dict[str, Any]] = []
        self._loaded = False

    @classmethod
    def get_instance(cls, csv_path: Path | None = None) -> "GazetteerIndex":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = cls(csv_path)
                    instance.load()
                    cls._instance = instance
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        with cls._lock:
            cls._instance = None

    def load(self) -> None:
        """Load trimmed gazetteer CSV into memory."""
        if self._loaded or not self.csv_path.exists():
            return

        with open(self.csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row["name"].strip()
                state = row["state"].strip().upper()
                lat = float(row["lat"])
                lon = float(row["lon"])
                if not is_within_usa(lat, lon):
                    continue
                aland = int(float(row.get("aland", 0)))
                kind = row.get("kind", "place")

                s_name = re.sub(r"\s*\(balance\)\s*$", "", name, flags=re.IGNORECASE).strip()
                clean_name = SUFFIX_PATTERN.sub("", s_name).strip()
                norm_clean = normalize_city_name(clean_name)
                norm_raw = normalize_city_name(name)

                target_dict = self.places if kind == "place" else self.cousubs
                for norm_key in ((norm_clean, state), (norm_raw, state)):
                    if norm_key not in target_dict or aland > target_dict[norm_key][2]:
                        target_dict[norm_key] = (lat, lon, aland)

                if kind == "place":
                    display_label = f"{clean_name}, {state}"
                    self.autocomplete_records.append(
                        {
                            "label": display_label,
                            "city": clean_name,
                            "norm_city": norm_clean,
                            "state": state,
                            "lat": round(lat, 5),
                            "lon": round(lon, 5),
                            "aland": aland,
                        }
                    )

        self._loaded = True

    def lookup(self, city: str, state: str) -> tuple[float, float, str] | None:
        """Look up coordinates for city and state.

        Returns (lat, lon, 'gazetteer_place' | 'gazetteer_cousub') or None.
        """
        if not self._loaded:
            self.load()

        st_u = state.upper().strip()
        norm_c = normalize_city_name(city)
        norm_c = CITY_ALIASES.get((norm_c, st_u), norm_c)
        clean_c = normalize_city_name(SUFFIX_PATTERN.sub("", city).strip())

        # 1. Places: direct normalized match, then suffix-stripped
        for k in ((norm_c, st_u), (clean_c, st_u)):
            if k in self.places:
                lat, lon, _ = self.places[k]
                if is_within_usa(lat, lon):
                    return lat, lon, "gazetteer_place"

        # 2. Cousubs: direct normalized match, then suffix-stripped
        for k in ((norm_c, st_u), (clean_c, st_u)):
            if k in self.cousubs:
                lat, lon, _ = self.cousubs[k]
                if is_within_usa(lat, lon):
                    return lat, lon, "gazetteer_cousub"

        return None

    def search_autocomplete(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Search cities offline for autocomplete, ranked by exact prefix first, then ALAND.

        Makes 0 external calls.
        """
        if not self._loaded:
            self.load()

        q = query.strip().lower()
        if not q:
            return []

        # Split query by comma if searching 'City, ST'
        q_parts = [p.strip() for p in q.split(",", 1)]
        q_city = q_parts[0]
        q_state = q_parts[1].upper() if len(q_parts) > 1 else ""

        prefix_matches = []
        contains_matches = []
        seen_labels = set()

        for rec in self.autocomplete_records:
            label = rec["label"]
            if label in seen_labels:
                continue

            city_lower = rec["city"].lower()
            state_upper = rec["state"]

            if q_state and not state_upper.startswith(q_state):
                continue

            if city_lower.startswith(q_city) or label.lower().startswith(q):
                prefix_matches.append(rec)
                seen_labels.add(label)
            elif q_city in city_lower:
                contains_matches.append(rec)
                seen_labels.add(label)

        # Rank: largest ALAND (city size) within each bucket
        prefix_matches.sort(key=lambda x: x["aland"], reverse=True)
        contains_matches.sort(key=lambda x: x["aland"], reverse=True)

        results = prefix_matches + contains_matches
        return [{"label": r["label"], "lat": r["lat"], "lon": r["lon"]} for r in results[:limit]]
