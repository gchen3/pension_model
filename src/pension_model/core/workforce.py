"""
Workforce Projection Module

Projects active workforce, terminated members, refunds, and retirees
based on mortality tables, separation rates, and benefit decisions.

Key Design Principles:
- Stream year-by-year to avoid keeping all years in memory
- Use long format for core data (one row = one entity)
- Pure functions for calculation logic
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd

from pension_config.plan import MembershipClass, PlanConfig
from pension_data.schemas import (
    WorkforceProjection,
    MortalityRate,
    WithdrawalRate,
    RetirementEligibility,
    EntrantProfile,
    SalaryHeadcountRecord
)
from pension_tools.mortality import qx
from pension_tools.withdrawal import get_withdrawal_rate


@dataclass
class WorkforceState:
    """Current state of workforce for a single year."""
    year: int
    active: pd.DataFrame  # Active members by entry_age, age
    term: pd.DataFrame    # Terminated members by entry_age, age, term_year
    refund: pd.DataFrame  # Refunded members by entry_age, age, term_year
    retire: pd.DataFrame  # Retired members by entry_age, age, term_year, retire_year


class WorkforceProjector:
    """
    Projects workforce over time using Markov chain approach.

    The workforce model tracks members through states:
    Active -> Terminated -> (Refund | Retire) -> Death
    """

    def __init__(self, config: PlanConfig):
        self.config = config
        self.start_year = config.start_year
        self.model_period = config.model_period
        self.max_age = config.max_age
        self.min_entry_age = config.min_entry_age
        self.max_entry_age = config.max_entry_age

    def get_age_range(self) -> range:
        """Get valid age range for projections."""
        return range(self.min_entry_age, self.max_age + 1)

    def get_entry_age_range(self, entrant_profile: pd.DataFrame) -> List[int]:
        """Get entry ages from entrant profile."""
        return sorted(entrant_profile['entry_age'].unique().tolist())

    def get_year_range(self) -> range:
        """Get projection year range."""
        return range(self.start_year, self.start_year + self.model_period + 1)

    def initialize_active_workforce(
        self,
        salary_headcount: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Initialize active workforce from salary/headcount data.

        Args:
            salary_headcount: Long format salary/headcount data

        Returns:
            DataFrame with columns: entry_age, age, n_active
        """
        # Filter to start year
        initial = salary_headcount[
            salary_headcount['entry_year'] == self.start_year
        ].copy()

        # Calculate count per entry_age, age combination
        active = initial.groupby(['entry_age', 'age']).agg(
            n_active=('count', 'sum')
        ).reset_index()

        return active

    def get_mortality_probability(
        self,
        mort_table: pd.DataFrame,
        entry_age: int,
        age: int,
        year: int,
        term_year: int,
        dist_age: int
    ) -> float:
        """
        Get mortality probability for a member at a given state.

        Args:
            mort_table: Mortality rate table
            entry_age: Age at entry
            age: Current age
            year: Current year
            term_year: Year of termination
            dist_age: Age at distribution (death or retirement)

        Returns:
            Mortality probability
        """
        # Find matching mortality rate
        match = mort_table[
            (mort_table['entry_age'] == entry_age) &
            (mort_table['age'] == age) &
            (mort_table['year'] == year) &
            (mort_table['term_year'] == term_year)
        ]

        if len(match) == 0:
            return 0.0

        return match['mort_final'].iloc[0]

    def get_separation_probability(
        self,
        sep_table: pd.DataFrame,
        entry_age: int,
        age: int,
        year: int
    ) -> float:
        """
        Get separation (withdrawal) probability for active members.

        Args:
            sep_table: Separation rate table
            entry_age: Age at entry
            age: Current age
            year: Current year

        Returns:
            Separation probability
        """
        entry_year = year - (age - entry_age)

        match = sep_table[
            (sep_table['entry_age'] == entry_age) &
            (sep_table['age'] == age) &
            (sep_table['entry_year'] == entry_year)
        ]

        if len(match) == 0:
            return 0.0

        return match['separation_rate'].iloc[0]

    def get_retirement_probability(
        self,
        benefit_decisions: pd.DataFrame,
        entry_age: int,
        age: int,
        year: int,
        term_year: int
    ) -> float:
        """
        Get retirement probability for terminated members.

        Args:
            benefit_decisions: Benefit decision table
            entry_age: Age at entry
            age: Current age
            year: Current year
            term_year: Year of termination

        Returns:
            Retirement probability (0 or 1 based on optimal decision)
        """
        entry_year = year - (age - entry_age)
        term_age = age - (year - term_year)
        yos = term_age - entry_age

        match = benefit_decisions[
            (benefit_decisions['entry_age'] == entry_age) &
            (benefit_decisions['age'] == age) &
            (benefit_decisions['entry_year'] == entry_year) &
            (benefit_decisions['term_age'] == term_age) &
            (benefit_decisions['yos'] == yos)
        ]

        if len(match) == 0:
            return 0.0

        return match['retire'].iloc[0]

    def get_refund_probability(
        self,
        benefit_decisions: pd.DataFrame,
        entry_age: int,
        age: int,
        year: int,
        term_year: int
    ) -> float:
        """
        Get refund probability for terminated members.

        Args:
            benefit_decisions: Benefit decision table
            entry_age: Age at entry
            age: Current age
            year: Current year
            term_year: Year of termination

        Returns:
            Refund probability (0 or 1 based on optimal decision)
        """
        entry_year = year - (age - entry_age)
        term_age = age - (year - term_year)
        yos = term_age - entry_age

        match = benefit_decisions[
            (benefit_decisions['entry_age'] == entry_age) &
            (benefit_decisions['age'] == age) &
            (benefit_decisions['entry_year'] == entry_year) &
            (benefit_decisions['term_age'] == term_age) &
            (benefit_decisions['yos'] == yos)
        ]

        if len(match) == 0:
            return 0.0

        return match['refund'].iloc[0]

    def project_year(
        self,
        prev_state: WorkforceState,
        mort_table: pd.DataFrame,
        sep_table: pd.DataFrame,
        benefit_decisions: pd.DataFrame,
        entrant_profile: pd.DataFrame,
        pop_growth: float
    ) -> WorkforceState:
        """
        Project workforce one year forward.

        Args:
            prev_state: Previous year's workforce state
            mort_table: Mortality rate table
            sep_table: Separation rate table
            benefit_decisions: Benefit decision table
            entrant_profile: New entrant profile
            pop_growth: Population growth rate for new entrants

        Returns:
            New workforce state
        """
        new_year = prev_state.year + 1

        # 1. Active to Terminated
        # Calculate newly terminated actives
        active2term = self._calculate_active_to_term(
            prev_state.active, sep_table, prev_state.year
        )

        # 2. Active aging (shift by 1 year)
        active_aged = self._age_active_population(
            prev_state.active, active2term
        )

        # 3. Add new entrants
        new_entrants = self._calculate_new_entrants(
            active_aged, entrant_profile, pop_growth
        )
        active_new = active_aged + new_entrants

        # 4. Terminated aging and death
        term_aged = self._age_terminated_population(
            prev_state.term, mort_table, prev_state.year
        )

        # 5. Add newly terminated to term population
        term_new = self._add_newly_terminated(
            term_aged, active2term, new_year
        )

        # 6. Terminated to Refund
        term2refund = self._calculate_term_to_refund(
            term_new, benefit_decisions, new_year
        )
        term_after_refund = term_new - term2refund

        # 7. Terminated to Retire
        term2retire = self._calculate_term_to_retire(
            term_after_refund, benefit_decisions, new_year
        )
        term_final = term_after_refund - term2retire

        # 8. Retiree aging and death
        retire_aged = self._age_retiree_population(
            prev_state.retire, mort_table, prev_state.year
        )

        # 9. Add newly retired to retiree population
        retire_new = self._add_newly_retired(
            retire_aged, term2retire, new_year
        )

        return WorkforceState(
            year=new_year,
            active=active_new,
            term=term_final,
            refund=term2refund,
            retire=retire_new
        )

    def _calculate_active_to_term(
        self,
        active: pd.DataFrame,
        sep_table: pd.DataFrame,
        year: int
    ) -> pd.DataFrame:
        """Calculate number of active members who terminate."""
        result = active.copy()

        for idx, row in result.iterrows():
            sep_prob = self.get_separation_probability(
                sep_table, row['entry_age'], row['age'], year
            )
            result.loc[idx, 'n_term'] = row['n_active'] * sep_prob

        return result

    def _age_active_population(
        self,
        active: pd.DataFrame,
        active2term: pd.DataFrame
    ) -> pd.DataFrame:
        """Age active population by 1 year and deduct terminated."""
        # Shift age by 1
        aged = active.copy()
        aged['age'] = aged['age'] + 1

        # Remove terminated members
        aged = aged.merge(
            active2term[['entry_age', 'age', 'n_term']],
            on=['entry_age', 'age'],
            how='left'
        )
        aged['n_term'] = aged['n_term'].fillna(0)
        aged['n_active'] = aged['n_active'] - aged['n_term']
        aged = aged[aged['n_active'] > 0]

        return aged

    def _calculate_new_entrants(
        self,
        active: pd.DataFrame,
        entrant_profile: pd.DataFrame,
        pop_growth: float
    ) -> pd.DataFrame:
        """Calculate new entrants based on population growth."""
        # Get total active population
        total_active = active['n_active'].sum()

        # Calculate target population with growth
        target_pop = total_active * (1 + pop_growth)

        # New entrants needed
        new_entrants_needed = target_pop - total_active

        # Distribute by entry age based on entrant profile
        result = []
        for _, row in entrant_profile.iterrows():
            entry_age = row['entry_age']
            dist = row['entrant_dist']
            n = new_entrants_needed * dist

            result.append({
                'entry_age': entry_age,
                'age': entry_age,  # New entrants start at entry age
                'n_active': n
            })

        return pd.DataFrame(result)

    def _age_terminated_population(
        self,
        term: pd.DataFrame,
        mort_table: pd.DataFrame,
        year: int
    ) -> pd.DataFrame:
        """Age terminated population and apply mortality."""
        result = term.copy()

        # Shift age by 1
        result['age'] = result['age'] + 1

        # Apply mortality
        for idx, row in result.iterrows():
            mort_prob = self.get_mortality_probability(
                mort_table,
                row['entry_age'],
                row['age'],
                year + 1,
                row['term_year'],
                row['age']
            )
            result.loc[idx, 'n_term'] = row['n_term'] * (1 - mort_prob)

        return result

    def _add_newly_terminated(
        self,
        term_aged: pd.DataFrame,
        active2term: pd.DataFrame,
        year: int
    ) -> pd.DataFrame:
        """Add newly terminated members to term population."""
        # Age the newly terminated by 1 year
        new_term = active2term.copy()
        new_term['age'] = new_term['age'] + 1
        new_term['term_year'] = year
        new_term['n_term'] = new_term['n_term']

        # Combine with aged term population
        if len(term_aged) == 0:
            return new_term

        # Group and sum
        combined = pd.concat([
            term_aged[['entry_age', 'age', 'term_year', 'n_term']],
            new_term[['entry_age', 'age', 'term_year', 'n_term']]
        ])

        return combined.groupby(
            ['entry_age', 'age', 'term_year']
        ).agg(n_term=('n_term', 'sum')).reset_index()

    def _calculate_term_to_refund(
        self,
        term: pd.DataFrame,
        benefit_decisions: pd.DataFrame,
        year: int
    ) -> pd.DataFrame:
        """Calculate terminated members who take refund."""
        result = term.copy()

        for idx, row in result.iterrows():
            refund_prob = self.get_refund_probability(
                benefit_decisions,
                row['entry_age'],
                row['age'],
                year,
                row['term_year']
            )
            result.loc[idx, 'n_refund'] = row['n_term'] * refund_prob

        return result

    def _calculate_term_to_retire(
        self,
        term: pd.DataFrame,
        benefit_decisions: pd.DataFrame,
        year: int
    ) -> pd.DataFrame:
        """Calculate terminated members who retire."""
        result = term.copy()

        for idx, row in result.iterrows():
            retire_prob = self.get_retirement_probability(
                benefit_decisions,
                row['entry_age'],
                row['age'],
                year,
                row['term_year']
            )
            result.loc[idx, 'n_retire'] = row['n_term'] * retire_prob

        return result

    def _age_retiree_population(
        self,
        retire: pd.DataFrame,
        mort_table: pd.DataFrame,
        year: int
    ) -> pd.DataFrame:
        """Age retiree population and apply mortality."""
        result = retire.copy()

        # Shift age by 1
        result['age'] = result['age'] + 1

        # Apply mortality
        for idx, row in result.iterrows():
            mort_prob = self.get_mortality_probability(
                mort_table,
                row['entry_age'],
                row['age'],
                year + 1,
                row['term_year'],
                row['age']
            )
            result.loc[idx, 'n_retire'] = row['n_retire'] * (1 - mort_prob)

        return result

    def _add_newly_retired(
        self,
        retire_aged: pd.DataFrame,
        term2retire: pd.DataFrame,
        year: int
    ) -> pd.DataFrame:
        """Add newly retired members to retiree population."""
        # Age the newly retired by 1 year
        new_retire = term2retire.copy()
        new_retire['age'] = new_retire['age'] + 1
        new_retire['retire_year'] = year
        new_retire['n_retire'] = new_retire['n_retire']

        # Combine with aged retiree population
        if len(retire_aged) == 0:
            return new_retire

        # Group and sum
        combined = pd.concat([
            retire_aged[['entry_age', 'age', 'term_year', 'retire_year', 'n_retire']],
            new_retire[['entry_age', 'age', 'term_year', 'retire_year', 'n_retire']]
        ])

        return combined.groupby(
            ['entry_age', 'age', 'term_year', 'retire_year']
        ).agg(n_retire=('n_retire', 'sum')).reset_index()

    def project_workforce(
        self,
        salary_headcount: pd.DataFrame,
        mort_table: pd.DataFrame,
        sep_table: pd.DataFrame,
        benefit_decisions: pd.DataFrame,
        entrant_profile: pd.DataFrame,
        pop_growth: float
    ) -> Dict[int, WorkforceState]:
        """
        Project workforce over the entire model period.

        Args:
            salary_headcount: Salary/headcount data
            mort_table: Mortality rate table
            sep_table: Separation rate table
            benefit_decisions: Benefit decision table
            entrant_profile: New entrant profile
            pop_growth: Population growth rate

        Returns:
            Dictionary mapping year to WorkforceState
        """
        # Initialize workforce
        active = self.initialize_active_workforce(salary_headcount)

        # Initialize empty term, refund, retire populations
        entry_ages = self.get_entry_age_range(entrant_profile)
        ages = list(self.get_age_range())

        # Create empty DataFrames
        term = pd.DataFrame(columns=['entry_age', 'age', 'term_year', 'n_term'])
        refund = pd.DataFrame(columns=['entry_age', 'age', 'term_year', 'n_refund'])
        retire = pd.DataFrame(columns=['entry_age', 'age', 'term_year', 'retire_year', 'n_retire'])

        # Initial state
        states = {
            self.start_year: WorkforceState(
                year=self.start_year,
                active=active,
                term=term,
                refund=refund,
                retire=retire
            )
        }

        # Project year by year
        for year in range(self.start_year, self.start_year + self.model_period):
            prev_state = states[year]
            new_state = self.project_year(
                prev_state,
                mort_table,
                sep_table,
                benefit_decisions,
                entrant_profile,
                pop_growth
            )
            states[new_state.year] = new_state

        return states


def project_workforce(
    config: PlanConfig,
    membership_class: MembershipClass,
    salary_headcount: pd.DataFrame,
    mort_table: pd.DataFrame,
    sep_table: pd.DataFrame,
    benefit_decisions: pd.DataFrame,
    entrant_profile: pd.DataFrame,
    pop_growth: float
) -> Dict[int, WorkforceState]:
    """
    Convenience function to project workforce for a membership class.

    Args:
        config: Plan configuration
        membership_class: Membership class to project
        salary_headcount: Salary/headcount data
        mort_table: Mortality rate table
        sep_table: Separation rate table
        benefit_decisions: Benefit decision table
        entrant_profile: New entrant profile
        pop_growth: Population growth rate

    Returns:
        Dictionary mapping year to WorkforceState
    """
    projector = WorkforceProjector(config)
    return projector.project_workforce(
        salary_headcount,
        mort_table,
        sep_table,
        benefit_decisions,
        entrant_profile,
        pop_growth
    )
