"""
Streaming workforce projection.

Projects active, terminated, refund, and retired populations year by year.
Matches R's Florida FRS workforce model.R logic.

Key design: process one year at a time, accumulate stocks incrementally.
Active population is a DataFrame of (entry_age, age, n_active).
Terminated/retired stocks grow each year as new separations enter.

Memory: O(n_cohorts × n_projection_years), not O(full cross-product).
"""

import numpy as np
import pandas as pd
from typing import Callable


def project_workforce(
    initial_active: pd.DataFrame,
    separation_rates: pd.DataFrame,
    entrant_profile: pd.DataFrame,
    class_name: str,
    start_year: int,
    model_period: int,
    pop_growth: float = 0.0,
) -> dict:
    """
    Project workforce for all years.

    Args:
        initial_active: DataFrame with (entry_age, age, n_active) at start_year.
        separation_rates: DataFrame with (entry_year, entry_age, term_age, yos,
            separation_rate) — one row per (entry_year, entry_age, yos).
        entrant_profile: DataFrame with (entry_age, start_sal, entrant_dist).
        class_name: Membership class name.
        start_year: Valuation year.
        model_period: Number of projection years.
        pop_growth: Annual population growth rate (0 for stable).

    Returns:
        Dict with:
          'wf_active': DataFrame (entry_age, age, year, n_active)
          'wf_term': DataFrame (entry_age, age, year, term_year, n_term)
          'wf_retire': DataFrame (entry_age, age, year, term_year, retire_year, n_retire)
          'wf_refund': DataFrame (entry_age, age, year, term_year, n_refund)
    """
    # Parse separation rates into lookup
    # R model uses: for each (entry_age, yos), get separation_rate
    # The separation rate determines what fraction leave, and the tier determines
    # whether they retire, vest, or get refund

    # Build active population indexed by (entry_age, age)
    active = initial_active.copy()
    active["yos"] = active["age"] - active["entry_age"]
    active["entry_year"] = start_year - active["yos"]

    # Collect all years' outputs
    all_active = []
    all_term = []
    all_retire = []
    all_refund = []

    # Current term/retire stocks (accumulated)
    term_stock = pd.DataFrame(columns=["entry_age", "age", "term_year", "n_term"])
    retire_stock = pd.DataFrame(columns=["entry_age", "age", "term_year", "retire_year", "n_retire"])

    entry_ages = entrant_profile["entry_age"].values

    for t in range(model_period + 1):
        year = start_year + t

        if t == 0:
            # Year 0: just record the initial state
            active["year"] = year
            all_active.append(active[["entry_age", "age", "year", "n_active"]].copy())
            continue

        prev_active = active.copy()
        pre_decrement_total = prev_active["n_active"].sum()

        # Apply separation: merge with separation rates
        prev_active["yos"] = prev_active["age"] - prev_active["entry_age"]
        prev_active["entry_year"] = year - 1 - prev_active["yos"]

        # Look up separation rate for each member's (entry_year, entry_age, yos)
        prev_active = prev_active.merge(
            separation_rates[["entry_year", "entry_age", "yos", "separation_rate"]].drop_duplicates(),
            on=["entry_year", "entry_age", "yos"],
            how="left",
        )
        prev_active["separation_rate"] = prev_active["separation_rate"].fillna(0)

        # Compute exits
        prev_active["n_exit"] = prev_active["n_active"] * prev_active["separation_rate"]
        prev_active["n_remaining"] = prev_active["n_active"] - prev_active["n_exit"]

        # Determine exit type from tier
        # For the workforce model, R uses the separation table's implicit logic:
        # - If separation_rate comes from retirement rates: retire
        # - If from withdrawal rates with vesting: term (vested)
        # - If from withdrawal rates without vesting: refund
        # R doesn't explicitly split — it uses the full wf_data structure.
        # For now, we need the tier to determine exit type.

        # Look up tier for each member
        from pension_model.core.tier_logic import get_sep_type as _get_sep_type

        def _get_tier_for_row(row):
            from pension_model.core.tier_logic import get_tier as _gt
            return _gt(class_name, int(row["entry_year"]), int(row["age"]), int(row["yos"]))

        prev_active["tier"] = prev_active.apply(_get_tier_for_row, axis=1)
        prev_active["sep_type"] = prev_active["tier"].apply(_get_sep_type)

        # Split exits by type
        n_retire = prev_active.loc[prev_active["sep_type"] == "retire", "n_exit"].copy()
        n_vested = prev_active.loc[prev_active["sep_type"] == "vested", "n_exit"].copy()
        n_refund = prev_active.loc[prev_active["sep_type"] == "non_vested", "n_exit"].copy()

        # New terminations (vested) and refunds this year
        term_new = prev_active[prev_active["sep_type"] == "vested"][["entry_age", "age", "n_exit"]].copy()
        term_new = term_new.rename(columns={"n_exit": "n_term"})
        term_new["term_year"] = year
        term_new["year"] = year

        refund_new = prev_active[prev_active["sep_type"] == "non_vested"][["entry_age", "age", "n_exit"]].copy()
        refund_new = refund_new.rename(columns={"n_exit": "n_refund"})
        refund_new["term_year"] = year
        refund_new["year"] = year

        # New retirees this year
        retire_new = prev_active[prev_active["sep_type"] == "retire"][["entry_age", "age", "n_exit"]].copy()
        retire_new = retire_new.rename(columns={"n_exit": "n_retire"})
        retire_new["term_year"] = year
        retire_new["retire_year"] = year
        retire_new["year"] = year

        # Age the active population
        active_next = prev_active[["entry_age", "n_remaining"]].copy()
        active_next = active_next.rename(columns={"n_remaining": "n_active"})
        active_next["age"] = prev_active["age"] + 1
        active_next = active_next[active_next["n_active"] > 0].copy()

        post_decrement_total = active_next["n_active"].sum()

        # Add new entrants
        n_new = pre_decrement_total * (1 + pop_growth) - post_decrement_total
        n_new = max(n_new, 0)

        if n_new > 0:
            new_entrants = entrant_profile[["entry_age"]].copy()
            new_entrants["n_active"] = new_entrants.index.map(
                lambda i: n_new * entrant_profile.iloc[i]["entrant_dist"]
            )
            new_entrants["age"] = new_entrants["entry_age"]
            active_next = pd.concat([active_next, new_entrants[["entry_age", "age", "n_active"]]],
                                    ignore_index=True)

        # Consolidate active (sum any duplicates from new entrants at same age)
        active_next = active_next.groupby(["entry_age", "age"], as_index=False)["n_active"].sum()

        active_next["year"] = year
        active = active_next.copy()
        all_active.append(active[["entry_age", "age", "year", "n_active"]].copy())

        # Age existing term stock with mortality (R model ages and applies mortality)
        if len(term_stock) > 0:
            term_stock["age"] = term_stock["age"] + 1
            # TODO: apply mortality to term stock (R does this via cum_mort_dr in liability)
            # For now, keep full stock — mortality is handled in liability computation
            term_stock["year"] = year

        # Add new terms to stock
        term_stock = pd.concat([term_stock, term_new[["entry_age", "age", "term_year", "n_term"]].assign(year=year)],
                               ignore_index=True)

        # Age existing retire stock
        if len(retire_stock) > 0:
            retire_stock["age"] = retire_stock["age"] + 1
            retire_stock["year"] = year

        # Add new retirees
        retire_stock = pd.concat([retire_stock, retire_new[["entry_age", "age", "term_year", "retire_year", "n_retire"]].assign(year=year)],
                                 ignore_index=True)

        all_term.append(term_stock.copy())
        all_retire.append(retire_stock.copy())
        all_refund.append(refund_new.copy())

    return {
        "wf_active": pd.concat(all_active, ignore_index=True),
        "wf_term": pd.concat(all_term, ignore_index=True) if all_term else pd.DataFrame(),
        "wf_retire": pd.concat(all_retire, ignore_index=True) if all_retire else pd.DataFrame(),
        "wf_refund": pd.concat(all_refund, ignore_index=True) if all_refund else pd.DataFrame(),
    }
