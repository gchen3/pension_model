"""
Validate Python benefit/liability calculations against R baseline.

Strategy: Rather than running the full Python model pipeline, directly replicate
the R model's calculation flow using R baseline data, and compare outputs.

R model flow for active members:
1. Load mortality table (entry_year, entry_age, dist_year, dist_age, mort_final)
2. Calculate annuity factors (cum_mort * cum_cola / cum_dr)
3. Calculate db_benefit = yos * ben_mult * fas * reduce_factor * cal_factor
4. Calculate pvfb_db_at_term_age = db_benefit * ann_factor_term
5. Calculate PVFB at current age using get_pvfb() with separation rates
6. Calculate PVFS at current age using get_pvfs()
7. NC rate = PVFB_entry / PVFS_entry (at yos=0)
8. AAL_active = PVFB - PVFNC (where PVFNC = NC_rate * PVFS)
"""

import sys
import json
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def load_r_baseline(class_name: str, baseline_dir: str = "baseline_outputs"):
    """Load all R baseline data for a class."""
    base = Path(baseline_dir)
    data = {}

    # Liability summary (target values)
    liability_file = base / f"{class_name}_liability.csv"
    if liability_file.exists():
        data['liability'] = pd.read_csv(liability_file)

    # Active workforce
    active_file = base / f"{class_name}_wf_active.csv"
    if active_file.exists():
        data['active'] = pd.read_csv(active_file)

    # Mortality rates
    mort_file = base / f"{class_name}_mortality_rates.csv"
    if mort_file.exists():
        data['mortality'] = pd.read_csv(mort_file)

    # Separation tables
    sep_file = base / f"separation_tables/separation_{class_name}.csv"
    if sep_file.exists():
        data['separation'] = pd.read_csv(sep_file)

    # Entrant profile
    ep_file = base / f"entrant_profiles/{class_name}_entrant_profile.csv"
    if ep_file.exists():
        data['entrant_profile'] = pd.read_csv(ep_file)

    # Input params
    params_file = base / "input_params.json"
    if params_file.exists():
        with open(params_file) as f:
            data['params'] = json.load(f)

    # Calibration
    cal_file = Path("configs/calibration_params.json")
    if cal_file.exists():
        with open(cal_file) as f:
            data['calibration'] = json.load(f)

    return data


def check_r_baseline_structure(class_name: str):
    """Check what R baseline data is available and its structure."""
    data = load_r_baseline(class_name)

    print(f"\n{'='*60}")
    print(f"R Baseline Data for: {class_name.upper()}")
    print(f"{'='*60}")

    for key, df in data.items():
        if isinstance(df, pd.DataFrame):
            print(f"\n  {key}: {len(df)} rows, cols: {list(df.columns)[:8]}...")
        elif isinstance(df, dict):
            print(f"\n  {key}: {len(df)} keys")

    # Show year-1 liability targets
    if 'liability' in data:
        lib = data['liability']
        yr1 = lib[lib['year'] == 2022].iloc[0]
        print(f"\n  Year 2022 Targets:")
        print(f"    total_payroll:       ${yr1['total_payroll_est']:>20,.0f}")
        print(f"    nc_rate_db_legacy:   {yr1['nc_rate_db_legacy_est']:>20.6f}")
        print(f"    pvfb_active_legacy:  ${yr1['pvfb_active_db_legacy_est']:>20,.0f}")
        print(f"    pvfnc_legacy:        ${yr1['pvfnc_db_legacy_est']:>20,.0f}")
        print(f"    aal_active_legacy:   ${yr1['aal_active_db_legacy_est']:>20,.0f}")
        print(f"    total_aal:           ${yr1['total_aal_est']:>20,.0f}")
        print(f"    total_n_active:      {yr1['total_n_active']:>20,.0f}")

    # Check mortality table structure
    if 'mortality' in data:
        mort = data['mortality']
        print(f"\n  Mortality table:")
        print(f"    Columns: {list(mort.columns)}")
        print(f"    entry_year range: {mort['entry_year'].min()}-{mort['entry_year'].max()}")
        print(f"    entry_age unique: {sorted(mort['entry_age'].unique())[:5]}...")
        print(f"    dist_age range: {mort['dist_age'].min()}-{mort['dist_age'].max()}")
        # Check unique tiers
        if 'tier_at_dist_age' in mort.columns:
            print(f"    tiers: {mort['tier_at_dist_age'].unique()[:6]}")

    return data


def compare_payroll(data: dict, class_name: str):
    """
    Compare payroll calculation.

    R computes: payroll = sum(salary * n_active) for each plan design
    This is the simplest check - just salary * headcount from active workforce.
    """
    if 'active' not in data or 'liability' not in data:
        print("  Missing active or liability data")
        return

    active = data['active']
    liability = data['liability']

    # Get year 2022 active workforce
    active_2022 = active[active['year'] == 2022].copy()

    print(f"\n  Active 2022: {len(active_2022)} rows, total n_active={active_2022['n_active'].sum():,.0f}")

    # Check if salary data is in the active table
    print(f"  Active columns: {list(active_2022.columns)}")

    if 'salary' in active_2022.columns:
        total_payroll = (active_2022['salary'] * active_2022['n_active']).sum()
        r_payroll = liability[liability['year'] == 2022]['total_payroll_est'].iloc[0]
        pct_diff = abs(total_payroll - r_payroll) / r_payroll * 100
        print(f"  Python payroll: ${total_payroll:>20,.0f}")
        print(f"  R payroll:      ${r_payroll:>20,.0f}")
        print(f"  Difference:     {pct_diff:.2f}%")
    else:
        print("  No salary column in active workforce data")
        # Check if there's salary data in mortality or elsewhere
        if 'mortality' in data and 'salary' in data['mortality'].columns:
            print("  (salary found in mortality table)")


def check_benefit_data_availability(data: dict, class_name: str):
    """
    Check if the R baseline includes pre-computed benefit/PVFB data.

    The R model computes benefit data in the benefit model step and passes it
    to the liability model. We need to check if any of that intermediate data
    was extracted.
    """
    base = Path("baseline_outputs")

    # Check for benefit-related files
    possible_files = [
        f"{class_name}_benefit_data.csv",
        f"{class_name}_benefit_table.csv",
        f"{class_name}_ann_factor.csv",
        f"{class_name}_pvfb.csv",
    ]

    print(f"\n  Checking for benefit intermediate data:")
    for fname in possible_files:
        fpath = base / fname
        if fpath.exists():
            df = pd.read_csv(fpath, nrows=3)
            print(f"    FOUND: {fname} - cols: {list(df.columns)[:8]}")
        else:
            print(f"    NOT FOUND: {fname}")

    # Check liability_summary JSON
    summary_file = base / f"{class_name}_liability_summary.json"
    if summary_file.exists():
        with open(summary_file) as f:
            summary = json.load(f)
        print(f"\n  Liability summary JSON keys: {list(summary.keys())[:10]}")

    # Check what the R extraction script saved
    print(f"\n  All files matching '{class_name}_*':")
    for f in sorted(base.glob(f"{class_name}_*")):
        size = f.stat().st_size
        print(f"    {f.name} ({size:,} bytes)")


def main():
    """Run benefit/liability validation."""
    print("=" * 70)
    print("Florida FRS - Benefit/Liability Validation Against R Baseline")
    print("=" * 70)

    classes = ['regular', 'special', 'admin', 'eco', 'eso', 'judges', 'senior_management']

    # First, check what data we have for regular class (our primary test case)
    print("\n" + "=" * 70)
    print("PHASE 1: Data Availability Check")
    print("=" * 70)

    for cls in ['regular']:
        data = check_r_baseline_structure(cls)
        check_benefit_data_availability(data, cls)
        compare_payroll(data, cls)

    # Show summary for all classes
    print("\n" + "=" * 70)
    print("PHASE 2: Year 2022 Liability Targets (All Classes)")
    print("=" * 70)

    print(f"\n{'Class':<20} {'Payroll':>15} {'NC Rate':>10} {'PVFB Active':>18} {'AAL Active':>18} {'Total AAL':>18}")
    print("-" * 100)

    for cls in classes:
        lib_file = Path(f"baseline_outputs/{cls}_liability.csv")
        if lib_file.exists():
            lib = pd.read_csv(lib_file)
            yr1 = lib[lib['year'] == 2022].iloc[0]
            print(f"{cls:<20} ${yr1['total_payroll_est']/1e9:>13.2f}B {yr1['nc_rate_db_legacy_est']:>9.4f} "
                  f"${yr1['pvfb_active_db_legacy_est']/1e9:>16.2f}B "
                  f"${yr1['aal_active_db_legacy_est']/1e9:>16.2f}B "
                  f"${yr1['total_aal_est']/1e9:>16.2f}B")


if __name__ == "__main__":
    main()
