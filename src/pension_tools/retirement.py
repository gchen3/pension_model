"""
Retirement eligibility functions for pension modeling.

This module provides retirement eligibility checking and benefit calculation
functions for various retirement types (normal, early, deferred).
"""

from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
import pandas as pd
import numpy as np


@dataclass
class RetirementEligibility:
    """Retirement eligibility rules for a tier."""
    normal_retirement_age: int
    normal_retirement_yos: int
    early_retirement_age: int
    early_retirement_yos: int
    early_retirement_factor: float = 0.0  # Reduction per year before normal
    deferred_vesting_yos: int = 5


# Default FRS retirement eligibility rules by tier
FRS_RETIREMENT_RULES = {
    1: RetirementEligibility(
        normal_retirement_age=62,
        normal_retirement_yos=6,
        early_retirement_age=55,
        early_retirement_yos=6,
        early_retirement_factor=0.03  # 3% per year reduction
    ),
    2: RetirementEligibility(
        normal_retirement_age=60,
        normal_retirement_yos=8,
        early_retirement_age=55,
        early_retirement_yos=8,
        early_retirement_factor=0.03
    ),
    3: RetirementEligibility(
        normal_retirement_age=65,
        normal_retirement_yos=8,
        early_retirement_age=55,
        early_retirement_yos=8,
        early_retirement_factor=0.0417  # 5/12% per month
    )
}

# Special Risk retirement rules
SPECIAL_RISK_RULES = {
    1: RetirementEligibility(
        normal_retirement_age=55,
        normal_retirement_yos=6,
        early_retirement_age=50,
        early_retirement_yos=6,
        early_retirement_factor=0.02
    ),
    2: RetirementEligibility(
        normal_retirement_age=55,
        normal_retirement_yos=8,
        early_retirement_age=50,
        early_retirement_yos=8,
        early_retirement_factor=0.02
    ),
    3: RetirementEligibility(
        normal_retirement_age=60,
        normal_retirement_yos=8,
        early_retirement_age=50,
        early_retirement_yos=8,
        early_retirement_factor=0.03
    )
}

# Judges retirement rules
JUDGES_RULES = {
    1: RetirementEligibility(
        normal_retirement_age=62,
        normal_retirement_yos=10,
        early_retirement_age=57,
        early_retirement_yos=10,
        early_retirement_factor=0.02
    )
}


def check_normal_retirement(yos: int, age: int, tier: int,
                           membership_class: str = "regular") -> bool:
    """
    Check if member is eligible for normal retirement.

    Args:
        yos: Years of service
        age: Current age
        tier: Benefit tier
        membership_class: Membership class (affects rules)

    Returns:
        True if eligible for normal retirement
    """
    rules = _get_retirement_rules(membership_class, tier)

    # Normal retirement: age >= NRA OR yos >= NRY
    return (age >= rules.normal_retirement_age or
            yos >= rules.normal_retirement_yos)


def check_early_retirement(yos: int, age: int, tier: int,
                          membership_class: str = "regular") -> bool:
    """
    Check if member is eligible for early retirement.

    Args:
        yos: Years of service
        age: Current age
        tier: Benefit tier
        membership_class: Membership class

    Returns:
        True if eligible for early retirement
    """
    rules = _get_retirement_rules(membership_class, tier)

    # Early retirement: age >= ERA AND yos >= ERY
    return (age >= rules.early_retirement_age and
            yos >= rules.early_retirement_yos)


def check_deferred_vesting(yos: int, tier: int,
                          membership_class: str = "regular") -> bool:
    """
    Check if member is eligible for deferred vested benefit.

    Args:
        yos: Years of service
        tier: Benefit tier
        membership_class: Membership class

    Returns:
        True if eligible for deferred vesting
    """
    rules = _get_retirement_rules(membership_class, tier)
    return yos >= rules.deferred_vesting_yos


def get_early_retirement_factor(yos: int, age: int, tier: int,
                               membership_class: str = "regular") -> Optional[float]:
    """
    Get early retirement reduction factor.

    Args:
        yos: Years of service
        age: Age at retirement
        tier: Benefit tier
        membership_class: Membership class

    Returns:
        Early retirement factor (1.0 = no reduction, <1.0 = reduction)
    """
    rules = _get_retirement_rules(membership_class, tier)

    # If normal retirement eligible, no reduction
    if check_normal_retirement(yos, age, tier, membership_class):
        return 1.0

    # If not early retirement eligible, return None
    if not check_early_retirement(yos, age, tier, membership_class):
        return None

    # Calculate years before normal retirement
    years_before_nra = rules.normal_retirement_age - age
    if years_before_nra <= 0:
        return 1.0

    # Apply reduction factor
    factor = 1.0 - (years_before_nra * rules.early_retirement_factor)
    return max(factor, 0.0)


def _get_retirement_rules(membership_class: str, tier: int) -> RetirementEligibility:
    """Get retirement rules for a class and tier."""
    class_lower = membership_class.lower()

    if class_lower in ['special', 'special_risk']:
        rules_dict = SPECIAL_RISK_RULES
    elif class_lower in ['judges', 'judge']:
        rules_dict = JUDGES_RULES
    else:
        rules_dict = FRS_RETIREMENT_RULES

    return rules_dict.get(tier, FRS_RETIREMENT_RULES[1])


def load_retirement_table(df: pd.DataFrame) -> Dict[tuple, bool]:
    """
    Convert a retirement eligibility DataFrame to a dictionary.

    Args:
        df: DataFrame with retirement eligibility data

    Returns:
        Dictionary mapping (age, yos, tier) to eligibility
    """
    table = {}

    for _, row in df.iterrows():
        age = row.get('age', 0)
        yos = row.get('yos', row.get('years_of_service', 0))
        tier = row.get('tier', 1)

        # Get eligibility from various possible column names
        if 'eligible' in row:
            eligible = bool(row['eligible'])
        elif 'normal_retirement' in row:
            eligible = bool(row['normal_retirement'])
        elif 'can_retire' in row:
            eligible = bool(row['can_retire'])
        else:
            eligible = False

        key = (int(age) if pd.notna(age) else 0,
               int(yos) if pd.notna(yos) else 0,
               int(tier) if pd.notna(tier) else 1)

        table[key] = eligible

    return table


def get_retirement_probability_from_df(
    df: pd.DataFrame,
    age: int,
    yos: int,
    entry_age: Optional[int] = None,
    term_year: Optional[int] = None,
    year: Optional[int] = None
) -> float:
    """
    Get retirement probability from a benefit decisions DataFrame.

    Args:
        df: Benefit decisions DataFrame
        age: Current age
        yos: Years of service
        entry_age: Entry age (optional)
        term_year: Termination year (optional)
        year: Current year (optional)

    Returns:
        Retirement probability (0 or 1 for deterministic decisions)
    """
    # Build filter conditions
    conditions = pd.Series([True] * len(df))

    if 'age' in df.columns:
        conditions &= (df['age'] == age)

    if 'yos' in df.columns:
        conditions &= (df['yos'] == yos)
    elif 'years_of_service' in df.columns:
        conditions &= (df['years_of_service'] == yos)

    if entry_age is not None and 'entry_age' in df.columns:
        conditions &= (df['entry_age'] == entry_age)

    if term_year is not None and 'term_year' in df.columns:
        conditions &= (df['term_year'] == term_year)

    if year is not None and 'year' in df.columns:
        conditions &= (df['year'] == year)

    # Find matching row
    matches = df[conditions]

    if len(matches) == 0:
        return 0.0

    # Get retirement column
    if 'retire' in matches.columns:
        return float(matches['retire'].iloc[0])
    elif 'retirement_probability' in matches.columns:
        return float(matches['retirement_probability'].iloc[0])

    return 0.0


def calculate_retirement_benefit(
    final_avg_salary: float,
    yos: int,
    benefit_multiplier: float,
    age: int,
    tier: int,
    membership_class: str = "regular"
) -> float:
    """
    Calculate annual retirement benefit.

    Args:
        final_avg_salary: Final average salary
        yos: Years of service
        benefit_multiplier: Benefit multiplier (e.g., 0.016 for 1.6%)
        age: Age at retirement
        tier: Benefit tier
        membership_class: Membership class

    Returns:
        Annual retirement benefit
    """
    # Calculate base benefit
    base_benefit = final_avg_salary * yos * benefit_multiplier

    # Apply early retirement factor if applicable
    erf = get_early_retirement_factor(yos, age, tier, membership_class)

    if erf is None:
        return 0.0

    return base_benefit * erf


def is_normal_retirement_eligible(age: int, yos: int, normal_age: int, normal_yos: int) -> bool:
    """Check if member meets normal retirement eligibility (age OR yos)."""
    return age >= normal_age or yos >= normal_yos


def is_early_retirement_eligible(age: int, yos: int, early_age: int, early_yos: int) -> bool:
    """Check if member meets early retirement eligibility (age AND yos)."""
    return age >= early_age and yos >= early_yos


def calculate_early_retirement_factor(
    current_age: int,
    current_yos: int,
    normal_age: int,
    normal_yos: int,
    reduction_per_year: float = 0.05
) -> float:
    """Calculate early retirement reduction factor (FRS: 5% per year early)."""
    years_early_by_age = max(0, normal_age - current_age)
    years_early_by_yos = max(0, normal_yos - current_yos)
    years_early = min(years_early_by_age, years_early_by_yos)
    return max(0.50, 1.0 - years_early * reduction_per_year)
