"""
Streaming workforce projection.

Streaming workforce projection engine (generic, config-driven).

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
    max_age = constants.max_age if constants is not None else 120
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
    # refund_prob_arr[entry_age_idx, term_age_idx, term_year_idx] -> refund probability
    # retire_prob_arr[term_year_idx, entry_age_idx, dist_age_idx, dist_year_idx] -> retire probability
    refund_prob_arr = np.zeros((n_entry, n_ages, n_years))
    retire_prob_arr = np.zeros((n_years, n_entry, n_ages, n_years))

    if len(benefit_decisions) > 0:
        bd = benefit_decisions
        bd_ey = bd["entry_year"].values.astype(int)
        bd_ea = bd["entry_age"].values.astype(int)
        bd_ta = bd["term_age"].values.astype(int) if "term_age" in bd.columns else (
            bd_ea + bd["yos"].values.astype(int))
        bd_da = bd["dist_age"].values.astype(int) if "dist_age" in bd.columns else bd_ta
        bd_dec = bd["ben_decision"].values
        bd_yos = bd["yos"].values.astype(int) if "yos" in bd.columns else (bd_ta - bd_ea)
        bd_ei = np.array([ea_to_idx.get(int(v), -1) for v in bd_ea])
        bd_ta_idx = bd_ta - min_age
        bd_da_idx = bd_da - min_age
        bd_ty_idx = bd_ey + (bd_ta - bd_ea) - start_year
        bd_dy_idx = bd_ey + (bd_da - bd_ea) - start_year

        is_refund = (bd_dec == "refund") | ((pd.isna(bd_dec)) & (bd_yos == 0))
        is_mix = bd_dec == "mix"
        is_retire = bd_dec == "retire"

        valid_refund = (
            (bd_ei >= 0)
            & (bd_ta_idx >= 0)
            & (bd_ta_idx < n_ages)
            & (bd_ty_idx >= 0)
            & (bd_ty_idx < n_years)
        )
        refund_prob_arr[
            bd_ei[valid_refund & is_refund],
            bd_ta_idx[valid_refund & is_refund],
            bd_ty_idx[valid_refund & is_refund],
        ] = 1.0
        refund_prob_arr[
            bd_ei[valid_refund & is_mix],
            bd_ta_idx[valid_refund & is_mix],
            bd_ty_idx[valid_refund & is_mix],
        ] = 1 - retire_refund_ratio

        valid_retire = (
            (bd_ei >= 0)
            & (bd_da_idx >= 0)
            & (bd_da_idx < n_ages)
            & (bd_ty_idx >= 0)
            & (bd_ty_idx < n_years)
            & (bd_dy_idx >= 0)
            & (bd_dy_idx < n_years)
        )
        retire_mask = valid_retire & (is_mix | is_retire)
        retire_prob_arr[
            bd_ty_idx[retire_mask],
            bd_ei[retire_mask],
            bd_da_idx[retire_mask],
            bd_dy_idx[retire_mask],
        ] = 1.0

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

    # --- Tier-aware mortality helper for term stocks ---
    # Deferred vested members use employee mortality until they reach a
    # retirement-eligible tier (norm/early), then switch to retiree mortality.
    # We batch-resolve tiers per term stock using resolve_tiers_vec.
    from pension_model.config_resolvers import resolve_tiers_vec as _resolve_tiers_vec, EARLY

    ea_arr_int = np.array(entry_ages, dtype=np.int64)

    # Storage: term_year -> [entry_age_idx, age_idx] matrix
    term_stocks = {}
    retire_stocks = {}

    # Helper: accumulate nonzero entries from a 2D matrix as column arrays.
    ea_grid = np.array(entry_ages)  # [n_entry]

    def _empty_record_store(value_col, extra_cols=()):
        """Return a column-oriented store for one workforce output."""
        cols = ["entry_age", "age", "year"]
        cols.extend(extra_cols)
        cols.append(value_col)
        return {col: [] for col in cols}

    def _append_matrix_records(store, matrix, year_val, value_col, extra_cols=()):
        """Append nonzero cells from a 2D [n_entry, n_ages] matrix."""
        ei_idx, ai_idx = np.nonzero(matrix > 1e-10)
        if len(ei_idx) == 0:
            return
        vals = matrix[ei_idx, ai_idx]
        eas = ea_grid[ei_idx].astype(np.int64, copy=False)
        cur_ages = (ai_idx + min_age).astype(np.int64, copy=False)
        n = len(ei_idx)
        year_arr = np.full(n, year_val, dtype=np.int64)
        store["entry_age"].append(eas)
        store["age"].append(cur_ages)
        store["year"].append(year_arr)
        for col_name, col_value in extra_cols:
            if isinstance(col_value, (int, np.integer)):
                store[col_name].append(np.full(n, col_value, dtype=np.int64))
            else:
                store[col_name].append(np.asarray(col_value))
        store[value_col].append(vals.astype(np.float64, copy=False))

    def _records_to_frame(store):
        """Build one workforce output DataFrame from accumulated arrays."""
        columns = list(store)
        first_col = columns[0]
        if not store[first_col]:
            return pd.DataFrame(columns=columns)
        data = {
            col: np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
            for col, chunks in store.items()
        }
        return pd.DataFrame(data)

    # Collect outputs
    all_active = _empty_record_store("n_active")
    all_term = _empty_record_store("n_term", extra_cols=("term_year",))
    all_retire = _empty_record_store("n_retire", extra_cols=("term_year", "retire_year"))
    all_refund = _empty_record_store("n_refund", extra_cols=("term_year",))

    # Record year 0
    _append_matrix_records(all_active, active, start_year, "n_active")

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
        _append_matrix_records(all_active, active, year, "n_active")

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
                _, ret_status = _resolve_tiers_vec(
                    constants, cn_arr, entry_yr, nz_age, yos_at_term,
                )
                is_ret = ret_status >= EARLY
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
        _append_matrix_records(
            all_refund,
            refund_amounts,
            year,
            "n_refund",
            extra_cols=(("term_year", year),),
        )

        # 7. Remove retirees from ALL term stocks
        for ty in list(new_term_stocks.keys()):
            ts = new_term_stocks[ty]
            nz_ei, nz_ai = np.nonzero(ts > 1e-10)
            if len(nz_ei) == 0:
                continue

            ty_idx = ty - start_year
            ret_probs = retire_prob_arr[ty_idx, nz_ei, nz_ai, t]

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
            _append_matrix_records(
                all_term,
                ts,
                year,
                "n_term",
                extra_cols=(("term_year", ty),),
            )

        for (ty, ry), rs in retire_stocks.items():
            _append_matrix_records(
                all_retire,
                rs,
                year,
                "n_retire",
                extra_cols=(("term_year", ty), ("retire_year", ry)),
            )

        term_stocks = new_term_stocks

    return {
        "wf_active": _records_to_frame(all_active),
        "wf_term": _records_to_frame(all_term),
        "wf_retire": _records_to_frame(all_retire),
        "wf_refund": _records_to_frame(all_refund),
    }
