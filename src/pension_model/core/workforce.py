"""
Streaming workforce projection.

Replicates R's Florida FRS workforce model.R.

R's flow each year:
  1. active2term = active * separation_rate  (all exits go to term first)
  2. active = (active - active2term) shifted right by 1 age + new entrants
  3. term stock: age with mortality, add new terms
  4. refunds: from new terms where ben_decision == "refund"
  5. retirees: from all terms where ben_decision includes retirement
     (at distribution age, which may be deferred for vested members)
"""

import numpy as np
import pandas as pd


def project_workforce(
    initial_active: pd.DataFrame,
    separation_rates: pd.DataFrame,
    benefit_decisions: pd.DataFrame,
    mortality_rates: pd.DataFrame,
    entrant_profile: pd.DataFrame,
    class_name: str,
    start_year: int,
    model_period: int,
    pop_growth: float = 0.0,
    retire_refund_ratio: float = 1.0,
) -> dict:
    """
    Project workforce for all years.

    Args:
        initial_active: (entry_age, age, n_active) at start_year.
        separation_rates: (entry_year, entry_age, term_age, yos, separation_rate).
        benefit_decisions: (entry_year, entry_age, yos, term_age, dist_age, ben_decision)
            from benefit_val_table. ben_decision is "retire", "mix", or "refund".
        mortality_rates: (entry_year, entry_age, dist_age, dist_year, yos, mort_final, tier_at_dist_age)
            or a CompactMortality object.
        entrant_profile: (entry_age, start_sal, entrant_dist).
        class_name: Membership class name.
        start_year: Valuation year.
        model_period: Number of projection years.
        pop_growth: Annual population growth (0 for stable).
        retire_refund_ratio: Fraction of vested "mix" who choose retirement (default 1.0).

    Returns:
        Dict with DataFrames: wf_active, wf_term, wf_retire, wf_refund
    """
    entry_ages = sorted(initial_active["entry_age"].unique())
    n_entry = len(entry_ages)
    ea_to_idx = {ea: i for i, ea in enumerate(entry_ages)}

    # Age range
    min_age = min(entry_ages)
    max_age = 120
    ages = list(range(min_age, max_age + 1))
    n_ages = len(ages)
    age_to_idx = {a: i for i, a in enumerate(ages)}

    years = list(range(start_year, start_year + model_period + 1))
    n_years = len(years)

    # Build separation rate lookup: sep_rates[entry_age_idx, age_idx, year_idx]
    sep_lookup = np.zeros((n_entry, n_ages, n_years))
    for _, row in separation_rates.iterrows():
        ea = int(row["entry_age"])
        ta = int(row.get("term_age", row.get("age", ea + row.get("yos", 0))))
        ey = int(row["entry_year"])
        sr = row["separation_rate"]
        if ea in ea_to_idx and ta in age_to_idx:
            # year = entry_year + yos = ey + (ta - ea)
            yr = ey + (ta - ea)
            if start_year <= yr <= start_year + model_period:
                yi = yr - start_year
                sep_lookup[ea_to_idx[ea], age_to_idx[ta], yi] = sr if not np.isnan(sr) else 0

    # Build benefit decision lookups: refund_prob and retire_prob
    # refund_prob: probability of refund given termination at (entry_age, term_age, entry_year)
    # retire_prob: probability of retirement at distribution age
    # R computes these from ben_decision in benefit_val_table
    refund_lookup = {}  # (entry_year, entry_age, term_age) -> refund probability
    retire_lookup = {}  # (entry_year, entry_age, term_age, dist_age) -> retire probability

    if len(benefit_decisions) > 0:
        for _, row in benefit_decisions.iterrows():
            ey = int(row["entry_year"])
            ea = int(row["entry_age"])
            ta = int(row.get("term_age", ea + row.get("yos", 0)))
            da = int(row.get("dist_age", ta))
            bd = row.get("ben_decision", None)

            if bd == "refund" or (pd.isna(bd) and row.get("yos", 1) == 0):
                refund_lookup[(ey, ea, ta)] = 1.0
            elif bd == "mix":
                refund_lookup[(ey, ea, ta)] = 1 - retire_refund_ratio
                retire_lookup[(ey, ea, ta, da)] = 1.0
            elif bd == "retire":
                retire_lookup[(ey, ea, ta, da)] = 1.0

    # Transition matrix: shifts ages right by 1
    TM = np.zeros((n_ages, n_ages))
    for i in range(n_ages - 1):
        TM[i, i + 1] = 1.0

    # Initialize active matrix [entry_age_idx, age_idx]
    active = np.zeros((n_entry, n_ages))
    for _, row in initial_active.iterrows():
        ea = int(row["entry_age"])
        age = int(row["age"])
        if ea in ea_to_idx and age in age_to_idx:
            active[ea_to_idx[ea], age_to_idx[age]] = row["n_active"]

    # New entrant distribution
    ne_dist = np.zeros(n_entry)
    for _, row in entrant_profile.iterrows():
        ea = int(row["entry_age"])
        if ea in ea_to_idx:
            ne_dist[ea_to_idx[ea]] = row["entrant_dist"]

    # Position matrix for new entrants: entry_age maps to age column
    pos_matrix = np.zeros((n_entry, n_ages))
    for i, ea in enumerate(entry_ages):
        if ea in age_to_idx:
            pos_matrix[i, age_to_idx[ea]] = 1.0

    # Storage: term_year -> [entry_age_idx, age_idx] matrix
    term_stocks = {}
    # Storage: (term_year, retire_year) -> [entry_age_idx, age_idx] matrix
    retire_stocks = {}

    # Collect outputs
    all_active = []
    all_term = []
    all_retire = []
    all_refund = []

    # Record year 0
    for ei, ea in enumerate(entry_ages):
        for ai, age in enumerate(ages):
            if active[ei, ai] > 0:
                all_active.append((ea, age, start_year, active[ei, ai]))

    # Main projection loop
    for t in range(1, n_years):
        year = start_year + t
        yi = t  # year index (0-based from start_year)
        prev_yi = t - 1

        new_retire_stocks = {}  # new retirees this year, keyed by (term_year, retire_year)

        # 1. active2term = active * separation_rate
        active2term = active * sep_lookup[:, :, prev_yi]

        # 2. Deduct exits and age
        active_after = (active - active2term) @ TM

        # 3. New entrants: ne = sum(wf1) * (1+g) - sum(wf2)
        pre_total = active.sum()
        post_total = active_after.sum()
        n_new = pre_total * (1 + pop_growth) - post_total
        n_new = max(n_new, 0)

        if n_new > 0:
            new_entrants = np.outer(ne_dist * n_new, np.ones(n_ages)) * pos_matrix
            active_after += new_entrants

        active = active_after

        # Record active
        for ei, ea in enumerate(entry_ages):
            for ai, age in enumerate(ages):
                if active[ei, ai] > 1e-10:
                    all_active.append((ea, age, year, active[ei, ai]))

        # 4. Age existing term stocks with mortality, then shift right
        # R: term2death = wf_term * mort_array; wf_term = (wf_term - term2death) %*% TM
        # R uses tier-aware mortality: employee below NRA, retiree at/above NRA
        new_term_stocks = {}
        for ty, ts in term_stocks.items():
            if hasattr(mortality_rates, 'get_rates_vec'):
                for ei, ea in enumerate(entry_ages):
                    for ai, age in enumerate(ages):
                        if ts[ei, ai] > 1e-10:
                            # Determine if member has reached retirement-eligible tier
                            # (which switches to retiree mortality in R's mort_table)
                            orig_term_age = age - (year - 1 - ty)  # age in prev year's indexing
                            yos_at_term = orig_term_age - ea
                            entry_yr = ty - yos_at_term
                            from pension_model.core.tier_logic import get_tier as _gt
                            tier = _gt(class_name, entry_yr, age, yos_at_term, 2024)
                            is_ret = "norm" in tier or "early" in tier
                            mort = mortality_rates.get_rate(age, year - 1, is_retiree=is_ret)
                            ts[ei, ai] *= (1 - mort)
            aged = ts @ TM
            new_term_stocks[ty] = aged

        # 5. New terms: active2term aged by 1
        new_terms_aged = active2term @ TM
        new_term_stocks[year] = new_terms_aged.copy()

        # 6. Remove refunds from new terms
        # After TM shift, members at age position `a` have term_age = a
        # (R counts termination at the post-shift age)
        # entry_year = year - (age - entry_age) = year - yos
        for ei, ea in enumerate(entry_ages):
            for ai, age in enumerate(ages):
                if new_term_stocks[year][ei, ai] > 1e-10:
                    term_age = age  # post-shift = R's term_age
                    yos = term_age - ea
                    entry_year_member = year - yos
                    rp = refund_lookup.get((entry_year_member, ea, term_age), 0)
                    if rp > 0:
                        refund_amount = new_term_stocks[year][ei, ai] * rp
                        new_term_stocks[year][ei, ai] -= refund_amount
                        all_refund.append((ea, age, year, year, refund_amount))

        # 7. Remove retirees from ALL term stocks → add to retire stocks
        for ty in list(new_term_stocks.keys()):
            ts = new_term_stocks[ty]
            for ei, ea in enumerate(entry_ages):
                for ai, age in enumerate(ages):
                    if ts[ei, ai] > 1e-10:
                        orig_term_age = age - (year - ty)
                        entry_year_member = year - (age - ea)
                        ret_prob = retire_lookup.get((entry_year_member, ea, orig_term_age, age), 0)
                        if ret_prob > 0:
                            retire_amount = ts[ei, ai] * ret_prob
                            ts[ei, ai] -= retire_amount
                            # Add to retire stock
                            key = (ty, year)
                            if key not in new_retire_stocks:
                                new_retire_stocks[key] = np.zeros((n_entry, n_ages))
                            new_retire_stocks[key][ei, ai] += retire_amount

        # 8. Age existing retire stocks with mortality + TM
        # R: retire2death = wf_retire * mort_array; wf_retire = (wf_retire - retire2death) %*% TM
        new_retire_stocks_all = {}
        for (ty, ry), rs in retire_stocks.items():
            # Apply retiree mortality
            if hasattr(mortality_rates, 'get_rates_vec'):
                for ei, ea in enumerate(entry_ages):
                    for ai, age in enumerate(ages):
                        if rs[ei, ai] > 1e-10:
                            # Retirees use retiree mortality
                            mort = mortality_rates.get_rate(age, year - 1, is_retiree=True)
                            rs[ei, ai] *= (1 - mort)
            aged = rs @ TM
            new_retire_stocks_all[(ty, ry)] = aged

        # Merge new retirees into the accumulated stocks
        for key, rs in new_retire_stocks.items():
            if key in new_retire_stocks_all:
                new_retire_stocks_all[key] += rs
            else:
                new_retire_stocks_all[key] = rs

        retire_stocks = new_retire_stocks_all

        # Record term stocks
        for ty, ts in new_term_stocks.items():
            for ei, ea in enumerate(entry_ages):
                for ai, age in enumerate(ages):
                    if ts[ei, ai] > 1e-10:
                        all_term.append((ea, age, year, ty, ts[ei, ai]))

        # Record retire stocks
        for (ty, ry), rs in retire_stocks.items():
            for ei, ea in enumerate(entry_ages):
                for ai, age in enumerate(ages):
                    if rs[ei, ai] > 1e-10:
                        all_retire.append((ea, age, year, ty, ry, rs[ei, ai]))

        term_stocks = new_term_stocks

    return {
        "wf_active": pd.DataFrame(all_active, columns=["entry_age", "age", "year", "n_active"]),
        "wf_term": pd.DataFrame(all_term, columns=["entry_age", "age", "year", "term_year", "n_term"]),
        "wf_retire": pd.DataFrame(all_retire, columns=["entry_age", "age", "year", "term_year", "retire_year", "n_retire"]),
        "wf_refund": pd.DataFrame(all_refund, columns=["entry_age", "age", "year", "term_year", "n_refund"]),
    }
