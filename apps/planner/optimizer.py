"""Pure-Python fuel optimizer for long-haul trucking (no Django imports).

Greedy refueling along a fixed route: at each stop, buy only enough fuel to reach
the next cheaper station within range, or fill the tank when nothing cheaper is
reachable. A truck that starts empty fills at the origin, priced at the nearest
station. An optional consolidation pass ("practical" mode) merges small top-ups
into fewer stops for a small extra cost.
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
        self.gap_start_mile = gap_start_mile
        self.gap_end_mile = gap_end_mile
        gap_dist = round(gap_end_mile - gap_start_mile)
        if gap_start_mile == 0.0:
            msg = (
                f"Not enough fuel to reach the first station ({gap_dist} mi away). "
                "Increase starting fuel or choose another start."
            )
        else:
            msg = (
                f"Not enough fuel to bridge the route gap between mile {gap_start_mile:.1f} and "
                f"mile {gap_end_mile:.1f} ({gap_dist} mi gap exceeds vehicle range)."
            )
        super().__init__(msg)


@dataclass(frozen=True)
class Stop:
    """Candidate fuel station along the route."""

    mile: float
    price: float
    ref: Any = None
    is_origin: bool = False


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
    kind: str = "fuel_stop"


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
    """Compute the minimum-cost fuel purchase plan along the route with the greedy algorithm."""
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
        # Truck starts empty: must fuel at origin stop (mile 0.0)
        if not sorted_stops:
            raise NoFuelNearOrigin("No fuel station is reachable near route origin.")

        if sorted_stops[0].mile > 0.0:
            if sorted_stops[0].mile > r_max:
                raise NoFuelNearOrigin("No fuel station is reachable near route origin.")
            origin_stop = Stop(
                mile=0.0,
                price=sorted_stops[0].price,
                ref=sorted_stops[0].ref,
                is_origin=True,
            )
            sorted_stops = [origin_stop] + sorted_stops
        else:
            origin_stop = sorted_stops[0]

        current_idx = 0
        current_mile = 0.0
        current_price = origin_stop.price
        current_fuel = 0.0
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

        # Calculate reachable set (sorted_stops is sorted by mile, so break as soon as out of range)
        effective_range = current_fuel * mpg if current_idx == -1 else r_max
        max_reach_mile = current_mile + effective_range + epsilon
        reach_indices = []
        for j in range(current_idx + 1, n_stops):
            if sorted_stops[j].mile > max_reach_mile:
                break
            reach_indices.append(j)

        # Case 3: Can reach destination within R and no stop in reach is cheaper than current
        if current_idx >= 0 and rem_miles <= r_max + epsilon:
            has_cheaper = any(
                sorted_stops[j].price < current_price - epsilon for j in reach_indices
            )
            if not has_cheaper:
                gallons_needed = max(0.0, (rem_miles / mpg) - current_fuel)
                record = purchases.setdefault(
                    current_idx,
                    {"purchased": 0.0, "arrival": current_fuel, "departure": current_fuel},
                )
                record["purchased"] += gallons_needed
                record["departure"] += gallons_needed
                break

        # Case 4: There is a cheaper stop in reach -> travel to the NEAREST such stop
        cheaper_indices = [
            j for j in reach_indices if sorted_stops[j].price < current_price - epsilon
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

    purchased_items = sorted(purchases.items(), key=lambda item: sorted_stops[item[0]].mile)
    has_origin_fill = bool(
        purchased_items
        and sorted_stops[purchased_items[0][0]].mile == 0.0
        and (start_fuel <= 0.0 or getattr(sorted_stops[purchased_items[0][0]], "is_origin", False))
    )
    seq = 0 if has_origin_fill else 1

    for idx, p in purchased_items:
        bought = p["purchased"]
        if bought > 1e-6:
            st = sorted_stops[idx]
            price_dec = Decimal(str(round(st.price, 3))).quantize(Decimal("0.001"))
            stop_cost = (Decimal(str(bought)) * price_dec).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

            total_gallons += bought
            total_cost += stop_cost

            is_orig = (st.mile == 0.0 and getattr(st, "is_origin", False)) or (
                seq == 0 and st.mile == 0.0
            )
            stop_kind = "origin_fill" if is_orig else "fuel_stop"

            planned_stops.append(
                PlannedStop(
                    sequence=seq,
                    mile=round(st.mile, 2),
                    price_per_gallon=round(st.price, 3),
                    price_decimal=price_dec,
                    gallons_purchased=round(bought, 4),
                    cost_usd=stop_cost,
                    fuel_on_arrival_gallons=round(p["arrival"], 2),
                    fuel_on_departure_gallons=round(p["departure"], 2),
                    ref=st.ref,
                    kind=stop_kind,
                )
            )
            seq += 1

    return PlanResult(
        total_gallons=round(total_gallons, 4),
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
    """Consolidate minor/wasteful stops into fewer, practical refueling purchases.

    1. In practical mode, origin fill buys at least MIN_PURCHASE_GALLONS or enough
       to reach the next chosen stop, whichever is larger (capped at tank capacity).
    2. Merges stops buying < MIN_PURCHASE_GALLONS into neighbouring stops when feasible
       and cost increase is within STOP_PENALTY_USD per removed stop.
    3. Guarantees arrival/departure consistency and non-last purchase >= MIN_PURCHASE_GALLONS.
    """
    initial_plan = _greedy_optimize_fuel(
        stops=stops,
        total_miles=total_miles,
        tank_gal=tank_gal,
        mpg=mpg,
        start_fuel=start_fuel,
        origin_radius=origin_radius,
    )
    if not initial_plan.stops:
        return initial_plan

    # Working list of stop dictionaries
    st_list = [
        {
            "sequence": s.sequence,
            "mile": s.mile,
            "price_per_gallon": s.price_per_gallon,
            "price_decimal": s.price_decimal,
            "gallons_purchased": s.gallons_purchased,
            "fuel_on_arrival_gallons": s.fuel_on_arrival_gallons,
            "fuel_on_departure_gallons": s.fuel_on_departure_gallons,
            "ref": s.ref,
            "kind": s.kind,
        }
        for s in initial_plan.stops
    ]

    def recompute_flow(items: list[dict[str, Any]]) -> bool:
        """Recompute arrival and departure gallons strictly adhering to burn rates."""
        for idx in range(len(items)):
            if idx == 0:
                if start_fuel <= 0.0:
                    items[idx]["fuel_on_arrival_gallons"] = 0.0
                else:
                    burn_to_first = (items[0]["mile"] - 0.0) / mpg
                    items[idx]["fuel_on_arrival_gallons"] = round(start_fuel - burn_to_first, 4)
            else:
                dist = items[idx]["mile"] - items[idx - 1]["mile"]
                items[idx]["fuel_on_arrival_gallons"] = round(
                    items[idx - 1]["fuel_on_departure_gallons"] - (dist / mpg), 4
                )
            items[idx]["fuel_on_departure_gallons"] = round(
                items[idx]["fuel_on_arrival_gallons"] + items[idx]["gallons_purchased"], 4
            )
            if (
                items[idx]["fuel_on_arrival_gallons"] < -1e-4
                or items[idx]["fuel_on_departure_gallons"] > tank_gal + 1e-4
            ):
                return False
        dist_last = total_miles - items[-1]["mile"]
        if items[-1]["fuel_on_departure_gallons"] < (dist_last / mpg) - 1e-4:
            return False
        return True

    # 1. Enforce origin fill minimum purchase
    if st_list[0]["kind"] == "origin_fill" or (st_list[0]["mile"] == 0.0 and start_fuel <= 0.0):
        if len(st_list) > 1:
            dist_next = st_list[1]["mile"] - st_list[0]["mile"]
            min_needed = dist_next / mpg
            target_orig = min(tank_gal, max(min_purchase_gallons, min_needed))
        else:
            min_needed = total_miles / mpg
            target_orig = min(tank_gal, max(min_purchase_gallons, min_needed))

        if st_list[0]["gallons_purchased"] < target_orig:
            diff = target_orig - st_list[0]["gallons_purchased"]
            st_list[0]["gallons_purchased"] = target_orig
            st_list[0]["fuel_on_departure_gallons"] = (
                st_list[0]["fuel_on_arrival_gallons"] + target_orig
            )
            extra = diff
            for j in range(1, len(st_list)):
                st_list[j]["fuel_on_arrival_gallons"] += extra
                st_list[j]["fuel_on_departure_gallons"] += extra
                if st_list[j]["fuel_on_departure_gallons"] > tank_gal:
                    overflow = st_list[j]["fuel_on_departure_gallons"] - tank_gal
                    st_list[j]["gallons_purchased"] = max(
                        0.0, st_list[j]["gallons_purchased"] - overflow
                    )
                    st_list[j]["fuel_on_departure_gallons"] = tank_gal
                    extra = 0.0
                else:
                    reduce_amt = min(st_list[j]["gallons_purchased"], extra)
                    st_list[j]["gallons_purchased"] -= reduce_amt
                    st_list[j]["fuel_on_departure_gallons"] -= reduce_amt
                    extra -= reduce_amt
                if extra <= 1e-6:
                    break

    recompute_flow(st_list)

    # 2. Iteratively merge intermediate minor stops into neighbours
    while True:
        candidates = list(range(1, len(st_list) - 1))
        candidates.sort(
            key=lambda i: (
                st_list[i]["gallons_purchased"] >= min_purchase_gallons,
                st_list[i]["gallons_purchased"],
            )
        )

        merged_any = False
        for i in candidates:
            curr = st_list[i]
            prev_m = st_list[i - 1]["mile"]
            next_m = st_list[i + 1]["mile"]
            gap = next_m - prev_m

            # Can the truck reach next stop directly from previous stop?
            if gap <= (tank_gal * mpg) + 1e-6:
                test_items = [dict(s) for j, s in enumerate(st_list) if j != i]
                # Previous stop fills more if needed
                needed_dep_prev = min(
                    tank_gal, max(test_items[i - 1]["fuel_on_departure_gallons"], gap / mpg)
                )
                extra_prev = needed_dep_prev - test_items[i - 1]["fuel_on_departure_gallons"]
                test_items[i - 1]["gallons_purchased"] += extra_prev
                test_items[i - 1]["fuel_on_departure_gallons"] = needed_dep_prev

                fuel_arr_next = needed_dep_prev - (gap / mpg)
                if fuel_arr_next >= -1e-4:
                    needed_next = max(0.0, curr["gallons_purchased"] - extra_prev)
                    test_items[i]["gallons_purchased"] += needed_next
                    cost_old = curr["gallons_purchased"] * curr["price_per_gallon"]
                    cost_new = (
                        extra_prev * test_items[i - 1]["price_per_gallon"]
                        + needed_next * test_items[i]["price_per_gallon"]
                    )
                    d_cost = cost_new - cost_old

                    if d_cost < stop_penalty_usd and recompute_flow(test_items):
                        st_list = test_items
                        merged_any = True
                        break

        if not merged_any:
            break

    # 3. Ensure any remaining non-last stop buys at least min_purchase_gallons
    for i in range(len(st_list) - 1):
        if st_list[i]["gallons_purchased"] < min_purchase_gallons:
            shortfall = min(
                min_purchase_gallons - st_list[i]["gallons_purchased"],
                tank_gal - st_list[i]["fuel_on_departure_gallons"],
            )
            if shortfall > 1e-4:
                st_list[i]["gallons_purchased"] += shortfall
                st_list[i]["fuel_on_departure_gallons"] += shortfall
                extra = shortfall
                for j in range(i + 1, len(st_list)):
                    st_list[j]["fuel_on_arrival_gallons"] += extra
                    st_list[j]["fuel_on_departure_gallons"] += extra
                    if st_list[j]["fuel_on_departure_gallons"] > tank_gal:
                        overflow = st_list[j]["fuel_on_departure_gallons"] - tank_gal
                        st_list[j]["gallons_purchased"] = max(
                            0.0, st_list[j]["gallons_purchased"] - overflow
                        )
                        st_list[j]["fuel_on_departure_gallons"] = tank_gal
                        extra = 0.0
                    else:
                        red = min(st_list[j]["gallons_purchased"], extra)
                        st_list[j]["gallons_purchased"] -= red
                        st_list[j]["fuel_on_departure_gallons"] -= red
                        extra -= red
                    if extra <= 1e-6:
                        break

    recompute_flow(st_list)

    # Rebuild PlannedStop results
    final_stops: list[PlannedStop] = []
    tot_gal = 0.0
    tot_cost = Decimal("0.00")
    has_orig = st_list[0]["kind"] == "origin_fill" or (
        st_list[0]["mile"] == 0.0 and start_fuel <= 0.0
    )
    seq = 0 if has_orig else 1

    for s in st_list:
        bought = round(s["gallons_purchased"], 4)
        if bought > 1e-6:
            p_dec = Decimal(str(round(s["price_per_gallon"], 3))).quantize(Decimal("0.001"))
            s_cost = (Decimal(str(bought)) * p_dec).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            tot_gal += bought
            tot_cost += s_cost
            final_stops.append(
                PlannedStop(
                    sequence=seq,
                    mile=round(s["mile"], 2),
                    price_per_gallon=round(s["price_per_gallon"], 3),
                    price_decimal=p_dec,
                    gallons_purchased=bought,
                    cost_usd=s_cost,
                    fuel_on_arrival_gallons=round(s["fuel_on_arrival_gallons"], 2),
                    fuel_on_departure_gallons=round(s["fuel_on_departure_gallons"], 2),
                    ref=s["ref"],
                    kind="origin_fill" if (seq == 0 and s["mile"] == 0.0) else "fuel_stop",
                )
            )
            seq += 1

    return PlanResult(
        total_gallons=round(tot_gal, 4),
        total_cost_usd=tot_cost,
        stops=final_stops,
        start_fuel_gallons=start_fuel,
        tank_gallons=tank_gal,
        mpg=mpg,
    )


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
