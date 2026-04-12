"""
Funding model — public entry point.

This module is the public API for the funding projection engine. The
heavy compute lives in :mod:`pension_model.core._funding_core`; this
file holds the input loaders, the amortization-table builder, and the
config-driven ``run_funding_model`` dispatcher.

Year-by-year, the funding model projects:
  * Payroll, benefit payments, normal cost
  * AAL roll-forward with liability gain/loss
  * MVA projection with investment returns
  * AVA smoothing (corridor or gain/loss deferral, selected from config)
  * UAAL amortization (layered, level % of payroll)
  * Employer contributions (NC + amortization + admin + DC + solvency)
  * Funded ratios (AVA and MVA basis)

Requires: liability pipeline output + initial funding data + amort layers.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from pension_model.core._funding_core import (
    _compute_funding_corridor,
    _compute_funding_gainloss,
)


def load_funding_inputs(funding_dir: Path) -> dict:
    """Load funding input data from ``data/<plan>/funding/``.

    Files:
      - ``init_funding.csv``  (required)
      - ``return_scenarios.csv`` (required)
      - ``amort_layers.csv`` (optional — plans with layered amortization)

    Also accepts the legacy ``baseline_outputs/`` layout where the files
    are named ``init_funding_data.csv`` and ``current_amort_layers.csv``.
    """
    # init_funding: try standard name first, fall back to legacy
    init_path = funding_dir / "init_funding.csv"
    if not init_path.exists():
        init_path = funding_dir / "init_funding_data.csv"
    init_funding = pd.read_csv(init_path)
    # Normalize column names (strip leading/trailing whitespace)
    init_funding.columns = [c.strip() for c in init_funding.columns]

    result = {
        "init_funding": init_funding,
        "return_scenarios": pd.read_csv(funding_dir / "return_scenarios.csv"),
    }

    # Amort layers (plans with layered amortization)
    amort_path = funding_dir / "amort_layers.csv"
    if not amort_path.exists():
        amort_path = funding_dir / "current_amort_layers.csv"
    if amort_path.exists():
        result["amort_layers"] = pd.read_csv(amort_path)

    return result


def build_amort_period_tables(
    amort_layers: pd.DataFrame, class_name: str,
    amo_period_new: int, funding_lag: int, model_period: int,
) -> tuple:
    """
    Build amortization period matrices for current and future hires.

    Returns (current_periods, future_periods, init_balances, max_col).
    Each period matrix: rows = years, columns = amortization layers.
    Periods count down diagonally.
    """
    lookup = class_name.replace("_", " ")
    class_layers = amort_layers[amort_layers["class"] == lookup].copy()
    # R converts "n/a" to amo_period_new, then groups by period
    class_layers["amo_period"] = pd.to_numeric(
        class_layers["amo_period"].replace("n/a", str(amo_period_new))
    ).fillna(amo_period_new)  # Also handle numeric NaN from CSV loading
    # R groups by (class, amo_period) and sums balances
    class_layers = (class_layers.groupby("amo_period", as_index=False)
                    .agg({"amo_balance": "sum"})
                    .sort_values("amo_period", ascending=False))

    current_periods_init = class_layers["amo_period"].dropna().values
    # max_col must accommodate all existing layers AND future layers
    max_col = max(
        len(current_periods_init),
        int(current_periods_init.max()) if len(current_periods_init) > 0 else 0,
        amo_period_new + funding_lag,
    )

    n_rows = model_period + 1

    # Current hire periods
    current = np.zeros((n_rows, max_col))
    current[0, :len(current_periods_init)] = current_periods_init
    future_period = amo_period_new + funding_lag
    for row in range(1, n_rows):
        current[row, 0] = future_period

    for i in range(1, n_rows):
        for j in range(1, max_col):
            current[i, j] = max(current[i - 1, j - 1] - 1, 0)

    # Future hire periods
    future = np.zeros((n_rows, max_col))
    for row in range(n_rows):
        future[row, 0] = future_period

    for i in range(1, n_rows):
        for j in range(1, max_col):
            future[i, j] = max(future[i - 1, j - 1] - 1, 0)

    init_balances = class_layers["amo_balance"].dropna().values
    return current, future, init_balances, max_col


# ---------------------------------------------------------------------------
# Public dispatcher — selects the funding compute path from config.
# ---------------------------------------------------------------------------


def run_funding_model(
    liability_results: dict,
    funding_inputs: dict,
    constants,
) -> dict:
    """Run the funding model for any plan, picking the path from config.

    Selects the AVA smoothing method from
    ``constants.funding.ava_smoothing["method"]`` (set in plan_config.json):

      * ``"corridor"``  → 5-year corridor at the plan-aggregate level.
        Calls :func:`_compute_funding_corridor`. Returns the dict it
        produces directly: per-class frames, an aggregate frame keyed
        by ``constants.plan_name``, and an optional ``"drop"`` frame.
      * ``"gain_loss"`` → 4-year gain/loss deferral cascade per class.
        Calls :func:`_compute_funding_gainloss` for the single class
        and wraps the result into a uniform two-key dict
        ``{class_name: df, plan_name: agg}`` where ``agg`` is a
        distinct copy of the class frame (no DataFrame aliasing).

    Args:
        liability_results: Dict mapping class_name -> liability DataFrame.
        funding_inputs: Output of :func:`load_funding_inputs`.
        constants: :class:`PlanConfig`.

    Returns:
        Dict mapping class_name -> funding DataFrame, plus an
        aggregate frame keyed by ``constants.plan_name`` and an
        optional ``"drop"`` frame for plans with ``has_drop=true``.

    Raises:
        ValueError: if ``funding.ava_smoothing.method`` is not one of
            the supported values, or if a single-class plan is paired
            with corridor smoothing (which currently has no
            implementation), or if a multi-class plan is paired with
            gain/loss smoothing (likewise).
    """
    method = (constants.funding.ava_smoothing or {}).get("method")
    class_names = list(constants.classes)

    if method == "corridor":
        if len(class_names) < 1:
            raise ValueError(
                "Corridor smoothing requires at least one class in plan config."
            )
        return _compute_funding_corridor(
            liability_results, funding_inputs, constants)

    if method == "gain_loss":
        if len(class_names) != 1:
            # Multi-class gain/loss is not an algorithmic barrier — gain/loss
            # smoothing operates per class, so N>1 classes is conceptually
            # fine. The constraint is a temporary implementation limit:
            # _compute_funding_gainloss currently iterates neither classes
            # nor builds an aggregate frame. Phase 2's body merge lifts this
            # limit by unifying the two compute functions into one that
            # handles any class count uniformly.
            raise NotImplementedError(
                f"Multi-class gain/loss smoothing is pending the Phase 2 "
                f"unified compute refactor (see plans/swirling-jingling-"
                f"popcorn.md, Step 2.I). Plan {constants.plan_name!r} has "
                f"{len(class_names)} classes."
            )
        first_class = class_names[0]
        df = _compute_funding_gainloss(
            liability_results[first_class], funding_inputs, constants)
        # Build a real aggregate frame as a distinct copy (no aliasing).
        # For a single-class plan, the aggregate IS the class frame
        # mathematically, so a copy is correct. Distinct objects mean
        # downstream code can mutate one without affecting the other.
        agg = df.copy()
        return {first_class: df, constants.plan_name: agg}

    raise ValueError(
        f"Unknown funding.ava_smoothing.method: {method!r}. "
        f"Supported values: 'corridor', 'gain_loss'."
    )
