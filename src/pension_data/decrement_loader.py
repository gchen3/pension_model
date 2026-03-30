"""
Decrement table loader for pension modeling.

This module provides loaders for mortality, withdrawal, and retirement
decrement tables extracted from the R baseline.
"""

from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple
import pandas as pd
import numpy as np


class DecrementLoader:
    """
    Load decrement tables from R baseline outputs.

    Handles mortality, withdrawal, and retirement tables for
    all membership classes.
    """

    # Standard membership classes
    CLASSES = [
        "regular", "special", "admin", "eco", "eso",
        "judges", "senior_management"
    ]

    # Map class names to retirement table class names
    RETIREMENT_CLASS_MAP = {
        "regular": "regular_non_k12",  # Default to non-k12 for regular
        "special": "special",
        "admin": "special",  # Admin uses special risk rates
        "eco": "elected_officers",
        "eso": "elected_officers",  # ESO uses elected officers rates
        "judges": "elected_officers",  # Judges use elected officers rates
        "senior_management": "senior_management",
    }

    # Map class names to withdrawal table names
    # Based on R model (Florida FRS benefit model.R lines 584-590):
    #   regular_separation_rate_table <- get_separation_table("regular")
    #   special_separation_rate_table <- get_separation_table("special")
    #   admin_separation_rate_table <- get_separation_table("admin")
    #   eco_separation_rate_table <- get_separation_table("eco")
    #   eso_separation_rate_table <- get_separation_table("regular")  # ESO uses REGULAR!
    #   judges_separation_rate_table <- get_separation_table("judges")
    #   senior_management_separation_rate_table <- get_separation_table("senior management")
    WITHDRAWAL_CLASS_MAP = {
        "special": "special",  # Has male/female variants
        "admin": "admin",  # Has male/female variants (now extracted)
        "senior_management": "senior_management",  # Has male/female variants
        "eco": "eco",  # Single table
        "eso": "regular",  # ESO uses REGULAR rates per R model!
        "judges": "judges",  # Single table
        "regular": "regular",  # Has male/female variants (now extracted)
    }

    def __init__(self, baseline_dir: Union[str, Path] = "baseline_outputs"):
        """
        Initialize the decrement loader.

        Args:
            baseline_dir: Directory containing baseline output files
        """
        self.baseline_dir = Path(baseline_dir)
        self.decrement_dir = self.baseline_dir / "decrement_tables"

        # Cache for loaded tables
        self._withdrawal_cache: Dict[str, pd.DataFrame] = {}
        self._retirement_cache: Dict[str, pd.DataFrame] = {}

    def load_mortality_table(self, class_name: str) -> pd.DataFrame:
        """
        Load mortality table for a membership class.

        Args:
            class_name: Name of membership class

        Returns:
            DataFrame with mortality rates by entry_year, entry_age, dist_year, etc.
        """
        filename = f"{class_name}_mortality_rates.csv"
        filepath = self.baseline_dir / filename

        if not filepath.exists():
            raise FileNotFoundError(f"Mortality table not found: {filepath}")

        return pd.read_csv(filepath)

    def load_all_mortality_tables(self) -> Dict[str, pd.DataFrame]:
        """Load mortality tables for all classes."""
        tables = {}
        for class_name in self.CLASSES:
            try:
                tables[class_name] = self.load_mortality_table(class_name)
            except FileNotFoundError:
                pass
        return tables

    def get_mortality_rate(
        self,
        mort_table: pd.DataFrame,
        entry_year: int,
        entry_age: int,
        dist_year: int,
        dist_age: int,
        term_year: Optional[int] = None
    ) -> float:
        """
        Get mortality rate from table for specific parameters.

        Args:
            mort_table: Mortality DataFrame
            entry_year: Year of entry
            entry_age: Age at entry
            dist_year: Year of distribution (death/retirement)
            dist_age: Age at distribution
            term_year: Year of termination (for terminated members)

        Returns:
            Mortality rate
        """
        # Build filter
        conditions = (
            (mort_table['entry_year'] == entry_year) &
            (mort_table['entry_age'] == entry_age) &
            (mort_table['dist_year'] == dist_year) &
            (mort_table['dist_age'] == dist_age)
        )

        if term_year is not None and 'term_year' in mort_table.columns:
            conditions &= (mort_table['term_year'] == term_year)

        matches = mort_table[conditions]

        if len(matches) == 0:
            return 0.0

        return matches['mort_final'].iloc[0]

    # ========================================
    # Withdrawal Table Loading
    # ========================================

    def load_withdrawal_table(
        self,
        class_name: str,
        gender: Optional[str] = None
    ) -> Optional[pd.DataFrame]:
        """
        Load withdrawal rate table for a membership class.

        Args:
            class_name: Name of membership class
            gender: 'male' or 'female' (required for some classes)

        Returns:
            DataFrame with withdrawal rates (columns: yos, age, withdrawal_rate)
        """
        cache_key = f"{class_name}_{gender}" if gender else class_name
        if cache_key in self._withdrawal_cache:
            return self._withdrawal_cache[cache_key]

        df = self._load_withdrawal_table_internal(class_name, gender)
        if df is not None:
            self._withdrawal_cache[cache_key] = df
        return df

    def _load_withdrawal_table_internal(
        self,
        class_name: str,
        gender: Optional[str] = None
    ) -> Optional[pd.DataFrame]:
        """Internal method to load withdrawal tables."""

        # Check decrement_tables directory first (new format)
        if self.decrement_dir.exists():
            df = self._load_withdrawal_from_decrement_dir(class_name, gender)
            if df is not None:
                return df

        # Fall back to baseline_dir (old format)
        return self._load_withdrawal_from_baseline_dir(class_name)

    def _load_withdrawal_from_decrement_dir(
        self,
        class_name: str,
        gender: Optional[str] = None
    ) -> Optional[pd.DataFrame]:
        """Load withdrawal table from decrement_tables directory."""

        # Map class name to table name FIRST
        table_class = self.WITHDRAWAL_CLASS_MAP.get(class_name, class_name)

        # Classes with gender-specific tables
        # Note: ESO maps to "regular" which IS gender-specific!
        gender_classes = ["special", "admin", "senior_management", "regular"]

        if table_class in gender_classes:
            # This class uses gender-specific tables
            if gender is None:
                # Default to male if not specified
                gender = "male"

            filename = f"withdrawal_{table_class}_{gender}.csv"
            filepath = self.decrement_dir / filename

            if filepath.exists():
                return pd.read_csv(filepath)

        else:
            # Classes with single tables (eco, judges)
            filename = f"withdrawal_{table_class}.csv"
            filepath = self.decrement_dir / filename

            if filepath.exists():
                return pd.read_csv(filepath)

        return None

    def _load_withdrawal_from_baseline_dir(
        self,
        class_name: str
    ) -> Optional[pd.DataFrame]:
        """Load withdrawal table from baseline_dir (legacy format)."""
        possible_names = [
            f"{class_name}_withdrawal_rates.csv",
            f"{class_name}_separation_rates.csv"
        ]

        for filename in possible_names:
            filepath = self.baseline_dir / filename
            if filepath.exists():
                return pd.read_csv(filepath)

        return None

    def get_withdrawal_rate(
        self,
        withdrawal_table: pd.DataFrame,
        age: int,
        yos: int
    ) -> float:
        """
        Get withdrawal rate from table for specific age and YOS.

        Args:
            withdrawal_table: DataFrame with yos, age, withdrawal_rate columns
            age: Age of member
            yos: Years of service

        Returns:
            Withdrawal rate
        """
        matches = withdrawal_table[
            (withdrawal_table['age'] == age) &
            (withdrawal_table['yos'] == yos)
        ]

        if len(matches) == 0:
            return 0.0

        return matches['withdrawal_rate'].iloc[0]

    # ========================================
    # Retirement Table Loading
    # ========================================

    def load_retirement_table(
        self,
        tier: str = "tier1",
        table_type: str = "normal"
    ) -> Optional[pd.DataFrame]:
        """
        Load retirement rate table.

        Args:
            tier: 'tier1' or 'tier2'
            table_type: 'normal', 'early', or 'drop_entry'

        Returns:
            DataFrame with retirement rates
        """
        cache_key = f"{table_type}_{tier}"
        if cache_key in self._retirement_cache:
            return self._retirement_cache[cache_key]

        df = self._load_retirement_table_internal(tier, table_type)
        if df is not None:
            self._retirement_cache[cache_key] = df
        return df

    def _load_retirement_table_internal(
        self,
        tier: str,
        table_type: str
    ) -> Optional[pd.DataFrame]:
        """Internal method to load retirement tables."""

        # Check decrement_tables directory first (new format)
        if self.decrement_dir.exists():
            if table_type == "normal":
                filename = f"normal_retirement_{tier}.csv"
            elif table_type == "early":
                filename = f"early_retirement_{tier}.csv"
            elif table_type == "drop_entry":
                filename = f"drop_entry_{tier}.csv"
            else:
                return None

            filepath = self.decrement_dir / filename
            if filepath.exists():
                return pd.read_csv(filepath)

        return None

    def get_retirement_rate(
        self,
        retirement_table: pd.DataFrame,
        class_name: str,
        age: int,
        gender: str = "male"
    ) -> float:
        """
        Get retirement rate from table for specific parameters.

        Args:
            retirement_table: DataFrame with retirement rates
            class_name: Membership class
            age: Age of member
            gender: 'male' or 'female'

        Returns:
            Retirement rate
        """
        # Map class name to retirement table class
        table_class = self.RETIREMENT_CLASS_MAP.get(class_name, class_name)

        matches = retirement_table[
            (retirement_table['class_name'] == table_class) &
            (retirement_table['age'] == age) &
            (retirement_table['gender'] == gender)
        ]

        if len(matches) == 0:
            return 0.0

        return matches['retirement_rate'].iloc[0]

    def load_all_retirement_tables(self, tier: str = "tier1") -> Dict[str, pd.DataFrame]:
        """
        Load all retirement tables for a tier.

        Args:
            tier: 'tier1' or 'tier2'

        Returns:
            Dictionary with 'normal', 'early', 'drop_entry' tables
        """
        tables = {}
        for table_type in ['normal', 'early', 'drop_entry']:
            table = self.load_retirement_table(tier=tier, table_type=table_type)
            if table is not None:
                tables[table_type] = table
        return tables

    # ========================================
    # Legacy Methods (for backwards compatibility)
    # ========================================

    def load_salary_growth_table(self) -> pd.DataFrame:
        """
        Load salary growth table.

        Returns:
            DataFrame with salary growth rates by age and YOS
        """
        filepath = self.baseline_dir / "salary_growth_table.csv"

        if not filepath.exists():
            raise FileNotFoundError(f"Salary growth table not found: {filepath}")

        return pd.read_csv(filepath)

    def load_distribution(self, class_name: str, data_type: str = "count") -> pd.DataFrame:
        """
        Load salary/headcount distribution for a class.

        Args:
            class_name: Name of membership class
            data_type: Type of data ('count' or 'salary')

        Returns:
            DataFrame with age/YOS distribution
        """
        filename = f"{class_name}_dist_{data_type}.csv"
        filepath = self.baseline_dir / filename

        if not filepath.exists():
            raise FileNotFoundError(f"Distribution file not found: {filepath}")

        return pd.read_csv(filepath)

    def load_workforce_data(self, class_name: str, data_type: str = "active") -> pd.DataFrame:
        """
        Load workforce projection data for a class.

        Args:
            class_name: Name of membership class
            data_type: Type of workforce data ('active', 'term', 'refund', 'retire')

        Returns:
            DataFrame with workforce projection
        """
        filename = f"{class_name}_wf_{data_type}.csv"
        filepath = self.baseline_dir / filename

        if not filepath.exists():
            raise FileNotFoundError(f"Workforce file not found: {filepath}")

        return pd.read_csv(filepath)

    def load_funding_data(self, class_name: str) -> pd.DataFrame:
        """
        Load funding data for a class.

        Args:
            class_name: Name of membership class

        Returns:
            DataFrame with funding projection
        """
        filename = f"{class_name}_funding.csv"
        filepath = self.baseline_dir / filename

        if not filepath.exists():
            raise FileNotFoundError(f"Funding file not found: {filepath}")

        return pd.read_csv(filepath)

    def load_liability_data(self, class_name: str) -> pd.DataFrame:
        """
        Load liability data for a class.

        Args:
            class_name: Name of membership class

        Returns:
            DataFrame with liability projection
        """
        filename = f"{class_name}_liability.csv"
        filepath = self.baseline_dir / filename

        if not filepath.exists():
            raise FileNotFoundError(f"Liability file not found: {filepath}")

        return pd.read_csv(filepath)

    def load_liability_summary(self, class_name: str) -> Dict:
        """
        Load liability summary for a class.

        Args:
            class_name: Name of membership class

        Returns:
            Dictionary with liability summary
        """
        import json

        filename = f"{class_name}_liability_summary.json"
        filepath = self.baseline_dir / filename

        if not filepath.exists():
            raise FileNotFoundError(f"Liability summary not found: {filepath}")

        with open(filepath, 'r') as f:
            return json.load(f)

    def load_workforce_summary(self, class_name: str) -> Dict:
        """
        Load workforce summary for a class.

        Args:
            class_name: Name of membership class

        Returns:
            Dictionary with workforce summary
        """
        import json

        filename = f"{class_name}_wf_summary.json"
        filepath = self.baseline_dir / filename

        if not filepath.exists():
            raise FileNotFoundError(f"Workforce summary not found: {filepath}")

        with open(filepath, 'r') as f:
            return json.load(f)

    def load_input_params(self) -> Dict:
        """
        Load input parameters from baseline.

        Returns:
            Dictionary with input parameters
        """
        import json

        filepath = self.baseline_dir / "input_params.json"

        if not filepath.exists():
            raise FileNotFoundError(f"Input params not found: {filepath}")

        with open(filepath, 'r') as f:
            return json.load(f)

    def load_separation_table(self, class_name: str) -> pd.DataFrame:
        """
        Load pre-computed combined separation rate table for a class.

        These tables combine withdrawal and retirement rates based on tier
        eligibility, following the R model's get_separation_table function.

        Args:
            class_name: Membership class name

        Returns:
            DataFrame with columns: entry_year, entry_age, term_age, yos,
                                   term_year, tier, separation_rate
        """
        separation_dir = self.baseline_dir / "separation_tables"
        filepath = separation_dir / f"separation_{class_name}.csv"

        if not filepath.exists():
            raise FileNotFoundError(f"Separation table not found: {filepath}")

        return pd.read_csv(filepath)

    def get_separation_rate(
        self,
        class_name: str,
        entry_year: int,
        entry_age: int,
        term_age: int,
        yos: int
    ) -> Tuple[str, float]:
        """
        Get separation rate for specific parameters from pre-computed table.

        Args:
            class_name: Membership class name
            entry_year: Year member entered the plan
            entry_age: Age at entry
            term_age: Age at potential termination
            yos: Years of service

        Returns:
            Tuple of (tier, separation_rate)
        """
        sep_df = self.load_separation_table(class_name)

        # Find matching row
        mask = (
            (sep_df['entry_year'] == entry_year) &
            (sep_df['entry_age'] == entry_age) &
            (sep_df['term_age'] == term_age) &
            (sep_df['yos'] == yos)
        )

        matching_rows = sep_df[mask]

        if len(matching_rows) == 0:
            return ("unknown", 0.0)

        row = matching_rows.iloc[0]
        return (row['tier'], row['separation_rate'])

    def get_available_classes(self) -> List[str]:
        """
        Get list of available membership classes with data.

        Returns:
            List of class names with available data
        """
        classes = set()

        # Check for workforce summary files
        for filepath in self.baseline_dir.glob("*_wf_summary.json"):
            class_name = filepath.stem.replace("_wf_summary", "")
            classes.add(class_name)

        return sorted(list(classes))


def create_decrement_loader(baseline_dir: str = "baseline_outputs") -> DecrementLoader:
    """
    Factory function to create a DecrementLoader.

    Args:
        baseline_dir: Directory containing baseline output files

    Returns:
        Configured DecrementLoader instance
    """
    return DecrementLoader(baseline_dir=baseline_dir)
