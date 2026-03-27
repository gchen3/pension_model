"""
Run Python Pension Model validation against R baseline.

This script:
1. Loads R baseline data and parameters
2. Initializes FRS adapter with proper configuration
3. Runs Python workforce projection
4. Compares results against R baseline
5. Reports discrepancies
"""

import json
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Tuple
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pension_config import PlanAdapter, FRSAdapter, MembershipClass


def load_baseline_params() -> Dict[str, Any]:
    """Load R baseline parameters."""
    with open("baseline_outputs/input_params.json", "r") as f:
        data = json.load(f)
    # Convert lists to single values
    return {k: v[0] if isinstance(v, list) else v for k, v in data.items()}


def load_baseline_workforce(class_name: str) -> Dict[str, pd.DataFrame]:
    """Load R baseline workforce data for a class."""
    baseline_dir = Path("baseline_outputs")
    data = {}

    for data_type in ["active", "term", "refund", "retire"]:
        file_path = baseline_dir / f"{class_name}_wf_{data_type}.csv"
        if file_path.exists():
            data[data_type] = pd.read_csv(file_path)

    return data


def create_frs_config(params: Dict[str, Any]) -> Dict[str, Any]:
    """Create FRS adapter configuration from R baseline parameters."""
    return {
        # Discount rates
        "dr_old": params["dr_old"],
        "dr_current": params["dr_current"],
        "dr_new": params["dr_new"],

        # Growth rates
        "payroll_growth": params["payroll_growth"],
        "pop_growth": params["pop_growth"],
        "inflation": params["inflation"],

        # COLA rates
        "cola_tier_1_active": params["cola_tier_1_active"],
        "cola_tier_2_active": params["cola_tier_2_active"],
        "cola_tier_3_active": params["cola_tier_3_active"],
        "cola_current_retire": params["cola_current_retire"],

        # DB/DC ratios
        "special_db_legacy_before_2018_ratio": params["special_db_legacy_before_2018_ratio"],
        "non_special_db_legacy_before_2018_ratio": params["non_special_db_legacy_before_2018_ratio"],
        "special_db_legacy_after_2018_ratio": params["special_db_legacy_after_2018_ratio"],
        "non_special_db_legacy_after_2018_ratio": params["non_special_db_legacy_after_2018_ratio"],
        "special_db_new_ratio": params["special_db_new_ratio"],
        "non_special_db_new_ratio": params["non_special_db_new_ratio"],

        # Model parameters
        "model_period": params["model_period"],
        "start_year": params["start_year"],
        "new_year": params["new_year"],
        "min_age": params["min_age"],
        "max_age": params["max_age"],

        # Funding parameters
        "funding_policy": params["funding_policy"],
        "db_ee_cont_rate": params["db_ee_cont_rate"],
        "amo_pay_growth": params["amo_pay_growth"],
        "amo_period_new": params["amo_period_new"],
        "amo_method": params["amo_method"],
        "funding_lag": params["funding_lag"],

        # DC contribution rates
        "regular_er_dc_cont_rate": params["regular_er_dc_cont_rate"],
        "special_er_dc_cont_rate": params["special_er_dc_cont_rate"],
        "admin_er_dc_cont_rate": params["admin_er_dc_cont_rate"],
        "judges_er_dc_cont_rate": params["judges_er_dc_cont_rate"],
        "eso_er_dc_cont_rate": params["eso_er_dc_cont_rate"],
        "eco_er_dc_cont_rate": params["eco_er_dc_cont_rate"],
        "senior_management_er_dc_cont_rate": params["senior_management_er_dc_cont_rate"],

        # Benefit rules (FRS-specific)
        "benefit_rules": {
            "regular": {
                "tier_1": 0.016,  # 1.6% per YOS
                "tier_2": {6: 0.016, 7: 0.0163, 8: 0.0166, 9: 0.0168},  # Graded
                "tier_3": 0.0165  # 1.65% per YOS
            },
            "special": {
                "tier_1": 0.020,  # 2.0% per YOS
                "tier_2": {6: 0.020, 7: 0.0205, 8: 0.0210, 9: 0.0215},  # Graded
                "tier_3": 0.020  # 2.0% per YOS
            },
            "admin": {
                "tier_1": 0.016,
                "tier_2": {6: 0.016, 7: 0.0163, 8: 0.0166, 9: 0.0168},
                "tier_3": 0.0165
            },
            "eco": {"tier_1": 0.016},
            "eso": {"tier_1": 0.016},
            "judges": {"tier_1": 0.033},  # 3.3% per YOS
            "senior_management": {"tier_1": 0.016}
        }
    }


def compare_workforce_totals(
    r_data: Dict[str, pd.DataFrame],
    class_name: str,
    tolerance: float = 0.05
) -> Dict[str, Any]:
    """Compare R baseline workforce totals."""
    results = {}

    for data_type, df in r_data.items():
        if df.empty:
            continue

        # Get value column
        value_col = f"n_{data_type}"
        if data_type == "active":
            value_col = "n_active"

        # Calculate totals by year
        by_year = df.groupby("year")[value_col].sum()

        results[data_type] = {
            "total": by_year.sum(),
            "year_range": (by_year.index.min(), by_year.index.max()),
            "first_year": by_year.iloc[0],
            "last_year": by_year.iloc[-1]
        }

    return results


def main():
    """Main validation function."""
    print("=" * 60)
    print("Florida FRS Pension Model - Python Validation")
    print("=" * 60)

    # Load R baseline parameters
    print("\n1. Loading R baseline parameters...")
    params = load_baseline_params()
    print(f"   Start year: {params['start_year']}")
    print(f"   Model period: {params['model_period']} years")
    print(f"   Discount rate: {params['dr_current']}")

    # Create FRS configuration
    print("\n2. Creating FRS adapter configuration...")
    frs_config = create_frs_config(params)
    print(f"   COLA rate (tier 1): {frs_config['cola_tier_1_active']}")
    print(f"   Payroll growth: {frs_config['payroll_growth']}")

    # Initialize FRS adapter
    print("\n3. Initializing FRS adapter...")
    adapter = FRSAdapter(frs_config)
    print(f"   Plan name: {adapter.plan_name}")
    print(f"   Membership classes: {len(adapter.membership_classes)}")

    # Load and analyze R baseline workforce data
    print("\n4. Analyzing R baseline workforce data...")
    print("-" * 60)

    classes = [
        "regular", "special", "admin", "eco", "eso", "judges", "senior_management"
    ]

    all_results = {}

    for class_name in classes:
        r_data = load_baseline_workforce(class_name)

        if not r_data:
            print(f"\n{class_name.upper()}: No data")
            continue

        results = compare_workforce_totals(r_data, class_name)
        all_results[class_name] = results

        print(f"\n{class_name.upper()}")
        print("-" * 40)

        for data_type, stats in results.items():
            print(f"  {data_type}:")
            print(f"    Total: {stats['total']:,.2f}")
            print(f"    Years: {stats['year_range'][0]} - {stats['year_range'][1]}")
            print(f"    First year: {stats['first_year']:,.2f}")
            print(f"    Last year: {stats['last_year']:,.2f}")

    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION STATUS")
    print("=" * 60)
    print("\n[OK] R baseline data loaded and analyzed")
    print("[OK] FRS adapter initialized with R parameters")
    print("\nNext steps:")
    print("1. Load input data (salary, headcount, mortality, etc.)")
    print("2. Run Python workforce projection")
    print("3. Compare year-by-year results")
    print("4. Document discrepancies in issues.md")

    return all_results


if __name__ == "__main__":
    results = main()
