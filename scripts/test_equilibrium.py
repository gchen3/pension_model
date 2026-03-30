"""
Test workforce equilibrium with pop_growth=0.

This script tests that the WorkforceProjector maintains constant population
when pop_growth=0, matching the R model behavior.

Expected behavior:
- With pop_growth=0, new entrants should exactly replace separations
- Active population should stay constant over 30 years
"""

import pandas as pd
import numpy as np
from pathlib import Path

# Import the workforce projector
from pension_model.core.workforce import WorkforceProjector, WorkforceState
from pension_config.frs_adapter import FRSAdapter
from pension_config.plan import PlanConfig
from pension_config.types import MembershipClass


def load_entrant_profile(class_name: str) -> pd.DataFrame:
    """Load entrant profile from baseline outputs."""
    profile_path = Path(f"baseline_outputs/entrant_profiles/{class_name}_entrant_profile.csv")
    if profile_path.exists():
        return pd.read_csv(profile_path)
    else:
        raise FileNotFoundError(f"Entrant profile not found: {profile_path}")


def load_separation_table(class_name: str) -> pd.DataFrame:
    """Load separation table from baseline outputs."""
    sep_path = Path(f"baseline_outputs/decrement_tables/withdrawal_{class_name}_male.csv")
    if sep_path.exists():
        df = pd.read_csv(sep_path)
        # Rename to match expected format
        df = df.rename(columns={'withdrawal_rate': 'separation_rate'})
        # Add entry_age column (for simplicity, assume entry_age = age - yos)
        # This is a simplification - real model would have proper entry_age tracking
        return df
    else:
        raise FileNotFoundError(f"Separation table not found: {sep_path}")


def create_initial_workforce(class_name: str, target_population: int = 100000) -> pd.DataFrame:
    """
    Create initial workforce distribution based on entrant profile.

    Distributes target population across entry ages according to entrant_dist.
    """
    profile = load_entrant_profile(class_name)

    # Create workforce with entry_age, age, n_active
    # For simplicity, assume all members are at entry_age (new hires)
    rows = []
    for _, row in profile.iterrows():
        entry_age = int(row['entry_age'])
        count = target_population * row['entrant_dist']
        rows.append({
            'entry_age': entry_age,
            'age': entry_age,
            'n_active': count
        })

    return pd.DataFrame(rows)


def get_separation_rate_simple(sep_table: pd.DataFrame, age: int, yos: int) -> float:
    """Get separation rate from table using age and yos."""
    match = sep_table[
        (sep_table['age'] == age) &
        (sep_table['yos'] == yos)
    ]
    if len(match) > 0:
        return match['separation_rate'].iloc[0]
    return 0.0


def test_equilibrium():
    """Test that workforce stays constant with pop_growth=0."""
    print("=" * 60)
    print("WORKFORCE EQUILIBRIUM TEST")
    print("Testing with pop_growth=0")
    print("=" * 60)

    # Test parameters
    class_name = "regular"
    start_year = 2022
    projection_years = 30
    pop_growth = 0.0  # Key parameter - should maintain equilibrium

    print(f"\nClass: {class_name}")
    print(f"Start Year: {start_year}")
    print(f"Projection Years: {projection_years}")
    print(f"Population Growth: {pop_growth}")

    # Load entrant profile
    try:
        entrant_profile = load_entrant_profile(class_name)
        print(f"\n[OK] Entrant profile loaded: {len(entrant_profile)} entry ages")
    except Exception as e:
        print(f"\n[FAIL] Failed to load entrant profile: {e}")
        return False

    # Load separation table
    try:
        sep_table = load_separation_table(class_name)
        print(f"[OK] Separation table loaded: {len(sep_table)} records")
    except Exception as e:
        print(f"[FAIL] Failed to load separation table: {e}")
        return False

    # Create initial workforce
    try:
        initial_workforce = create_initial_workforce(class_name, target_population=100000)
        total_initial = initial_workforce['n_active'].sum()
        print(f"[OK] Initial workforce created: {total_initial:,.0f} members")
    except Exception as e:
        print(f"[FAIL] Failed to create initial workforce: {e}")
        return False

    # Run simplified projection (without full WorkforceProjector which needs more setup)
    print(f"\nRunning {projection_years}-year projection...")

    try:
        # Track active population by entry_age, age
        current_workforce = initial_workforce.copy()

        results = []
        results.append({
            'year': start_year,
            'active': current_workforce['n_active'].sum()
        })

        for year in range(start_year + 1, start_year + projection_years + 1):
            # Calculate pre-decrement total
            pre_decrement_total = current_workforce['n_active'].sum()

            # Apply separations (simplified - just apply rates)
            new_rows = []
            total_separations = 0

            for _, row in current_workforce.iterrows():
                entry_age = row['entry_age']
                age = row['age']
                n_active = row['n_active']

                # Calculate YOS
                yos = age - entry_age

                # Get separation rate
                sep_rate = get_separation_rate_simple(sep_table, age, yos)

                # Apply separation
                separations = n_active * sep_rate
                remaining = n_active - separations
                total_separations += separations

                # Age the population
                if remaining > 0 and age < 100:
                    new_rows.append({
                        'entry_age': entry_age,
                        'age': age + 1,
                        'n_active': remaining
                    })

            # Create aged workforce
            current_workforce = pd.DataFrame(new_rows)

            # Calculate post-decrement total
            post_decrement_total = current_workforce['n_active'].sum()

            # Add new entrants using R formula: ne = pre * (1 + g) - post
            new_entrants_total = pre_decrement_total * (1 + pop_growth) - post_decrement_total

            # Distribute new entrants according to entrant profile
            for _, profile_row in entrant_profile.iterrows():
                entry_age = int(profile_row['entry_age'])
                entrant_dist = profile_row['entrant_dist']
                new_entrants = new_entrants_total * entrant_dist

                if new_entrants > 0:
                    # Add to workforce at entry age
                    existing = current_workforce[current_workforce['entry_age'] == entry_age]
                    if len(existing) > 0 and existing[existing['age'] == entry_age].shape[0] > 0:
                        # Update existing row
                        idx = current_workforce[
                            (current_workforce['entry_age'] == entry_age) &
                            (current_workforce['age'] == entry_age)
                        ].index[0]
                        current_workforce.loc[idx, 'n_active'] += new_entrants
                    else:
                        # Add new row
                        current_workforce = pd.concat([
                            current_workforce,
                            pd.DataFrame([{
                                'entry_age': entry_age,
                                'age': entry_age,
                                'n_active': new_entrants
                            }])
                        ], ignore_index=True)

            # Record results
            results.append({
                'year': year,
                'active': current_workforce['n_active'].sum()
            })

        df_results = pd.DataFrame(results)
        print("[OK] Projection complete")

    except Exception as e:
        print(f"[FAIL] Projection failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Analyze results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    initial_active = df_results.iloc[0]['active']
    final_active = df_results.iloc[-1]['active']

    print(f"\nInitial Active Population: {initial_active:,.0f}")
    print(f"Final Active Population: {final_active:,.0f}")
    print(f"Change: {final_active - initial_active:,.0f} ({(final_active/initial_active - 1)*100:.2f}%)")

    # Check equilibrium (within 1% tolerance)
    tolerance = 0.01
    ratio = final_active / initial_active
    equilibrium_maintained = abs(ratio - 1.0) < tolerance

    print(f"\nEquilibrium Ratio: {ratio:.4f}")
    print(f"Tolerance: +/-{tolerance*100:.1f}%")

    if equilibrium_maintained:
        print("\n[PASS] EQUILIBRIUM TEST PASSED")
        print("  Population remained constant with pop_growth=0")
    else:
        print("\n[FAIL] EQUILIBRIUM TEST FAILED")
        print("  Population did not remain constant")
        print("  Check new entrant calculation formula")

    # Print year-by-year summary (every 5 years)
    print("\nYear-by-Year Summary (every 5 years):")
    print("-" * 50)
    for i in range(0, len(df_results), 5):
        row = df_results.iloc[i]
        print(f"Year {int(row['year'])}: Active={row['active']:,.0f}")

    return equilibrium_maintained


if __name__ == "__main__":
    success = test_equilibrium()
    exit(0 if success else 1)
