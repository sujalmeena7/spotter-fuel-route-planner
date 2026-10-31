"""Dynamic Programming reference solver for verifying greedy fuel optimizer."""

from apps.planner.optimizer import Stop


def solve_dp(
    stops: list[Stop],
    total_miles: float,
    tank_gal: int = 50,
    mpg: int = 10,
) -> float:
    """Exact dynamic programming solver on integer-gallon grid.

    State: (station_index, fuel_gal in 0..tank_gal).
    Minimizes total cost with whole-gallon buy decisions.
    """
    n = len(stops)
    dist_finish = int(round((total_miles - stops[-1].mile) / mpg))

    # dp[i][g]: min cost to finish from stop i with arrival fuel g
    dp: list[dict[int, float]] = [{} for _ in range(n)]

    # Base case: last stop
    for g in range(tank_gal + 1):
        if g >= dist_finish:
            dp[-1][g] = 0.0
        elif dist_finish - g <= tank_gal - g:
            dp[-1][g] = (dist_finish - g) * stops[-1].price
        else:
            dp[-1][g] = float("inf")

    # Transitions backwards from second-to-last to first stop
    for i in range(n - 2, -1, -1):
        d_next = int(round((stops[i + 1].mile - stops[i].mile) / mpg))
        for g in range(tank_gal + 1):
            min_c = float("inf")
            for b in range(tank_gal - g + 1):
                f_dep = g + b
                if f_dep >= d_next:
                    f_arr_next = f_dep - d_next
                    c = b * stops[i].price + dp[i + 1][f_arr_next]
                    if c < min_c:
                        min_c = c
            dp[i][g] = min_c

    approach_g = int(round(stops[0].mile / mpg))
    return approach_g * stops[0].price + dp[0][0]
