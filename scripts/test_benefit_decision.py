"""
Test benefit decision optimization (refund vs annuity).

This script tests the benefit decision optimization logic that compares
the present value of a deferred annuity vs an immediate refund.
"""

from pension_tools.benefit import (
    calculate_deferred_annuity_pv,
    calculate_refund_pv,
    optimize_benefit_decision
)


def test_benefit_decision():
    """Test benefit decision optimization."""
    print("=" * 60)
    print("BENEFIT DECISION OPTIMIZATION TEST")
    print("=" * 60)

    # Test case 1: Long-serving member (should prefer annuity)
    print("\n--- Test Case 1: Long-serving member (30 YOS) ---")
    final_salary = 80000
    yos = 30
    current_age = 55
    entry_age = 25
    employee_contributions = 150000
    contribution_interest_rate = 0.04
    normal_retirement_age = 62
    benefit_multiplier = 0.016
    discount_rate = 0.067
    cola_rate = 0.02
    min_vesting_yos = 5

    decision, annuity_pv, refund_pv = optimize_benefit_decision(
        final_salary=final_salary,
        yos=yos,
        current_age=current_age,
        entry_age=entry_age,
        employee_contributions=employee_contributions,
        contribution_interest_rate=contribution_interest_rate,
        normal_retirement_age=normal_retirement_age,
        benefit_multiplier=benefit_multiplier,
        discount_rate=discount_rate,
        cola_rate=cola_rate,
        min_vesting_yos=min_vesting_yos
    )

    print(f"Final Salary: ${final_salary:,.0f}")
    print(f"Years of Service: {yos}")
    print(f"Current Age: {current_age}")
    print(f"Employee Contributions: ${employee_contributions:,.0f}")
    print(f"Contribution Interest Rate: {contribution_interest_rate:.1%}")
    print(f"Normal Retirement Age: {normal_retirement_age}")
    print(f"Benefit Multiplier: {benefit_multiplier:.1%}")
    print(f"Discount Rate: {discount_rate:.1%}")
    print(f"COLA Rate: {cola_rate:.1%}")
    print(f"\nResults:")
    print(f"  Annuity PV: ${annuity_pv:,.2f}")
    print(f"  Refund PV: ${refund_pv:,.2f}")
    print(f"  Decision: {decision.upper()}")

    # Test case 2: Short-serving member (should prefer refund)
    print("\n--- Test Case 2: Short-serving member (6 YOS) ---")
    final_salary = 50000
    yos = 6
    current_age = 35
    entry_age = 29
    employee_contributions = 15000

    decision, annuity_pv, refund_pv = optimize_benefit_decision(
        final_salary=final_salary,
        yos=yos,
        current_age=current_age,
        entry_age=entry_age,
        employee_contributions=employee_contributions,
        contribution_interest_rate=contribution_interest_rate,
        normal_retirement_age=normal_retirement_age,
        benefit_multiplier=benefit_multiplier,
        discount_rate=discount_rate,
        cola_rate=cola_rate,
        min_vesting_yos=min_vesting_yos
    )

    print(f"Final Salary: ${final_salary:,.0f}")
    print(f"Years of Service: {yos}")
    print(f"Current Age: {current_age}")
    print(f"Employee Contributions: ${employee_contributions:,.0f}")
    print(f"\nResults:")
    print(f"  Annuity PV: ${annuity_pv:,.2f}")
    print(f"  Refund PV: ${refund_pv:,.2f}")
    print(f"  Decision: {decision.upper()}")

    # Test case 3: Non-vested member (must take refund)
    print("\n--- Test Case 3: Non-vested member (3 YOS) ---")
    final_salary = 45000
    yos = 3
    current_age = 28
    entry_age = 25
    employee_contributions = 6000

    decision, annuity_pv, refund_pv = optimize_benefit_decision(
        final_salary=final_salary,
        yos=yos,
        current_age=current_age,
        entry_age=entry_age,
        employee_contributions=employee_contributions,
        contribution_interest_rate=contribution_interest_rate,
        normal_retirement_age=normal_retirement_age,
        benefit_multiplier=benefit_multiplier,
        discount_rate=discount_rate,
        cola_rate=cola_rate,
        min_vesting_yos=min_vesting_yos
    )

    print(f"Final Salary: ${final_salary:,.0f}")
    print(f"Years of Service: {yos}")
    print(f"Current Age: {current_age}")
    print(f"Employee Contributions: ${employee_contributions:,.0f}")
    print(f"\nResults:")
    print(f"  Annuity PV: ${annuity_pv:,.2f}")
    print(f"  Refund PV: ${refund_pv:,.2f}")
    print(f"  Decision: {decision.upper()}")

    # Test case 4: Member at retirement age
    print("\n--- Test Case 4: Member at retirement age (62 YOS) ---")
    final_salary = 90000
    yos = 25
    current_age = 62
    entry_age = 37
    employee_contributions = 120000

    decision, annuity_pv, refund_pv = optimize_benefit_decision(
        final_salary=final_salary,
        yos=yos,
        current_age=current_age,
        entry_age=entry_age,
        employee_contributions=employee_contributions,
        contribution_interest_rate=contribution_interest_rate,
        normal_retirement_age=normal_retirement_age,
        benefit_multiplier=benefit_multiplier,
        discount_rate=discount_rate,
        cola_rate=cola_rate,
        min_vesting_yos=min_vesting_yos
    )

    print(f"Final Salary: ${final_salary:,.0f}")
    print(f"Years of Service: {yos}")
    print(f"Current Age: {current_age}")
    print(f"Employee Contributions: ${employee_contributions:,.0f}")
    print(f"\nResults:")
    print(f"  Annuity PV: ${annuity_pv:,.2f}")
    print(f"  Refund PV: ${refund_pv:,.2f}")
    print(f"  Decision: {decision.upper()}")

    print("\n" + "=" * 60)
    print("BENEFIT DECISION OPTIMIZATION TEST COMPLETE")
    print("=" * 60)

    return True


if __name__ == "__main__":
    test_benefit_decision()
