"""
Separation rate calculation module.

Implements the R model's combined separation rate logic that includes:
1. Withdrawal rates (for vested members not retirement-eligible)
2. Normal retirement rates (tier 1 and tier 2)
3. Early retirement rates (tier 1 and tier 2)

Based on R model: Florida FRS benefit model.R, get_separation_table function
"""

from typing import Dict, Optional, Tuple
import pandas as pd


# Tier determination based on entry year
# From R model: Florida FRS model input.R
TIER_1_CUTOFF_YEAR = 2011  # Hired before 2011 are tier 1
TIER_2_CUTOFF_YEAR = 2024  # Hired 2011-2023 are tier 2, after 2024 are tier 3


def determine_tier(entry_year: int, new_year: int = 2024) -> str:
    """
    Determine the tier based on entry year.

    From R model get_tier function:
    - Tier 1: Hired before 2011
    - Tier 2: Hired 2011 to new_year-1
    - Tier 3: Hired new_year or later

    Args:
        entry_year: Year the member entered the plan
        new_year: Year when tier 3 starts (default 2024)

    Returns:
        Tier string: "tier_1", "tier_2", or "tier_3"
    """
    if entry_year < TIER_1_CUTOFF_YEAR:
        return "tier_1"
    elif entry_year < new_year:
        return "tier_2"
    else:
        return "tier_3"


def get_normal_retirement_age(class_name: str) -> int:
    """
    Get normal retirement age for a membership class.

    From R model benefit rules:
    - Regular: 62 or 30 YOS (any age)
    - Special Risk: 55 or 25 YOS (any age)
    - Admin: 55 or 25 YOS (any age) - uses special risk rules
    - ECO: 62 or 30 YOS
    - ESO: 62 or 30 YOS
    - Judges: 62 or 30 YOS
    - Senior Management: 62 or 30 YOS

    Args:
        class_name: Membership class name

    Returns:
        Normal retirement age
    """
    NORMAL_RETIREMENT_AGES = {
        "regular": 62,
        "special": 55,
        "admin": 55,  # Uses special risk rules
        "eco": 62,
        "eso": 62,
        "judges": 62,
        "senior_management": 62,
    }
    return NORMAL_RETIREMENT_AGES.get(class_name, 62)


def get_normal_retirement_yos(class_name: str) -> int:
    """
    Get normal retirement YOS for a membership class.

    Args:
        class_name: Membership class name

    Returns:
        Years of service needed for normal retirement
    """
    NORMAL_RETIREMENT_YOS = {
        "regular": 30,
        "special": 25,
        "admin": 25,  # Uses special risk rules
        "eco": 30,
        "eso": 30,
        "judges": 30,
        "senior_management": 30,
    }
    return NORMAL_RETIREMENT_YOS.get(class_name, 30)


def get_early_retirement_age(class_name: str) -> int:
    """
    Get early retirement age for a membership class.

    Args:
        class_name: Membership class name

    Returns:
        Early retirement age
    """
    EARLY_RETIREMENT_AGES = {
        "regular": 55,
        "special": 50,
        "admin": 50,  # Uses special risk rules
        "eco": 55,
        "eso": 55,
        "judges": 55,
        "senior_management": 55,
    }
    return EARLY_RETIREMENT_AGES.get(class_name, 55)


def get_early_retirement_yos(class_name: str) -> int:
    """
    Get early retirement YOS for a membership class.

    Args:
        class_name: Membership class name

    Returns:
        Years of service needed for early retirement
    """
    EARLY_RETIREMENT_YOS = {
        "regular": 10,
        "special": 10,
        "admin": 10,
        "eco": 10,
        "eso": 10,
        "judges": 10,
        "senior_management": 10,
    }
    return EARLY_RETIREMENT_YOS.get(class_name, 10)


def check_retirement_eligibility(
    age: int,
    yos: int,
    class_name: str,
    tier: str
) -> Tuple[bool, str]:
    """
    Check if member is eligible for retirement.

    Args:
        age: Current age
        yos: Years of service
        class_name: Membership class name
        tier: Tier string ("tier_1", "tier_2", "tier_3")

    Returns:
        Tuple of (is_eligible, retirement_type)
        retirement_type: "normal", "early", or ""
    """
    normal_age = get_normal_retirement_age(class_name)
    normal_yos = get_normal_retirement_yos(class_name)
    early_age = get_early_retirement_age(class_name)
    early_yos = get_early_retirement_yos(class_name)

    # Check normal retirement eligibility
    # Normal retirement: age >= normal_age OR yos >= normal_yos
    if age >= normal_age or yos >= normal_yos:
        return (True, "normal")

    # Check early retirement eligibility
    # Early retirement: age >= early_age AND yos >= early_yos
    if age >= early_age and yos >= early_yos:
        return (True, "early")

    return (False, "")


def get_retirement_rate_from_table(
    retirement_table: pd.DataFrame,
    class_name: str,
    age: int,
    gender: str = "male"
) -> Optional[float]:
    """
    Get retirement rate from table.

    Args:
        retirement_table: DataFrame with retirement rates
        class_name: Membership class name
        age: Current age
        gender: "male" or "female"

    Returns:
        Retirement rate or None if not found
    """
    if retirement_table is None or retirement_table.empty:
        return None

    # Try to find matching row
    # Tables have columns: age, class_name, gender, retirement_rate, table_type

    # First try exact match
    match = retirement_table[
        (retirement_table['age'] == age) &
        (retirement_table['class_name'] == class_name) &
        (retirement_table['gender'] == gender)
    ]

    if len(match) > 0 and 'retirement_rate' in match.columns:
        return match['retirement_rate'].iloc[0]

    # Try without gender
    match = retirement_table[
        (retirement_table['age'] == age) &
        (retirement_table['class_name'] == class_name)
    ]

    if len(match) > 0 and 'retirement_rate' in match.columns:
        return match['retirement_rate'].iloc[0]

    # Try just by age
    match = retirement_table[retirement_table['age'] == age]

    if len(match) > 0 and 'retirement_rate' in match.columns:
        return match['retirement_rate'].iloc[0]

    return None


def get_withdrawal_rate_from_table(
    withdrawal_table: pd.DataFrame,
    age: int,
    yos: int
) -> Optional[float]:
    """
    Get withdrawal rate from table.

    Args:
        withdrawal_table: DataFrame with withdrawal rates
        age: Current age
        yos: Years of service

    Returns:
        Withdrawal rate or None if not found
    """
    if withdrawal_table is None or withdrawal_table.empty:
        return None

    # Tables have columns: age, yos, withdrawal_rate
    if 'age' in withdrawal_table.columns and 'yos' in withdrawal_table.columns:
        match = withdrawal_table[
            (withdrawal_table['age'] == age) &
            (withdrawal_table['yos'] == yos)
        ]
        if len(match) > 0 and 'withdrawal_rate' in match.columns:
            return match['withdrawal_rate'].iloc[0]

    return None


class SeparationRateCalculator:
    """
    Calculator for combined separation rates.

    Implements the R model's combined separation rate logic that combines
    withdrawal and retirement rates based on tier eligibility.
    """

    def __init__(
        self,
        withdrawal_table: pd.DataFrame,
        normal_retirement_tier1: Optional[pd.DataFrame] = None,
        normal_retirement_tier2: Optional[pd.DataFrame] = None,
        early_retirement_tier1: Optional[pd.DataFrame] = None,
        early_retirement_tier2: Optional[pd.DataFrame] = None,
        class_name: str = "regular",
        new_year: int = 2024
    ):
        """
        Initialize the separation rate calculator.

        Args:
            withdrawal_table: DataFrame with withdrawal rates
            normal_retirement_tier1: DataFrame with tier 1 normal retirement rates
            normal_retirement_tier2: DataFrame with tier 2 normal retirement rates
            early_retirement_tier1: DataFrame with tier 1 early retirement rates
            early_retirement_tier2: DataFrame with tier 2 early retirement rates
            class_name: Membership class name
            new_year: Year when tier 3 starts (default 2024)
        """
        self.withdrawal_table = withdrawal_table
        self.normal_retirement_tier1 = normal_retirement_tier1
        self.normal_retirement_tier2 = normal_retirement_tier2
        self.early_retirement_tier1 = early_retirement_tier1
        self.early_retirement_tier2 = early_retirement_tier2
        self.class_name = class_name
        self.new_year = new_year

    def get_rate(
        self,
        age: int,
        yos: int,
        entry_year: int,
        entry_age: int,
        gender: str = "male"
    ) -> float:
        """
        Get combined separation rate.

        Args:
            age: Current age
            yos: Years of service
            entry_year: Year member entered the plan
            entry_age: Age at entry
            gender: "male" or "female"

        Returns:
            Combined separation rate (0.0 to to 1.0)
        """
        # Determine tier
        tier = determine_tier(entry_year, self.new_year)

        # Check retirement eligibility
        is_eligible, retirement_type = check_retirement_eligibility(
            age, yos, self.class_name, tier
        )

        if is_eligible and retirement_type == "normal":
            # Use normal retirement rate
            if tier == "tier_1":
                table = self.normal_retirement_tier1
            else:
                table = self.normal_retirement_tier2

            if table is not None:
                rate = get_retirement_rate_from_table(
                    table, self.class_name, age, gender
                )
                if rate is not None and rate > 0:
                    return rate

        if is_eligible and retirement_type == "early":
            # Use early retirement rate
            if tier == "tier_1":
                table = self.early_retirement_tier1
            else:
                table = self.early_retirement_tier2

            if table is not None:
                rate = get_retirement_rate_from_table(
                    table, self.class_name, age, gender
                )
                if rate is not None and rate > 0:
                    return rate

        # Not retirement-eligible, use withdrawal rate
        if self.withdrawal_table is not None:
            rate = get_withdrawal_rate_from_table(
                self.withdrawal_table, age, yos
            )
            if rate is not None:
                return rate

        return 0.0
