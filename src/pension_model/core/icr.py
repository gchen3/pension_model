"""
Interest Crediting Rate (ICR) computation for cash balance plans.

Provides:
  - compute_expected_icr: Monte Carlo expected ICR (single scalar)
  - compute_actual_icr_series: Year-indexed actual ICR from return scenario
  - smooth_return: Floor + upside participation formula

Matches R's expected_icr_rcpp() and actual_icr_table construction
from TxTRS_R_BModel revised.R and utility_functions.R.
"""

import numpy as np
import pandas as pd


def _geo_return(returns: np.ndarray) -> float:
    """Geometric mean return: prod(1 + r)^(1/n) - 1."""
    return np.prod(1.0 + returns) ** (1.0 / len(returns)) - 1.0


def smooth_return(returns: np.ndarray, floor: float, cap: float,
                  upside_share: float) -> float:
    """Smoothed ICR: floor + upside_share * max(0, geo_return - floor), capped.

    Formula: min(cap, max(floor, floor + upside_share * (geo_return - floor)))
    Matches R's smooth_return().
    """
    g = _geo_return(returns)
    return min(cap, max(floor, floor + upside_share * (g - floor)))


def _est_arith_return(geo_return: float, sd: float) -> float:
    """Estimate arithmetic return from geometric return and standard deviation.

    R's est_arith_return: arith = (1 + geo) * exp(sd^2 / 2) - 1
    Approximation: arith ≈ geo + sd^2 / 2
    """
    return (1 + geo_return) * np.exp(sd ** 2 / 2) - 1


def compute_expected_icr(
    geometric_return: float,
    sd_return: float,
    smooth_period: int,
    floor: float,
    cap: float,
    upside_share: float,
    n_periods: int = 30,
    n_simulations: int = 10000,
    seed: int = 1234,
) -> float:
    """Monte Carlo expected ICR. Matches R's expected_icr_rcpp().

    Simulates investment returns, applies rolling smooth_return,
    computes geometric average of smoothed returns, returns median.

    Args:
        geometric_return: Expected geometric investment return.
        sd_return: Standard deviation of annual returns.
        smooth_period: Rolling window for ICR smoothing.
        floor: Minimum ICR.
        cap: Maximum ICR.
        upside_share: Fraction of upside shared with members.
        n_periods: Number of years to simulate.
        n_simulations: Number of Monte Carlo paths.
        seed: Random seed for reproducibility.

    Returns:
        Expected ICR as a single float.
    """
    rng = np.random.default_rng(seed)
    mean_return = _est_arith_return(geometric_return, sd_return)

    # Simulate returns: n_periods × n_simulations
    simulated = rng.normal(mean_return, sd_return, (n_periods, n_simulations))

    # Prepend (smooth_period - 1) initial periods at floor
    initial = np.full((smooth_period - 1, n_simulations), floor)
    returns_matrix = np.vstack([initial, simulated])

    # Apply rolling smooth_return over each column
    total_rows = returns_matrix.shape[0]
    smooth_rows = total_rows - smooth_period + 1
    smoothed = np.zeros((smooth_rows, n_simulations))
    for i in range(smooth_rows):
        window = returns_matrix[i:i + smooth_period, :]
        for j in range(n_simulations):
            smoothed[i, j] = smooth_return(window[:, j], floor, cap, upside_share)

    # Geometric average of smoothed returns for each simulation
    avg_rates = np.zeros(n_simulations)
    for j in range(n_simulations):
        avg_rates[j] = _geo_return(smoothed[:, j])

    return float(np.median(avg_rates))


def compute_actual_icr_series(
    years: range,
    start_year: int,
    return_scenario: pd.Series,
    smooth_period: int,
    floor: float,
    cap: float,
    upside_share: float,
) -> pd.Series:
    """Compute year-indexed actual ICR series from return scenario.

    Matches R's actual_icr_table construction:
      - Pre-start_year: investment return = floor (no data)
      - Post-start_year: from return_scenario, with NA → dr_current
      - Apply rolling smooth_return over smooth_period window

    Args:
        years: Full year range (e.g., range(1980, 2155)).
        start_year: First year with actual/projected returns.
        return_scenario: Year → investment return (may have gaps).
        smooth_period: Rolling window for smoothing.
        floor: ICR floor.
        cap: ICR cap.
        upside_share: Upside sharing fraction.

    Returns:
        pd.Series indexed by year with actual ICR values.
    """
    year_list = list(years)
    inv_returns = np.full(len(year_list), floor)

    for i, yr in enumerate(year_list):
        if yr <= start_year:
            inv_returns[i] = floor
        elif yr in return_scenario.index:
            inv_returns[i] = return_scenario[yr]
        else:
            # Default to floor when no scenario data
            inv_returns[i] = floor

    # Apply rolling smooth_return
    actual_icr = np.full(len(year_list), floor)
    for i in range(len(year_list)):
        if i < smooth_period - 1:
            actual_icr[i] = floor
        else:
            window = inv_returns[i - smooth_period + 1:i + 1]
            actual_icr[i] = smooth_return(window, floor, cap, upside_share)

    return pd.Series(actual_icr, index=year_list)
