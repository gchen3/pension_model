"""
Separation Table Generator Module

Generates pre-computed separation rate tables following the R model's approach.
Handles missing data by filling with adjacent values.
"""
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np


def get_tier(entry_year: int, age: int, yos: int, class_name: str, new_year: int = 2024) -> str:
    """
    Determine tier and retirement eligibility based on R model's get_tier function.

    Args:
        entry_year: Year the member entered the plan
        age: Current age
        yos: Years of service
        class_name: Membership class
        new_year: Year for new tier (default 2024)

    Returns:
        Tier string indicating tier and eligibility status
    """
    is_special_admin = class_name.lower() in ("special", "admin")

    if entry_year < 2011:
        # Tier 1
        if is_special_admin:
            if yos >= 25 or (age >= 55 and yos >= 6) or (age >= 52 and yos >= 25):
                return "tier_1_norm"
            elif yos >= 6 and age >= 53:
                return "tier_1_early"
            elif yos >= 6:
                return "tier_1_vested"
            else:
                return "tier_1_non_vested"
        else:
            if yos >= 30 or (age >= 62 and yos >= 6):
                return "tier_1_norm"
            elif yos >= 6 and age >= 58:
                return "tier_1_early"
            elif yos >= 6:
                return "tier_1_vested"
            else:
                return "tier_1_non_vested"
    elif entry_year < new_year:
        # Tier 2
        if is_special_admin:
            if yos >= 30 or (age >= 60 and yos >= 8):
                return "tier_2_norm"
            elif yos >= 8 and age >= 56:
                return "tier_2_early"
            elif yos >= 8:
                return "tier_2_vested"
            else:
                return "tier_2_non_vested"
        else:
            if yos >= 33 or (age >= 65 and yos >= 8):
                return "tier_2_norm"
            elif yos >= 8 and age >= 61:
                return "tier_2_early"
            elif yos >= 8:
                return "tier_2_vested"
            else:
                return "tier_2_non_vested"
    else:
        # Tier 3
        if is_special_admin:
            if yos >= 30 or (age >= 60 and yos >= 8):
                return "tier_3_norm"
            elif yos >= 8 and age >= 56:
                return "tier_3_early"
            elif yos >= 8:
                return "tier_3_vested"
            else:
                return "tier_3_non_vested"
        else:
            if yos >= 33 or (age >= 65 and yos >= 8):
                return "tier_3_norm"
            elif yos >= 8 and age >= 61:
                return "tier_3_early"
            elif yos >= 8:
                return "tier_3_vested"
            else:
                return "tier_3_non_vested"


# Class name mappings for retirement tables
# Based on R model's get_normal_retire_rate_table and get_early_retire_rate_table functions
# IMPORTANT: ESO uses Regular's entire separation table per R model line 588:
#   eso_separation_rate_table <- get_separation_table("regular")
RETIREMENT_CLASS_MAP = {
    "regular": ["regular_k12", "regular_non_k12"],  # Average of both
    "special": ["special"],
    "admin": ["special"],  # Admin uses Special rates per R model line 383
    "eco": ["elected_officers"],  # ECO uses elected_officers rates
    "eso": ["regular_k12", "regular_non_k12"],  # ESO uses Regular rates per R model line 588!
    "judges": ["elected_officers"],  # Judges use elected_officers rates
    "senior_management": ["senior_management"],
}


def load_withdrawal_table(class_name: str, decrement_dir: Path) -> pd.DataFrame:
    """
    Load withdrawal table for a class (average of male/female rates).
    Fills missing values with adjacent values.
    """
    male_file = decrement_dir / f"withdrawal_{class_name}_male.csv"
    female_file = decrement_dir / f"withdrawal_{class_name}_female.csv"

    # Some classes use same table for both genders
    if not male_file.exists():
        male_file = decrement_dir / f"withdrawal_{class_name}.csv"
        female_file = male_file

    if male_file.exists() and female_file.exists():
        male_df = pd.read_csv(male_file)
        female_df = pd.read_csv(female_file)

        # Average male and female rates
        combined = male_df.copy()
        combined['withdrawal_rate'] = (male_df['withdrawal_rate'] + female_df['withdrawal_rate']) / 2

        # Fill missing values with forward/backward fill
        combined = combined.sort_values(['yos', 'age'])
        combined['withdrawal_rate'] = combined.groupby('yos')['withdrawal_rate'].transform(
            lambda x: x.ffill().bfill()
        )

        return combined
    else:
        raise FileNotFoundError(f"Withdrawal table not found for {class_name}")


def load_retirement_tables(decrement_dir: Path) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    Load retirement rate tables for both tiers, organized by class.

    Returns:
        Dict with structure: {class_name: {"normal_t1": df, "normal_t2": df, "early_t1": df, "early_t2": df}}
    """
    normal_t1_raw = pd.read_csv(decrement_dir / "normal_retirement_tier1.csv")
    normal_t2_raw = pd.read_csv(decrement_dir / "normal_retirement_tier2.csv")
    early_t1_raw = pd.read_csv(decrement_dir / "early_retirement_tier1.csv")
    early_t2_raw = pd.read_csv(decrement_dir / "early_retirement_tier2.csv")

    # Organize by class
    class_tables = {}
    for class_name, table_classes in RETIREMENT_CLASS_MAP.items():
        def get_class_rates(df, table_classes):
            filtered = df[df['class_name'].isin(table_classes)]
            # Group by age and average the retirement_rate
            return filtered.groupby('age')['retirement_rate'].mean().reset_index()

        class_tables[class_name] = {
            "normal_t1": get_class_rates(normal_t1_raw, table_classes),
            "normal_t2": get_class_rates(normal_t2_raw, table_classes),
            "early_t1": get_class_rates(early_t1_raw, table_classes),
            "early_t2": get_class_rates(early_t2_raw, table_classes),
        }

    return class_tables


def get_withdrawal_rate(withdrawal_df: pd.DataFrame, age: int, yos: int) -> float:
    """
    Get withdrawal rate for given age and yos.
    Falls back to nearest age/yos if exact match not found.
    """
    if withdrawal_df is None or withdrawal_df.empty:
        return 0.0

    # Try exact match first
    matching = withdrawal_df[(withdrawal_df['yos'] == yos) & (withdrawal_df['age'] == age)]

    if len(matching) > 0:
        return float(matching['withdrawal_rate'].iloc[0])

    # Fall back to nearest yos
    yos_matches = withdrawal_df[withdrawal_df['yos'] == yos]
    if len(yos_matches) > 0:
        # Find nearest age
        ages = yos_matches['age'].values
        nearest_age = ages[np.argmin(np.abs(ages - age))]
        matching = yos_matches[yos_matches['age'] == nearest_age]
        if len(matching) > 0:
            return float(matching['withdrawal_rate'].iloc[0])

    # Fall back to nearest age
    age_matches = withdrawal_df[withdrawal_df['age'] == age]
    if len(age_matches) > 0:
        # Find nearest yos
        yoses = age_matches['yos'].values
        nearest_yos = yoses[np.argmin(np.abs(yoses - yos))]
        matching = age_matches[age_matches['yos'] == nearest_yos]
        if len(matching) > 0:
            return float(matching['withdrawal_rate'].iloc[0])

    # Last resort: find globally nearest point
    distances = np.sqrt((withdrawal_df['age'] - age)**2 + (withdrawal_df['yos'] - yos)**2)
    nearest_idx = distances.idxmin()
    return float(withdrawal_df.loc[nearest_idx, 'withdrawal_rate'])


def get_retirement_rate(retirement_df: pd.DataFrame, age: int) -> float:
    """
    Get retirement rate for given age from processed table.
    Falls back to nearest age if exact match not found.
    """
    if 'age' not in retirement_df.columns or 'retirement_rate' not in retirement_df.columns:
        return 0.0

    row = retirement_df[retirement_df['age'] == age]
    if len(row) > 0:
        return row['retirement_rate'].iloc[0]

    # Fall back to nearest age
    ages = retirement_df['age'].values
    nearest_age = ages[np.argmin(np.abs(ages - age))]
    row = retirement_df[retirement_df['age'] == nearest_age]
    if len(row) > 0:
        return row['retirement_rate'].iloc[0]

    return 0.0


def get_entry_ages_from_workforce(class_name: str, baseline_dir: Path) -> List[int]:
    """Get actual entry ages from workforce data."""
    try:
        wf_file = baseline_dir / f"{class_name}_wf_active.csv"
        if wf_file.exists():
            wf_df = pd.read_csv(wf_file)
            return sorted(wf_df['entry_age'].unique().tolist())
    except Exception as e:
        print(f"Warning: Could not load workforce data for {class_name}: {e}")
    return []


def generate_separation_table(
    class_name: str,
    withdrawal_df: pd.DataFrame,
    retirement_tables: Dict[str, pd.DataFrame],
    entry_year_range: range,
    entry_age_range: List[int],
    age_range: range,
    yos_range: range,
    new_year: int = 2024
) -> pd.DataFrame:
    """
    Generate combined separation rate table following R model's get_separation_table function.

    The R model creates separation rates based on tier eligibility:
    - Normal retirement: Use normal retirement rate
    - Early retirement: Use early retirement rate
    - Vested: Use withdrawal (termination) rate
    - Non-vested: Use withdrawal rate
    """
    rows = []

    for entry_year in entry_year_range:
        for entry_age in entry_age_range:
            for yos in yos_range:
                term_age = entry_age + yos

                # Skip if term_age is outside valid range
                if term_age < min(age_range) or term_age > max(age_range):
                    continue

                # Calculate term_year
                term_year = entry_year + yos

                # Get tier at this point
                tier = get_tier(entry_year, term_age, yos, class_name, new_year)

                # Get withdrawal rate (with fallback)
                withdrawal_rate = get_withdrawal_rate(withdrawal_df, term_age, yos)

                # Get retirement rates (with fallback)
                normal_t1 = get_retirement_rate(retirement_tables["normal_t1"], term_age)
                normal_t2 = get_retirement_rate(retirement_tables["normal_t2"], term_age)
                early_t1 = get_retirement_rate(retirement_tables["early_t1"], term_age)
                early_t2 = get_retirement_rate(retirement_tables["early_t2"], term_age)

                # Determine separation rate based on tier (following R model lines 565-571)
                if tier in ("tier_3_norm", "tier_2_norm"):
                    separation_rate = normal_t2
                elif tier in ("tier_3_early", "tier_2_early"):
                    separation_rate = early_t2
                elif tier == "tier_1_norm":
                    separation_rate = normal_t1
                elif tier == "tier_1_early":
                    separation_rate = early_t1
                elif "vested" in tier:
                    separation_rate = withdrawal_rate
                else:
                    separation_rate = withdrawal_rate

                rows.append({
                    'entry_year': entry_year,
                    'entry_age': entry_age,
                    'term_age': term_age,
                    'yos': yos,
                    'term_year': term_year,
                    'tier': tier,
                    'separation_rate': separation_rate
                })

    return pd.DataFrame(rows)


def generate_all_separation_tables(baseline_dir: Path = None) -> None:
    """
    Generate separation tables for all classes.
    Uses entry ages from actual workforce data to ensure complete coverage.
    """
    if baseline_dir is None:
        baseline_dir = Path("baseline_outputs")

    decrement_dir = baseline_dir / "decrement_tables"
    output_dir = baseline_dir / "separation_tables"
    output_dir.mkdir(exist_ok=True)

    # Load retirement tables (organized by class)
    retirement_tables = load_retirement_tables(decrement_dir)

    # Class configurations
    # Note: ESO uses Regular withdrawal table per R model line 588
    classes = {
        "regular": {"withdrawal_class": "regular"},
        "special": {"withdrawal_class": "special"},
        "admin": {"withdrawal_class": "admin"},
        "eco": {"withdrawal_class": "eco"},
        "eso": {"withdrawal_class": "regular"},  # ESO uses Regular!
        "judges": {"withdrawal_class": "judges"},
        "senior_management": {"withdrawal_class": "senior_management"},
    }

    # Ranges from R model
    min_year = 1970
    start_year = 2022
    model_period = 30
    max_age = 120
    min_age = 18
    new_year = 2024

    entry_year_range = range(min_year, start_year + model_period + 1)
    age_range = range(min_age, max_age + 1)
    yos_range = range(0, 71)

    for class_name, config in classes.items():
        print(f"Generating separation table for {class_name}...")

        # Load withdrawal table
        withdrawal_class = config["withdrawal_class"]
        withdrawal_df = load_withdrawal_table(withdrawal_class, decrement_dir)

        # Get entry ages from actual workforce data to ensure complete coverage
        entry_ages = get_entry_ages_from_workforce(class_name, baseline_dir)
        if not entry_ages:
            # Fall back to default entry ages
            print(f"  Warning: No workforce data found, using default entry ages")
            entry_ages = list(range(20, 56))

        print(f"  Entry ages: {entry_ages}")

        # Generate separation table
        sep_df = generate_separation_table(
            class_name=class_name,
            withdrawal_df=withdrawal_df,
            retirement_tables=retirement_tables[class_name],
            entry_year_range=entry_year_range,
            entry_age_range=entry_ages,
            age_range=age_range,
            yos_range=yos_range,
            new_year=new_year
        )

        # Save to CSV
        output_file = output_dir / f"separation_{class_name}.csv"
        sep_df.to_csv(output_file, index=False)
        print(f"  Saved {output_file} ({len(sep_df)} rows)")

    print("\nDone!")


if __name__ == "__main__":
    generate_all_separation_tables()
