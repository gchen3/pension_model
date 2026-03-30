"""
Extract decrement tables from R model Excel files and convert to clean CSV format.

This script parses the raw Excel files from the R model's extracted inputs
and converts them to standardized CSV files for use in the Python model.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def parse_withdrawal_table(filepath: Path) -> pd.DataFrame:
    """
    Parse a withdrawal rate table from Excel.

    The tables have:
    - Rows: Years of service (0 to 30+)
    - Columns: Age bands (Under 25, 25 to 29, 30 to 34, 35 to 44, 45 to 54, 55+)

    Returns a DataFrame in long format with columns:
    - yos: Years of service (int, 30+ mapped to 30)
    - age_band: Age band string
    - withdrawal_rate: Withdrawal rate (float)
    """
    # Read raw Excel file
    df_raw = pd.read_excel(filepath, header=None)

    # Find the data rows by looking for the YOS header row
    start_row = None
    for idx, row in df_raw.iterrows():
        if row[0] == 'Combined Years' or (isinstance(row[0], str) and 'of Service' in str(row[0])):
            start_row = idx + 1
            if row[0] == 'Combined Years':
                # Header row is next, data starts after
                start_row = idx + 2
            break

    if start_row is None:
        # Try to find by looking for numeric YOS values
        for idx, row in df_raw.iterrows():
            if row[0] == 0 or row[0] == '0':
                start_row = idx
                break

    # Extract age bands from header row
    age_bands = []
    header_row_idx = start_row - 1
    for col_idx in range(1, len(df_raw.columns)):
        val = df_raw.iloc[header_row_idx, col_idx]
        if pd.notna(val):
            age_bands.append(str(val).strip())

    # If no age bands found, use defaults
    if not age_bands:
        age_bands = ['Under 25', '25 to 29', '30 to 34', '35 to 44', '45 to 54', '55+']

    # Extract data rows
    data_rows = []
    for idx in range(start_row, len(df_raw)):
        row = df_raw.iloc[idx]
        yos_raw = row[0]

        # Stop at non-numeric YOS or NaN
        if pd.isna(yos_raw):
            continue

        # Handle YOS values
        if yos_raw == '30+':
            yos = 30
        elif isinstance(yos_raw, (int, float)):
            try:
                yos = int(yos_raw)
            except (ValueError, TypeError):
                break
        else:
            break

        # Extract rates for each age band
        for col_idx, age_band in enumerate(age_bands):
            if col_idx + 1 < len(row):
                rate = row[col_idx + 1]
                if pd.notna(rate):
                    data_rows.append({
                        'yos': yos,
                        'age_band': age_band,
                        'withdrawal_rate': float(rate)
                    })

    return pd.DataFrame(data_rows)


def parse_retirement_table(filepath: Path, table_type: str = 'normal') -> pd.DataFrame:
    """
    Parse a retirement rate table from Excel.

    The tables have varying structures:
    - Normal retirement tier 1: 11 columns (includes K-12 and Non-K12 Regular)
    - Normal retirement tier 2: 11 columns
    - Early retirement: 9 columns (no K-12 split)
    - DROP entry: 11 columns

    Returns a DataFrame in long format with columns:
    - age: Age (int, 70-79 band mapped to 70)
    - class_name: Membership class
    - gender: 'male' or 'female'
    - retirement_rate: Retirement rate (float)
    """
    # Read raw Excel file
    df_raw = pd.read_excel(filepath, header=None)

    # Find the Age header row to determine table structure
    age_header_row = None
    for idx, row in df_raw.iterrows():
        if row[0] == 'Age':
            age_header_row = idx
            break

    if age_header_row is None:
        raise ValueError(f"Could not find Age header in {filepath}")

    # Determine column structure based on number of columns with data
    num_cols = 0
    for col_idx in range(len(df_raw.columns)):
        val = df_raw.iloc[age_header_row, col_idx]
        if pd.notna(val):
            num_cols = col_idx + 1

    # Define column mappings based on table structure
    if num_cols >= 11:
        # Full structure with K-12 split (11 columns)
        column_mappings = {
            1: ('regular_k12', 'female'),
            2: ('regular_k12', 'male'),
            3: ('regular_non_k12', 'female'),
            4: ('regular_non_k12', 'male'),
            5: ('special', 'female'),
            6: ('special', 'male'),
            7: ('elected_officers', 'female'),
            8: ('elected_officers', 'male'),
            9: ('senior_management', 'female'),
            10: ('senior_management', 'male'),
        }
    else:
        # Reduced structure without K-12 split (9 columns)
        column_mappings = {
            1: ('regular_non_k12', 'female'),
            2: ('regular_non_k12', 'male'),
            3: ('special', 'female'),
            4: ('special', 'male'),
            5: ('elected_officers', 'female'),
            6: ('elected_officers', 'male'),
            7: ('senior_management', 'female'),
            8: ('senior_management', 'male'),
        }

    # Extract data rows
    data_rows = []
    for idx in range(age_header_row + 1, len(df_raw)):
        row = df_raw.iloc[idx]
        age_raw = row[0]

        # Stop if we hit a non-numeric age (footer text)
        if pd.isna(age_raw):
            continue

        # Handle age values
        if age_raw == '70-79':
            age = 70
        elif isinstance(age_raw, (int, float)) and not pd.isna(age_raw):
            try:
                age = int(age_raw)
            except (ValueError, TypeError):
                break
        else:
            break

        # Extract rates for each class/gender combination
        for col_idx, (class_name, gender) in column_mappings.items():
            if col_idx < len(row):
                rate = row[col_idx]
                if pd.notna(rate):
                    data_rows.append({
                        'age': age,
                        'class_name': class_name,
                        'gender': gender,
                        'retirement_rate': float(rate)
                    })

    df = pd.DataFrame(data_rows)
    df['table_type'] = table_type
    return df


def parse_drop_entry_table(filepath: Path) -> pd.DataFrame:
    """
    Parse a DROP entry rate table from Excel.

    DROP (Deferred Retirement Option Program) entry rates indicate
    the probability of entering DROP at each age.

    Returns a DataFrame in long format.
    """
    return parse_retirement_table(filepath, table_type='drop_entry')


def parse_early_retirement_table(filepath: Path) -> pd.DataFrame:
    """
    Parse an early retirement rate table from Excel.

    Returns a DataFrame in long format.
    """
    return parse_retirement_table(filepath, table_type='early')


def expand_age_band(age_band: str) -> Tuple[int, int]:
    """
    Convert age band string to min/max ages.

    Args:
        age_band: String like 'Under 25', '25 to 29', '55+'

    Returns:
        Tuple of (min_age, max_age)
    """
    if age_band == 'Under 25':
        return (18, 24)
    elif age_band == '25 to 29':
        return (25, 29)
    elif age_band == '30 to 34':
        return (30, 34)
    elif age_band == '35 to 44':
        return (35, 44)
    elif age_band == '45 to 54':
        return (45, 54)
    elif age_band == '55+':
        return (55, 120)
    else:
        return (18, 120)


def expand_withdrawal_to_single_ages(df: pd.DataFrame) -> pd.DataFrame:
    """
    Expand withdrawal table from age bands to single ages.

    Args:
        df: DataFrame with age_band column

    Returns:
        DataFrame with single age column
    """
    rows = []
    for _, row in df.iterrows():
        min_age, max_age = expand_age_band(row['age_band'])
        for age in range(min_age, max_age + 1):
            rows.append({
                'yos': row['yos'],
                'age': age,
                'withdrawal_rate': row['withdrawal_rate']
            })
    return pd.DataFrame(rows)


def parse_withdrawal_from_main_excel(
    filepath: Path,
    sheet_name: str
) -> pd.DataFrame:
    """
    Parse withdrawal table from main Excel file (Florida FRS inputs.xlsx).

    These tables have a different format than the extracted inputs.

    Returns a DataFrame in long format with columns:
    - yos: Years of service (int)
    - age_band: Age band string
    - withdrawal_rate: Withdrawal rate (float)
    """
    # Read the sheet
    df_raw = pd.read_excel(filepath, sheet_name=sheet_name, header=None)

    # Find the header row with age bands
    # Look for row containing "Years of Service" or similar
    start_row = None
    for idx, row in df_raw.iterrows():
        first_val = str(row[0]).strip() if pd.notna(row[0]) else ""
        if 'Years of Service' in first_val or 'years of service' in first_val.lower():
            start_row = idx + 1
            break
        # Also check for numeric YOS values starting at 0
        if row[0] == 0 or row[0] == '0':
            start_row = idx
            break

    if start_row is None:
        raise ValueError(f"Could not find data start in sheet {sheet_name}")

    # Extract age bands from header row (if exists)
    header_row = start_row - 1
    age_bands = []
    for col_idx in range(1, len(df_raw.columns)):
        val = df_raw.iloc[header_row, col_idx]
        if pd.notna(val):
            age_bands.append(str(val).strip())

    # If no age bands found, use defaults
    if not age_bands or all(ab == '' for ab in age_bands):
        age_bands = ['Under 25', '25 to 29', '30 to 34', '35 to 39', '40 to 44', '45 to 49', '50 to 54', '55 to 59', '60 to 64', '65+']

    # Extract data rows
    data_rows = []
    for idx in range(start_row, len(df_raw)):
        row = df_raw.iloc[idx]
        yos_raw = row[0]

        # Stop at non-numeric YOS or NaN
        if pd.isna(yos_raw):
            continue

        # Handle YOS values
        if isinstance(yos_raw, str) and '+' in yos_raw:
            yos = int(yos_raw.replace('+', ''))
        elif isinstance(yos_raw, (int, float)):
            try:
                yos = int(yos_raw)
            except (ValueError, TypeError):
                break
        else:
            break

        # Stop if YOS > 30 (beyond normal range)
        if yos > 30:
            break

        # Extract rates for each age band
        for col_idx, age_band in enumerate(age_bands):
            if col_idx + 1 < len(row):
                rate = row[col_idx + 1]
                if pd.notna(rate):
                    data_rows.append({
                        'yos': yos,
                        'age_band': age_band,
                        'withdrawal_rate': float(rate)
                    })

    return pd.DataFrame(data_rows)


def main():
    """Main extraction function."""
    # Define paths
    extracted_inputs_dir = Path("R_model/R_model_original/Reports/extracted inputs")
    main_excel_file = Path("R_model/R_model_original/Florida FRS inputs.xlsx")
    output_dir = Path("baseline_outputs/decrement_tables")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Extracting Decrement Tables from R Model")
    print("=" * 60)

    # ========================================
    # 1. Extract Withdrawal Tables from extracted inputs
    # ========================================
    print("\n1. Extracting Withdrawal Tables from extracted inputs...")

    withdrawal_files = {
        'special_male': 'withdrawal rate spec risk male.xlsx',
        'special_female': 'withdrawal rate spec risk female.xlsx',
        'senior_management_male': 'withdrawal rate sen man male.xlsx',
        'senior_management_female': 'withdrawal rate sen man female.xlsx',
        'eco': 'withdrawal rate eco.xlsx',
        'eso': 'withdrawal rate eso.xlsx',
        'judges': 'withdrawal rate judges.xlsx',
    }

    for name, filename in withdrawal_files.items():
        filepath = extracted_inputs_dir / filename
        if filepath.exists():
            print(f"   Processing {filename}...")
            try:
                df = parse_withdrawal_table(filepath)
                df_expanded = expand_withdrawal_to_single_ages(df)

                # Save both formats
                df.to_csv(output_dir / f"withdrawal_{name}_banded.csv", index=False)
                df_expanded.to_csv(output_dir / f"withdrawal_{name}.csv", index=False)
                print(f"      Saved {len(df_expanded)} records")
            except Exception as e:
                print(f"      ERROR: {e}")
        else:
            print(f"   WARNING: {filename} not found")

    # ========================================
    # 1b. Extract Withdrawal Tables from main Excel file
    # ========================================
    print("\n1b. Extracting Withdrawal Tables from main Excel file...")

    main_excel_withdrawal = {
        'regular_male': 'Withdrawal Rate Regular Male',
        'regular_female': 'Withdrawal Rate Regular Female',
        'admin_male': 'Withdrawal Rate Admin Male',
        'admin_female': 'Withdrawal Rate Admin Female',
    }

    if main_excel_file.exists():
        for name, sheet_name in main_excel_withdrawal.items():
            print(f"   Processing sheet: {sheet_name}...")
            try:
                df = parse_withdrawal_from_main_excel(main_excel_file, sheet_name)
                if len(df) > 0:
                    df_expanded = expand_withdrawal_to_single_ages(df)

                    # Save both formats
                    df.to_csv(output_dir / f"withdrawal_{name}_banded.csv", index=False)
                    df_expanded.to_csv(output_dir / f"withdrawal_{name}.csv", index=False)
                    print(f"      Saved {len(df_expanded)} records")
                else:
                    print(f"      WARNING: No data extracted")
            except Exception as e:
                print(f"      ERROR: {e}")
    else:
        print(f"   WARNING: Main Excel file not found: {main_excel_file}")

    # ========================================
    # 2. Extract Retirement Tables
    # ========================================
    print("\n2. Extracting Retirement Tables...")

    # Normal retirement
    retirement_files = {
        'tier1': 'normal retirement tier 1.xlsx',
        'tier2': 'normal retirement tier 2.xlsx',
    }

    for tier, filename in retirement_files.items():
        filepath = extracted_inputs_dir / filename
        if filepath.exists():
            print(f"   Processing {filename}...")
            try:
                df = parse_retirement_table(filepath, table_type='normal')
                df.to_csv(output_dir / f"normal_retirement_{tier}.csv", index=False)
                print(f"      Saved {len(df)} records")
            except Exception as e:
                print(f"      ERROR: {e}")
        else:
            print(f"   WARNING: {filename} not found")

    # Early retirement
    early_files = {
        'tier1': 'early retirement tier 1.xlsx',
        'tier2': 'early retirement tier 2.xlsx',
    }

    for tier, filename in early_files.items():
        filepath = extracted_inputs_dir / filename
        if filepath.exists():
            print(f"   Processing {filename}...")
            try:
                df = parse_retirement_table(filepath, table_type='early')
                df.to_csv(output_dir / f"early_retirement_{tier}.csv", index=False)
                print(f"      Saved {len(df)} records")
            except Exception as e:
                print(f"      ERROR: {e}")
        else:
            print(f"   WARNING: {filename} not found")

    # DROP entry
    drop_files = {
        'tier1': 'drop entry tier 1.xlsx',
        'tier2': 'drop entry tier 2.xlsx',
    }

    for tier, filename in drop_files.items():
        filepath = extracted_inputs_dir / filename
        if filepath.exists():
            print(f"   Processing {filename}...")
            try:
                df = parse_drop_entry_table(filepath)
                df.to_csv(output_dir / f"drop_entry_{tier}.csv", index=False)
                print(f"      Saved {len(df)} records")
            except Exception as e:
                print(f"      ERROR: {e}")
        else:
            print(f"   WARNING: {filename} not found")

    # ========================================
    # 3. Create Summary
    # ========================================
    print("\n" + "=" * 60)
    print("Extraction Complete!")
    print("=" * 60)
    print(f"\nOutput directory: {output_dir}")
    print("\nGenerated files:")
    for f in sorted(output_dir.glob("*.csv")):
        print(f"   - {f.name}")

    return True


if __name__ == "__main__":
    main()
