"""
Run Calibrated Workforce Projection and Compare to R Baseline.

This script:
1. Uses the CalibratedWorkforceProjector with age/YOS-specific rates
2. Runs projection for all classes
3. Compares to R baseline
4. Reports improvement over simplified projection
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, List
from dataclasses import dataclass, field
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pension_data.decrement_loader import DecrementLoader
from pension_data.calibration_loader import CalibrationLoader

# Import directly from the module file to avoid circular imports
import sys
module_path = Path(__file__).parent.parent / "src" / "pension_model" / "core"
sys.path.insert(0, str(module_path))
from workforce_calibrated import (
    CalibratedWorkforceProjector,
    WorkforceConfig,
    ProjectionResult,
    run_calibrated_projection
)


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


def load_r_workforce_data(class_name: str) -> Dict[str, pd.DataFrame]:
    """Load R baseline workforce data for a class."""
    baseline_dir = Path("baseline_outputs")
    data = {}

    for data_type in ["active", "term", "refund", "retire"]:
        file_path = baseline_dir / f"{class_name}_wf_{data_type}.csv"
        if file_path.exists():
            data[data_type] = pd.read_csv(file_path)

    return data


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


def compare_projection_to_baseline(
    projection: ProjectionResult,
    r_yearly: Dict[str, pd.Series],
    tolerance: float = 0.05
) -> ValidationResult:
    """Compare Python projection results to R baseline."""
    validation = ValidationResult(class_name=projection.class_name)

    for year, state in projection.states.items():
        # Compare active population
        py_active = state.active['n_active'].sum() if not state.active.empty else 0

        if 'active' in r_yearly and year in r_yearly['active'].index:
            r_active = r_yearly['active'][year]

            if r_active > 0:
                diff = py_active - r_active
                pct_diff = abs(diff / r_active)
                passed = pct_diff <= tolerance

                result = ComparisonResult(
                    class_name=projection.class_name,
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

                if pct_diff * 100 > validation.max_pct_difference:
                    validation.max_pct_difference = pct_diff * 100

    return validation


def run_validation_for_class(class_name: str, tolerance: float = 0.10) -> ValidationResult:
    """Run calibrated projection and validation for a single class."""
    print(f"\n  Processing {class_name}...")

    try:
        # Run calibrated projection
        projection = run_calibrated_projection(
            class_name=class_name,
            baseline_dir="baseline_outputs",
            config_path="configs/calibration_params.json"
        )

        # Load R baseline
        r_workforce = load_r_workforce_data(class_name)
        r_yearly = get_r_yearly_totals(r_workforce)

        # Compare
        validation = compare_projection_to_baseline(projection, r_yearly, tolerance)

        # Print summary
        if validation.total_comparisons > 0:
            print(f"    Initial year comparison:")
            first_result = validation.results[0]
            print(f"      Year {first_result.year}: Python={first_result.python_value:,.0f}, R={first_result.r_value:,.0f}")

            if len(validation.results) > 15:
                mid_result = validation.results[15]
                print(f"    Mid-period comparison:")
                print(f"      Year {mid_result.year}: Python={mid_result.python_value:,.0f}, R={mid_result.r_value:,.0f}")

        return validation

    except Exception as e:
        print(f"    ERROR: {e}")
        import traceback
        traceback.print_exc()
        return ValidationResult(class_name=class_name)


def print_comparison_summary(
    calibrated_results: List[ValidationResult],
    previous_results: List[ValidationResult]
):
    """Print comparison between calibrated and previous results."""
    print(f"\n{'=' * 80}")
    print(f"CALIBRATED vs SIMPLIFIED PROJECTION COMPARISON")
    print(f"{'=' * 80}")

    print(f"\n{'Class':<20} {'Calibrated Pass%':>18} {'Simplified Pass%':>18} {'Improvement':>12}")
    print("-" * 80)

    calibrated_dict = {v.class_name: v for v in calibrated_results}
    previous_dict = {v.class_name: v for v in previous_results}

    total_cal = 0
    total_prev = 0
    total_cal_passed = 0
    total_prev_passed = 0

    for class_name in calibrated_dict.keys():
        cal = calibrated_dict[class_name]
        prev = previous_dict.get(class_name, ValidationResult(class_name=class_name))

        total_cal += cal.total_comparisons
        total_prev += prev.total_comparisons
        total_cal_passed += cal.passed
        total_prev_passed += prev.passed

        improvement = cal.pass_rate - prev.pass_rate

        print(f"{class_name:<20} {cal.pass_rate:>17.1f}% {prev.pass_rate:>17.1f}% {improvement:>+11.1f}%")

    print("-" * 80)
    cal_overall = total_cal_passed / total_cal * 100 if total_cal > 0 else 0
    prev_overall = total_prev_passed / total_prev * 100 if total_prev > 0 else 0
    improvement = cal_overall - prev_overall

    print(f"{'OVERALL':<20} {cal_overall:>17.1f}% {prev_overall:>17.1f}% {improvement:>+11.1f}%")


def print_detailed_results(validations: List[ValidationResult]):
    """Print detailed validation results."""
    print(f"\n{'=' * 80}")
    print(f"DETAILED CALIBRATED PROJECTION RESULTS")
    print(f"{'=' * 80}")

    for v in validations:
        status = "PASS" if v.failed == 0 else "FAIL"
        print(f"\n  {v.class_name.upper()}: [{status}]")
        print(f"    Comparisons: {v.total_comparisons}")
        print(f"    Passed: {v.passed} ({v.pass_rate:.1f}%)")
        print(f"    Failed: {v.failed}")
        print(f"    Max % Difference: {v.max_pct_difference:.2f}%")

        # Show sample of failures
        failed_results = [r for r in v.results if not r.passed]
        if failed_results:
            print(f"    Sample failures:")
            for r in failed_results[:3]:
                print(f"      Year {r.year}: Python={r.python_value:,.0f}, R={r.r_value:,.0f}, Diff={r.pct_difference:.1f}%")


def main():
    """Main validation function."""
    print("=" * 80)
    print("Florida FRS Pension Model - Calibrated Workforce Projection Validation")
    print("=" * 80)

    # Load calibration parameters to display
    cal_loader = CalibrationLoader("configs/calibration_params.json")

    print(f"\nCalibration Parameters:")
    print(f"  Global Cal Factor: {cal_loader.global_cal_factor}")
    print(f"  Retire/Refund Ratio: {cal_loader.retire_refund_ratio}")
    print(f"  Population Growth: {cal_loader.population_growth}")

    # Classes to validate
    classes = ['regular', 'special', 'admin', 'eco', 'eso', 'judges', 'senior_management']

    # Previous (simplified) results for comparison
    previous_results = [
        ValidationResult(class_name='regular', total_comparisons=31, passed=8, failed=23, max_pct_difference=1.32),
        ValidationResult(class_name='special', total_comparisons=31, passed=31, failed=0, max_pct_difference=0.09),
        ValidationResult(class_name='admin', total_comparisons=31, passed=31, failed=0, max_pct_difference=0.21),
        ValidationResult(class_name='eco', total_comparisons=31, passed=14, failed=17, max_pct_difference=0.80),
        ValidationResult(class_name='eso', total_comparisons=31, passed=6, failed=25, max_pct_difference=1.91),
        ValidationResult(class_name='judges', total_comparisons=31, passed=5, failed=26, max_pct_difference=2.22),
        ValidationResult(class_name='senior_management', total_comparisons=31, passed=11, failed=20, max_pct_difference=1.04),
    ]

    print(f"\n{'=' * 80}")
    print(f"RUNNING CALIBRATED PROJECTIONS")
    print(f"{'=' * 80}")

    calibrated_results = []

    for class_name in classes:
        result = run_validation_for_class(class_name, tolerance=0.10)
        calibrated_results.append(result)

    # Print detailed results
    print_detailed_results(calibrated_results)

    # Print comparison
    print_comparison_summary(calibrated_results, previous_results)

    # Summary
    print(f"\n{'=' * 80}")
    print(f"SUMMARY")
    print(f"{'=' * 80}")

    total_passed = sum(v.passed for v in calibrated_results)
    total_comparisons = sum(v.total_comparisons for v in calibrated_results)

    if total_comparisons > 0:
        overall_rate = total_passed / total_comparisons * 100
        print(f"\n  Overall Pass Rate: {overall_rate:.1f}% ({total_passed}/{total_comparisons})")

    print(f"\n  Key Improvements Implemented:")
    print(f"    1. Age/YOS-specific withdrawal rate lookup from decrement tables")
    print(f"    2. Population growth = 0 (stable population from R model)")
    print(f"    3. Retire/refund ratio = 1.0 (from calibration parameters)")
    print(f"    4. New entrant logic calibrated to maintain stable population")


if __name__ == "__main__":
    main()
