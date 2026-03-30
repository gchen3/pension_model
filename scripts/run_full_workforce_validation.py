"""
Full Workforce Projection Validation Script.

This script:
1. Loads R baseline workforce data for all classes
2. Runs Python workforce projection using extracted decrement tables
3. Compares year-by-year results to R baseline
4. Documents discrepancies found
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pension_data.decrement_loader import DecrementLoader
from pension_config.frs_adapter import FRSAdapter


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
    tolerance: float = 0.05


@dataclass
class ValidationResult:
    """Overall validation result for a class."""
    class_name: str
    total_comparisons: int = 0
    passed: int = 0
    failed: int = 0
    max_pct_difference: float = 0.0
    results: List[ComparisonResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if self.total_comparisons == 0:
            return 0.0
        return self.passed / self.total_comparisons * 100


def load_baseline_params() -> Dict[str, Any]:
    """Load R baseline parameters."""
    with open("baseline_outputs/input_params.json", "r") as f:
        data = json.load(f)
    return {k: v[0] if isinstance(v, list) else v for k, v in data.items()}


def load_r_workforce_data(class_name: str) -> Dict[str, pd.DataFrame]:
    """Load R baseline workforce data for a class."""
    baseline_dir = Path("baseline_outputs")
    data = {}

    for data_type in ["active", "term", "refund", "retire"]:
        file_path = baseline_dir / f"{class_name}_wf_{data_type}.csv"
        if file_path.exists():
            data[data_type] = pd.read_csv(file_path)

    return data


def load_r_workforce_summary(class_name: str) -> Dict[str, Any]:
    """Load R baseline workforce summary."""
    file_path = Path("baseline_outputs") / f"{class_name}_wf_summary.json"
    if file_path.exists():
        with open(file_path, "r") as f:
            return json.load(f)
    return {}


def get_r_yearly_totals(r_workforce: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
    """Get yearly totals from R baseline workforce data."""
    totals = {}

    for data_type, df in r_workforce.items():
        if df.empty:
            continue

        if 'year' in df.columns:
            count_col = f"n_{data_type}" if f"n_{data_type}" in df.columns else "n_active"
            if count_col in df.columns:
                totals[data_type] = df.groupby('year')[count_col].sum()

    return totals


def create_separation_table(loader: DecrementLoader, class_name: str) -> pd.DataFrame:
    """
    Create separation (withdrawal) table for workforce projection.

    The separation table needs: entry_age, age, entry_year, separation_rate
    """
    # Try to load withdrawal table (try male first, then without gender)
    withdrawal_df = loader.load_withdrawal_table(class_name, gender="male")
    if withdrawal_df is None:
        withdrawal_df = loader.load_withdrawal_table(class_name)

    if withdrawal_df is None:
        return pd.DataFrame()

    # Check what columns we have
    print(f"    Withdrawal table columns: {list(withdrawal_df.columns)}")
    print(f"    Sample data:\n{withdrawal_df.head()}")

    # Build separation table
    # R model uses age bands and YOS, need to convert to entry_age/age format
    rows = []

    # Get unique ages and YOS values
    if 'age' in withdrawal_df.columns and 'yos' in withdrawal_df.columns:
        ages = withdrawal_df['age'].unique()
        yos_values = withdrawal_df['yos'].unique()

        for entry_age in range(18, 70):
            for age in range(entry_age, 80):
                yos = age - entry_age
                if yos < 0:
                    continue

                # Find matching rate
                rate = loader.get_withdrawal_rate(withdrawal_df, age, yos)
                if rate is not None and rate > 0:
                    rows.append({
                        'entry_age': entry_age,
                        'age': age,
                        'entry_year': 2022,  # Base year
                        'separation_rate': rate
                    })

    if rows:
        return pd.DataFrame(rows)

    return pd.DataFrame()


def create_mortality_table(loader: DecrementLoader, class_name: str) -> pd.DataFrame:
    """Load mortality table for workforce projection."""
    try:
        mort_df = loader.load_mortality_table(class_name)
        print(f"    Mortality table columns: {list(mort_df.columns)}")
        print(f"    Mortality rows: {len(mort_df)}")
        return mort_df
    except FileNotFoundError:
        print(f"    No mortality table found for {class_name}")
        return pd.DataFrame()


def create_entrant_distribution(loader: DecrementLoader, class_name: str) -> pd.DataFrame:
    """Create entrant distribution from baseline data."""
    dist_df = loader.load_distribution(class_name, data_type="count")

    if dist_df.empty:
        # Create default distribution
        print(f"    No distribution found, using default")
        entry_ages = list(range(18, 65))
        n_ages = len(entry_ages)
        dist = [1.0 / n_ages] * n_ages
        return pd.DataFrame({
            'entry_age': entry_ages,
            'entrant_dist': dist
        })

    print(f"    Distribution columns: {list(dist_df.columns)}")

    # Normalize to distribution
    if 'count' in dist_df.columns and 'entry_age' in dist_df.columns:
        total = dist_df['count'].sum()
        dist_df['entrant_dist'] = dist_df['count'] / total
        return dist_df[['entry_age', 'entrant_dist']]

    return pd.DataFrame()


def run_simple_workforce_projection(
    loader: DecrementLoader,
    class_name: str,
    params: Dict[str, Any],
    years: int = 30
) -> Dict[int, Dict[str, float]]:
    """
    Run a simplified workforce projection for validation.

    This is a simplified version that tracks total counts by year
    for comparison with R baseline.
    """
    start_year = params.get('start_year', 2022)
    pop_growth = params.get('pop_growth', 0.0)  # Use actual pop_growth from R baseline (should be 0)

    print(f"\n  Running simplified projection for {class_name}...")

    # Load R baseline active workforce to get initial population
    r_workforce = load_r_workforce_data(class_name)
    r_active = r_workforce.get('active', pd.DataFrame())

    if r_active.empty:
        print(f"    No R baseline data for {class_name}")
        return {}

    # Get initial active population by year
    r_by_year = r_active.groupby('year')['n_active'].sum().to_dict()

    # Get initial year population
    initial_active = r_by_year.get(start_year, 0)
    print(f"    Initial active (from R): {initial_active:,.0f}")

    # Load decrement tables
    withdrawal_df = loader.load_withdrawal_table(class_name, gender="male")
    if withdrawal_df is None:
        withdrawal_df = loader.load_withdrawal_table(class_name)

    retirement_df = loader.load_retirement_table(tier="tier1", table_type="normal")

    # Track population by year
    results = {}
    current_active = initial_active
    current_term = 0.0
    current_retire = 0.0
    current_refund = 0.0

    for year_offset in range(years + 1):
        year = start_year + year_offset

        # Store current state
        r_active_this_year = r_by_year.get(year, 0)
        results[year] = {
            'python_active': current_active,
            'r_active': r_active_this_year,
            'python_term': current_term,
            'python_retire': current_retire,
            'python_refund': current_refund,
        }

        if year_offset == years:
            break

        # Calculate decrements (simplified)
        # Use average withdrawal rate
        avg_withdrawal_rate = 0.05  # Default
        if withdrawal_df is not None and not withdrawal_df.empty:
            rate_col = None
            for col in ['rate', 'withdrawal_rate', 'separation_rate']:
                if col in withdrawal_df.columns:
                    rate_col = col
                    break
            if rate_col:
                avg_withdrawal_rate = withdrawal_df[rate_col].mean()

        # Calculate transitions
        new_terminations = current_active * avg_withdrawal_rate
        new_refunds = new_terminations * 0.4  # Approximate refund rate
        new_retirements = current_term * 0.1  # Approximate retirement from terminated

        # Update populations
        current_active = current_active - new_terminations
        current_active = current_active * (1 + pop_growth)  # Add new entrants
        current_term = current_term + new_terminations - new_refunds - new_retirements
        current_refund = current_refund + new_refunds
        current_retire = current_retire + new_retirements

    return results


def compare_workforce_results(
    class_name: str,
    python_results: Dict[int, Dict[str, float]],
    r_yearly: Dict[str, pd.Series],
    tolerance: float = 0.05
) -> ValidationResult:
    """Compare Python projection results to R baseline."""
    validation = ValidationResult(class_name=class_name)

    for year, py_data in python_results.items():
        r_active = py_data.get('r_active', 0)
        py_active = py_data.get('python_active', 0)

        if r_active > 0:
            diff = py_active - r_active
            pct_diff = abs(diff / r_active)
            passed = pct_diff <= tolerance

            result = ComparisonResult(
                class_name=class_name,
                metric='active_count',
                year=year,
                python_value=py_active,
                r_value=r_active,
                difference=diff,
                pct_difference=pct_diff * 100,
                passed=passed,
                tolerance=tolerance
            )

            validation.results.append(result)
            validation.total_comparisons += 1
            if passed:
                validation.passed += 1
            else:
                validation.failed += 1

            if pct_diff > validation.max_pct_difference:
                validation.max_pct_difference = pct_diff * 100

    return validation


def print_validation_summary(validations: List[ValidationResult]):
    """Print summary of validation results."""
    print(f"\n{'=' * 80}")
    print(f"WORKFORCE PROJECTION VALIDATION SUMMARY")
    print(f"{'=' * 80}")

    total_comparisons = 0
    total_passed = 0
    total_failed = 0

    for v in validations:
        total_comparisons += v.total_comparisons
        total_passed += v.passed
        total_failed += v.failed

        status = "PASS" if v.failed == 0 else "FAIL"
        print(f"\n  {v.class_name.upper()}: [{status}]")
        print(f"    Comparisons: {v.total_comparisons}")
        print(f"    Passed: {v.passed} ({v.pass_rate:.1f}%)")
        print(f"    Failed: {v.failed}")
        print(f"    Max % Difference: {v.max_pct_difference:.2f}%")

        # Show sample of failed comparisons
        failed_results = [r for r in v.results if not r.passed]
        if failed_results:
            print(f"    Sample failures:")
            for r in failed_results[:3]:
                print(f"      Year {r.year}: Python={r.python_value:,.0f}, R={r.r_value:,.0f}, Diff={r.pct_difference:.1f}%")

    print(f"\n{'=' * 80}")
    print(f"OVERALL SUMMARY")
    print(f"{'=' * 80}")
    print(f"  Total Comparisons: {total_comparisons}")
    print(f"  Total Passed: {total_passed}")
    print(f"  Total Failed: {total_failed}")

    if total_comparisons > 0:
        overall_rate = total_passed / total_comparisons * 100
        print(f"  Overall Pass Rate: {overall_rate:.1f}%")


def run_detailed_comparison(class_name: str, loader: DecrementLoader):
    """Run detailed comparison for a single class."""
    print(f"\n{'=' * 60}")
    print(f"DETAILED COMPARISON: {class_name.upper()}")
    print(f"{'=' * 60}")

    # Load R baseline data
    r_workforce = load_r_workforce_data(class_name)
    r_summary = load_r_workforce_summary(class_name)

    if r_summary:
        print(f"\n  R Baseline Summary:")
        print(f"    Total Active: {r_summary.get('total_active', [0])[0]:,.0f}")
        print(f"    Total Terminations: {r_summary.get('total_terminations', [0])[0]:,.0f}")
        print(f"    Total Refunds: {r_summary.get('total_refunds', [0])[0]:,.0f}")
        print(f"    Total Retirements: {r_summary.get('total_retirements', [0])[0]:,.0f}")

    # Get yearly totals
    r_yearly = get_r_yearly_totals(r_workforce)

    if 'active' in r_yearly:
        print(f"\n  R Active Population by Year:")
        active_by_year = r_yearly['active']
        sample_years = [2022, 2025, 2030, 2040, 2050]
        for year in sample_years:
            if year in active_by_year.index:
                print(f"    {year}: {active_by_year[year]:,.0f}")

    # Load decrement tables
    print(f"\n  Decrement Tables:")

    # Withdrawal
    withdrawal_df = loader.load_withdrawal_table(class_name, gender="male")
    if withdrawal_df is None:
        withdrawal_df = loader.load_withdrawal_table(class_name)

    if withdrawal_df is not None:
        print(f"    Withdrawal: {len(withdrawal_df)} records")
        print(f"      Columns: {list(withdrawal_df.columns)}")
    else:
        print(f"    Withdrawal: NOT FOUND")

    # Retirement
    retirement_df = loader.load_retirement_table(tier="tier1", table_type="normal")
    if retirement_df is not None:
        print(f"    Retirement (tier1 normal): {len(retirement_df)} records")
        print(f"      Columns: {list(retirement_df.columns)}")
    else:
        print(f"    Retirement: NOT FOUND")

    # Mortality
    try:
        mortality_df = loader.load_mortality_table(class_name)
        print(f"    Mortality: {len(mortality_df)} records")
    except FileNotFoundError:
        print(f"    Mortality: NOT FOUND")


def main():
    """Main validation function."""
    print("=" * 80)
    print("Florida FRS Pension Model - Full Workforce Projection Validation")
    print("=" * 80)

    # Load baseline parameters
    params = load_baseline_params()

    print(f"\nBaseline Parameters:")
    print(f"  Start Year: {params.get('start_year', 2022)}")
    print(f"  Model Period: {params.get('model_period', 30)} years")
    print(f"  Discount Rate: {params.get('dr_current', 0.07)}")
    print(f"  Payroll Growth: {params.get('payroll_growth', 0.025)}")

    # Initialize loader
    loader = DecrementLoader()

    # Classes to validate
    classes = ['regular', 'special', 'admin', 'eco', 'eso', 'judges', 'senior_management']

    # Run detailed comparison for each class
    print(f"\n{'=' * 80}")
    print(f"1. DETAILED DATA COMPARISON")
    print(f"{'=' * 80}")

    for class_name in classes:
        run_detailed_comparison(class_name, loader)

    # Run simplified projection for comparison
    print(f"\n{'=' * 80}")
    print(f"2. SIMPLIFIED PROJECTION COMPARISON")
    print(f"{'=' * 80}")

    validations = []

    for class_name in classes:
        print(f"\n  Processing {class_name}...")

        # Run simplified projection
        python_results = run_simple_workforce_projection(
            loader, class_name, params, years=30
        )

        if python_results:
            # Load R baseline yearly totals
            r_workforce = load_r_workforce_data(class_name)
            r_yearly = get_r_yearly_totals(r_workforce)

            # Compare results
            validation = compare_workforce_results(
                class_name, python_results, r_yearly, tolerance=0.10
            )
            validations.append(validation)

    # Print summary
    print_validation_summary(validations)

    # Document findings
    print(f"\n{'=' * 80}")
    print(f"3. DISCREPANCY ANALYSIS")
    print(f"{'=' * 80}")

    print("""
    Key Findings:

    1. The simplified Python projection uses average decrement rates rather than
       age/YOS-specific rates from the R model.

    2. The R model uses detailed workforce transition matrices that track:
       - Entry age cohorts
       - Years of service (YOS)
       - Age-specific withdrawal rates
       - Tier-specific retirement eligibility

    3. To achieve closer alignment, the Python model needs:
       - Full integration with extracted decrement tables
       - Age/YOS-specific withdrawal rate lookup
       - Tier-aware retirement eligibility logic
       - Benefit decision optimization (refund vs annuity)

    4. Current status:
       - Decrement tables: EXTRACTED and LOADING
       - WorkforceProjector: IMPLEMENTED but needs integration
       - Validation framework: READY
    """)


if __name__ == "__main__":
    main()
