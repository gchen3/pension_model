"""
Data transformers for pension modeling.

This module transforms raw plan-specific data into standardized formats
for use throughout the pension modeling framework.
"""

from typing import Optional, Dict, List, Tuple
import pandas as pd
import numpy as np

from pension_data.schemas import (
    SalaryData,
    HeadcountData,
    SalaryHeadcountData,
    MortalityRate,
    WithdrawalRate,
    RetirementEligibility,
    SalaryGrowthRate,
    EntrantProfile,
    WorkforceData,
    BenefitValuation,
)


class DataTransformer:
    """
    Transform raw plan-specific data into standardized formats.

    This class handles converting Excel/CSV data into the standardized
    Pydantic models used throughout the pension modeling framework.
    """

    def __init__(self, config):
        """
        Initialize the transformer with plan configuration.

        Args:
            config: Plan configuration object
        """
        self.config = config

    def create_salary_headcount_table(
        self,
        salary_df: pd.DataFrame,
        headcount_df: pd.DataFrame,
        salary_growth_df: pd.DataFrame,
        membership_class: str
    ) -> pd.DataFrame:
        """
        Create combined salary and headcount table with cumulative salary growth.

        Args:
            salary_df: Salary table by yos and age
            headcount_df: Headcount table by yos and age
            salary_growth_df: Salary growth rates by yos
            membership_class: Name of membership class

        Returns:
            Combined table with salary, count, and cumulative growth
        """
        # Calculate cumulative salary growth
        salary_growth_df = salary_growth_df.sort_values('yos')
        salary_growth_df['cumprod_salary_increase'] = (
            (1 + salary_growth_df['growth_rate']).cumprod() - 1
        )

        # Merge salary and headcount data
        combined = salary_df.merge(
            headcount_df,
            on=['yos', 'age'],
            how='left',
            suffixes=('_sal', '_hc')
        )

        # Add cumulative salary growth
        combined = combined.merge(
            salary_growth_df[['yos', 'cumprod_salary_increase']],
            on='yos',
            how='left'
        )

        # Calculate entry salary (salary / cumulative growth)
        combined['entry_salary'] = combined['salary_sal'] / combined['cumprod_salary_increase']

        # Calculate entry age
        combined['entry_age'] = combined['age'] - combined['yos']

        # Add membership class
        combined['membership_class'] = membership_class

        return combined

    def create_entrant_profile(
        self,
        salary_headcount_df: pd.DataFrame,
        membership_class: str
    ) -> pd.DataFrame:
        """
        Create entrant profile from salary headcount table.

        Args:
            salary_headcount_df: Combined salary and headcount table
            membership_class: Name of membership class

        Returns:
            Entrant profile with entry age, salary, and distribution
        """
        # Filter for latest entry year (highest entry_year)
        latest_entry_year = salary_headcount_df['entry_year'].max()
        entrants = salary_headcount_df[
            salary_headcount_df['entry_year'] == latest_entry_year
        ].copy()

        # Calculate entrant distribution
        total_count = entrants['count'].sum()
        entrants['entrant_dist'] = entrants['count'] / total_count

        # Rename for consistency
        entrants = entrants.rename(columns={
            'entry_salary': 'start_sal'
        })

        # Add membership class
        entrants['membership_class'] = membership_class

        return entrants[['entry_age', 'start_sal', 'entrant_dist']]

    def standardize_mortality_table(
        self,
        mortality_df: pd.DataFrame,
        gender: str
    ) -> pd.DataFrame:
        """
        Standardize mortality table format.

        Args:
            mortality_df: Raw mortality table
            gender: Gender for the table (male/female)

        Returns:
            Standardized mortality table
        """
        df = mortality_df.copy()

        # Ensure required columns exist
        required_cols = ['age', 'qx']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        # Add gender column
        df['gender'] = gender.lower()

        # Validate qx values
        if not df['qx'].between(0, 1).all():
            raise ValueError("Mortality rates (qx) must be between 0 and 1")

        return df

    def standardize_withdrawal_table(
        self,
        withdrawal_df: pd.DataFrame,
        membership_class: str,
        gender: str
    ) -> pd.DataFrame:
        """
        Standardize withdrawal rate table format.

        Args:
            withdrawal_df: Raw withdrawal rate table
            membership_class: Name of membership class
            gender: Gender for the table (male/female)

        Returns:
            Standardized withdrawal table
        """
        df = withdrawal_df.copy()

        # Ensure required columns exist
        required_cols = ['yos', 'age', 'rate']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        # Add metadata
        df['membership_class'] = membership_class
        df['gender'] = gender.lower()

        # Validate rate values
        if not df['rate'].between(0, 1).all():
            raise ValueError("Withdrawal rates must be between 0 and 1")

        return df

    def standardize_retirement_table(
        self,
        retirement_df: pd.DataFrame,
        tier: int
    ) -> pd.DataFrame:
        """
        Standardize retirement eligibility table format.

        Args:
            retirement_df: Raw retirement eligibility table
            tier: Tier number for the table

        Returns:
            Standardized retirement table
        """
        df = retirement_df.copy()

        # Ensure required columns exist
        required_cols = ['yos', 'age', 'normal_retirement', 'early_retirement']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        # Add tier column
        df['tier'] = tier

        # Validate boolean columns
        bool_cols = ['normal_retirement', 'early_retirement']
        for col in bool_cols:
            if not df[col].isin([True, False]).all():
                raise ValueError(f"Column {col} must contain only True/False values")

        return df

    def validate_data_consistency(
        self,
        data_dict: Dict[str, pd.DataFrame]
    ) -> List[str]:
        """
        Validate consistency across multiple data sources.

        Args:
            data_dict: Dictionary of data sources by name

        Returns:
            List of validation warnings/errors
        """
        warnings = []

        # Check age ranges
        for name, df in data_dict.items():
            if 'age' in df.columns:
                min_age = df['age'].min()
                max_age = df['age'].max()
                if min_age < 18:
                    warnings.append(f"{name}: Minimum age {min_age} is below 18")
                if max_age > 120:
                    warnings.append(f"{name}: Maximum age {max_age} exceeds 120")

        # Check YOS ranges
        for name, df in data_dict.items():
            if 'yos' in df.columns:
                max_yos = df['yos'].max()
                if max_yos > 70:
                    warnings.append(f"{name}: Maximum YOS {max_yos} exceeds 70")

        return warnings
