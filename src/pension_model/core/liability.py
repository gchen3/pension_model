"""
Liability Calculation Module

Calculates actuarial liabilities including:
- Active member liabilities (PVFB, PVFS, AAL)
- Terminated member liabilities
- Retiree liabilities
- Total accrued actuarial liability (AAL)

Key Design Principles:
- Stream year-by-year to avoid keeping all years in memory
- Use long format for core data (one row = one entity)
- Pure functions for calculation logic
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from pension_config.types import MembershipClass
from pension_config.plan import PlanConfig
from pension_data.schemas import LiabilityResult
from pension_tools.financial import (
    present_value,
    present_value_series
)


@dataclass
class LiabilitySummary:
    """Summary of liabilities for a single year."""
    year: int

    # Active members
    payroll_db_legacy: float
    payroll_db_new: float
    payroll_dc_legacy: float
    payroll_dc_new: float
    total_payroll: float

    nc_rate_db_legacy: float
    nc_rate_db_new: float
    total_nc_rate: float

    pvfb_active_db_legacy: float
    pvfb_active_db_new: float
    pvfnc_db_legacy: float
    pvfnc_db_new: float

    aal_active_db_legacy: float
    aal_active_db_new: float

    # Terminated members
    aal_term_db_legacy: float
    aal_term_db_new: float

    # Refunds
    refund_db_legacy: float
    refund_db_new: float

    # Retirees
    retire_ben_db_legacy: float
    retire_ben_db_new: float
    aal_retire_db_legacy: float
    aal_retire_db_new: float

    # Current retirees
    retire_ben_current: float
    aal_retire_current: float

    # Current terminated vested
    retire_ben_term_current: float
    aal_term_current: float

    # Totals
    total_aal_legacy: float
    total_aal_new: float
    total_aal: float


class LiabilityCalculator:
    """
    Calculates actuarial liabilities for the pension plan.

    This module handles:
    - Active member liabilities (PVFB, PVFS, AAL)
    - Terminated member liabilities
    - Retiree liabilities
    - Refund liabilities
    - Total AAL calculation
    """

    def __init__(self, config: PlanConfig):
        self.config = config
        self.start_year = config.start_year
        self.model_period = config.model_period

        # Plan design ratios
        # These determine what percentage of members are in DB vs DC plans
        self.db_legacy_before_2018_ratio = config.db_legacy_before_2018_ratio
        self.db_legacy_after_2018_ratio = config.db_legacy_after_2018_ratio
        self.db_new_ratio = config.db_new_ratio

        self.dc_legacy_before_2018_ratio = 1 - self.db_legacy_before_2018_ratio
        self.dc_legacy_after_2018_ratio = 1 - self.db_legacy_after_2018_ratio
        self.dc_new_ratio = 1 - self.db_new_ratio

    def allocate_to_plan_design(
        self,
        n_members: float,
        entry_year: int
    ) -> Dict[str, float]:
        """
        Allocate members to plan designs based on entry year.

        Args:
            n_members: Number of members
            entry_year: Year of entry

        Returns:
            Dictionary with counts for each plan design
        """
        if entry_year < 2018:
            n_db_legacy = n_members * self.db_legacy_before_2018_ratio
            n_db_new = 0.0
            n_dc_legacy = n_members * self.dc_legacy_before_2018_ratio
            n_dc_new = 0.0
        elif entry_year < self.config.new_hire_year:
            n_db_legacy = n_members * self.db_legacy_after_2018_ratio
            n_db_new = 0.0
            n_dc_legacy = n_members * self.dc_legacy_after_2018_ratio
            n_dc_new = 0.0
        else:
            n_db_legacy = 0.0
            n_db_new = n_members * self.db_new_ratio
            n_dc_legacy = 0.0
            n_dc_new = n_members * self.dc_new_ratio

        return {
            'n_db_legacy': n_db_legacy,
            'n_db_new': n_db_new,
            'n_dc_legacy': n_dc_legacy,
            'n_dc_new': n_dc_new
        }

    def calculate_active_liabilities(
        self,
        workforce_active: pd.DataFrame,
        benefit_table: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate liabilities for active members.

        Args:
            workforce_active: Active workforce data
            benefit_table: Benefit valuation table

        Returns:
            DataFrame with active liabilities by year
        """
        # Join workforce with benefit table
        joined = workforce_active.merge(
            benefit_table,
            on=['entry_age', 'age', 'year', 'entry_year'],
            how='left'
        )

        # Fill missing values with 0
        joined = joined.fillna(0)

        # Allocate members to plan designs
        allocation = joined.apply(
            lambda row: self.allocate_to_plan_design(row['n_active'], row['entry_year']),
            axis=1,
            result_type='expand'
        )
        joined['n_active_db_legacy'] = allocation['n_db_legacy']
        joined['n_active_db_new'] = allocation['n_db_new']
        joined['n_active_dc_legacy'] = allocation['n_dc_legacy']
        joined['n_active_dc_new'] = allocation['n_dc_new']

        # Calculate payroll
        joined['payroll_db_legacy'] = joined['salary'] * joined['n_active_db_legacy']
        joined['payroll_db_new'] = joined['salary'] * joined['n_active_db_new']
        joined['payroll_dc_legacy'] = joined['salary'] * joined['n_active_dc_legacy']
        joined['payroll_dc_new'] = joined['salary'] * joined['n_active_dc_new']
        joined['payroll_total'] = joined['salary'] * joined['n_active']

        # Pre-compute weighted columns for aggregation
        joined['weighted_pvfb_db_legacy'] = joined['pvfb_db_wealth_at_current_age'] * joined['n_active_db_legacy']
        joined['weighted_pvfb_db_new'] = joined['pvfb_db_wealth_at_current_age'] * joined['n_active_db_new']
        joined['weighted_pvfnc_db_legacy'] = joined['pvfnc_db'] * joined['n_active_db_legacy']
        joined['weighted_pvfnc_db_new'] = joined['pvfnc_db'] * joined['n_active_db_new']

        # Group by year and aggregate
        summary = joined.groupby('year').agg(
            payroll_db_legacy=('payroll_db_legacy', 'sum'),
            payroll_db_new=('payroll_db_new', 'sum'),
            payroll_dc_legacy=('payroll_dc_legacy', 'sum'),
            payroll_dc_new=('payroll_dc_new', 'sum'),
            total_payroll=('payroll_total', 'sum'),

            pvfb_active_db_legacy=('weighted_pvfb_db_legacy', 'sum'),
            pvfb_active_db_new=('weighted_pvfb_db_new', 'sum'),
            pvfnc_db_legacy=('weighted_pvfnc_db_legacy', 'sum'),
            pvfnc_db_new=('weighted_pvfnc_db_new', 'sum')
        ).reset_index()

        # Calculate normal cost rates
        summary['nc_rate_db_legacy'] = np.where(
            summary['payroll_db_legacy'] > 0,
            summary['pvfnc_db_legacy'] / summary['payroll_db_legacy'],
            0
        )
        summary['nc_rate_db_new'] = np.where(
            summary['payroll_db_new'] > 0,
            summary['pvfnc_db_new'] / summary['payroll_db_new'],
            0
        )

        # Calculate AAL for active members
        summary['aal_active_db_legacy'] = (
            summary['pvfb_active_db_legacy'] - summary['pvfnc_db_legacy']
        )
        summary['aal_active_db_new'] = (
            summary['pvfb_active_db_new'] - summary['pvfnc_db_new']
        )

        # Total NC rate (weighted by payroll)
        summary['total_nc_rate'] = np.where(
            (summary['payroll_db_legacy'] + summary['payroll_db_new']) > 0,
            (
                summary['nc_rate_db_legacy'] * summary['payroll_db_legacy'] +
                summary['nc_rate_db_new'] * summary['payroll_db_new']
            ) / (summary['payroll_db_legacy'] + summary['payroll_db_new']),
            0
        )

        return summary

    def calculate_term_liabilities(
        self,
        workforce_term: pd.DataFrame,
        benefit_table: pd.DataFrame,
        benefit_val_table: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate liabilities for terminated members.

        Args:
            workforce_term: Terminated workforce data
            benefit_table: Benefit table
            benefit_val_table: Benefit valuation table

        Returns:
            DataFrame with term liabilities by year
        """
        # Join with benefit valuation table
        joined = workforce_term.merge(
            benefit_val_table,
            on=['entry_age', 'term_year', 'entry_year'],
            how='left'
        )

        # Join with benefit table for survival probability
        joined = joined.merge(
            benefit_table[['entry_age', 'age', 'year', 'term_year', 'entry_year', 'cum_mort_dr']],
            on=['entry_age', 'age', 'year', 'term_year', 'entry_year'],
            how='left',
            suffixes=('', '_current')
        )

        # Fill missing values
        joined = joined.fillna(0)

        # Calculate PVFB at termination age
        # PVFB_term = PVFB_at_term_age / cum_mort_dr_current
        joined['pvfb_db_term'] = np.where(
            joined['cum_mort_dr_current'] > 0,
            joined['pvfb_db_at_term_age'] / joined['cum_mort_dr_current'],
            joined['pvfb_db_at_term_age']
        )

        # Allocate to plan designs
        allocation = joined.apply(
            lambda row: self.allocate_to_plan_design(row['n_term'], row['entry_year']),
            axis=1,
            result_type='expand'
        )
        joined['n_term_db_legacy'] = allocation['n_db_legacy']
        joined['n_term_db_new'] = allocation['n_db_new']

        # Calculate AAL for terminated members
        joined['aal_term_db_legacy'] = joined['pvfb_db_term'] * joined['n_term_db_legacy']
        joined['aal_term_db_new'] = joined['pvfb_db_term'] * joined['n_term_db_new']

        # Group by year
        summary = joined.groupby('year').agg(
            aal_term_db_legacy=('aal_term_db_legacy', 'sum'),
            aal_term_db_new=('aal_term_db_new', 'sum')
        ).reset_index()

        return summary

    def calculate_refund_liabilities(
        self,
        workforce_refund: pd.DataFrame,
        benefit_table: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate refund liabilities.

        Args:
            workforce_refund: Refund workforce data
            benefit_table: Benefit table

        Returns:
            DataFrame with refund liabilities by year
        """
        # Join with benefit table
        joined = workforce_refund.merge(
            benefit_table[['entry_age', 'age', 'year', 'term_year', 'entry_year', 'db_ee_balance']],
            on=['entry_age', 'age', 'year', 'term_year', 'entry_year'],
            how='left'
        )

        # Fill missing values
        joined = joined.fillna(0)

        # Allocate to plan designs
        allocation = joined.apply(
            lambda row: self.allocate_to_plan_design(row['n_refund'], row['entry_year']),
            axis=1,
            result_type='expand'
        )
        joined['n_refund_db_legacy'] = allocation['n_db_legacy']
        joined['n_refund_db_new'] = allocation['n_db_new']

        # Calculate refund amounts
        joined['refund_db_legacy'] = joined['db_ee_balance'] * joined['n_refund_db_legacy']
        joined['refund_db_new'] = joined['db_ee_balance'] * joined['n_refund_db_new']

        # Group by year
        summary = joined.groupby('year').agg(
            refund_db_legacy=('refund_db_legacy', 'sum'),
            refund_db_new=('refund_db_new', 'sum')
        ).reset_index()

        return summary

    def calculate_retire_liabilities(
        self,
        workforce_retire: pd.DataFrame,
        benefit_table: pd.DataFrame,
        ann_factor_table: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate liabilities for new retirees.

        Args:
            workforce_retire: Retiree workforce data
            benefit_table: Benefit table
            ann_factor_table: Annuity factor table

        Returns:
            DataFrame with retiree liabilities by year
        """
        # Join with benefit table
        joined = workforce_retire.merge(
            benefit_table[['entry_age', 'entry_year', 'term_year', 'retire_year', 'db_benefit', 'cola']],
            on=['entry_age', 'entry_year', 'term_year', 'retire_year'],
            how='left'
        )

        # Join with annuity factor table
        joined = joined.merge(
            ann_factor_table[['entry_age', 'entry_year', 'term_year', 'year', 'ann_factor']],
            on=['entry_age', 'entry_year', 'term_year', 'year'],
            how='left'
        )

        # Fill missing values
        joined = joined.fillna(0)

        # Calculate final benefit with COLA
        joined['db_benefit_final'] = joined['db_benefit'] * (
            (1 + joined['cola']) ** (joined['year'] - joined['retire_year'])
        )

        # Calculate PVFB for retirees (excludes first payment)
        # PVFB = Benefit * (AnnuityFactor - 1)
        joined['pvfb_db_retire'] = joined['db_benefit_final'] * (joined['ann_factor'] - 1)

        # Allocate to plan designs
        allocation = joined.apply(
            lambda row: self.allocate_to_plan_design(row['n_retire'], row['entry_year']),
            axis=1,
            result_type='expand'
        )
        joined['n_retire_db_legacy'] = allocation['n_db_legacy']
        joined['n_retire_db_new'] = allocation['n_db_new']

        # Calculate benefit payments and AAL
        joined['retire_ben_db_legacy'] = joined['db_benefit_final'] * joined['n_retire_db_legacy']
        joined['retire_ben_db_new'] = joined['db_benefit_final'] * joined['n_retire_db_new']
        joined['aal_retire_db_legacy'] = joined['pvfb_db_retire'] * joined['n_retire_db_legacy']
        joined['aal_retire_db_new'] = joined['pvfb_db_retire'] * joined['n_retire_db_new']

        # Group by year
        summary = joined.groupby('year').agg(
            retire_ben_db_legacy=('retire_ben_db_legacy', 'sum'),
            retire_ben_db_new=('retire_ben_db_new', 'sum'),
            aal_retire_db_legacy=('aal_retire_db_legacy', 'sum'),
            aal_retire_db_new=('aal_retire_db_new', 'sum')
        ).reset_index()

        return summary

    def calculate_current_retiree_liabilities(
        self,
        retiree_distribution: pd.DataFrame,
        retiree_pop_current: float,
        ben_payment_current: float,
        ann_factor_table: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate liabilities for current retirees.

        Args:
            retiree_distribution: Current retiree distribution by age
            retiree_pop_current: Current retiree population
            ben_payment_current: Current benefit payments
            ann_factor_table: Annuity factor table

        Returns:
            DataFrame with current retiree liabilities by year
        """
        # Initialize current retirees
        initial = retiree_distribution.copy()
        initial['n_retire_current'] = initial['n_retire_ratio'] * retiree_pop_current
        initial['total_ben_current'] = initial['total_ben_ratio'] * ben_payment_current
        initial['avg_ben_current'] = (
            initial['total_ben_current'] / initial['n_retire_current']
        )
        initial['year'] = self.start_year

        # Project over years
        results = []

        for year_offset in range(self.model_period + 1):
            year = self.start_year + year_offset

            if year_offset == 0:
                current = initial.copy()
            else:
                # Age the population
                current['age'] = current['age'] + 1

                # Apply mortality (simplified - should use actual mortality table from R)
                # TODO: Issue #1 - Replace with R model's actual retiree mortality logic
                # Keeping 5% flat rate to match R model behavior until verified
                current['n_retire_current'] = current['n_retire_current'] * 0.95

                # Apply COLA to benefits
                # TODO: Issue #2 - Verify this matches R model's COLA rate exactly
                # Keeping hardcoded 1.03 to match R model until verified
                current['avg_ben_current'] = current['avg_ben_current'] * 1.03

                # Calculate total benefits
                current['total_ben_current'] = (
                    current['n_retire_current'] * current['avg_ben_current']
                )

            # Get annuity factor
            joined = current.merge(
                ann_factor_table,
                on=['age', 'year'],
                how='left'
            )
            joined = joined.fillna(0)

            # Calculate PVFB for current retirees
            joined['pvfb_retire_current'] = joined['avg_ben_current'] * (joined['ann_factor'] - 1)

            # Summarize by year
            summary = joined.groupby('year').agg(
                retire_ben_current=('total_ben_current', 'sum'),
                aal_retire_current=('pvfb_retire_current', lambda x: np.sum(x * joined.loc[x.index, 'n_retire_current']))
            ).reset_index()

            results.append(summary)

        return pd.concat(results, ignore_index=True)

    def calculate_term_current_liabilities(
        self,
        pvfb_term_current: float,
        amo_period_term: int,
        dr: float,
        payroll_growth: float
    ) -> pd.DataFrame:
        """
        Calculate liabilities for current terminated vested members.

        Args:
            pvfb_term_current: Current PVFB for terminated vested
            amo_period_term: Amortization period for term benefits
            dr: Discount rate
            payroll_growth: Payroll growth rate

        Returns:
            DataFrame with term current liabilities by year
        """
        years = np.arange(self.start_year, self.start_year + self.model_period + 1)

        # Calculate payment using PMT formula
        # Payment = PVFB * dr / (1 - (1 + dr)^(-n))
        payment = pvfb_term_current * dr / (1 - (1 + dr) ** (-amo_period_term))

        # Project payments with growth
        retire_ben_term_est = np.zeros(len(years))
        amo_years = np.arange(self.start_year + 1, self.start_year + amo_period_term + 1)

        for i, year in enumerate(years):
            if year in amo_years:
                year_idx = np.where(amo_years == year)[0][0]
                retire_ben_term_est[i] = payment * ((1 + payroll_growth) ** year_idx)

        # Calculate PV of remaining payments
        aal_term_current_est = np.zeros(len(years))
        for i, year in enumerate(years):
            remaining_years = max(0, amo_period_term - (year - self.start_year))
            if remaining_years > 0:
                remaining_payments = retire_ben_term_est[i:i+remaining_years]
                discount_factors = np.array([1 / ((1 + dr) ** t) for t in range(remaining_years)])
                aal_term_current_est[i] = np.sum(remaining_payments * discount_factors)

        return pd.DataFrame({
            'year': years,
            'retire_ben_term_current': retire_ben_term_est,
            'aal_term_current': aal_term_current_est
        })

    def calculate_total_liabilities(
        self,
        active_summary: pd.DataFrame,
        term_summary: pd.DataFrame,
        refund_summary: pd.DataFrame,
        retire_summary: pd.DataFrame,
        retire_current_summary: pd.DataFrame,
        term_current_summary: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate total liabilities by year.

        Args:
            active_summary: Active member liabilities
            term_summary: Terminated member liabilities
            refund_summary: Refund liabilities
            retire_summary: New retiree liabilities
            retire_current_summary: Current retiree liabilities
            term_current_summary: Current terminated vested liabilities

        Returns:
            DataFrame with total liabilities by year
        """
        # Merge all summaries
        merged = active_summary.merge(
            term_summary, on='year', how='outer'
        ).merge(
            refund_summary, on='year', how='outer'
        ).merge(
            retire_summary, on='year', how='outer'
        ).merge(
            retire_current_summary, on='year', how='outer'
        ).merge(
            term_current_summary, on='year', how='outer'
        )

        # Fill missing values with 0
        merged = merged.fillna(0)

        # Calculate totals
        merged['total_aal_legacy'] = (
            merged['aal_active_db_legacy'] +
            merged['aal_term_db_legacy'] +
            merged['aal_retire_db_legacy']
        )

        merged['total_aal_new'] = (
            merged['aal_active_db_new'] +
            merged['aal_term_db_new'] +
            merged['aal_retire_db_new']
        )

        merged['total_aal'] = merged['total_aal_legacy'] + merged['total_aal_new']

        return merged


def calculate_liabilities(
    config: PlanConfig,
    workforce_active: pd.DataFrame,
    workforce_term: pd.DataFrame,
    workforce_refund: pd.DataFrame,
    workforce_retire: pd.DataFrame,
    benefit_table: pd.DataFrame,
    benefit_val_table: pd.DataFrame,
    ann_factor_table: pd.DataFrame,
    retiree_distribution: pd.DataFrame,
    retiree_pop_current: float,
    ben_payment_current: float,
    pvfb_term_current: float,
    amo_period_term: int,
    dr: float,
    payroll_growth: float
) -> pd.DataFrame:
    """
    Convenience function to calculate all liabilities.

    Args:
        config: Plan configuration
        workforce_active: Active workforce data
        workforce_term: Terminated workforce data
        workforce_refund: Refund workforce data
        workforce_retire: Retiree workforce data
        benefit_table: Benefit table
        benefit_val_table: Benefit valuation table
        ann_factor_table: Annuity factor table
        retiree_distribution: Current retiree distribution
        retiree_pop_current: Current retiree population
        ben_payment_current: Current benefit payments
        pvfb_term_current: Current PVFB for terminated vested
        amo_period_term: Amortization period for term benefits
        dr: Discount rate
        payroll_growth: Payroll growth rate

    Returns:
        DataFrame with total liabilities by year
    """
    calculator = LiabilityCalculator(config)

    # Calculate each component
    active_summary = calculator.calculate_active_liabilities(
        workforce_active, benefit_table
    )

    term_summary = calculator.calculate_term_liabilities(
        workforce_term, benefit_table, benefit_val_table
    )

    refund_summary = calculator.calculate_refund_liabilities(
        workforce_refund, benefit_table
    )

    retire_summary = calculator.calculate_retire_liabilities(
        workforce_retire, benefit_table, ann_factor_table
    )

    retire_current_summary = calculator.calculate_current_retiree_liabilities(
        retiree_distribution, retiree_pop_current, ben_payment_current, ann_factor_table
    )

    term_current_summary = calculator.calculate_term_current_liabilities(
        pvfb_term_current, amo_period_term, dr, payroll_growth
    )

    # Calculate total liabilities
    return calculator.calculate_total_liabilities(
        active_summary, term_summary, refund_summary,
        retire_summary, retire_current_summary, term_current_summary
    )
