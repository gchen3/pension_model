"""
Data loaders for pension modeling.

This module handles loading data from Excel and CSV files
and converting them to standardized formats.
"""

from pathlib import Path
from typing import Optional, Union

import pandas as pd
import openpyxl


class ExcelLoader:
    """
    Load and validate Excel data files for pension modeling.

    This class provides methods to load various Excel files
    used in pension modeling (salary, headcount, mortality,
    withdrawal rates, retirement tables, etc.).
    """

    def __init__(self, base_path: Union[str, Path]):
        """
        Initialize the loader with a base path for data files.

        Args:
            base_path: Base directory containing data files
        """
        self.base_path = Path(base_path)

    def load_salary_table(self, filename: str, sheet_name: str = 0) -> pd.DataFrame:
        """
        Load salary table from Excel file.

        Args:
            filename: Name of the Excel file
            sheet_name: Name or index of sheet to load

        Returns:
            DataFrame with salary data
        """
        filepath = self.base_path / filename
        df = pd.read_excel(filepath, sheet_name=sheet_name, engine='openpyxl')

        # Standardize column names (lowercase, replace spaces with underscores)
        df.columns = df.columns.str.lower().str.replace(' ', '_')

        return df

    def load_headcount_table(self, filename: str, sheet_name: str = 0) -> pd.DataFrame:
        """
        Load headcount table from Excel file.

        Args:
            filename: Name of the Excel file
            sheet_name: Name or index of sheet to load

        Returns:
            DataFrame with headcount data
        """
        filepath = self.base_path / filename
        df = pd.read_excel(filepath, sheet_name=sheet_name, engine='openpyxl')

        # Standardize column names
        df.columns = df.columns.str.lower().str.replace(' ', '_')

        return df

    def load_mortality_table(self, filename: str, sheet_name: str = 0) -> pd.DataFrame:
        """
        Load mortality table from Excel file.

        Args:
            filename: Name of the Excel file
            sheet_name: Name or index of sheet to load

        Returns:
            DataFrame with mortality data
        """
        filepath = self.base_path / filename
        df = pd.read_excel(filepath, sheet_name=sheet_name, engine='openpyxl')

        # Standardize column names
        df.columns = df.columns.str.lower().str.replace(' ', '_')

        return df

    def load_withdrawal_table(
        self,
        filename: str,
        sheet_name: str = 0,
        gender: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Load withdrawal rate table from Excel file.

        Args:
            filename: Name of the Excel file
            sheet_name: Name or index of sheet to load
            gender: Gender for the table (male/female)

        Returns:
            DataFrame with withdrawal rate data
        """
        filepath = self.base_path / filename
        df = pd.read_excel(filepath, sheet_name=sheet_name, engine='openpyxl')

        # Standardize column names
        df.columns = df.columns.str.lower().str.replace(' ', '_')

        # Add gender column if specified
        if gender:
            df['gender'] = gender.lower()

        return df

    def load_retirement_table(
        self,
        filename: str,
        sheet_name: str = 0,
        tier: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Load retirement eligibility table from Excel file.

        Args:
            filename: Name of the Excel file
            sheet_name: Name or index of sheet to load
            tier: Tier number for the table

        Returns:
            DataFrame with retirement eligibility data
        """
        filepath = self.base_path / filename
        df = pd.read_excel(filepath, sheet_name=sheet_name, engine='openpyxl')

        # Standardize column names
        df.columns = df.columns.str.lower().str.replace(' ', '_')

        # Add tier column if specified
        if tier:
            df['tier'] = tier

        return df


class CSVLoader:
    """
    Load and validate CSV data files for pension modeling.
    """

    def __init__(self, base_path: Union[str, Path]):
        """
        Initialize the loader with a base path for data files.

        Args:
            base_path: Base directory containing data files
        """
        self.base_path = Path(base_path)

    def load(self, filename: str) -> pd.DataFrame:
        """
        Load CSV file.

        Args:
            filename: Name of the CSV file

        Returns:
            DataFrame with data
        """
        filepath = self.base_path / filename
        df = pd.read_csv(filepath)

        # Standardize column names
        df.columns = df.columns.str.lower().str.replace(' ', '_')

        return df
