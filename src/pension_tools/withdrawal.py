"""
Withdrawal rate functions for pension modeling.

This module provides withdrawal (separation) rate calculations
for active members leaving employment before retirement.
"""

from typing import Dict, Optional, Union
import pandas as pd
import numpy as np


def get_withdrawal_rate(yos: int, age: int, membership_class: str, gender: str = "male") -> float:
    """
    Get withdrawal rate for a given combination of YOS, age, and gender.

    Args:
        yos: Years of service
        age: Age of member
        membership_class: Membership class
        gender: Gender (male or female)

    Returns:
        Withdrawal rate (probability of leaving plan)
    """
    # This is a placeholder - actual rates come from withdrawal tables
    # Implementation will load from withdrawal rate tables
    return 0.01  # Default placeholder


def load_withdrawal_table(df: pd.DataFrame) -> Dict[tuple, float]:
    """
    Convert a withdrawal DataFrame to a dictionary.

    Supports various table formats:
    - By age and YOS
    - By age only
    - By YOS only
    - With gender distinction

    Args:
        df: DataFrame with withdrawal rate data

    Returns:
        Dictionary mapping (age, yos, gender) to withdrawal rate
    """
    table = {}

    for _, row in df.iterrows():
        age = row.get('age', row.get('age_band', 0))
        yos = row.get('yos', row.get('years_of_service', row.get('yos_band', 0)))
        gender = row.get('gender', 'all')

        # Get rate from various possible column names
        if 'withdrawal_rate' in row:
            rate = row['withdrawal_rate']
        elif 'sep_rate' in row:
            rate = row['sep_rate']
        elif 'separation_rate' in row:
            rate = row['separation_rate']
        elif 'rate' in row:
            rate = row['rate']
        else:
            # Try to find a numeric column that could be the rate
            numeric_cols = row.select_dtypes(include=[np.number]).index
            rate = row[numeric_cols[0]] if len(numeric_cols) > 0 else 0.0

        key = (int(age) if pd.notna(age) else 0,
               int(yos) if pd.notna(yos) else 0,
               str(gender) if pd.notna(gender) else 'all')

        table[key] = rate

    return table


def get_withdrawal_rate_from_table(
    table: Dict[tuple, float],
    age: int,
    yos: int,
    gender: str = "male"
) -> float:
    """
    Get withdrawal rate from a loaded table.

    Tries exact match first, then falls back to approximations.

    Args:
        table: Withdrawal table dictionary
        age: Current age
        yos: Years of service
        gender: Gender (male, female, or all)

    Returns:
        Withdrawal rate
    """
    # Try exact match
    key = (age, yos, gender)
    if key in table:
        return table[key]

    # Try with 'all' gender
    key = (age, yos, 'all')
    if key in table:
        return table[key]

    # Try age-only match
    key = (age, 0, gender)
    if key in table:
        return table[key]

    # Try YOS-only match
    key = (0, yos, gender)
    if key in table:
        return table[key]

    # Default
    return 0.01


def get_separation_rate_from_df(
    df: pd.DataFrame,
    age: int,
    yos: int,
    entry_age: Optional[int] = None,
    year: Optional[int] = None
) -> float:
    """
    Get separation rate directly from DataFrame.

    Supports various table formats from R baseline extraction.

    Args:
        df: Separation rate DataFrame
        age: Current age
        yos: Years of service
        entry_age: Entry age (optional)
        year: Current year (optional)

    Returns:
        Separation rate
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

    if year is not None and 'year' in df.columns:
        conditions &= (df['year'] == year)

    # Find matching row
    matches = df[conditions]

    if len(matches) == 0:
        return 0.01  # Default

    # Get rate column
    if 'separation_rate' in matches.columns:
        return matches['separation_rate'].iloc[0]
    elif 'sep_rate' in matches.columns:
        return matches['sep_rate'].iloc[0]
    elif 'withdrawal_rate' in matches.columns:
        return matches['withdrawal_rate'].iloc[0]
    else:
        # Return first numeric column that's not an identifier
        numeric = matches.select_dtypes(include=[np.number])
        exclude_cols = ['age', 'yos', 'years_of_service', 'entry_age', 'year', 'entry_year']
        rate_cols = [c for c in numeric.columns if c not in exclude_cols]
        if rate_cols:
            return matches[rate_cols[0]].iloc[0]

    return 0.01


def apply_withdrawal_to_cohort(
    cohort: pd.DataFrame,
    withdrawal_table: Dict[tuple, float],
    age_col: str = 'age',
    yos_col: str = 'yos',
    count_col: str = 'n_active',
    gender: str = 'male'
) -> pd.DataFrame:
    """
    Apply withdrawal to a cohort of members.

    Args:
        cohort: DataFrame with member counts by age/YOS
        withdrawal_table: Withdrawal table dictionary
        age_col: Name of age column
        yos_col: Name of YOS column
        count_col: Name of count column
        gender: Gender for withdrawal rates

    Returns:
        DataFrame with added columns:
        - withdrawal_rate: withdrawal rate
        - withdrawals: expected withdrawals
        - remaining: expected remaining active
    """
    result = cohort.copy()

    result['withdrawal_rate'] = result.apply(
        lambda row: get_withdrawal_rate_from_table(
            withdrawal_table,
            int(row[age_col]) if pd.notna(row[age_col]) else 0,
            int(row[yos_col]) if pd.notna(row[yos_col]) else 0,
            gender
        ),
        axis=1
    )

    result['withdrawals'] = result[count_col] * result['withdrawal_rate']
    result['remaining'] = result[count_col] * (1 - result['withdrawal_rate'])

    return result
