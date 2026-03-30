"""
Mortality rate functions for pension modeling.

This module provides mortality rate calculations using standard actuarial
notation (qx = probability of death within one year).
"""

from typing import Dict, Optional, Union
import pandas as pd
import numpy as np


def qx(age: int, table: Dict[int, float]) -> float:
    """
    Get mortality rate (qx) for a given age from a mortality table.

    Args:
        age: Age of the member
        table: Dictionary mapping age to mortality rate

    Returns:
        Mortality rate (probability of death within one year)
    """
    return table.get(age, table.get(max(table.keys()), 0.0))


def load_mortality_table(df: pd.DataFrame) -> Dict[int, float]:
    """
    Convert a mortality DataFrame to a dictionary.

    Args:
        df: DataFrame with 'age' and 'mort_rate' or 'qx' columns

    Returns:
        Dictionary mapping age to mortality rate
    """
    if 'mort_rate' in df.columns:
        rate_col = 'mort_rate'
    elif 'qx' in df.columns:
        rate_col = 'qx'
    elif 'mort_final' in df.columns:
        rate_col = 'mort_final'
    else:
        # Try to find a numeric column that could be the rate
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        rate_col = numeric_cols[0] if len(numeric_cols) > 0 else None

    if rate_col is None:
        raise ValueError("Could not find mortality rate column")

    # Get age column
    if 'age' in df.columns:
        age_col = 'age'
    else:
        age_col = df.columns[0]

    return dict(zip(df[age_col], df[rate_col]))


def tp_r(n: int, age: int, table: Dict[int, float]) -> float:
    """
    Calculate n-year survival probability from age x.

    Uses recursion: n_p_x = p_x * (n-1)_p_(x+1)

    Args:
        n: Number of years
        age: Starting age
        table: Mortality table dictionary

    Returns:
        Probability of surviving n years from age x
    """
    if n == 0:
        return 1.0
    if n == 1:
        return 1.0 - qx(age, table)

    # Recursive calculation
    p_x = 1.0 - qx(age, table)
    return p_x * tp_r(n - 1, age + 1, table)


def tq_r(n: int, age: int, table: Dict[int, float]) -> float:
    """
    Calculate n-year mortality probability from age x.

    Args:
        n: Number of years
        age: Starting age
        table: Mortality table dictionary

    Returns:
        Probability of dying within n years from age x
    """
    return 1.0 - tp_r(n, age, table)


def ex(age: int, table: Dict[int, float], max_age: int = 120) -> float:
    """
    Calculate life expectancy from age x.

    Uses curtate life expectancy formula:
    e_x = sum(k=1 to infinity) of k_p_x

    Args:
        age: Starting age
        table: Mortality table dictionary
        max_age: Maximum age for calculation

    Returns:
        Curtate life expectancy from age x
    """
    expectancy = 0.0
    for k in range(1, max_age - age + 1):
        expectancy += tp_r(k, age, table)
    return expectancy


def apply_mortality_to_cohort(
    cohort: pd.DataFrame,
    mort_table: Dict[int, float],
    age_col: str = 'age',
    count_col: str = 'n_active'
) -> pd.DataFrame:
    """
    Apply mortality to a cohort of members.

    Args:
        cohort: DataFrame with member counts by age
        mort_table: Mortality table dictionary
        age_col: Name of age column
        count_col: Name of count column

    Returns:
        DataFrame with added columns:
        - mort_rate: mortality rate for each age
        - deaths: expected deaths
        - survivors: expected survivors
    """
    result = cohort.copy()
    result['mort_rate'] = result[age_col].apply(lambda a: qx(a, mort_table))
    result['deaths'] = result[count_col] * result['mort_rate']
    result['survivors'] = result[count_col] * (1 - result['mort_rate'])

    return result


def get_mortality_rate_from_table(
    df: pd.DataFrame,
    age: int,
    year: Optional[int] = None,
    entry_age: Optional[int] = None,
    term_year: Optional[int] = None
) -> float:
    """
    Get mortality rate from a mortality table DataFrame.

    Supports various table formats:
    - Simple: age -> rate
    - With year: age, year -> rate
    - With entry_age and term_year for terminated members

    Args:
        df: Mortality table DataFrame
        age: Current age
        year: Current year (optional)
        entry_age: Entry age (optional)
        term_year: Termination year (optional)

    Returns:
        Mortality rate
    """
    # Build filter conditions
    conditions = pd.Series([True] * len(df))

    if 'age' in df.columns:
        conditions &= (df['age'] == age)

    if year is not None and 'year' in df.columns:
        conditions &= (df['year'] == year)

    if entry_age is not None and 'entry_age' in df.columns:
        conditions &= (df['entry_age'] == entry_age)

    if term_year is not None and 'term_year' in df.columns:
        conditions &= (df['term_year'] == term_year)

    # Find matching row
    matches = df[conditions]

    if len(matches) == 0:
        return 0.0

    # Get rate column
    if 'mort_final' in matches.columns:
        return matches['mort_final'].iloc[0]
    elif 'mort_rate' in matches.columns:
        return matches['mort_rate'].iloc[0]
    elif 'qx' in matches.columns:
        return matches['qx'].iloc[0]
    else:
        # Return first numeric column
        numeric = matches.select_dtypes(include=[np.number])
        if len(numeric.columns) > 0:
            return numeric.iloc[0, 0]

    return 0.0


def complement_of_survival(qx_values: list) -> list:
    """
    Calculate complement of survival probabilities (1 - qx for each value).

    Args:
        qx_values: List of mortality rates (qx)

    Returns:
        List of survival probabilities (1 - qx)
    """
    return [1.0 - qx for qx in qx_values]


def survival_probability(qx_table: Dict[int, float], start_age: int, end_age: int) -> float:
    """
    Calculate cumulative probability of surviving from start_age to end_age.

    Formula: product of (1 - qx) for each age

    Args:
        qx_table: Dictionary mapping age to mortality rate
        start_age: Starting age
        end_age: Ending age

    Returns:
        Cumulative survival probability
    """
    prob = 1.0
    for age in range(start_age, end_age):
        qx = qx_table.get(age, 0.0)
        prob *= (1.0 - qx)
    return prob
