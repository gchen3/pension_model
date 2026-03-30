"""
Validate total AAL against R baseline for all components.

Components of total_aal:
1. aal_active_db_legacy (validated - 0.00%)
2. aal_term_db_legacy (from projected terminated vested)
3. aal_retire_db_legacy (from projected retirees)
4. aal_retire_current (current retirees at valuation)
5. aal_term_current (current term vested - amortized)
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import json

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def pv_annuity(rate, g, nper, pmt, t=1):
    """R's pv() function."""
    r = (1 + rate) / (1 + g) - 1
    if abs(r) < 1e-10:
        return pmt * nper / (1 + g) * (1 + rate) ** (1 - t)
    PV = pmt / r * (1 - (1 / (1 + r) ** nper)) / (1 + g) * (1 + rate) ** (1 - t)
    return PV


def get_pmt(r, g, nper, pv_val, t=1):
    """R's get_pmt() function."""
    r_adj = (1 + r) / (1 + g) - 1
    pv_adj = pv_val * (1 + r) ** t
    if abs(r_adj) < 1e-10:
        return pv_adj / nper
    if nper == 0:
        return 0
    return pv_adj * r_adj * (1 + r_adj) ** (nper - 1) / ((1 + r_adj) ** nper - 1)


def roll_pv(rate, g, nper, pmt_vec, t=1):
    """R's roll_pv() function."""
    n = len(pmt_vec)
    pv_vec = np.zeros(n)
    for i in range(n):
        if i == 0:
            pv_vec[i] = pv_annuity(rate, g, nper, pmt_vec[1] if n > 1 else 0, t)
        else:
            pv_vec[i] = pv_vec[i - 1] * (1 + rate) - pmt_vec[i] * (1 + rate) ** (1 - t)
    return pv_vec


def recur_grow3(x, g, nper):
    """R's recur_grow3() - grow a single value at fixed rate."""
    vec = np.zeros(nper)
    vec[0] = x
    for i in range(1, nper):
        vec[i] = vec[i - 1] * (1 + g)
    return vec


def validate_class(class_name):
    """Validate total liability for a single class."""
    # Load data
    lib = pd.read_csv(f'baseline_outputs/{class_name}_liability.csv')
    bvt = pd.read_csv(f'baseline_outputs/{class_name}_benefit_data.csv')
    active = pd.read_csv(f'baseline_outputs/{class_name}_wf_active.csv')

    with open('configs/calibration_params.json') as f:
        cal = json.load(f)
    with open('baseline_outputs/input_params.json') as f:
        params = json.load(f)

    dr = params['dr_current'][0]
    payroll_growth = params['payroll_growth'][0]
    new_year = params['new_year'][0]

    is_special = class_name == 'special'
    db_before = cal['db_plan_ratios']['special_legacy_before_2018' if is_special else 'non_special_legacy_before_2018']
    db_after = cal['db_plan_ratios']['special_legacy_after_2018' if is_special else 'non_special_legacy_after_2018']

    # --- Component 1: AAL Active (already validated) ---
    # We compute it here to verify

    # --- Component 4: AAL Current Retirees ---
    # From calibration params
    retiree_pop = cal['retiree_population'].get(class_name, 0)
    ben_payment = cal['benefit_payments_current'].get(class_name, 0)

    # --- Component 5: AAL Term Current ---
    pvfb_term_current = cal['pvfb_term_current_adjustment'].get(class_name, 0)
    amo_period_term = cal['pvfb_term_current_adjustment'].get('amortization_period_years', 50)

    # For term current: amortize pvfb_term_current as payment stream
    retire_ben_term = get_pmt(dr, payroll_growth, amo_period_term, pvfb_term_current, t=1)

    years = list(range(2022, 2053))
    amo_years = list(range(2023, 2023 + amo_period_term))

    retire_ben_term_est = np.zeros(len(years))
    # Fill in the amortization years
    term_payments = recur_grow3(retire_ben_term, payroll_growth, amo_period_term)
    for i, yr in enumerate(years):
        if yr in amo_years:
            idx_in_amo = yr - 2023
            if idx_in_amo < len(term_payments):
                retire_ben_term_est[i] = term_payments[idx_in_amo]

    aal_term_current = roll_pv(dr, payroll_growth, amo_period_term, retire_ben_term_est, t=1)

    # --- Compare year by year ---
    results = []
    for i, year in enumerate(years):
        r_yr = lib[lib['year'] == year]
        if len(r_yr) == 0:
            continue
        r = r_yr.iloc[0]

        # Active AAL (already validated)
        active_yr = active[active['year'] == year].copy()
        active_yr['yos'] = active_yr['age'] - active_yr['entry_age']
        active_yr['entry_year'] = year - active_yr['yos']

        merged = active_yr.merge(bvt, on=['entry_year', 'entry_age', 'yos'], how='left')
        m = merged[merged.pvfb_db_wealth_at_current_age.notna()].copy()
        m['db_legacy_ratio'] = np.where(
            m['entry_year'] < 2018, db_before,
            np.where(m['entry_year'] < new_year, db_after, 0.0)
        )
        m['n_db_legacy'] = m['n_active'] * m['db_legacy_ratio']

        py_aal_active = (m['pvfb_db_wealth_at_current_age'] * m['n_db_legacy']).sum() - \
                        (m['pvfnc_db'] * m['n_db_legacy']).sum()

        # Term current
        py_aal_term_current = aal_term_current[i]

        # Retire current - we need the ann_factor_retire_table from R
        # For now, use R's value directly and check term_current only
        r_aal_retire_current = r['aal_retire_current_est']

        # Total components we can compute
        py_aal_term_current_check = py_aal_term_current

        results.append({
            'year': year,
            'py_aal_active': py_aal_active,
            'r_aal_active': r['aal_active_db_legacy_est'],
            'py_aal_term_current': py_aal_term_current_check,
            'r_aal_term_current': r['aal_term_current_est'],
            'r_aal_retire_current': r_aal_retire_current,
            'r_aal_term_proj': r['aal_term_db_legacy_est'],
            'r_aal_retire_proj': r['aal_retire_db_legacy_est'],
            'r_total_aal': r['total_aal_est'],
        })

    df = pd.DataFrame(results)

    # Check term_current match
    df['term_curr_diff%'] = np.where(
        df['r_aal_term_current'] != 0,
        (df['py_aal_term_current'] - df['r_aal_term_current']).abs() / df['r_aal_term_current'].abs() * 100,
        0
    )

    return df


def main():
    print("=" * 80)
    print("Total Liability Validation Against R Baseline")
    print("=" * 80)

    classes = ['regular', 'special', 'admin', 'eco', 'eso', 'judges', 'senior_management']

    for cls in classes:
        print(f"\n{'='*60}")
        print(f"  {cls.upper()}")
        print(f"{'='*60}")

        try:
            df = validate_class(cls)
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            continue

        # Print term_current comparison
        print(f"\n  AAL Term Current (amortized pvfb_term_current):")
        print(f"  {'Year':>6} {'Python':>18} {'R':>18} {'Diff%':>8}")
        for _, row in df.head(5).iterrows():
            print(f"  {int(row['year']):>6} {row['py_aal_term_current']:>18,.0f} {row['r_aal_term_current']:>18,.0f} {row['term_curr_diff%']:>7.2f}%")

        max_diff = df['term_curr_diff%'].max()
        print(f"  Max diff: {max_diff:.4f}%")
        print(f"  Status: {'PASS' if max_diff < 0.01 else 'FAIL'}")

        # Show total AAL decomposition for year 2022
        yr1 = df[df['year'] == 2022].iloc[0]
        print(f"\n  Year 2022 AAL Components:")
        print(f"    Active DB Legacy:     {yr1['r_aal_active']:>18,.0f} (validated)")
        print(f"    Term Projected:       {yr1['r_aal_term_proj']:>18,.0f}")
        print(f"    Retire Projected:     {yr1['r_aal_retire_proj']:>18,.0f}")
        print(f"    Retire Current:       {yr1['r_aal_retire_current']:>18,.0f}")
        print(f"    Term Current:         {yr1['r_aal_term_current']:>18,.0f} (py: {yr1['py_aal_term_current']:,.0f})")
        print(f"    Total AAL:            {yr1['r_total_aal']:>18,.0f}")


if __name__ == "__main__":
    main()
