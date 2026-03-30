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


class DistributionLoader:
    """
    Load salary and headcount distribution files from R baseline outputs.

    These files contain age/YOS (years of service) grids with member counts
    and average salaries extracted from actuarial valuation reports.
    """

    # Standard age group ordering
    AGE_GROUPS = [
        "Under 20", "20 to 24", "25 to 29", "30 to 34", "35 to 39",
        "40 to 44", "45 to 49", "50 to 54", "55 to 59", "60 to 64", "65 & Up"
    ]

    # Standard YOS group ordering
    YOS_GROUPS = [
        "Under 5", "5 to 10", "10 to 15", "15 to 20", "20 to 25",
        "25 to 30", "30 to 35", "35 to 40", "40 to 45", "45 to 50", "50 & Up", "All Years"
    ]

    def __init__(self, base_path: Union[str, Path]):
        """
        Initialize the distribution loader.

        Args:
            base_path: Base directory containing distribution files
        """
        self.base_path = Path(base_path)

    def load_distribution_csv(
        self,
        class_name: str,
        data_type: str = "count"
    ) -> pd.DataFrame:
        """
        Load a distribution CSV file extracted from R baseline.

        Args:
            class_name: Membership class name (e.g., 'admin', 'eco')
            data_type: Type of data ('count' or 'salary')

        Returns:
            DataFrame with distribution data in long format
        """
        filename = f"{class_name}_dist_{data_type}.csv"
        filepath = self.base_path / filename

        if not filepath.exists():
            raise FileNotFoundError(f"Distribution file not found: {filepath}")

        df = pd.read_csv(filepath)
        return self._standardize_distribution(df)

    def load_distribution_excel(
        self,
        filename: str,
        data_type: str = "count"
    ) -> pd.DataFrame:
        """
        Load distribution data directly from Excel file.

        Args:
            filename: Name of the Excel file
            data_type: Type of data ('count' or 'salary')

        Returns:
            DataFrame with distribution data in long format
        """
        filepath = self.base_path / filename

        if not filepath.exists():
            raise FileNotFoundError(f"Distribution file not found: {filepath}")

        # Read Excel without headers
        df_raw = pd.read_excel(filepath, header=None, engine='openpyxl')

        return self._parse_distribution_excel(df_raw, data_type)

    def _parse_distribution_excel(
        self,
        df_raw: pd.DataFrame,
        data_type: str
    ) -> pd.DataFrame:
        """
        Parse raw Excel data into structured format.

        Args:
            df_raw: Raw DataFrame from Excel
            data_type: Type of data ('count' or 'salary')

        Returns:
            Structured DataFrame with distribution data
        """
        # Find header row (contains "Age" in first column)
        header_row = None
        for idx, row in df_raw.iterrows():
            if isinstance(row[0], str) and 'age' in row[0].lower():
                header_row = idx
                break

        if header_row is None:
            raise ValueError("Could not find header row with 'Age' column")

        # Extract YOS headers from header row
        yos_headers = []
        for val in df_raw.iloc[header_row, 1:]:
            if pd.notna(val) and str(val).strip():
                yos_headers.append(str(val).strip())

        # Determine data rows based on type
        if data_type == "count":
            # Count data is typically right after header
            data_start = header_row + 1
        else:
            # Salary data is after count data (look for "Avg. Annual Salary" or similar)
            for idx, row in df_raw.iterrows():
                if isinstance(row[0], str) and 'avg' in row[0].lower() and 'salary' in row[0].lower():
                    data_start = idx + 1
                    break
            else:
                # Fallback: assume salary is 16 rows after header
                data_start = header_row + 17

        data_end = data_start + len(self.AGE_GROUPS)

        # Extract data rows
        data_rows = df_raw.iloc[data_start:data_end]

        # Build structured DataFrame
        records = []
        for _, row in data_rows.iterrows():
            age_group = str(row[0]).strip() if pd.notna(row[0]) else None
            if not age_group:
                continue

            for i, yos in enumerate(yos_headers[:-1], start=1):  # Skip "All Years"
                value = row[i] if i < len(row) else None
                if pd.notna(value):
                    records.append({
                        'age_group': age_group,
                        'yos_group': yos,
                        'value': float(value)
                    })

        df = pd.DataFrame(records)
        return self._standardize_distribution(df)

    def _standardize_distribution(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize distribution DataFrame column names and values.

        Args:
            df: Raw distribution DataFrame

        Returns:
            Standardized DataFrame
        """
        # Standardize column names
        df.columns = df.columns.str.lower().str.replace(' ', '_')

        # Rename common variations
        rename_map = {
            'years_of_service': 'yos_group',
            'yrs_of_service': 'yos_group',
            'all_years': 'total'
        }
        df = df.rename(columns=rename_map)

        return df

    def load_all_distributions(
        self,
        class_names: Optional[list] = None
    ) -> dict:
        """
        Load all distribution files for specified classes.

        Args:
            class_names: List of class names to load. If None, loads all available.

        Returns:
            Dictionary mapping class_name to dict of count/salary DataFrames
        """
        if class_names is None:
            class_names = ['admin', 'eco', 'eso', 'judges', 'senior_management']

        distributions = {}
        for class_name in class_names:
            try:
                count_df = self.load_distribution_csv(class_name, 'count')
                salary_df = self.load_distribution_csv(class_name, 'salary')
                distributions[class_name] = {
                    'count': count_df,
                    'salary': salary_df
                }
            except FileNotFoundError as e:
                print(f"Warning: {e}")
                continue

        return distributions

    def to_long_format(
        self,
        df: pd.DataFrame,
        age_col: str = 'age_group',
        yos_cols: Optional[list] = None
    ) -> pd.DataFrame:
        """
        Convert wide-format distribution to long format.

        Args:
            df: Distribution DataFrame in wide format
            age_col: Name of age group column
            yos_cols: List of YOS column names. If None, uses standard groups.

        Returns:
            DataFrame in long format with columns: age_group, yos_group, value
        """
        if yos_cols is None:
            yos_cols = [c for c in df.columns if c != age_col and c != 'data_type' and c != 'total']

        records = []
        for _, row in df.iterrows():
            age = row[age_col]
            for yos in yos_cols:
                if yos in df.columns and pd.notna(row[yos]):
                    records.append({
                        'age_group': age,
                        'yos_group': yos,
                        'value': row[yos]
                    })

        return pd.DataFrame(records)

    def get_age_yos_index(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Create indexed distribution with numeric age and YOS midpoints.

        Args:
            df: Distribution DataFrame with age_group and yos_group columns

        Returns:
            DataFrame with added age_mid and yos_mid columns
        """
        df = df.copy()

        # Parse age groups to midpoints
        def parse_age_group(group):
            if not isinstance(group, str):
                return None
            group = group.strip()
            if 'under' in group.lower():
                return 17.5  # Under 20 -> midpoint 17.5
            elif '65' in group:
                return 67.5  # 65 & Up
            else:
                # Parse "X to Y" format
                parts = group.replace('to', '-').split('-')
                if len(parts) == 2:
                    try:
                        return (float(parts[0].strip()) + float(parts[1].strip())) / 2
                    except ValueError:
                        return None
            return None

        # Parse YOS groups to midpoints
        def parse_yos_group(group):
            if not isinstance(group, str):
                return None
            group = group.strip()
            if 'under' in group.lower():
                return 2.5  # Under 5 -> midpoint 2.5
            elif '50' in group and 'up' in group.lower():
                return 52.5  # 50 & Up
            elif 'all' in group.lower():
                return None  # Skip totals
            else:
                # Parse "X to Y" or "X-Y" format
                parts = group.replace('to', '-').replace('_', ' ').split('-')
                if len(parts) == 2:
                    try:
                        return (float(parts[0].strip()) + float(parts[1].strip())) / 2
                    except ValueError:
                        return None
            return None

        df['age_mid'] = df['age_group'].apply(parse_age_group)
        df['yos_mid'] = df['yos_group'].apply(parse_yos_group)

        return df
