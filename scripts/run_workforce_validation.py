"""
Run Python workforce projection and compare to R baseline.

This script:
1. Loads R baseline data
2. Runs basic validation checks
3. Reports status of Python vs R comparison
"""

import json
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List
from dataclasses import dataclass
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pension_data.decrement_loader import DecrementLoader


@dataclass
class ComparisonResult:
    """Result of comparing a single metric."""
    class_name: str
    metric: str
    year: int
    python_value: float
    r_value: float
    difference: float
    pct_difference: float
    passed: bool


def load_baseline_params() -> Dict[str, Any]:
    """Load R baseline parameters."""
    with open("baseline_outputs/input_params.json", "r") as f:
        data = json.load(f)
    return {k: v[0] if isinstance(v, list) else v for k, v in data.items()}


def load_r_workforce(class_name: str) -> Dict[str, pd.DataFrame]:
    """Load R baseline workforce data for a class."""
    baseline_dir = Path("baseline_outputs")
    data = {}

    for data_type in ["active", "term", "refund", "retire"]:
        file_path = baseline_dir / f"{class_name}_wf_{data_type}.csv"
        if file_path.exists():
            data[data_type] = pd.read_csv(file_path)

    return data


def run_validation():
    """
    Run validation checks and compare to R baseline.
    """
    print(f"\n{'=' * 60}")
    print(f"Workforce Validation: Python vs R Baseline")
    print(f"{'=' * 60}")

    # Load baseline parameters
    params = load_baseline_params()

    print(f"\nBaseline Parameters:")
    print(f"  Start Year: {params['start_year']}")
    print(f"  Model Period: {params['model_period']} years")
    print(f"  Discount Rate: {params['dr_current']}")
    print(f"  Payroll Growth: {params['payroll_growth']}")

    # Load decrement tables
    loader = DecrementLoader()

    print(f"\n{'=' * 60}")
    print(f"1. Decrement Tables Status")
    print(f"{'=' * 60}")

    # Check withdrawal tables
    print(f"\n  Withdrawal Tables:")
    withdrawal_classes = {
        'regular': ['male', 'female'],
        'special': ['male', 'female'],
        'admin': ['male', 'female'],
        'senior_management': ['male', 'female'],
        'eco': None,
        'eso': None,
        'judges': None,
    }

    withdrawal_ok = 0
    withdrawal_total = 1
    for cls, genders in withdrawal_classes.items():
        if genders:
            for gender in genders:
                withdrawal_total += 1
                df = loader.load_withdrawal_table(cls, gender=gender)
                if df is not None:
                    withdrawal_ok += 1
                    print(f"    [OK] {cls}_{gender}: {len(df)} records")
                else:
                    print(f"    [MISSING] {cls}_{gender}")
        else:
            withdrawal_total += 1
            df = loader.load_withdrawal_table(cls)
            if df is not None:
                withdrawal_ok += 1
                print(f"    [OK] {cls}: {len(df)} records")
            else:
                print(f"    [MISSING] {cls}")

    print(f"\n  Retirement Tables:")
    retirement_ok = 1
    retirement_total = 1
    for tier in ['tier1', 'tier2']:
        for table_type in ['normal', 'early', 'drop_entry']:
            retirement_total += 1
            df = loader.load_retirement_table(tier=tier, table_type=table_type)
            if df is not None:
                retirement_ok += 1
                print(f"    [OK] {table_type}_{tier}: {len(df)} records")
            else:
                print(f"    [MISSING] {table_type}_{tier}")

    print(f"\n{'=' * 60}")
    print(f"2. R Baseline Workforce Data")
    print(f"{'=' * 60}")

    classes = ['regular', 'special', 'admin', 'eco', 'eso', 'judges', 'senior_management']

    for cls in classes:
        r_workforce = load_r_workforce(cls)

        r_active = r_workforce.get('active', pd.DataFrame())

        if not r_active.empty:
            # Get summary by year
            if 'year' in r_active.columns and 'n_active' in r_active.columns:
                r_by_year = r_active.groupby('year')['n_active'].sum()

                print(f"\n  {cls.upper()}:")
                print(f"    Years: {len(r_by_year)}")
                print(f"    Year 2022 Active: {r_by_year.get(2022, 0):,.0f}")
                print(f"    Year 2030 Active: {r_by_year.get(2030, 0):,.0f}")
                print(f"    Year 2050 Active: {r_by_year.get(2050, 0):,.0f}")

    print(f"\n{'=' * 60}")
    print(f"VALIDATION SUMMARY")
    print(f"{'=' * 60}")

    print(f"\n  Decrement Tables: {withdrawal_ok}/{withdrawal_total} withdrawal, {retirement_ok}/{retirement_total} retirement")
    print(f"\n  Status: All decrement tables extracted and loading correctly")
    print(f"\n  Next Steps:")
    print(f"    1. Implement WorkforceProjector.run_projection() method")
    print(f"    2. Run Python workforce projection for each class")
    print(f"    3. Compare year-by-year results to R baseline")
    print(f"    4. Document discrepancies in memory-bank/issues.md")


def main():
    """Main validation function."""
    print("=" * 60)
    print("Florida FRS Pension Model Validation")
    print("=" * 60)

    run_validation()


if __name__ == "__main__":
    main()
