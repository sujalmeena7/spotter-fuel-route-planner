"""Thread-safe in-memory index of geocoded stations for sub-millisecond querying."""

import threading
from decimal import Decimal

import numpy as np

from apps.routing.geometry import lat_lon_to_unit_vectors
from apps.stations.models import Station


class StationIndex:
    """In-memory numpy-backed index of all geocoded retail fuel stations."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self.ids: np.ndarray = np.array([], dtype=np.int32)
        self.lats: np.ndarray = np.array([], dtype=np.float64)
        self.lons: np.ndarray = np.array([], dtype=np.float64)
        self.prices: np.ndarray = np.array([], dtype=np.float64)
        self.prices_decimal: list[Decimal] = []
        self.unit_vectors: np.ndarray = np.empty((0, 3), dtype=np.float64)

        self.names: list[str] = []
        self.addresses: list[str] = []
        self.cities: list[str] = []
        self.states: list[str] = []
        self.rack_ids: list[int] = []

        self._loaded = False

    @classmethod
    def get_instance(cls) -> "StationIndex":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = cls()
                    instance.load()
                    cls._instance = instance
        return cls._instance

    @classmethod
    def refresh(cls) -> "StationIndex":
        """Force reload station data from DB."""
        with cls._lock:
            instance = cls()
            instance.load()
            cls._instance = instance
            return cls._instance

    def load(self) -> None:
        """Load stations from database into vectorized contiguous numpy arrays."""
        qs = (
            Station.objects.filter(lat__isnull=False, lon__isnull=False)
            .order_by("opis_id")
            .values(
                "opis_id",
                "name",
                "address",
                "city",
                "state",
                "rack_id",
                "price",
                "lat",
                "lon",
            )
        )

        stations = list(qs)
        n = len(stations)
        if n == 0:
            self._loaded = True
            return

        self.ids = np.empty(n, dtype=np.int32)
        self.lats = np.empty(n, dtype=np.float64)
        self.lons = np.empty(n, dtype=np.float64)
        self.prices = np.empty(n, dtype=np.float64)
        self.prices_decimal = []
        self.names = []
        self.addresses = []
        self.cities = []
        self.states = []
        self.rack_ids = []

        for i, s in enumerate(stations):
            self.ids[i] = s["opis_id"]
            self.lats[i] = s["lat"]
            self.lons[i] = s["lon"]
            self.prices[i] = float(s["price"])
            self.prices_decimal.append(s["price"])
            self.names.append(s["name"])
            self.addresses.append(s["address"])
            self.cities.append(s["city"])
            self.states.append(s["state"])
            self.rack_ids.append(s["rack_id"])

        # Precompute 3D unit vectors on unit sphere
        self.unit_vectors = lat_lon_to_unit_vectors(self.lats, self.lons)
        self._loaded = True

    def __len__(self) -> int:
        return len(self.ids)
