"""
Run Python Pension Model validation against R baseline.

This script:
1. Loads R baseline data from baseline_outputs/
2. Validates data availability and structure
3. Compares workforce, liability, and funding metrics
4. Reports discrepancies
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


def load_baseline_workforce(class_name: str) -> Dict[str, pd.DataFrame]:
    """Load R baseline workforce data for a class."""
    baseline_dir = Path("baseline_outputs")
    data = {}

    for data_type in ["active", "term", "refund", "retire"]:
        file_path = baseline_dir / f"{class_name}_wf_{data_type}.csv"
        if file_path.exists():
            data[data_type] = pd.read_csv(file_path)

    return data


def load_baseline_summary(class_name: str) -> Dict[str, Any]:
    """Load R baseline workforce summary for a class."""
    baseline_dir = Path("baseline_outputs")
    summary_file = baseline_dir / f"{class_name}_wf_summary.json"

    if summary_file.exists():
        with open(summary_file, "r") as f:
            return json.load(f)
    return {}


def load_liability_summary(class_name: str) -> Dict[str, Any]:
    """Load R baseline liability summary for a class."""
    baseline_dir = Path("baseline_outputs")
    summary_file = baseline_dir / f"{class_name}_liability_summary.json"

    if summary_file.exists():
        with open(summary_file, "r") as f:
            return json.load(f)
    return {}


def validate_decrement_tables():
    """Validate that all decrement tables are available."""
    print("\n" + "=" * 60)
    print("Validating Decrement Tables")
    print("=" * 60)

    loader = DecrementLoader()

    # Check withdrawal tables
    print("\n1. Withdrawal Tables:")
    withdrawal_classes = {
        'regular': ['male', 'female'],
        'special': ['male', 'female'],
        'admin': ['male', 'female'],
        'senior_management': ['male', 'female'],
        'eco': None,
        'eso': None,
        'judges': None,
    }

    withdrawal_results = {}
    for cls, genders in withdrawal_classes.items():
        if genders:
            for gender in genders:
                df = loader.load_withdrawal_table(cls, gender=gender)
                key = f"{cls}_{gender}"
                if df is not None:
                    withdrawal_results[key] = {'status': 'OK', 'records': len(df)}
                    print(f"   [OK] {key}: {len(df)} records")
                else:
                    withdrawal_results[key] = {'status': 'MISSING', 'records': 0}
                    print(f"   [MISSING] {key}: NOT FOUND")
        else:
            df = loader.load_withdrawal_table(cls)
            if df is not None:
                withdrawal_results[cls] = {'status': 'OK', 'records': len(df)}
                print(f"   [OK] {cls}: {len(df)} records")
            else:
                withdrawal_results[cls] = {'status': 'MISSING', 'records': 0}
                print(f"   [MISSING] {cls}: NOT FOUND")

    # Check retirement tables
    print("\n2. Retirement Tables:")
    retirement_results = {}
    for tier in ['tier1', 'tier2']:
        for table_type in ['normal', 'early', 'drop_entry']:
            df = loader.load_retirement_table(tier=tier, table_type=table_type)
            key = f"{table_type}_{tier}"
            if df is not None:
                retirement_results[key] = {'status': 'OK', 'records': len(df)}
                print(f"   [OK] {key}: {len(df)} records")
            else:
                retirement_results[key] = {'status': 'MISSING', 'records': 0}
                print(f"   [MISSING] {key}: NOT FOUND")

    return withdrawal_results, retirement_results


def validate_baseline_data():
    """Validate R baseline data availability."""
    print("\n" + "=" * 60)
    print("Validating R Baseline Data")
    print("=" * 60)

    classes = ['regular', 'special', 'admin', 'eco', 'eso', 'judges', 'senior_management']

    baseline_results = {}
    for cls in classes:
        wf_data = load_baseline_workforce(cls)
        wf_summary = load_baseline_summary(cls)
        liab_summary = load_liability_summary(cls)

        baseline_results[cls] = {
            'workforce_files': list(wf_data.keys()),
            'has_wf_summary': bool(wf_summary),
            'has_liability_summary': bool(liab_summary)
        }

        status_parts = []
        if wf_data:
            status_parts.append(f"wf: {len(wf_data)} files")
        if wf_summary:
            status_parts.append("wf_summary: OK")
        if liab_summary:
            status_parts.append("liab_summary: OK")

        status = ", ".join(status_parts) if status_parts else "NO DATA"
        print(f"   {cls}: {status}")

    return baseline_results


def compare_workforce_data(class_name: str, tolerance: float = 0.05) -> List[ComparisonResult]:
    """Compare workforce data between Python and R (placeholder for now)."""
    results = []

    # Load R baseline
    r_workforce = load_baseline_workforce(class_name)

    if not r_workforce:
        return results

    # Get summary statistics from R baseline
    r_active = r_workforce.get('active', pd.DataFrame())
    if not r_active.empty:
        # Summarize by year
        if 'year' in r_active.columns and 'n_active' in r_active.columns:
            r_by_year = r_active.groupby('year')['n_active'].sum()

            print(f"\n   {class_name.upper()} - Active workforce by year (R baseline):")
            for year, count in r_by_year.head(5).items():
                print(f"      Year {year}: {count:,.0f}")

            if len(r_by_year) > 5:
                print(f"      ... ({len(r_by_year) - 5} more years)")

    return results


def generate_validation_report(
    decrement_results,
    baseline_results,
    workforce_comparisons,
    liability_comparisons
):
    """Generate a summary validation report."""
    print("\n" + "=" * 60)
    print("VALIDATION REPORT")
    print("=" * 60)

    withdrawal_results, retirement_results = decrement_results

    # Count successes
    withdrawal_ok = sum(1 for v in withdrawal_results.values() if v['status'] == 'OK')
    withdrawal_total = len(withdrawal_results)

    retirement_ok = sum(1 for v in retirement_results.values() if v['status'] == 'OK')
    retirement_total = len(retirement_results)

    print(f"\n1. Decrement Tables:")
    print(f"   Withdrawal: {withdrawal_ok}/{withdrawal_total} available")
    print(f"   Retirement: {retirement_ok}/{retirement_total} available")

    # Baseline data
    classes_with_data = sum(1 for v in baseline_results.values() if v['workforce_files'])
    print(f"\n2. Baseline Data:")
    print(f"   Classes with data: {classes_with_data}/{len(baseline_results)}")

    print("\n3. Next Steps:")
    print("   - Integrate decrement tables with workforce model")
    print("   - Run Python model for each class")
    print("   - Compare outputs to R baseline")
    print("   - Document discrepancies")


def main():
    """Main validation function."""
    print("=" * 60)
    print("Florida FRS Pension Model Validation")
    print("=" * 60)

    # Load baseline parameters
    params = load_baseline_params()
    print(f"\nBaseline Parameters:")
    print(f"   Start Year: {params.get('start_year')}")
    print(f"   Model Period: {params.get('model_period')} years")
    print(f"   Discount Rate: {params.get('dr_current')}")
    print(f"   Payroll Growth: {params.get('payroll_growth')}")

    # Validate decrement tables
    decrement_results = validate_decrement_tables()

    # Validate baseline data
    baseline_results = validate_baseline_data()

    # Compare workforce data (placeholder)
    print("\n" + "=" * 60)
    print("Workforce Data Summary (R Baseline)")
    print("=" * 60)

    workforce_comparisons = {}
    liability_comparisons = {}

    for cls in ['regular', 'special', 'admin', 'eco', 'eso', 'judges', 'senior_management']:
        results = compare_workforce_data(cls)
        workforce_comparisons[cls] = results

    # Generate report
    generate_validation_report(
        decrement_results,
        baseline_results,
        workforce_comparisons,
        liability_comparisons
    )


if __name__ == "__main__":
    main()
