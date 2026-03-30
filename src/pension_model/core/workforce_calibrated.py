"""
Enhanced Workforce Projection Module with Calibration.

This module provides workforce projection that integrates with:
- Age/YOS-specific withdrawal rates from extracted decrement tables
- Tier-aware retirement eligibility logic
- Benefit decision optimization (refund vs annuity)
- Calibrated new entrant logic to maintain stable population
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import pandas as pd
from pathlib import Path

from pension_data.decrement_loader import DecrementLoader
from pension_data.calibration_loader import CalibrationLoader
from pension_tools.separation import (
    SeparationRateCalculator
)
from pension_tools.separation import (
    SeparationRateCalculator,
)
from pension_tools.separation import (
    SeparationRateCalculator,
)


@dataclass
class WorkforceConfig:
    """Configuration for workforce projection."""
    start_year: int = 2022
    model_period: int = 30
    min_age: int = 18
    max_age: int = 120
    min_entry_age: int = 18
    max_entry_age: int = 70
    population_growth: float = 0.0  # From R model: stable population
    retire_refund_ratio: float = 1.0  # From R model: 100% retire


@dataclass
class WorkforceState:
    """Current state of workforce for a single year."""
    year: int
    active: pd.DataFrame  # Active members by entry_age, age
    term: pd.DataFrame    # Terminated members by entry_age, age, term_year
    refund: pd.DataFrame  # Refunded members by entry_age, age, term_year
    retire: pd.DataFrame  # Retired members by entry_age, age, term_year, retire_year


@dataclass
class ProjectionResult:
    """Result of workforce projection for a single class."""
    class_name: str
    states: Dict[int, WorkforceState] = field(default_factory=dict)
    yearly_summary: pd.DataFrame = field(default_factory=pd.DataFrame)

    def get_active_count(self, year: int) -> float:
        """Get total active count for a year."""
        if year in self.states and not self.states[year].active.empty:
            return self.states[year].active['n_active'].sum()
        return 0.0

    def get_term_count(self, year: int) -> float:
        """Get total terminated count for a year."""
        if year in self.states and not self.states[year].term.empty:
            return self.states[year].term['n_term'].sum()
        return 0.0

    def get_retire_count(self, year: int) -> float:
        """Get total retired count for a year."""
        if year in self.states and not self.states[year].retire.empty:
            return self.states[year].retire['n_retire'].sum()
        return 0.0


class CalibratedWorkforceProjector:
    """
    Workforce projector with calibration support.

    Integrates with:
    - DecrementLoader for age/YOS-specific rates
    - CalibrationLoader for adjustment factors
    """

    def __init__(
        self,
        config: WorkforceConfig,
        decrement_loader: DecrementLoader,
        calibration_loader: CalibrationLoader,
        class_name: str
    ):
        """
        Initialize the calibrated workforce projector.

        Args:
            config: Workforce configuration
            decrement_loader: Loader for decrement tables
            calibration_loader: Loader for calibration parameters
            class_name: Membership class name
        """
        self.config = config
        self.decrement_loader = decrement_loader
        self.calibration_loader = calibration_loader
        self.class_name = class_name

        # Load decrement tables for this class
        self._load_decrement_tables()

    def _load_decrement_tables(self) -> None:
        """Load pre-computed separation tables for this class."""
        # Load pre-computed combined separation table
        # This follows the R model's get_separation_table approach
        try:
            self.separation_table = self.decrement_loader.load_separation_table(self.class_name)
        except FileNotFoundError:
            # Fall back to separate tables if separation table doesn't exist
            self.separation_table = None
            self.withdrawal_table = self.decrement_loader.load_withdrawal_table(
                self.class_name, gender="male"
            )
            if self.withdrawal_table is None:
                self.withdrawal_table = self.decrement_loader.load_withdrawal_table(
                    self.class_name
                )
            self.retirement_table_tier1 = self.decrement_loader.load_retirement_table(
                tier="tier1", table_type="normal"
            )
            self.retirement_table_tier2 = self.decrement_loader.load_retirement_table(
                tier="tier2", table_type="normal"
            )

    def get_separation_rate_from_table(
        self,
        entry_year: int,
        entry_age: int,
        term_age: int,
        yos: int
    ) -> Tuple[str, float]:
        """
        Get separation rate from pre-computed table.

        Args:
            entry_year: Year member entered the plan
            entry_age: Age at entry
            term_age: Age at potential termination
            yos: Years of service

        Returns:
            Tuple of (tier, separation_rate)
        """
        if self.separation_table is None:
            return ("unknown", 0.0)

        # Query the pre-computed separation table
        mask = (
            (self.separation_table['entry_year'] == entry_year) &
            (self.separation_table['entry_age'] == entry_age) &
            (self.separation_table['term_age'] == term_age) &
            (self.separation_table['yos'] == yos)
        )

        matching = self.separation_table[mask]

        if len(matching) == 0:
            return ("unknown", 0.0)

        row = matching.iloc[0]
        return (row['tier'], row['separation_rate'])

    def get_withdrawal_rate(self, age: int, yos: int) -> float:
        """
        Get age/YOS-specific withdrawal rate.

        Args:
            age: Current age
            yos: Years of service

        Returns:
            Withdrawal rate (0.0 to 1.0)
        """
        if self.separation_table is not None:
            # If using pre-computed separation tables, this method
            # should not be called directly - use get_separation_rate_from_table
            return 0.0

        if self.withdrawal_table is None:
            return 0.0

        return self.decrement_loader.get_withdrawal_rate(
            self.withdrawal_table, age, yos
        ) or 0.0

    def get_retirement_rate(
        self,
        age: int,
        tier: str = "tier1",
        gender: str = "male"
    ) -> float:
        """
        Get retirement rate based on age, tier, and class.

        Args:
            age: Current age
            tier: "tier1" or "tier2"
            gender: "male" or "female"

        Returns:
            Retirement rate (0.0 to 1.0)
        """
        table = (
            self.retirement_table_tier1 if tier == "tier1"
            else self.retirement_table_tier2
        )

        if table is None:
            return 0.0

        return self.decrement_loader.get_retirement_rate(
            table, self.class_name, age, gender
        ) or 0.0

    def get_retire_refund_decision(self, yos: int, age: int) -> Tuple[float, float]:
        """
        Determine retire vs refund decision for terminated vested members.

        Uses the retire_refund_ratio from calibration parameters.

        Args:
            yos: Years of service at termination
            age: Age at decision

        Returns:
            Tuple of (retire_prob, refund_prob)
        """
        ratio = self.calibration_loader.retire_refund_ratio

        # Simple model: use the ratio directly
        # In a more sophisticated model, this would consider:
        # - PV of annuity vs lump sum refund
        # - Interest rates
        # - Member demographics

        return (ratio, 1.0 - ratio)

    def calculate_new_entrants(
        self,
        prev_active_total: float,
        current_active_after_decrements: float
    ) -> float:
        """
        Calculate new entrants needed to maintain stable population.

        From R model (utility_functions.R line181):
            ne <- sum(wf1)*(1 + g) - sum(wf2)

        Where:
            wf1 = previous period active population
            wf2 = current period active population AFTER decrements
            g = population growth rate (0 for stable population)

        Args:
            prev_active_total: Previous period's total active population
            current_active_after_decrements: Current active after terminations

        Returns:
            Number of new entrants needed
        """
        growth = self.config.population_growth

        # R model formula: ne = prev_pop * (1 + g) - current_pop_after_decrements
        new_entrants = prev_active_total * (1 + growth) - current_active_after_decrements

        return max(0, new_entrants)

    def initialize_from_baseline(self, baseline_df: pd.DataFrame) -> pd.DataFrame:
        """
        Initialize active workforce from R baseline data.

        Args:
            baseline_df: DataFrame with entry_age, age, n_active columns

        Returns:
            Initialized active workforce DataFrame
        """
        # Filter to start year if year column exists
        if 'year' in baseline_df.columns:
            baseline_df = baseline_df[
                baseline_df['year'] == self.config.start_year
            ]

        # Aggregate by entry_age, age
        if 'entry_age' in baseline_df.columns and 'age' in baseline_df.columns:
            active = baseline_df.groupby(['entry_age', 'age']).agg(
                n_active=('n_active', 'sum')
            ).reset_index()
        else:
            # Create from distribution
            active = baseline_df.copy()
            if 'n_active' not in active.columns and 'count' in active.columns:
                active['n_active'] = active['count']

        return active

    def project_year(
        self,
        prev_state: WorkforceState,
        entrant_profile: pd.DataFrame
    ) -> WorkforceState:
        """
        Project workforce one year forward.

        Args:
            prev_state: Previous year's workforce state
            entrant_profile: Distribution of new entrants by entry_age

        Returns:
            New workforce state
        """
        new_year = prev_state.year + 1

        # 1. Calculate terminations using pre-computed separation rates
        active = prev_state.active.copy()
        terminations = []

        for idx, row in active.iterrows():
            age = int(row['age'])
            entry_age = int(row['entry_age'])
            yos = age - entry_age

            # Calculate entry year from current year and YOS
            entry_year = prev_state.year - yos

            # Get separation rate from pre-computed table
            if self.separation_table is not None:
                tier, separation_rate = self.get_separation_rate_from_table(
                    entry_year, entry_age, age, yos
                )
            else:
                # Fall back to withdrawal rate if no separation table
                separation_rate = self.get_withdrawal_rate(age, yos)
                tier = "unknown"

            # Calculate terminations
            n_term = row['n_active'] * separation_rate
            terminations.append({
                'entry_age': entry_age,
                'age': age,
                'n_term': n_term,
                'n_remaining': row['n_active'] - n_term,
                'tier': tier
            })

        term_df = pd.DataFrame(terminations)

        # 2. Age the active population
        if not term_df.empty:
            aged_active = term_df.copy()
            aged_active['age'] = aged_active['age'] + 1
            aged_active['n_active'] = aged_active['n_remaining']
            aged_active = aged_active[['entry_age', 'age', 'n_active']]
            aged_active = aged_active[aged_active['n_active'] > 0]
        else:
            aged_active = pd.DataFrame(columns=['entry_age', 'age', 'n_active'])

        # 3. Calculate new entrants to maintain stable population
        # From R model: ne = sum(wf1)*(1+g) - sum(wf2)
        # where wf1 = prev active, wf2 = current active after decrements
        prev_active_total = active['n_active'].sum() if not active.empty else 0
        current_active_after_decrements = aged_active['n_active'].sum() if not aged_active.empty else 0

        new_entrant_count = self.calculate_new_entrants(
            prev_active_total, current_active_after_decrements
        )

        # 4. Add new entrants based on profile
        if not entrant_profile.empty and new_entrant_count > 0:
            if 'entrant_dist' in entrant_profile.columns:
                new_entrants = entrant_profile.copy()
                new_entrants['n_active'] = (
                    new_entrant_count * new_entrants['entrant_dist']
                )
                new_entrants['age'] = new_entrants['entry_age']
                new_entrants = new_entrants[['entry_age', 'age', 'n_active']]

                # Combine with aged active
                aged_active = pd.concat([aged_active, new_entrants], ignore_index=True)
                aged_active = aged_active.groupby(['entry_age', 'age']).sum().reset_index()

        # 5. Process terminated members
        # Age the existing terminated population
        aged_term = prev_state.term.copy() if not prev_state.term.empty else pd.DataFrame(
            columns=['entry_age', 'age', 'term_year', 'n_term']
        )

        if not aged_term.empty:
            aged_term['age'] = aged_term['age'] + 1

        # Add newly terminated
        if not term_df.empty:
            new_term = term_df[['entry_age', 'n_term']].copy()
            new_term['age'] = term_df['age'] + 1  # Age at start of next year
            new_term['term_year'] = prev_state.year
            new_term = new_term.rename(columns={'n_term': 'n_term'})

            # Combine
            aged_term = pd.concat([
                aged_term[['entry_age', 'age', 'term_year', 'n_term']],
                new_term[['entry_age', 'age', 'term_year', 'n_term']]
            ], ignore_index=True)

            aged_term = aged_term.groupby(
                ['entry_age', 'age', 'term_year']
            ).sum().reset_index()

        # 6. Process retire/refund decisions for terminated members
        # For simplicity, apply retire_refund_ratio to terminated members
        # who meet vesting requirements (typically 5-6 YOS)

        refund_df = pd.DataFrame(
            columns=['entry_age', 'age', 'term_year', 'n_refund']
        )
        retire_df = pd.DataFrame(
            columns=['entry_age', 'age', 'term_year', 'retire_year', 'n_retire']
        )

        if not aged_term.empty:
            retire_records = []
            refund_records = []
            term_remaining = []

            for idx, row in aged_term.iterrows():
                age = int(row['age'])
                entry_age = int(row['entry_age'])
                yos = age - entry_age
                n_term = row['n_term']

                # Check vesting (simplified: 5 YOS for tier 1, 8 for tier 2)
                if yos >= 5:
                    retire_prob, refund_prob = self.get_retire_refund_decision(yos, age)

                    n_retire = n_term * retire_prob
                    n_refund = n_term * refund_prob

                    if n_retire > 0:
                        retire_records.append({
                            'entry_age': entry_age,
                            'age': age,
                            'term_year': row['term_year'],
                            'retire_year': new_year,
                            'n_retire': n_retire
                        })

                    if n_refund > 0:
                        refund_records.append({
                            'entry_age': entry_age,
                            'age': age,
                            'term_year': row['term_year'],
                            'n_refund': n_refund
                        })
                else:
                    # Not vested, remains terminated
                    term_remaining.append(row.to_dict())

            if retire_records:
                retire_df = pd.DataFrame(retire_records)
            if refund_records:
                refund_df = pd.DataFrame(refund_records)
            if term_remaining:
                aged_term = pd.DataFrame(term_remaining)
            else:
                aged_term = pd.DataFrame(
                    columns=['entry_age', 'age', 'term_year', 'n_term']
                )

        # 7. Age retiree population
        aged_retire = prev_state.retire.copy() if not prev_state.retire.empty else pd.DataFrame(
            columns=['entry_age', 'age', 'term_year', 'retire_year', 'n_retire']
        )

        if not aged_retire.empty:
            aged_retire['age'] = aged_retire['age'] + 1

        # Add newly retired
        if not retire_df.empty:
            aged_retire = pd.concat([
                aged_retire,
                retire_df
            ], ignore_index=True)

            aged_retire = aged_retire.groupby(
                ['entry_age', 'age', 'term_year', 'retire_year']
            ).sum().reset_index()

        return WorkforceState(
            year=new_year,
            active=aged_active,
            term=aged_term,
            refund=refund_df,
            retire=aged_retire
        )

    def project(
        self,
        initial_active: pd.DataFrame,
        entrant_profile: pd.DataFrame
    ) -> ProjectionResult:
        """
        Run full workforce projection.

        Args:
            initial_active: Initial active workforce
            entrant_profile: Distribution of new entrants

        Returns:
            ProjectionResult with all yearly states
        """
        result = ProjectionResult(class_name=self.class_name)

        # Initialize state
        initial_state = WorkforceState(
            year=self.config.start_year,
            active=initial_active,
            term=pd.DataFrame(columns=['entry_age', 'age', 'term_year', 'n_term']),
            refund=pd.DataFrame(columns=['entry_age', 'age', 'term_year', 'n_refund']),
            retire=pd.DataFrame(columns=['entry_age', 'age', 'term_year', 'retire_year', 'n_retire'])
        )

        result.states[self.config.start_year] = initial_state

        # Project year by year
        current_state = initial_state

        for year_offset in range(self.config.model_period):
            current_state = self.project_year(current_state, entrant_profile)
            result.states[current_state.year] = current_state

        # Create yearly summary
        summary_data = []
        for year, state in result.states.items():
            summary_data.append({
                'year': year,
                'active': state.active['n_active'].sum() if not state.active.empty else 0,
                'term': state.term['n_term'].sum() if not state.term.empty else 0,
                'refund': state.refund['n_refund'].sum() if not state.refund.empty else 0,
                'retire': state.retire['n_retire'].sum() if not state.retire.empty else 0
            })

        result.yearly_summary = pd.DataFrame(summary_data)

        return result


def run_calibrated_projection(
    class_name: str,
    baseline_dir: str = "baseline_outputs",
    config_path: str = "configs/calibration_params.json"
) -> ProjectionResult:
    """
    Run calibrated workforce projection for a class.

    Args:
        class_name: Membership class name
        baseline_dir: Directory with baseline data
        config_path: Path to calibration config

    Returns:
        ProjectionResult
    """
    # Initialize loaders
    decrement_loader = DecrementLoader(baseline_dir)
    calibration_loader = CalibrationLoader(config_path)

    # Create config from calibration parameters
    config = WorkforceConfig(
        start_year=2022,
        model_period=30,
        population_growth=calibration_loader.population_growth,
        retire_refund_ratio=calibration_loader.retire_refund_ratio
    )

    # Create projector
    projector = CalibratedWorkforceProjector(
        config=config,
        decrement_loader=decrement_loader,
        calibration_loader=calibration_loader,
        class_name=class_name
    )

    # Load initial active workforce
    baseline_file = Path(baseline_dir) / f"{class_name}_wf_active.csv"
    if baseline_file.exists():
        baseline_df = pd.read_csv(baseline_file)
        initial_active = projector.initialize_from_baseline(baseline_df)
    else:
        raise FileNotFoundError(f"Baseline file not found: {baseline_file}")

    # Load entrant profile (from workforce data distribution)
    entrant_file = Path(baseline_dir) / f"{class_name}_entrant_profile.csv"
    if entrant_file.exists():
        entrant_profile = pd.read_csv(entrant_file)
    else:
        # Fall back to dist_count file
        dist_file = Path(baseline_dir) / f"{class_name}_dist_count.csv"
        if dist_file.exists():
            entrant_profile = pd.read_csv(dist_file)
            if 'entrant_dist' not in entrant_profile.columns and 'count' in entrant_profile.columns:
                total = entrant_profile['count'].sum()
                entrant_profile['entrant_dist'] = entrant_profile['count'] / total
        else:
            # Create uniform distribution
            entry_ages = range(config.min_entry_age, config.max_entry_age + 1)
            n_ages = len(list(entry_ages))
            entrant_profile = pd.DataFrame({
                'entry_age': list(entry_ages),
                'entrant_dist': [1.0 / n_ages] * n_ages
            })

    # Run projection
    return projector.project(initial_active, entrant_profile)
