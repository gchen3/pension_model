"""
Compact mortality table.

Instead of the R model's 3M-row cross-product table, store mortality as:
  - Base rates by (age, status) from pub-2010 tables (~200 rows)
  - Improvement scale by (age, year) from MP-2018 (~10K rows)
  - Final rate computed on demand: q(age, year, status)

For the initial implementation, we extract the compact form from R's
pre-computed 3M-row table. Later, we'll build directly from the raw
Excel mortality tables.
"""

import numpy as np
import pandas as pd
from pathlib import Path


class CompactMortality:
    """
    Compact mortality lookup: q(age, year, status) without materialization.

    Status is either 'employee' (active/vested/non-vested) or 'retiree' (norm/early).
    Stores only unique (age, year) → rate mappings (~24K rows for 2 statuses).
    """

    def __init__(self, employee_rates: pd.DataFrame, retiree_rates: pd.DataFrame):
        """
        Args:
            employee_rates: DataFrame with columns (dist_age, dist_year, mort_final)
            retiree_rates: DataFrame with columns (dist_age, dist_year, mort_final)
        """
        # Index for O(1) lookup
        self._emp = employee_rates.set_index(["dist_age", "dist_year"])["mort_final"]
        self._ret = retiree_rates.set_index(["dist_age", "dist_year"])["mort_final"]

        self.min_age = int(employee_rates["dist_age"].min())
        self.max_age = int(employee_rates["dist_age"].max())
        self.min_year = int(employee_rates["dist_year"].min())
        self.max_year = int(employee_rates["dist_year"].max())

        # Also store as 2D arrays for fast vectorized access
        ages = range(self.min_age, self.max_age + 1)
        years = range(self.min_year, self.max_year + 1)
        n_ages = len(ages)
        n_years = len(years)

        self._emp_grid = np.zeros((n_ages, n_years))
        self._ret_grid = np.zeros((n_ages, n_years))

        for i, a in enumerate(ages):
            for j, y in enumerate(years):
                key = (a, y)
                self._emp_grid[i, j] = self._emp.get(key, 0.0)
                self._ret_grid[i, j] = self._ret.get(key, 0.0)

        self._age_offset = self.min_age
        self._year_offset = self.min_year

    def get_rate(self, age: int, year: int, is_retiree: bool = False) -> float:
        """Get mortality rate for a single (age, year, status)."""
        grid = self._ret_grid if is_retiree else self._emp_grid
        ai = age - self._age_offset
        yi = year - self._year_offset
        if 0 <= ai < grid.shape[0] and 0 <= yi < grid.shape[1]:
            return grid[ai, yi]
        return 0.0

    def get_rates_vec(self, ages: np.ndarray, years: np.ndarray,
                      is_retiree: bool = False) -> np.ndarray:
        """Get mortality rates for vectors of (age, year)."""
        grid = self._ret_grid if is_retiree else self._emp_grid
        ai = ages - self._age_offset
        yi = years - self._year_offset
        # Clip to valid range
        ai = np.clip(ai, 0, grid.shape[0] - 1)
        yi = np.clip(yi, 0, grid.shape[1] - 1)
        return grid[ai, yi]

    def get_survival_discount(self, start_age: int, start_year: int,
                              end_age: int, dr: float,
                              is_retiree: bool = False) -> np.ndarray:
        """
        Compute cumulative survival × discount from start_age to end_age.

        Returns array of length (end_age - start_age + 1) where:
          result[0] = 1.0 (at start_age)
          result[k] = prod(1 - q[start..start+k-1]) / (1+dr)^k

        This is the key building block for PVFB, annuity factors, etc.
        """
        n = end_age - start_age + 1
        if n <= 0:
            return np.array([1.0])

        ages = np.arange(start_age, end_age + 1)
        years = np.arange(start_year, start_year + n)
        # Clip years to available range
        years = np.clip(years, self.min_year, self.max_year)

        mort = self.get_rates_vec(ages, years, is_retiree)

        # cum_mort_dr[0] = 1, cum_mort_dr[k] = prod(1-q[j]) / prod(1+dr) for j=0..k-1
        surv = np.cumprod(np.concatenate([[1.0], 1 - mort[:-1]]))
        disc = (1 + dr) ** np.arange(n)
        return surv / disc


def extract_compact_mortality(mort_table_path: Path, class_name: str) -> CompactMortality:
    """
    Extract compact mortality from R's pre-computed 3M-row table.

    Reduces to ~24K rows by keeping only unique (age, year, status) rates.
    """
    mort = pd.read_csv(mort_table_path)

    # Split by retirement status
    mort["is_retired"] = mort["tier_at_dist_age"].str.contains("norm|early")

    employee = (mort[~mort["is_retired"]]
                .groupby(["dist_age", "dist_year"])["mort_final"]
                .first().reset_index())

    retiree = (mort[mort["is_retired"]]
               .groupby(["dist_age", "dist_year"])["mort_final"]
               .first().reset_index())

    return CompactMortality(employee, retiree)
