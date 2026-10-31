"""Pure-Python fuel optimizer for long-haul trucking (no Django imports).

Implements Section 4.3 greedy refueling algorithm with configurable tank, MPG,
origin approach logic, and practical stop consolidation.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


class OptimizerError(Exception):
    """Base exception for fuel optimizer errors."""


class NoFuelNearOrigin(OptimizerError):
    """Raised when truck starts empty and no station is reachable near origin."""


class Unreachable(OptimizerError):
    """Raised when distance between consecutive reachable stations exceeds range."""

    def __init__(self, gap_start_mile: float, gap_end_mile: float):
        super().__init__(
            f"Unreachable route gap from mile {gap_start_mile:.1f} to {gap_end_mile:.1f}."
        )
        self.gap_start_mile = gap_start_mile
        self.gap_end_mile = gap_end_mile


@dataclass(frozen=True)
class Stop:
    """Candidate fuel station along the route."""

    mile: float
    price: float
    ref: Any = None


@dataclass
class PlannedStop:
    """A scheduled fuel stop in the optimal itinerary."""

    sequence: int
    mile: float
    price_per_gallon: float
    price_decimal: Decimal
    gallons_purchased: float
    cost_usd: Decimal
    fuel_on_arrival_gallons: float
    fuel_on_departure_gallons: float
    ref: Any = None


@dataclass
class PlanResult:
    """Optimal route fuel plan result."""

    total_gallons: float
    total_cost_usd: Decimal
    stops: list[PlannedStop]
    start_fuel_gallons: float
    tank_gallons: float
    mpg: float


def _greedy_optimize_fuel(
    stops: list[Stop],
    total_miles: float,
    tank_gal: float = 50.0,
    mpg: float = 10.0,
    start_fuel: float = 0.0,
    origin_radius: float = 25.0,
) -> PlanResult:
    """Compute optimal fuel purchase plan along route using pure greedy algorithm per Section 4.3."""
    if total_miles <= 0:
        return PlanResult(
            total_gallons=0.0,
            total_cost_usd=Decimal("0.00"),
            stops=[],
            start_fuel_gallons=start_fuel,
            tank_gallons=tank_gal,
            mpg=mpg,
        )

    r_max = tank_gal * mpg

    # Filter and sort stops by mile marker
    sorted_stops = sorted(
        [s for s in stops if 0.0 <= s.mile <= total_miles],
        key=lambda s: s.mile,
    )

    # 1. Origin handling
    current_idx: int
    current_mile: float
    current_price: float
    current_fuel: float

    # Track purchases keyed by stop index in sorted_stops:
    # index -> {"purchased": float, "arrival": float, "departure": float}
    purchases: dict[int, dict[str, float]] = {}

    if start_fuel <= 0.0:
        # Truck starts empty: must fuel at origin stop
        origin_candidates = [s for s in sorted_stops if s.mile <= origin_radius]
        if origin_candidates:
            origin_stop = min(origin_candidates, key=lambda s: s.price)
        elif sorted_stops and sorted_stops[0].mile <= r_max:
            origin_stop = sorted_stops[0]
        else:
            raise NoFuelNearOrigin("No fuel station is reachable near route origin.")

        current_idx = sorted_stops.index(origin_stop)
        current_mile = origin_stop.mile
        current_price = origin_stop.price

        # Approach fuel burned reaching origin stop is billed at origin price
        approach_gallons = current_mile / mpg
        current_fuel = 0.0

        purchases[current_idx] = {
            "purchased": approach_gallons,
            "arrival": 0.0,
            "departure": approach_gallons,
        }
    else:
        # Truck starts with initial fuel at virtual origin
        if total_miles <= start_fuel * mpg + 1e-9:
            # Initial fuel alone covers the whole trip
            return PlanResult(
                total_gallons=0.0,
                total_cost_usd=Decimal("0.00"),
                stops=[],
                start_fuel_gallons=start_fuel,
                tank_gallons=tank_gal,
                mpg=mpg,
            )

        current_idx = -1  # virtual start stop
        current_mile = 0.0
        current_price = float("inf")
        current_fuel = min(start_fuel, tank_gal)

    # 2. Greedy refueling loop
    n_stops = len(sorted_stops)
    epsilon = 1e-9

    while True:
        # If destination is reachable with current fuel: done
        rem_miles = total_miles - current_mile
        if rem_miles <= current_fuel * mpg + epsilon:
            break

        # Calculate reachable set
        effective_range = current_fuel * mpg if current_idx == -1 else r_max
        reach_indices = [
            j
            for j in range(current_idx + 1, n_stops)
            if sorted_stops[j].mile - current_mile <= effective_range + epsilon
        ]

        # Case 3: Can reach destination within R and no stop in reach is cheaper than current
        if rem_miles <= r_max + epsilon:
            has_cheaper = any(
                sorted_stops[j].price < current_price - epsilon for j in reach_indices
            )
            if not has_cheaper:
                gallons_needed = max(0.0, (rem_miles / mpg) - current_fuel)
                if current_idx >= 0:
                    record = purchases.setdefault(
                        current_idx,
                        {"purchased": 0.0, "arrival": current_fuel, "departure": current_fuel},
                    )
                    record["purchased"] += gallons_needed
                    record["departure"] += gallons_needed
                break

        # Case 4: There is a cheaper stop in reach -> travel to the NEAREST such stop
        cheaper_indices = [
            j
            for j in range(current_idx + 1, n_stops)
            if sorted_stops[j].mile - current_mile <= effective_range + epsilon
            and sorted_stops[j].price < current_price - epsilon
        ]

        if cheaper_indices:
            next_idx = cheaper_indices[0]  # Nearest cheaper stop
            next_stop = sorted_stops[next_idx]
            dist = next_stop.mile - current_mile
            gallons_needed = dist / mpg
            gallons_to_buy = max(0.0, gallons_needed - current_fuel)

            if current_idx >= 0:
                record = purchases.setdefault(
                    current_idx,
                    {"purchased": 0.0, "arrival": current_fuel, "departure": current_fuel},
                )
                record["purchased"] += gallons_to_buy
                record["departure"] += gallons_to_buy

            arrival_fuel = (current_fuel + gallons_to_buy) - gallons_needed
            current_idx = next_idx
            current_mile = next_stop.mile
            current_price = next_stop.price
            current_fuel = max(0.0, arrival_fuel)
            continue

        # Case 5: No cheaper stop in reach
        if not reach_indices:
            # Gap exceeds vehicle range
            next_unreachable_mile = (
                sorted_stops[current_idx + 1].mile if current_idx + 1 < n_stops else total_miles
            )
            raise Unreachable(current_mile, next_unreachable_mile)

        # Fill to tank_gal and travel to the CHEAPEST stop in reach (ties to farther stop)
        min_reach_price = min(sorted_stops[j].price for j in reach_indices)
        tied_cheapest = [
            j for j in reach_indices if abs(sorted_stops[j].price - min_reach_price) < epsilon
        ]
        next_idx = tied_cheapest[-1]  # Farther stop on ties
        next_stop = sorted_stops[next_idx]

        gallons_to_buy = max(0.0, tank_gal - current_fuel)
        if current_idx >= 0:
            record = purchases.setdefault(
                current_idx,
                {"purchased": 0.0, "arrival": current_fuel, "departure": current_fuel},
            )
            record["purchased"] += gallons_to_buy
            record["departure"] = tank_gal

        dist = next_stop.mile - current_mile
        arrival_fuel = tank_gal - (dist / mpg)

        current_idx = next_idx
        current_mile = next_stop.mile
        current_price = next_stop.price
        current_fuel = max(0.0, arrival_fuel)

    # 3. Construct results, dropping stops with 0 gallons purchased
    planned_stops: list[PlannedStop] = []
    total_gallons = 0.0
    total_cost = Decimal("0.00")
    seq = 1

    for idx, p in sorted(purchases.items(), key=lambda item: sorted_stops[item[0]].mile):
        bought = p["purchased"]
        if bought > 1e-6:
            st = sorted_stops[idx]
            price_dec = Decimal(str(round(st.price, 3))).quantize(Decimal("0.001"))
            stop_cost = (Decimal(str(bought)) * price_dec).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            total_gallons += bought
            total_cost += stop_cost

            planned_stops.append(
                PlannedStop(
                    sequence=seq,
                    mile=round(st.mile, 2),
                    price_per_gallon=round(st.price, 3),
                    price_decimal=price_dec,
                    gallons_purchased=round(bought, 2),
                    cost_usd=stop_cost,
                    fuel_on_arrival_gallons=round(p["arrival"], 2),
                    fuel_on_departure_gallons=round(p["departure"], 2),
                    ref=st.ref,
                )
            )
            seq += 1

    return PlanResult(
        total_gallons=round(total_gallons, 2),
        total_cost_usd=total_cost,
        stops=planned_stops,
        start_fuel_gallons=start_fuel,
        tank_gallons=tank_gal,
        mpg=mpg,
    )


def consolidate_stops(
    stops: list[Stop],
    total_miles: float,
    tank_gal: float = 50.0,
    mpg: float = 10.0,
    start_fuel: float = 0.0,
    origin_radius: float = 25.0,
    min_purchase_gallons: float = 10.0,
    stop_penalty_usd: float = 5.0,
    cluster_radius_miles: float = 2.0,
) -> PlanResult:
    """Consolidate minor/wasteful stops into fewer, larger refueling purchases.

    Iteratively attempts to exclude stops buying less than MIN_PURCHASE_GALLONS
    (or prunable stops) if the route remains feasible and the total cost increases
    by less than STOP_PENALTY_USD per eliminated stop.
    """
    current_plan = _greedy_optimize_fuel(
        stops=stops,
        total_miles=total_miles,
        tank_gal=tank_gal,
        mpg=mpg,
        start_fuel=start_fuel,
        origin_radius=origin_radius,
    )
    if not current_plan.stops:
        return current_plan

    curr_stops = list(stops)

    while True:
        # Eligible candidates for consolidation (exclude origin stop if truck starts empty)
        candidates = [
            s for s in current_plan.stops if not (start_fuel <= 0.0 and s.mile <= origin_radius)
        ]
        # Evaluate small purchases (< min_purchase_gallons) first, sorted ascending by purchase
        candidates = sorted(
            candidates,
            key=lambda s: (s.gallons_purchased >= min_purchase_gallons, s.gallons_purchased),
        )

        improved = False
        for ps in candidates:
            # First try excluding just this station
            test_stops = [
                s
                for s in curr_stops
                if not (
                    abs(s.mile - ps.mile) < 1e-4
                    and abs(s.price - ps.price_per_gallon) < 1e-4
                    and (ps.ref is None or s.ref == ps.ref)
                )
            ]
            try:
                cand_plan = _greedy_optimize_fuel(
                    stops=test_stops,
                    total_miles=total_miles,
                    tank_gal=tank_gal,
                    mpg=mpg,
                    start_fuel=start_fuel,
                    origin_radius=origin_radius,
                )
            except OptimizerError:
                continue

            delta_stops = len(current_plan.stops) - len(cand_plan.stops)
            delta_cost = float(cand_plan.total_cost_usd - current_plan.total_cost_usd)

            # If stop count didn't drop because another station at the same interchange/cluster was picked,
            # try excluding all stations within the cluster radius.
            if delta_stops == 0 and any(
                abs(ns.mile - ps.mile) <= cluster_radius_miles for ns in cand_plan.stops
            ):
                test_stops_cluster = [
                    s for s in curr_stops if abs(s.mile - ps.mile) > cluster_radius_miles
                ]
                try:
                    cand_plan_cluster = _greedy_optimize_fuel(
                        stops=test_stops_cluster,
                        total_miles=total_miles,
                        tank_gal=tank_gal,
                        mpg=mpg,
                        start_fuel=start_fuel,
                        origin_radius=origin_radius,
                    )
                    d_stops_cl = len(current_plan.stops) - len(cand_plan_cluster.stops)
                    d_cost_cl = float(
                        cand_plan_cluster.total_cost_usd - current_plan.total_cost_usd
                    )
                    if d_stops_cl >= 1 and d_cost_cl < stop_penalty_usd * d_stops_cl:
                        current_plan = cand_plan_cluster
                        curr_stops = test_stops_cluster
                        improved = True
                        break
                except OptimizerError:
                    pass
            elif delta_stops >= 1 and delta_cost < stop_penalty_usd * delta_stops:
                current_plan = cand_plan
                curr_stops = test_stops
                improved = True
                break

        if not improved:
            break

    return current_plan


def optimize_fuel(
    stops: list[Stop],
    total_miles: float,
    tank_gal: float = 50.0,
    mpg: float = 10.0,
    start_fuel: float = 0.0,
    origin_radius: float = 25.0,
    optimize_for: str = "practical",
    min_purchase_gallons: float = 10.0,
    stop_penalty_usd: float = 5.0,
) -> PlanResult:
    """Compute optimal fuel purchase plan along route.

    Args:
        stops: Candidate fuel stations along route corridor.
        total_miles: Total route distance in miles.
        tank_gal: Truck fuel tank capacity in gallons (default: 50.0).
        mpg: Truck miles per gallon (default: 10.0).
        start_fuel: Fuel gallons in tank at trip origin (default: 0.0).
        origin_radius: Radius in miles near origin to search for initial fuel stop.
        optimize_for: Strategy - "cost" (pure mathematical greedy) or "practical"
            (consolidates minor stops with configurable penalty). Default is "practical".
        min_purchase_gallons: Minimum threshold below which a stop is considered minor.
        stop_penalty_usd: Maximum acceptable cost increase per eliminated stop.
    """
    if optimize_for == "cost":
        return _greedy_optimize_fuel(
            stops=stops,
            total_miles=total_miles,
            tank_gal=tank_gal,
            mpg=mpg,
            start_fuel=start_fuel,
            origin_radius=origin_radius,
        )

    return consolidate_stops(
        stops=stops,
        total_miles=total_miles,
        tank_gal=tank_gal,
        mpg=mpg,
        start_fuel=start_fuel,
        origin_radius=origin_radius,
        min_purchase_gallons=min_purchase_gallons,
        stop_penalty_usd=stop_penalty_usd,
    )
