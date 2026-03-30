"""
Main Pension Model Orchestrator

Coordinates all calculation engines to run the full pension model.

Key Design Principles:
- Stream year-by-year to avoid keeping all years in memory
- Use long format for core data (one row = one entity)
- Modular design with clear separation of concerns
"""

from typing import Dict, List, Optional
import pandas as pd

from pension_config import MembershipClass, PlanConfig
from pension_config.adapters import PlanAdapter
from pension_data.loaders import ExcelLoader, CSVLoader
# Note: Import actual schema names from pension_data.schemas
# (Some may not exist yet, using DataFrame directly where needed)
from pension_model.core import (
    WorkforceProjector,
    WorkforceState,
    project_workforce,
    BenefitCalculator,
    calculate_benefit_table,
    LiabilityCalculator,
    calculate_liabilities,
    FundingCalculator,
    calculate_funding
)


class PensionModel:
    """
    Main pension model orchestrator.

    Coordinates:
    1. Data loading
    2. Workforce projection
    3. Benefit calculation
    4. Liability calculation
    5. Funding calculation
    """

    def __init__(self, config: PlanConfig):
        self.config = config
        self.start_year = config.start_year
        self.model_period = config.model_period

        # Import adapter for FRS
        from pension_config.frs_adapter import FRSAdapter

        self.adapter = FRSAdapter(config)

        # Initialize calculators with adapter
        self.workforce_projector = WorkforceProjector(self.adapter)
        self.benefit_calculator = BenefitCalculator(self.adapter)
        self.liability_calculator = LiabilityCalculator(config)
        self.funding_calculator = FundingCalculator(config)

        # Storage for results
        self.workforce_results: Dict[MembershipClass, Dict[int, WorkforceState]] = {}
        self.benefit_results: Dict[MembershipClass, pd.DataFrame] = {}
        self.liability_results: Dict[MembershipClass, pd.DataFrame] = {}
        self.funding_results: Dict[MembershipClass, pd.DataFrame] = {}

    def load_data(
        self,
        loader: ExcelLoader
    ) -> Dict[MembershipClass, Dict[str, pd.DataFrame]]:
        """
        Load all input data.

        Args:
            loader: Data loader instance

        Returns:
            Dictionary mapping membership class to data tables
        """
        # Load salary/headcount data
        salary_headcount = loader.load_salary_headcount()

        # Load mortality tables
        mortality = loader.load_mortality()

        # Load withdrawal/separation tables
        withdrawal = loader.load_withdrawal()

        # Load retirement eligibility tables
        retirement = loader.load_retirement_eligibility()

        # Load salary growth table
        salary_growth = loader.load_salary_growth()

        # Load entrant profiles
        entrant_profiles = loader.load_entrant_profiles()

        # Organize by membership class
        data_by_class = {}

        for class_name in MembershipClass:
            class_str = class_name.value.lower().replace('_', ' ')

            data_by_class[class_name] = {
                'salary_headcount': salary_headcount.get(class_str, pd.DataFrame()),
                'mortality': mortality.get(class_str, pd.DataFrame()),
                'withdrawal': withdrawal.get(class_str, pd.DataFrame()),
                'retirement': retirement.get(class_str, pd.DataFrame()),
                'salary_growth': salary_growth,
                'entrant_profile': entrant_profiles.get(class_str, pd.DataFrame())
            }

        return data_by_class

    def run_workforce_projection(
        self,
        class_name: MembershipClass,
        data: Dict[str, pd.DataFrame],
        pop_growth: float,
        gender: str = 'male'
    ) -> Dict[int, WorkforceState]:
        """
        Run workforce projection for a membership class.

        Args:
            class_name: Membership class
            data: Input data tables
            pop_growth: Population growth rate
            gender: Gender for loading gender-specific tables

        Returns:
            Dictionary mapping year to workforce state
        """
        salary_headcount = data['salary_headcount']
        entrant_profile = data['entrant_profile']

        # Load decrement tables from adapter (uses extracted baseline tables)
        mort_table = self.adapter.load_mortality_table(class_name)
        sep_table = self.adapter.load_withdrawal_table(class_name, gender)

        # Fallback to loaded data if adapter tables not available
        if mort_table is None:
            mort_table = data.get('mortality', pd.DataFrame())
        if sep_table is None:
            sep_table = data.get('withdrawal', pd.DataFrame())

        # Create benefit decisions table (simplified)
        # In full implementation, this would be calculated from benefit model
        benefit_decisions = self._create_benefit_decisions(
            salary_headcount, mort_table, sep_table
        )

        # Project workforce
        workforce_states = project_workforce(
            self.config,
            class_name,
            salary_headcount,
            mort_table,
            sep_table,
            benefit_decisions,
            entrant_profile,
            pop_growth
        )

        return workforce_states

    def run_benefit_calculation(
        self,
        class_name: MembershipClass,
        data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        Run benefit calculation for a membership class.

        Args:
            class_name: Membership class
            data: Input data tables

        Returns:
            DataFrame with benefit calculations
        """
        salary_headcount = data['salary_headcount']
        mort_table = data['mortality']
        salary_growth = data['salary_growth']

        return calculate_benefit_table(
            self.config,
            class_name,
            salary_headcount,
            mort_table,
            salary_growth,
            self.config.dr_current,
            self.config.dr_new,
            self.config.cola_tier_1_active,
            self.config.cola_current_retire
        )

    def run_liability_calculation(
        self,
        class_name: MembershipClass,
        workforce_states: Dict[int, WorkforceState],
        benefit_table: pd.DataFrame,
        data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        Run liability calculation for a membership class.

        Args:
            class_name: Membership class
            workforce_states: Workforce states by year
            benefit_table: Benefit calculation results
            data: Input data tables

        Returns:
            DataFrame with liability calculations
        """
        mort_table = data['mortality']
        salary_growth = data['salary_growth']

        # Create annuity factor table (simplified)
        ann_factor_table = self._create_annuity_factor_table(
            benefit_table, mort_table
        )

        # Create benefit valuation table (simplified)
        benefit_val_table = self._create_benefit_valuation_table(benefit_table)

        # Extract workforce data frames
        workforce_active = self._workforce_to_df(workforce_states, 'active')
        workforce_term = self._workforce_to_df(workforce_states, 'term')
        workforce_refund = self._workforce_to_df(workforce_states, 'refund')
        workforce_retire = self._workforce_to_df(workforce_states, 'retire')

        # Calculate liabilities
        return calculate_liabilities(
            self.config,
            workforce_active,
            workforce_term,
            workforce_refund,
            workforce_retire,
            benefit_table,
            benefit_val_table,
            ann_factor_table,
            pd.DataFrame(),  # retiree_distribution - placeholder
            1000.0,  # retiree_pop_current - placeholder
            50000000.0,  # ben_payment_current - placeholder
            100000000.0,  # pvfb_term_current - placeholder
            20,  # amo_period_term - placeholder
            self.config.dr_current,
            self.config.payroll_growth
        )

    def run_funding_calculation(
        self,
        class_name: MembershipClass,
        liability_summary: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Run funding calculation for a membership class.

        Args:
            class_name: Membership class
            liability_summary: Liability calculation results

        Returns:
            DataFrame with funding calculations
        """
        # Initial values (would come from actual data)
        initial_aal_legacy = liability_summary['aal_legacy_est'].iloc[0] if len(liability_summary) > 0 else 0.0
        initial_aal_new = liability_summary['aal_new_est'].iloc[0] if len(liability_summary) > 0 else 0.0
        initial_payroll = liability_summary['total_payroll_est'].iloc[0] if len(liability_summary) > 0 else 100000000.0

        # Placeholder ratios
        initial_payroll_db_legacy_ratio = 0.7
        initial_payroll_db_new_ratio = 0.3
        initial_payroll_dc_legacy_ratio = 0.2
        initial_payroll_dc_new_ratio = 0.1
        initial_nc_rate_db_legacy = 0.15
        initial_nc_rate_db_new = 0.12
        initial_ben_payment = 50000000.0
        initial_refund = 5000000.0

        return calculate_funding(
            self.config,
            liability_summary,
            initial_aal_legacy,
            initial_aal_new,
            initial_payroll,
            initial_payroll_db_legacy_ratio,
            initial_payroll_db_new_ratio,
            initial_payroll_dc_legacy_ratio,
            initial_payroll_dc_new_ratio,
            initial_nc_rate_db_legacy,
            initial_nc_rate_db_new,
            initial_ben_payment,
            initial_refund
        )

    def run_model(
        self,
        loader: ExcelLoader,
        pop_growth: float = 0.01
    ) -> Dict[MembershipClass, Dict[str, pd.DataFrame]]:
        """
        Run full pension model for all classes.

        Args:
            loader: Data loader instance
            pop_growth: Population growth rate

        Returns:
            Dictionary mapping membership class to result tables
        """
        # Load all data
        data_by_class = self.load_data(loader)

        results = {}

        for class_name in MembershipClass:
            print(f"Running model for {class_name.value}...")

            data = data_by_class[class_name]

            # Skip if no data
            if len(data['salary_headcount']) == 0:
                print(f"  No data for {class_name.value}, skipping")
                continue

            # 1. Workforce projection
            workforce_states = self.run_workforce_projection(
                class_name, data, pop_growth
            )
            self.workforce_results[class_name] = workforce_states

            # 2. Benefit calculation
            benefit_table = self.run_benefit_calculation(class_name, data)
            self.benefit_results[class_name] = benefit_table

            # 3. Liability calculation
            liability_summary = self.run_liability_calculation(
                class_name, workforce_states, benefit_table, data
            )
            self.liability_results[class_name] = liability_summary

            # 4. Funding calculation
            funding_summary = self.run_funding_calculation(
                class_name, liability_summary
            )
            self.funding_results[class_name] = funding_summary

            results[class_name] = {
                'workforce_active': self._workforce_to_df(workforce_states, 'active'),
                'workforce_term': self._workforce_to_df(workforce_states, 'term'),
                'workforce_refund': self._workforce_to_df(workforce_states, 'refund'),
                'workforce_retire': self._workforce_to_df(workforce_states, 'retire'),
                'benefit': benefit_table,
                'liability': liability_summary,
                'funding': funding_summary
            }

            print(f"  Completed {class_name.value}")

        return results

    def _create_benefit_decisions(
        self,
        salary_headcount: pd.DataFrame,
        mort_table: pd.DataFrame,
        sep_table: pd.DataFrame
    ) -> pd.DataFrame:
        """Create benefit decision table (simplified placeholder)."""
        # In full implementation, this would calculate optimal
        # benefit decisions (retire vs refund) based on
        # benefit comparison

        # Placeholder: assume all eligible members retire
        decisions = salary_headcount[['entry_age', 'age', 'entry_year']].copy()
        decisions['ben_decision'] = 'retire'
        decisions['retire'] = 1.0
        decisions['refund'] = 0.0

        return decisions

    def _create_annuity_factor_table(
        self,
        benefit_table: pd.DataFrame,
        mort_table: pd.DataFrame
    ) -> pd.DataFrame:
        """Create annuity factor table (simplified placeholder)."""
        # Placeholder: use constant annuity factor
        annuity = benefit_table[['entry_age', 'age', 'year', 'entry_year']].copy()
        annuity['ann_factor'] = 15.0  # Simplified

        return annuity

    def _create_benefit_valuation_table(
        self,
        benefit_table: pd.DataFrame
    ) -> pd.DataFrame:
        """Create benefit valuation table (simplified placeholder)."""
        # Placeholder: copy benefit table with valuation columns
        val = benefit_table.copy()
        val['pvfb_db_at_term_age'] = val['pvfb'] * 0.8
        val['pvfb_db_wealth_at_current_age'] = val['pvfb']
        val['pvfnc_db'] = val['pvfs'] * 0.15
        val['cum_mort_dr'] = 0.9
        val['db_benefit'] = val['benefit']
        val['db_ee_balance'] = val['benefit'] * 0.05
        val['cola'] = self.config.cola_current_retire

        return val

    def _workforce_to_df(
        self,
        workforce_states: Dict[int, WorkforceState],
        population_type: str
    ) -> pd.DataFrame:
        """Convert workforce states to DataFrame."""
        rows = []

        for year, state in workforce_states.items():
            if population_type == 'active':
                df = state.active
                df['year'] = year
                rows.append(df)
            elif population_type == 'term':
                df = state.term
                df['year'] = year
                rows.append(df)
            elif population_type == 'refund':
                df = state.refund
                df['year'] = year
                rows.append(df)
            elif population_type == 'retire':
                df = state.retire
                df['year'] = year
                rows.append(df)

        if rows:
            return pd.concat(rows, ignore_index=True)
        else:
            return pd.DataFrame()


def run_pension_model(
    config: PlanConfig,
    data_file: str,
    pop_growth: float = 0.01
) -> Dict[MembershipClass, Dict[str, pd.DataFrame]]:
    """
    Convenience function to run full pension model.

    Args:
        config: Plan configuration
        data_file: Path to input Excel file
        pop_growth: Population growth rate

    Returns:
        Dictionary mapping membership class to result tables
    """
    # Create data loader
    loader = ExcelLoader(data_file)

    # Create and run model
    model = PensionModel(config)

    return model.run_model(loader, pop_growth)
