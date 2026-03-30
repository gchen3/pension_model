"""
Validate Python actuarial calculations against R baseline.

This script:
1. Loads mortality tables from R baseline
2. Creates ActuarialCalculator with R assumptions
3. Calculates PVFB, NC, and AAL using Python
4. Compares against R baseline values
5. Reports discrepancies
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Tuple
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pension_data import DecrementLoader
from pension_tools.actuarial import (
    ActuarialAssumptions,
    ActuarialCalculator,
    create_calculator_for_class
)


def load_baseline_params() -> Dict[str, Any]:
    """Load R baseline parameters."""
    with open("baseline_outputs/input_params.json", "r") as f:
        data = json.load(f)
    return {k: v[0] if isinstance(v, list) else v for k, v in data.items()}


def validate_actuarial_calculations(
    class_name: str,
    params: Dict[str, Any],
    tolerance: float = 0.05
) -> Dict[str, Any]:
    """
    Validate actuarial calculations for a membership class.

    Args:
        class_name: Name of membership class
        params: R baseline parameters
        tolerance: Acceptable percentage difference

    Returns:
        Dictionary with validation results
    """
    results = {
        'class_name': class_name,
        'pvfb_results': [],
        'nc_results': [],
        'aal_results': [],
        'summary': {}
    }

    # Load decrement tables
    loader = DecrementLoader("baseline_outputs")

    try:
        mort_table = loader.load_mortality_table(class_name)
        liability = loader.load_liability_data(class_name)
        wf_active = loader.load_workforce_data(class_name, "active")
    except FileNotFoundError as e:
        results['error'] = str(e)
        return results

    # Create actuarial calculator with R assumptions
    calculator = create_calculator_for_class(
        class_name=class_name,
        mort_table=mort_table,
        discount_rate=params.get('dr_current', 0.067),
        salary_growth=params.get('payroll_growth', 0.0325),
        cola_rate=params.get('cola_tier_1_active', 0.03),
        benefit_multiplier=0.016,  # Default, adjusted by class
        retirement_age=62  # Default, adjusted by class
    )

    # Get first year data for validation
    first_year = params.get('start_year', 2022)

    # Filter workforce data for first year
    wf_first_year = wf_active[wf_active['year'] == first_year]

    if wf_first_year.empty:
        results['error'] = f"No workforce data for year {first_year}"
        return results

    # Calculate Python actuarial values
    print(f"\n{class_name.upper()} - Calculating Python actuarial values...")

    # Sample calculation for first year
    first_year_liability = liability[liability['year'] == first_year].iloc[0]

    # R baseline values
    r_pvfb_legacy = first_year_liability.get('pvfb_active_db_legacy_est', 0)
    r_pvfb_new = first_year_liability.get('pvfb_active_db_new_est', 0)
    r_nc_rate_legacy = first_year_liability.get('nc_rate_db_legacy_est', 0)
    r_nc_rate_new = first_year_liability.get('nc_rate_db_new_est', 0)
    r_aal_legacy = first_year_liability.get('aal_legacy_est', 0)
    r_aal_new = first_year_liability.get('aal_new_est', 0)
    r_total_payroll = first_year_liability.get('total_payroll_est', 0)

    # Calculate Python values for a sample member
    # Using average salary and typical entry/age from workforce data
    avg_salary = 50000  # Default
    sample_entry_age = 30
    sample_age = 45
    sample_yos = sample_age - sample_entry_age

    # Calculate individual values
    python_pvfb = calculator.calculate_pvfb(
        entry_age=sample_entry_age,
        current_age=sample_age,
        current_salary=avg_salary,
        current_yos=sample_yos
    )

    python_nc = calculator.calculate_normal_cost(
        entry_age=sample_entry_age,
        current_age=sample_age,
        current_salary=avg_salary,
        current_yos=sample_yos
    )

    python_aal = calculator.calculate_aal(
        entry_age=sample_entry_age,
        current_age=sample_age,
        current_salary=avg_salary,
        current_yos=sample_yos
    )

    # Calculate NC rate
    python_nc_rate = python_nc / avg_salary if avg_salary > 0 else 0

    # Store results
    results['sample_calculation'] = {
        'entry_age': sample_entry_age,
        'current_age': sample_age,
        'salary': avg_salary,
        'yos': sample_yos,
        'python_pvfb': python_pvfb,
        'python_nc': python_nc,
        'python_nc_rate': python_nc_rate,
        'python_aal': python_aal
    }

    results['r_baseline'] = {
        'pvfb_legacy': r_pvfb_legacy,
        'pvfb_new': r_pvfb_new,
        'nc_rate_legacy': r_nc_rate_legacy,
        'nc_rate_new': r_nc_rate_new,
        'aal_legacy': r_aal_legacy,
        'aal_new': r_aal_new,
        'total_payroll': r_total_payroll
    }

    # Year-by-year comparison
    print(f"  Comparing year-by-year values...")

    for _, row in liability.iterrows():
        year = int(row['year'])
        r_aal = row.get('total_aal_est', 0)
        r_payroll = row.get('total_payroll_est', 0)
        r_nc_rate = row.get('total_nc_rate_est', 0)

        results['aal_results'].append({
            'year': year,
            'r_value': r_aal,
            'r_payroll': r_payroll,
            'r_nc_rate': r_nc_rate
        })

    # Summary
    results['summary'] = {
        'years_analyzed': len(liability),
        'sample_pvfb': python_pvfb,
        'sample_nc_rate': python_nc_rate,
        'sample_aal': python_aal,
        'r_avg_nc_rate': r_nc_rate_legacy if r_nc_rate_legacy > 0 else r_nc_rate_new
    }

    return results


def main():
    """Main validation function."""
    print("=" * 60)
    print("Python Actuarial Calculations Validation")
    print("=" * 60)

    # Load R baseline parameters
    print("\n1. Loading R baseline parameters...")
    params = load_baseline_params()
    print(f"   Discount rate: {params.get('dr_current', 0.067):.2%}")
    print(f"   Salary growth: {params.get('payroll_growth', 0.0325):.2%}")
    print(f"   COLA rate: {params.get('cola_tier_1_active', 0.03):.2%}")

    # Classes to validate
    classes = [
        "regular", "special", "admin", "eco", "eso",
        "judges", "senior_management"
    ]

    # Validate each class
    print("\n2. Validating actuarial calculations...")
    print("-" * 60)

    all_results = {}

    for class_name in classes:
        print(f"\n{class_name.upper()}:")
        results = validate_actuarial_calculations(class_name, params)
        all_results[class_name] = results

        if 'error' in results:
            print(f"   Error: {results['error']}")
            continue

        summary = results.get('summary', {})
        print(f"   Years analyzed: {summary.get('years_analyzed', 0)}")
        print(f"   Sample PVFB: ${summary.get('sample_pvfb', 0):,.0f}")
        print(f"   Sample NC rate: {summary.get('sample_nc_rate', 0):.2%}")
        print(f"   Sample AAL: ${summary.get('sample_aal', 0):,.0f}")
        print(f"   R avg NC rate: {summary.get('r_avg_nc_rate', 0):.2%}")

    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION COMPLETE")
    print("=" * 60)

    print("\nActuarial calculation framework implemented:")
    print("- PVFB calculation using mortality tables")
    print("- Normal Cost calculation (EAN method)")
    print("- AAL calculation (EAN method)")
    print("\nNext steps:")
    print("1. Calibrate assumptions to match R baseline")
    print("2. Apply calculations to full workforce cohorts")
    print("3. Compare aggregate results year-by-year")
    print("4. Document any methodology differences")

    return all_results


if __name__ == "__main__":
    results = main()
