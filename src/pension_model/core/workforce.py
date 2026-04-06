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
    no_new_entrants: bool = False,
    constants=None,
) -> dict:
    """
    Project workforce for all years.

    Args:
        initial_active: (entry_age, age, n_active) at start_year.
        separation_rates: (entry_year, entry_age, term_age, yos, separation_rate).
        benefit_decisions: (entry_year, entry_age, yos, term_age, dist_age, ben_decision)
            from benefit_val_table. ben_decision is "retire", "mix", or "refund".
        mortality_rates: CompactMortality object.
        entrant_profile: (entry_age, start_sal, entrant_dist).
        class_name: Membership class name.
        start_year: Valuation year.
        model_period: Number of projection years.
        pop_growth: Annual population growth (0 for stable).
        retire_refund_ratio: Fraction of vested "mix" who choose retirement (default 1.0).
        constants: PlanConfig for tier resolution (needed for tier-aware mortality).

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

    years = list(range(start_year, start_year + model_period + 1))
    n_years = len(years)

    # Build separation rate lookup: sep_rates[entry_age_idx, age_idx, year_idx]
    # Vectorized: compute array indices from DataFrame columns, then assign.
    sep_lookup = np.zeros((n_entry, n_ages, n_years))
    if len(separation_rates) > 0:
        sr = separation_rates
        ea_vals = sr["entry_age"].values.astype(int)
        ta_vals = sr["term_age"].values.astype(int) if "term_age" in sr.columns else (
            ea_vals + sr["yos"].values.astype(int))
        ey_vals = sr["entry_year"].values.astype(int)
        sr_vals = sr["separation_rate"].values.astype(float)
        yr_vals = ey_vals + (ta_vals - ea_vals)

        # Map to index arrays; filter to rows within our ranges
        ea_idx = np.array([ea_to_idx.get(int(v), -1) for v in ea_vals])
        ta_idx = ta_vals - min_age  # age_to_idx is contiguous from min_age
        yr_idx = yr_vals - start_year

        valid = ((ea_idx >= 0) & (ta_idx >= 0) & (ta_idx < n_ages)
                 & (yr_idx >= 0) & (yr_idx < n_years))
        sr_clean = np.where(np.isnan(sr_vals), 0.0, sr_vals)
        sep_lookup[ea_idx[valid], ta_idx[valid], yr_idx[valid]] = sr_clean[valid]

    # Build benefit decision lookups as numpy-indexed arrays.
    # refund_lookup: 3D [entry_age_idx, age_idx, year_idx] -> refund probability
    # retire_lookup: 4D [entry_age_idx, age_idx, dist_age_idx, year_idx] -> 1.0
    # Using dicts with tuple keys is the bottleneck-free approach here because
    # the inner-year loops (steps 6-7) do sparse lookups; a dense 4D array would
    # be too large. But we build the dicts from vectorized column ops, not iterrows.
    refund_lookup = {}
    retire_lookup = {}

    if len(benefit_decisions) > 0:
        bd = benefit_decisions
        bd_ey = bd["entry_year"].values.astype(int)
        bd_ea = bd["entry_age"].values.astype(int)
        bd_ta = bd["term_age"].values.astype(int) if "term_age" in bd.columns else (
            bd_ea + bd["yos"].values.astype(int))
        bd_da = bd["dist_age"].values.astype(int) if "dist_age" in bd.columns else bd_ta
        bd_dec = bd["ben_decision"].values
        bd_yos = bd["yos"].values.astype(int) if "yos" in bd.columns else (bd_ta - bd_ea)

        is_refund = (bd_dec == "refund") | ((pd.isna(bd_dec)) & (bd_yos == 0))
        is_mix = bd_dec == "mix"
        is_retire = bd_dec == "retire"

        for i in np.where(is_refund)[0]:
            refund_lookup[(int(bd_ey[i]), int(bd_ea[i]), int(bd_ta[i]))] = 1.0
        for i in np.where(is_mix)[0]:
            refund_lookup[(int(bd_ey[i]), int(bd_ea[i]), int(bd_ta[i]))] = 1 - retire_refund_ratio
            retire_lookup[(int(bd_ey[i]), int(bd_ea[i]), int(bd_ta[i]), int(bd_da[i]))] = 1.0
        for i in np.where(is_retire)[0]:
            retire_lookup[(int(bd_ey[i]), int(bd_ea[i]), int(bd_ta[i]), int(bd_da[i]))] = 1.0

    # Transition matrix: shifts ages right by 1
    TM = np.zeros((n_ages, n_ages))
    np.fill_diagonal(TM[:-1, 1:], 1.0)

    # Initialize active matrix [entry_age_idx, age_idx]
    active = np.zeros((n_entry, n_ages))
    if len(initial_active) > 0:
        ia_ea = initial_active["entry_age"].values.astype(int)
        ia_age = initial_active["age"].values.astype(int)
        ia_n = initial_active["n_active"].values.astype(float)
        ia_ei = np.array([ea_to_idx.get(int(v), -1) for v in ia_ea])
        ia_ai = ia_age - min_age
        valid = (ia_ei >= 0) & (ia_ai >= 0) & (ia_ai < n_ages)
        active[ia_ei[valid], ia_ai[valid]] = ia_n[valid]

    # New entrant distribution
    ne_dist = np.zeros(n_entry)
    if len(entrant_profile) > 0:
        ep_ea = entrant_profile["entry_age"].values.astype(int)
        ep_dist = entrant_profile["entrant_dist"].values.astype(float)
        ep_ei = np.array([ea_to_idx.get(int(v), -1) for v in ep_ea])
        valid = ep_ei >= 0
        ne_dist[ep_ei[valid]] = ep_dist[valid]

    # Position matrix for new entrants: entry_age maps to age column
    pos_matrix = np.zeros((n_entry, n_ages))
    ea_arr = np.array(entry_ages)
    ea_ai = ea_arr - min_age
    valid = (ea_ai >= 0) & (ea_ai < n_ages)
    pos_matrix[np.arange(n_entry)[valid], ea_ai[valid]] = 1.0

    # --- Pre-build mortality grids for the full projection horizon ---
    # Extract 2D slices from CompactMortality's internal grids. Indexed as
    # mort_grid[age_idx, year_idx] where age_idx = age - min_age and
    # year_idx = year - start_year. Employee and retiree grids are separate.
    cm = mortality_rates
    mort_year_offset = cm.min_year
    mort_age_offset = cm.min_age
    emp_mort_full = cm._emp_grid  # [age - mort_age_offset, year - mort_year_offset]
    ret_mort_full = cm._ret_grid

    # Build 2D mortality survival arrays for each projection year:
    # emp_surv[age_idx] = 1 - emp_mort(age, year-1) for age in ages
    # Used to age term and retire stocks via elementwise multiply.
    emp_surv_by_year = np.ones((n_ages, n_years))
    ret_surv_by_year = np.ones((n_ages, n_years))
    for t in range(1, n_years):
        yr = start_year + t - 1  # mortality is applied at year-1
        yr_idx = yr - mort_year_offset
        if 0 <= yr_idx < emp_mort_full.shape[1]:
            a_lo = max(min_age - mort_age_offset, 0)
            a_hi = min(max_age + 1 - mort_age_offset, emp_mort_full.shape[0])
            out_lo = a_lo + mort_age_offset - min_age
            out_hi = a_hi + mort_age_offset - min_age
            emp_surv_by_year[out_lo:out_hi, t] = 1.0 - emp_mort_full[a_lo:a_hi, yr_idx]
            ret_surv_by_year[out_lo:out_hi, t] = 1.0 - ret_mort_full[a_lo:a_hi, yr_idx]

    # --- Pre-build refund probability array ---
    # refund_prob_arr[entry_age_idx, age_idx, year_idx]
    # For new terms at (year, entry_age, term_age=age), gives refund prob.
    refund_prob_arr = np.zeros((n_entry, n_ages, n_years))
    for (ey, ea, ta), rp in refund_lookup.items():
        ea_i = ea_to_idx.get(ea, -1)
        ta_i = ta - min_age
        yr_i = ey + (ta - ea) - start_year
        if ea_i >= 0 and 0 <= ta_i < n_ages and 0 <= yr_i < n_years:
            refund_prob_arr[ea_i, ta_i, yr_i] = rp

    # --- Tier-aware mortality helper for term stocks ---
    # Deferred vested members use employee mortality until they reach a
    # retirement-eligible tier (norm/early), then switch to retiree mortality.
    # We batch-resolve tiers per term stock using resolve_tiers_vec.
    from pension_model.plan_config import resolve_tiers_vec as _resolve_tiers_vec

    ea_arr_int = np.array(entry_ages, dtype=np.int64)

    # Storage: term_year -> [entry_age_idx, age_idx] matrix
    term_stocks = {}
    retire_stocks = {}

    # Helper: record nonzero entries from a 2D matrix
    ea_grid = np.array(entry_ages)  # [n_entry]

    def _record_matrix(matrix, year_val, extra_cols=()):
        """Extract nonzero cells from a 2D [n_entry, n_ages] matrix.

        Returns list of row tuples: (entry_age, age, year, *extra_cols, value).
        """
        ei_idx, ai_idx = np.nonzero(matrix > 1e-10)
        if len(ei_idx) == 0:
            return []
        vals = matrix[ei_idx, ai_idx]
        eas = ea_grid[ei_idx]
        cur_ages = ai_idx + min_age
        n = len(ei_idx)
        year_arr = np.full(n, year_val, dtype=np.int64)
        cols = [eas, cur_ages, year_arr]
        for ec in extra_cols:
            if isinstance(ec, (int, np.integer)):
                cols.append(np.full(n, ec, dtype=np.int64))
            else:
                cols.append(ec)
        cols.append(vals)
        return list(zip(*[c.tolist() if hasattr(c, 'tolist') else c for c in cols]))

    # Collect outputs
    all_active = []
    all_term = []
    all_retire = []
    all_refund = []

    # Record year 0
    all_active.extend(_record_matrix(active, start_year))

    # Main projection loop
    for t in range(1, n_years):
        year = start_year + t
        prev_yi = t - 1

        new_retire_stocks = {}

        # 1. active → term via separation rates
        active2term = active * sep_lookup[:, :, prev_yi]

        # 2. Deduct exits and age
        active_after = (active - active2term) @ TM

        # 3. New entrants
        pre_total = active.sum()
        post_total = active_after.sum()
        if no_new_entrants:
            n_new = 0
        else:
            n_new = max(pre_total * (1 + pop_growth) - post_total, 0)

        if n_new > 0:
            new_entrants = np.outer(ne_dist * n_new, np.ones(n_ages)) * pos_matrix
            active_after += new_entrants

        active = active_after
        all_active.extend(_record_matrix(active, year))

        # 4. Age existing term stocks with tier-aware mortality
        # For each term stock, batch-resolve tiers for nonzero cells to determine
        # employee vs retiree mortality, then apply the appropriate survival rate.
        new_term_stocks = {}
        surv_year = t  # index into emp/ret_surv_by_year
        for ty, ts in term_stocks.items():
            nz_ei, nz_ai = np.nonzero(ts > 1e-10)
            if len(nz_ei) == 0:
                new_term_stocks[ty] = ts @ TM
                continue

            # Compute tier parameters for nonzero cells
            nz_age = nz_ai + min_age  # current age (pre-shift)
            orig_term_age = nz_age - (year - 1 - ty)
            nz_ea = ea_arr_int[nz_ei]
            yos_at_term = orig_term_age - nz_ea
            entry_yr = ty - yos_at_term

            # Batch resolve tiers to determine mortality type
            if constants is not None:
                cn_arr = np.full(len(nz_ei), class_name, dtype=object)
                tiers = _resolve_tiers_vec(
                    constants, cn_arr, entry_yr, nz_age, yos_at_term,
                )
                is_ret = np.array(
                    ["norm" in t_str or "early" in t_str for t_str in tiers]
                )
            else:
                # Fallback: all use employee mortality
                is_ret = np.zeros(len(nz_ei), dtype=bool)

            # Apply appropriate survival rate
            emp_surv = emp_surv_by_year[nz_ai, surv_year]
            ret_surv = ret_surv_by_year[nz_ai, surv_year]
            surv = np.where(is_ret, ret_surv, emp_surv)
            ts[nz_ei, nz_ai] *= surv

            new_term_stocks[ty] = ts @ TM

        # 5. New terms
        new_term_stocks[year] = (active2term @ TM).copy()

        # 6. Remove refunds from new terms (vectorized)
        rp_slice = refund_prob_arr[:, :, t]
        refund_amounts = new_term_stocks[year] * rp_slice
        new_term_stocks[year] -= refund_amounts
        all_refund.extend(_record_matrix(refund_amounts, year, extra_cols=(year,)))

        # 7. Remove retirees from ALL term stocks
        for ty in list(new_term_stocks.keys()):
            ts = new_term_stocks[ty]
            nz_ei, nz_ai = np.nonzero(ts > 1e-10)
            if len(nz_ei) == 0:
                continue

            nz_age = nz_ai + min_age
            nz_ea = ea_arr_int[nz_ei]
            orig_ta = nz_age - (year - ty)
            entry_year_member = year - (nz_age - nz_ea)

            # Look up retire probabilities for nonzero cells
            ret_probs = np.array([
                retire_lookup.get(
                    (int(entry_year_member[k]), int(nz_ea[k]),
                     int(orig_ta[k]), int(nz_age[k])), 0)
                for k in range(len(nz_ei))
            ])

            has_ret = ret_probs > 0
            if not has_ret.any():
                continue

            ret_ei = nz_ei[has_ret]
            ret_ai = nz_ai[has_ret]
            retire_amounts_vals = ts[ret_ei, ret_ai] * ret_probs[has_ret]
            ts[ret_ei, ret_ai] -= retire_amounts_vals

            key = (ty, year)
            if key not in new_retire_stocks:
                new_retire_stocks[key] = np.zeros((n_entry, n_ages))
            new_retire_stocks[key][ret_ei, ret_ai] += retire_amounts_vals

        # 8. Age existing retire stocks with retiree mortality
        new_retire_stocks_all = {}
        for (ty, ry), rs in retire_stocks.items():
            rs = rs * ret_surv_by_year[:, surv_year]  # retirees always use retiree mortality
            new_retire_stocks_all[(ty, ry)] = rs @ TM

        # Merge new retirees
        for key, rs in new_retire_stocks.items():
            if key in new_retire_stocks_all:
                new_retire_stocks_all[key] += rs
            else:
                new_retire_stocks_all[key] = rs

        retire_stocks = new_retire_stocks_all

        # Record term and retire stocks
        for ty, ts in new_term_stocks.items():
            all_term.extend(_record_matrix(ts, year, extra_cols=(ty,)))

        for (ty, ry), rs in retire_stocks.items():
            all_retire.extend(_record_matrix(rs, year, extra_cols=(ty, ry)))

        term_stocks = new_term_stocks

    return {
        "wf_active": pd.DataFrame(all_active, columns=["entry_age", "age", "year", "n_active"]),
        "wf_term": pd.DataFrame(all_term, columns=["entry_age", "age", "year", "term_year", "n_term"]),
        "wf_retire": pd.DataFrame(all_retire, columns=["entry_age", "age", "year", "term_year", "retire_year", "n_retire"]),
        "wf_refund": pd.DataFrame(all_refund, columns=["entry_age", "age", "year", "term_year", "n_refund"]),
    }
