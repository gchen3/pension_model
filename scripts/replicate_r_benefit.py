"""
Replicate R model's benefit/liability calculation for Regular class.

This script implements the R model's exact calculation flow:
1. Build salary_benefit_table (entry_year × entry_age × yos)
2. Calculate annuity factors from mortality table
3. Calculate db_benefit = yos * ben_mult * fas * reduce_factor * cal_factor
4. Calculate PVFB using get_pvfb()
5. Calculate PVFS using get_pvfs()
6. NC rate = PVFB_entry / PVFS_entry
7. Compare to R liability CSV

Uses R baseline data directly (mortality tables, separation rates).
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import json

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def npv(rate, cashflows):
    """Net present value - matches R's FinCal::npv or basic NPV."""
    if len(cashflows) == 0:
        return 0.0
    factors = (1 + rate) ** (-np.arange(1, len(cashflows) + 1))
    return np.sum(np.array(cashflows) * factors)


def get_pvfb(sep_rate_vec, interest_vec, value_vec):
    """
    Replicate R's get_pvfb function from utility_functions.R lines 226-238.

    For each age i, calculates:
    PVFB[i] = sum over future ages of (pension_wealth * separation_probability / discount)
    """
    n = len(value_vec)
    PVFB = np.zeros(n)

    for i in range(n):
        sep_rate = sep_rate_vec[i:]
        # sep_prob = cumprod(1 - lag(sep_rate, n=2, default=0)) * lag(sep_rate, default=0)
        # This is: probability of surviving to age t and separating at age t
        lagged_1 = np.concatenate([[0], sep_rate[:-1]])
        lagged_2 = np.concatenate([[0, 0], sep_rate[:-2]])
        cum_surv = np.cumprod(1 - lagged_2)
        sep_prob = cum_surv * lagged_1

        interest = interest_vec[i] if isinstance(interest_vec, (list, np.ndarray)) else interest_vec
        value = value_vec[i:]
        value_adjusted = value * sep_prob

        # NPV of future adjusted values (skip first element)
        if len(value_adjusted) > 1:
            PVFB[i] = npv(interest, value_adjusted[1:])
        else:
            PVFB[i] = 0.0

    return PVFB


def get_pvfs(remaining_prob_vec, interest_vec, sal_vec):
    """
    Replicate R's get_pvfs function from utility_functions.R lines 287-298.
    """
    n = len(sal_vec)
    PVFS = np.zeros(n)

    for i in range(n):
        remaining_prob = remaining_prob_vec[i:]
        if remaining_prob[0] > 0:
            remaining_prob = remaining_prob / remaining_prob[0]

        interest = interest_vec[i] if isinstance(interest_vec, (list, np.ndarray)) else interest_vec
        sal = sal_vec[i:]
        sal_adjusted = sal * remaining_prob

        PVFS[i] = npv(interest, sal_adjusted)

    return PVFS


def main():
    print("=" * 70)
    print("Replicate R Model Benefit Calculation - Regular Class")
    print("=" * 70)

    # Load parameters
    with open("baseline_outputs/input_params.json") as f:
        params = json.load(f)
    with open("configs/calibration_params.json") as f:
        cal = json.load(f)

    dr_current = params['dr_current'][0]
    cal_factor = cal['global_calibration']['cal_factor']
    payroll_growth = params['payroll_growth'][0]
    cola_tier_1 = params['cola_tier_1_active'][0]

    print(f"  dr_current: {dr_current}")
    print(f"  cal_factor: {cal_factor}")
    print(f"  payroll_growth: {payroll_growth}")
    print(f"  cola_tier_1: {cola_tier_1}")

    # Load mortality table
    print("\nLoading mortality table...")
    mort = pd.read_csv("baseline_outputs/regular_mortality_rates.csv")
    print(f"  Loaded {len(mort):,} rows")

    # Load separation table
    print("Loading separation table...")
    sep = pd.read_csv("baseline_outputs/separation_tables/separation_regular.csv")
    print(f"  Loaded {len(sep):,} rows")

    # Load active workforce (to get entry_age distribution for year 2022)
    active = pd.read_csv("baseline_outputs/regular_wf_active.csv")
    active_2022 = active[active['year'] == 2022].copy()
    print(f"  Active 2022: {len(active_2022)} cohorts, {active_2022['n_active'].sum():,.0f} members")

    # Load salary/headcount
    sal_table = pd.read_csv("baseline_outputs/regular_salary.csv")
    hc_table = pd.read_csv("baseline_outputs/regular_headcount.csv")
    sal_growth = pd.read_csv("baseline_outputs/salary_growth_table.csv")

    # Load entrant profile
    entrant = pd.read_csv("baseline_outputs/entrant_profiles/regular_entrant_profile.csv")

    # R target values
    r_liability = pd.read_csv("baseline_outputs/regular_liability.csv")
    r_yr1 = r_liability[r_liability['year'] == 2022].iloc[0]

    print(f"\n  R Targets (Year 2022):")
    print(f"    NC rate:      {r_yr1['nc_rate_db_legacy_est']:.6f}")
    print(f"    PVFB active:  ${r_yr1['pvfb_active_db_legacy_est']:,.0f}")
    print(f"    AAL active:   ${r_yr1['aal_active_db_legacy_est']:,.0f}")
    print(f"    Total payroll:${r_yr1['total_payroll_est']:,.0f}")

    # Test: pick a single cohort and trace through the calculation
    # Entry year 2000, entry age 20, so in 2022 they're age 42 with 22 YOS
    test_entry_year = 2000
    test_entry_age = 20
    test_age_2022 = test_entry_age + (2022 - test_entry_year)  # 42
    test_yos = test_age_2022 - test_entry_age  # 22

    print(f"\n{'='*70}")
    print(f"TRACE: Single Cohort (entry_year={test_entry_year}, entry_age={test_entry_age})")
    print(f"  In 2022: age={test_age_2022}, yos={test_yos}")
    print(f"{'='*70}")

    # Get mortality data for this cohort
    cohort_mort = mort[
        (mort['entry_year'] == test_entry_year) &
        (mort['entry_age'] == test_entry_age)
    ].sort_values('dist_age')

    print(f"\n  Mortality rows: {len(cohort_mort)}")
    if len(cohort_mort) > 0:
        print(f"  dist_age range: {cohort_mort['dist_age'].min()}-{cohort_mort['dist_age'].max()}")
        print(f"  Tiers: {cohort_mort['tier_at_dist_age'].unique()}")
        print(f"  Sample mort rates (age 40-50):")
        sample = cohort_mort[(cohort_mort['dist_age'] >= 40) & (cohort_mort['dist_age'] <= 50)]
        for _, row in sample.iterrows():
            print(f"    age {int(row['dist_age'])}: qx={row['mort_final']:.6f}, tier={row['tier_at_dist_age']}")

    # Get separation data for this cohort
    cohort_sep = sep[
        (sep['entry_year'] == test_entry_year) &
        (sep['entry_age'] == test_entry_age)
    ].sort_values('term_age')

    print(f"\n  Separation rows: {len(cohort_sep)}")
    if len(cohort_sep) > 0:
        print(f"  term_age range: {cohort_sep['term_age'].min()}-{cohort_sep['term_age'].max()}")
        print(f"  Sample separation rates (age 40-50):")
        sample = cohort_sep[(cohort_sep['term_age'] >= 40) & (cohort_sep['term_age'] <= 50)]
        for _, row in sample.iterrows():
            print(f"    age {int(row['term_age'])}: rate={row['separation_rate']:.6f}, tier={row['tier']}")

    # Get salary growth for this cohort
    sg_reg = sal_growth[['yos', 'salary_increase_regular']].copy()
    sg_reg['cumprod_growth'] = (1 + sg_reg['salary_increase_regular'].shift(1, fill_value=0)).cumprod()

    # Get entry salary from entrant profile
    entry_sal_row = entrant[entrant['entry_age'] == test_entry_age]
    if len(entry_sal_row) > 0:
        entry_salary = entry_sal_row['start_sal'].iloc[0]
    else:
        entry_salary = 25000  # fallback

    # Project salary for each YOS
    max_yos = len(sg_reg)
    salary_vec = np.array([
        entry_salary * sg_reg.iloc[min(y, max_yos-1)]['cumprod_growth'] * (1 + payroll_growth) ** max(0, test_entry_year - 2022 + y)
        for y in range(100)
    ])

    print(f"\n  Entry salary: ${entry_salary:,.0f}")
    print(f"  Salary at yos=0: ${salary_vec[0]:,.0f}")
    print(f"  Salary at yos=22: ${salary_vec[22]:,.0f}")
    print(f"  Salary at yos=30: ${salary_vec[30]:,.0f}")

    # Calculate FAS (5-year average for tier 1)
    fas_period = 5
    for yos in [22, 30, 40]:
        if yos >= fas_period:
            fas = np.mean(salary_vec[yos-fas_period:yos])
            print(f"  FAS at yos={yos}: ${fas:,.0f}")

    print(f"\n{'='*70}")
    print(f"DATA AVAILABILITY SUMMARY")
    print(f"{'='*70}")
    print(f"  Mortality table:    {len(mort):>10,} rows  ✓")
    print(f"  Separation table:   {len(sep):>10,} rows  ✓")
    print(f"  Salary growth:      {len(sal_growth):>10,} rows  ✓")
    print(f"  Entrant profile:    {len(entrant):>10,} rows  ✓")
    print(f"  Active workforce:   {len(active_2022):>10,} rows  ✓")
    print(f"  Salary input table: {sal_table.shape[0]:>10,} rows  ✓")
    print(f"  Headcount input:    {hc_table.shape[0]:>10,} rows  ✓")

    print(f"\n  To fully replicate R's benefit calculation, we need to:")
    print(f"  1. Build salary_benefit_table: expand_grid(entry_year, entry_age, yos)")
    print(f"  2. Merge with salary growth and compute salary at each yos")
    print(f"  3. Compute FAS (5-year or 8-year rolling mean)")
    print(f"  4. Compute benefit multipliers and db_benefit * cal_factor")
    print(f"  5. Compute annuity factors from mortality table")
    print(f"  6. Compute PVFB using get_pvfb()")
    print(f"  7. Compute PVFS using get_pvfs()")
    print(f"  8. NC rate = PVFB_entry / PVFS_entry")
    print(f"  9. Aggregate across all active members weighted by n_active")


if __name__ == "__main__":
    main()
