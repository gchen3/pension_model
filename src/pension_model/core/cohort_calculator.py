"""
Per-cohort actuarial calculations.

For each (entry_age, entry_year) cohort, computes the full benefit/liability
vector along the age/yos axis using 1D vectorized operations.

This replaces the R model's approach of materializing 3M-row cross-product
tables. Each cohort's computation is O(n_ages), not O(n_ages²).

Key functions:
  compute_cohort_benefits() - salary, FAS, benefit, PVFB, PVFS, NC for one cohort
  compute_cohort_annuity_factors() - annuity factors and cum_mort_dr for one cohort
"""

import numpy as np
from typing import Callable

from pension_model.core.compact_mortality import CompactMortality


def compute_cohort_salary(
    entry_age: int,
    entry_year: int,
    entry_salary: float,
    salary_growth_cumprod: np.ndarray,
    max_yos: int,
    payroll_growth: float,
    max_hist_year: int,
    start_sal: float,
) -> np.ndarray:
    """
    Compute salary vector for a cohort (one value per yos from 0 to max_yos).

    For historical cohorts (entry_year <= max_hist_year):
      salary[yos] = entry_salary * cumprod_growth[yos]
    For future cohorts:
      salary[yos] = start_sal * cumprod_growth[yos] * (1+payroll_growth)^(entry_year - max_hist_year)
    """
    n = min(max_yos + 1, len(salary_growth_cumprod))
    growth = salary_growth_cumprod[:n]

    if entry_year <= max_hist_year:
        return entry_salary * growth
    else:
        payroll_adj = (1 + payroll_growth) ** (entry_year - max_hist_year)
        return start_sal * growth * payroll_adj


def compute_cohort_fas(salary: np.ndarray, fas_period: int) -> np.ndarray:
    """
    Compute FAS (final average salary) using lagged rolling mean.

    FAS[t] = mean(salary[t-fas_period : t]). NaN where t < 1.
    """
    n = len(salary)
    fas = np.full(n, np.nan)
    for t in range(1, n):
        start = max(0, t - fas_period)
        fas[t] = salary[start:t].mean()
    return fas


def compute_cohort_db_ee_balance(salary: np.ndarray, ee_cont_rate: float,
                                  ee_interest_rate: float) -> np.ndarray:
    """
    Compute employee contribution balance.

    balance[0] = 0
    balance[i] = balance[i-1] * (1+rate) + contribution[i-1]
    """
    n = len(salary)
    contrib = ee_cont_rate * salary
    balance = np.zeros(n)
    for i in range(1, n):
        balance[i] = balance[i - 1] * (1 + ee_interest_rate) + contrib[i - 1]
    return balance


def compute_cohort_annuity_factors(
    entry_age: int,
    entry_year: int,
    max_yos: int,
    mortality: CompactMortality,
    constants,
    get_tier: Callable,
    class_name: str,
) -> dict:
    """
    Compute annuity factors and cumulative survival-discount for one cohort.

    For each yos (termination age = entry_age + yos), computes:
      - The annuity factor at the distribution age (for retirees)
      - cum_mort_dr at each future age (for discounting term vested PVFB)

    Returns dict with:
      'ann_factor_at_dist': array[max_yos+1] — annuity factor at distribution age
      'cum_mort_dr': 2D array[max_yos+1, max_dist_ages] — survival-discount from term to dist
      'dist_age': array[max_yos+1] — chosen distribution age for each yos
      'db_benefit_factor': array[max_yos+1] — yos * ben_mult * reduce_factor * cal_factor
    """
    econ = constants.economic
    ben = constants.benefit
    r = constants.ranges

    n_yos = max_yos + 1
    max_age = r.max_age

    # COLA depends on tier (computed per yos)
    dr_current = econ.dr_current
    dr_new = econ.dr_new

    # For each yos, determine tier, COLA, discount rate
    ann_factor_at_term = np.zeros(n_yos)
    dist_ages = np.zeros(n_yos, dtype=int)

    for yos in range(n_yos):
        term_age = entry_age + yos
        if term_age > max_age:
            continue

        term_year = entry_year + yos
        tier = get_tier(class_name, entry_year, term_age, yos, r.new_year)
        dr = dr_new if "tier_3" in tier else dr_current

        # Determine distribution age
        # Vested: defer to earliest normal retirement age
        # Retiree/non-vested: distribute at term_age
        from pension_model.plan_config import get_sep_type
        sep_type = get_sep_type(tier)
        is_special = class_name in ("special", "admin")

        if sep_type == "vested":
            # Find earliest normal retirement age
            if "tier_1" in tier:
                nra = 55 if is_special else 62
                nra_yos = 6
            else:
                nra = 60 if is_special else 65
                nra_yos = 8
            # Earliest age where normal retirement is reached
            # Either age >= nra with enough yos, or yos reaches threshold
            if "tier_1" in tier:
                yos_threshold = 25 if is_special else 30
            else:
                yos_threshold = 30 if is_special else 33
            # dist_age is the age when first eligible for norm retirement
            # given current yos at termination
            if yos >= yos_threshold:
                dist_ages[yos] = term_age  # already eligible by yos
            elif yos >= nra_yos:
                dist_ages[yos] = max(term_age, nra)  # wait until NRA
            else:
                dist_ages[yos] = term_age  # won't vest — shouldn't get here
        else:
            dist_ages[yos] = term_age

        dist_age = dist_ages[yos]
        if dist_age <= 0 or dist_age > max_age:
            continue

        # Compute annuity factor at distribution age
        # ä = Σ_{t=0}^{max-dist} survival(t) × discount(t) × cola(t)
        dist_year = term_year + (dist_age - term_age)
        n_future = max_age - dist_age + 1

        # COLA rate for this cohort
        if "tier_1" in tier:
            if ben.cola_tier_1_active_constant:
                cola = ben.cola_tier_1_active
            else:
                yos_b4_2011 = min(max(2011 - entry_year, 0), yos)
                cola = ben.cola_tier_1_active * yos_b4_2011 / yos if yos > 0 else 0
        elif "tier_2" in tier:
            cola = ben.cola_tier_2_active
        else:
            cola = ben.cola_tier_3_active

        # Build survival × discount × cola vector from dist_age to max_age
        future_ages = np.arange(dist_age, max_age + 1)
        future_years = np.arange(dist_year, dist_year + len(future_ages))
        future_years = np.clip(future_years, mortality.min_year, mortality.max_year)

        # Determine if member is retiree at dist_age
        is_retiree = sep_type == "retire" or sep_type == "vested"
        mort_rates = mortality.get_rates_vec(future_ages, future_years, is_retiree)

        # cum_mort = cumprod(1 - lag(mort, default=0))
        cum_mort = np.cumprod(np.concatenate([[1.0], 1 - mort_rates[:-1]]))
        cum_dr = (1 + dr) ** np.arange(len(future_ages))
        cum_cola = (1 + cola) ** np.arange(len(future_ages))

        cum_mort_dr_cola = cum_mort / cum_dr * cum_cola

        # ann_factor = reverse_cumsum(cum_mort_dr_cola) / cum_mort_dr_cola
        rev_cumsum = np.flip(np.cumsum(np.flip(cum_mort_dr_cola)))
        ann_factor_vec = rev_cumsum / cum_mort_dr_cola

        # ann_factor at dist_age (index 0)
        ann_factor_at_dist = ann_factor_vec[0]

        # ann_factor_term = ann_factor * cum_mort_dr at term_age
        # cum_mort_dr from term_age to dist_age
        cum_mort_dr = cum_mort[0] / cum_dr[0]  # = 1.0 at dist_age itself
        if dist_age > term_age:
            # Need survival from term_age to dist_age
            transit_ages = np.arange(term_age, dist_age)
            transit_years = np.arange(term_year, term_year + len(transit_ages))
            transit_years = np.clip(transit_years, mortality.min_year, mortality.max_year)
            transit_mort = mortality.get_rates_vec(transit_ages, transit_years, is_retiree=False)
            transit_surv = np.prod(1 - transit_mort)
            transit_disc = (1 + dr) ** (dist_age - term_age)
            cum_mort_dr_at_term = transit_surv / transit_disc
            ann_factor_at_term[yos] = ann_factor_at_dist * cum_mort_dr_at_term
        else:
            ann_factor_at_term[yos] = ann_factor_at_dist

    return {
        "ann_factor_at_term": ann_factor_at_term,
        "dist_ages": dist_ages,
    }


def compute_cohort_benefits(
    entry_age: int,
    entry_year: int,
    salary: np.ndarray,
    fas: np.ndarray,
    db_ee_balance: np.ndarray,
    ann_factors: dict,
    sep_rates: np.ndarray,
    remaining_prob: np.ndarray,
    constants,
    class_name: str,
    get_tier: Callable,
    get_ben_mult: Callable,
    get_reduce_factor: Callable,
) -> dict:
    """
    Compute PVFB, PVFS, NC for one cohort.

    This is the core per-cohort computation that replaces the R model's
    materialized benefit_val_table.

    Returns dict with arrays indexed by yos:
      salary, fas, db_benefit, pvfb_at_term, pvfb_wealth_at_term,
      pvfb_at_current, pvfs_at_current, indv_norm_cost, pvfnc
    """
    from pension_model.plan_config import get_sep_type

    r = constants.ranges
    econ = constants.economic
    ben = constants.benefit
    cal = ben.cal_factor
    rrr = ben.retire_refund_ratio

    n = len(salary)
    max_yos = n - 1

    # Compute db_benefit for each yos at the distribution age
    db_benefit = np.zeros(n)
    pvfb_at_term = np.zeros(n)
    pvfb_wealth_at_term = np.zeros(n)

    ann_factor_at_term = ann_factors["ann_factor_at_term"]
    dist_ages = ann_factors["dist_ages"]

    for yos in range(n):
        term_age = entry_age + yos
        if term_age > r.max_age:
            continue

        tier = get_tier(class_name, entry_year, term_age, yos, r.new_year)
        dist_age = dist_ages[yos]
        if dist_age <= 0:
            continue

        # Benefit at distribution age
        dist_year = entry_year + (dist_age - entry_age)
        bm = get_ben_mult(class_name, tier, dist_age, yos, dist_year)
        rf = get_reduce_factor(class_name, tier, dist_age)

        if np.isnan(bm) or np.isnan(rf):
            db_benefit[yos] = 0
        else:
            # FAS at term_age (yos index)
            f = fas[yos] if yos < len(fas) and not np.isnan(fas[yos]) else 0
            db_benefit[yos] = yos * bm * f * rf * cal

        # pvfb_db_at_term_age = db_benefit * ann_factor_term
        pvfb_at_term[yos] = db_benefit[yos] * ann_factor_at_term[yos]

        # Wealth at termination: mix of annuity and refund
        sep_type = get_sep_type(tier)
        if sep_type == "retire":
            pvfb_wealth_at_term[yos] = pvfb_at_term[yos]
        elif sep_type == "vested":
            pvfb_wealth_at_term[yos] = (rrr * pvfb_at_term[yos]
                                        + (1 - rrr) * db_ee_balance[yos])
        else:  # non_vested
            pvfb_wealth_at_term[yos] = db_ee_balance[yos]

    # Compute PVFB at current age (discount wealth back from term to current)
    dr_vec = np.full(n, econ.dr_current)
    for yos in range(n):
        tier = get_tier(class_name, entry_year, entry_age + yos, yos, r.new_year)
        if "tier_3" in tier:
            dr_vec[yos] = econ.dr_new

    pvfb_current = _get_pvfb(sep_rates, dr_vec, pvfb_wealth_at_term)
    pvfs_current = _get_pvfs(remaining_prob, dr_vec, salary)

    nc_rate = pvfb_current[0] / pvfs_current[0] if pvfs_current[0] > 0 else 0
    pvfnc = nc_rate * pvfs_current

    return {
        "salary": salary,
        "fas": fas,
        "db_benefit": db_benefit,
        "pvfb_at_term": pvfb_at_term,
        "pvfb_wealth_at_term": pvfb_wealth_at_term,
        "pvfb_at_current": pvfb_current,
        "pvfs_at_current": pvfs_current,
        "indv_norm_cost": nc_rate,
        "pvfnc": pvfnc,
    }


def _npv(rate: float, cashflows: np.ndarray) -> float:
    """R's npv(): sum of cashflows[i] / (1+rate)^(i+1)."""
    if len(cashflows) == 0:
        return 0.0
    disc = (1 + rate) ** np.arange(1, len(cashflows) + 1)
    return (cashflows / disc).sum()


def _get_pvfb(sep_rate: np.ndarray, dr: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Present value of future benefits at each yos (replicates R's get_pvfb)."""
    n = len(sep_rate)
    pvfb = np.zeros(n)
    for i in range(n):
        sr = sep_rate[i:]
        m = len(sr)
        lag2 = np.zeros(m)
        if m > 2:
            lag2[2:] = sr[:-2]
        cum_surv = np.cumprod(1 - lag2)
        lag1 = np.zeros(m)
        if m > 1:
            lag1[1:] = sr[:-1]
        sep_prob = cum_surv * lag1
        val = values[i:]
        val_adjusted = val * sep_prob
        pvfb[i] = _npv(dr[i], val_adjusted[1:])
    return pvfb


def _get_pvfs(remaining_prob: np.ndarray, dr: np.ndarray, salary: np.ndarray) -> np.ndarray:
    """Present value of future salary at each yos (replicates R's get_pvfs)."""
    n = len(remaining_prob)
    pvfs = np.zeros(n)
    for i in range(n):
        rp = remaining_prob[i:]
        rp_norm = rp / rp[0] if rp[0] > 0 else rp
        sal = salary[i:]
        sal_adjusted = sal * rp_norm
        pvfs[i] = _npv(dr[i], sal_adjusted)
    return pvfs
