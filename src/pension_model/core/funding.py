"""
Funding Calculation Module

Calculates funding status using roll-forward method for AAL.

Key R Model Patterns:
1. AAL roll-forward: AAL_t = AAL_{t-1} * (1 + dr) + (NC - Benefits - Refunds) * (1 + dr)^0.5
2. Liability gain/loss: Difference between estimated and rolled-forward AAL
3. Mid-year timing: NC accrued, benefits paid at mid-year (discounted by (1+dr)^0.5)

Key Design Principles:
- Stream year-by-year to avoid keeping all years in memory
- Use long format for core data (one row = one entity)
- Match R model's roll-forward methodology
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from pension_config.plan import MembershipClass, PlanConfig, FundingPolicy, AmortizationMethod
from pension_data.schemas import FundingResult


@dataclass
class FundingSummary:
    """Summary of funding status for a single year."""
    year: int

    # Payroll
    total_payroll: float
    payroll_db_legacy: float
    payroll_db_new: float
    payroll_dc_legacy: float
    payroll_dc_new: float

    # Benefit payments and refunds
    ben_payment_legacy: float
    ben_payment_new: float
    total_ben_payment: float
    refund_legacy: float
    refund_new: float
    total_refund: float

    # Normal cost
    nc_legacy: float
    nc_new: float
    total_nc_rate: float

    # Accrued liability (roll-forward method)
    aal_legacy: float
    aal_new: float
    total_aal: float

    # Liability gain/loss
    liability_gain_loss_legacy: float
    liability_gain_loss_new: float
    total_liability_gain_loss: float

    # Assets (to be calculated separately)
    ava_legacy: float = 0.0
    ava_new: float = 0.0
    total_ava: float = 0.0
    mva_legacy: float = 0.0
    mva_new: float = 0.0
    total_mva: float = 0.0

    # Unfunded liability
    ual_ava_legacy: float = 0.0
    ual_ava_new: float = 0.0
    total_ual_ava: float = 0.0
    ual_mva_legacy: float = 0.0
    ual_mva_new: float = 0.0
    total_ual_mva: float = 0.0

    # Funding ratios
    fr_ava: float = 0.0
    fr_mva: float = 0.0


class FundingCalculator:
    """
    Calculates funding status using roll-forward method.

    This module handles:
    - Payroll projection with growth
    - AAL roll-forward with mid-year timing
    - Liability gain/loss calculation
    - Amortization layer management
    - Funding ratio calculation
    """

    def __init__(self, config: PlanConfig):
        self.config = config
        self.start_year = config.start_year
        self.model_period = config.model_period

        # Funding parameters
        self.funding_policy = config.funding_policy
        self.amortization_method = config.amortization_method
        self.amortization_period_new = config.amortization_period_new
        self.amortization_period_current = config.amortization_period_current
        self.funding_lag = config.funding_lag

        # Return assumptions
        self.dr_current = config.dr_current
        self.dr_new = config.dr_new
        self.model_return = config.model_return
        self.payroll_growth = config.payroll_growth
        self.amo_pay_growth = config.amo_pay_growth

    def roll_forward_aal(
        self,
        aal_prev: float,
        nc: float,
        benefits: float,
        refunds: float,
        dr: float,
        liability_gain_loss: float = 0.0
    ) -> float:
        """
        Roll forward AAL using R model's methodology.

        Formula:
        AAL_t = AAL_{t-1} * (1 + dr)
                + (NC - Benefits - Refunds) * (1 + dr)^0.5
                + LiabilityGainLoss

        The (1 + dr)^0.5 factor accounts for mid-year timing
        of NC accrual and benefit payments.

        Args:
            aal_prev: Previous year's AAL
            nc: Normal cost
            benefits: Benefit payments
            refunds: Refund payments
            dr: Discount rate
            liability_gain_loss: Liability gain/loss (experience adjustment)

        Returns:
            Rolled-forward AAL
        """
        # Interest on previous AAL
        interest = aal_prev * dr

        # Mid-year discount factor for NC, benefits, refunds
        mid_year_discount = (1 + dr) ** 0.5

        # Net accrual (NC - Benefits - Refunds)
        net_accrual = nc - benefits - refunds

        # Roll forward
        aal = aal_prev + interest + net_accrual * mid_year_discount + liability_gain_loss

        return aal

    def calculate_liability_gain_loss(
        self,
        aal_estimated: float,
        aal_rolled: float
    ) -> float:
        """
        Calculate liability gain/loss.

        This captures the difference between the estimated AAL
        (from workforce/benefit calculations) and the rolled-forward AAL
        (from previous year's AAL plus experience).

        Args:
            aal_estimated: Estimated AAL from liability model
            aal_rolled: Rolled-forward AAL

        Returns:
            Liability gain/loss (positive = gain, negative = loss)
        """
        return aal_estimated - aal_rolled

    def project_funding(
        self,
        liability_summary: pd.DataFrame,
        initial_aal_legacy: float,
        initial_aal_new: float,
        initial_payroll: float,
        initial_payroll_db_legacy_ratio: float,
        initial_payroll_db_new_ratio: float,
        initial_payroll_dc_legacy_ratio: float,
        initial_payroll_dc_new_ratio: float,
        initial_nc_rate_db_legacy: float,
        initial_nc_rate_db_new: float,
        initial_ben_payment: float,
        initial_refund: float
    ) -> pd.DataFrame:
        """
        Project funding status over time using roll-forward method.

        Args:
            liability_summary: Liability summary by year
            initial_aal_legacy: Initial AAL for legacy members
            initial_aal_new: Initial AAL for new members
            initial_payroll: Initial total payroll
            initial_payroll_db_legacy_ratio: Initial payroll ratio for legacy DB
            initial_payroll_db_new_ratio: Initial payroll ratio for new DB
            initial_payroll_dc_legacy_ratio: Initial payroll ratio for legacy DC
            initial_payroll_dc_new_ratio: Initial payroll ratio for new DC
            initial_nc_rate_db_legacy: Initial NC rate for legacy DB
            initial_nc_rate_db_new: Initial NC rate for new DB
            initial_ben_payment: Initial benefit payments
            initial_refund: Initial refund payments

        Returns:
            DataFrame with funding summary by year
        """
        results = []

        # Initialize state for year 1 (start_year)
        aal_legacy = initial_aal_legacy
        aal_new = initial_aal_new
        total_payroll = initial_payroll

        # Calculate year 1 values
        year = self.start_year

        # Get liability estimates for year 1
        liab_row = liability_summary[liability_summary['year'] == year]
        if len(liab_row) > 0:
            liab = liab_row.iloc[0]

            # Estimated AAL from liability model
            aal_legacy_est = liab['aal_active_db_legacy'] + liab['aal_term_db_legacy'] + liab['aal_retire_db_legacy']
            aal_new_est = liab['aal_active_db_new'] + liab['aal_term_db_new'] + liab['aal_retire_db_new']

            # Use estimated values as initial
            aal_legacy = aal_legacy_est
            aal_new = aal_new_est

        # Payroll components
        payroll_db_legacy = total_payroll * initial_payroll_db_legacy_ratio
        payroll_db_new = total_payroll * initial_payroll_db_new_ratio
        payroll_dc_legacy = total_payroll * initial_payroll_dc_legacy_ratio
        payroll_dc_new = total_payroll * initial_payroll_dc_new_ratio

        # Benefit payments and refunds
        ben_payment_legacy = initial_ben_payment * 0.5  # Assume half to legacy
        ben_payment_new = initial_ben_payment * 0.5  # Assume half to new
        refund_legacy = initial_refund * 0.5
        refund_new = initial_refund * 0.5

        # Normal cost
        nc_legacy = payroll_db_legacy * initial_nc_rate_db_legacy
        nc_new = payroll_db_new * initial_nc_rate_db_new
        total_nc_rate = (nc_legacy + nc_new) / (payroll_db_legacy + payroll_db_new)

        # Store year 1 results
        results.append(FundingSummary(
            year=year,
            total_payroll=total_payroll,
            payroll_db_legacy=payroll_db_legacy,
            payroll_db_new=payroll_db_new,
            payroll_dc_legacy=payroll_dc_legacy,
            payroll_dc_new=payroll_dc_new,
            ben_payment_legacy=ben_payment_legacy,
            ben_payment_new=ben_payment_new,
            total_ben_payment=initial_ben_payment,
            refund_legacy=refund_legacy,
            refund_new=refund_new,
            total_refund=initial_refund,
            nc_legacy=nc_legacy,
            nc_new=nc_new,
            total_nc_rate=total_nc_rate,
            aal_legacy=aal_legacy,
            aal_new=aal_new,
            total_aal=aal_legacy + aal_new,
            liability_gain_loss_legacy=0.0,
            liability_gain_loss_new=0.0,
            total_liability_gain_loss=0.0
        ))

        # Project forward years 2 to model_period
        for year_offset in range(1, self.model_period + 1):
            year = self.start_year + year_offset

            # Get liability estimates for this year
            liab_row = liability_summary[liability_summary['year'] == year]
            if len(liab_row) == 0:
                continue

            liab = liab_row.iloc[0]

            # Project payroll with growth
            total_payroll = total_payroll * (1 + self.payroll_growth)

            # Calculate payroll components (using previous year's ratios)
            prev_result = results[-1]
            payroll_db_legacy_ratio = prev_result.payroll_db_legacy / prev_result.total_payroll
            payroll_db_new_ratio = prev_result.payroll_db_new / prev_result.total_payroll
            payroll_dc_legacy_ratio = prev_result.payroll_dc_legacy / prev_result.total_payroll
            payroll_dc_new_ratio = prev_result.payroll_dc_new / prev_result.total_payroll

            payroll_db_legacy = total_payroll * payroll_db_legacy_ratio
            payroll_db_new = total_payroll * payroll_db_new_ratio
            payroll_dc_legacy = total_payroll * payroll_dc_legacy_ratio
            payroll_dc_new = total_payroll * payroll_dc_new_ratio

            # Benefit payments and refunds (from liability model)
            ben_payment_legacy = liab['retire_ben_db_legacy'] + liab['aal_retire_current'] * 0.3  # Simplified
            ben_payment_new = liab['retire_ben_db_new']
            refund_legacy = liab['refund_db_legacy']
            refund_new = liab['refund_db_new']

            total_ben_payment = ben_payment_legacy + ben_payment_new
            total_refund = refund_legacy + refund_new

            # Normal cost
            nc_legacy = payroll_db_legacy * prev_result.total_nc_rate * 0.5  # Simplified
            nc_new = payroll_db_new * prev_result.total_nc_rate * 0.5
            total_nc_rate = (nc_legacy + nc_new) / (payroll_db_legacy + payroll_db_new)

            # Estimated AAL from liability model
            aal_legacy_est = (
                liab['aal_active_db_legacy'] +
                liab['aal_term_db_legacy'] +
                liab['aal_retire_db_legacy']
            )
            aal_new_est = (
                liab['aal_active_db_new'] +
                liab['aal_term_db_new'] +
                liab['aal_retire_db_new']
            )

            # Roll forward AAL for legacy
            aal_legacy_rolled = self.roll_forward_aal(
                prev_result.aal_legacy,
                nc_legacy,
                ben_payment_legacy,
                refund_legacy,
                self.dr_current
            )

            # Roll forward AAL for new
            aal_new_rolled = self.roll_forward_aal(
                prev_result.aal_new,
                nc_new,
                ben_payment_new,
                refund_new,
                self.dr_new
            )

            # Calculate liability gain/loss
            liability_gain_loss_legacy = self.calculate_liability_gain_loss(
                aal_legacy_est, aal_legacy_rolled
            )
            liability_gain_loss_new = self.calculate_liability_gain_loss(
                aal_new_est, aal_new_rolled
            )

            # Apply liability gain/loss to rolled AAL
            aal_legacy = aal_legacy_rolled + liability_gain_loss_legacy
            aal_new = aal_new_rolled + liability_gain_loss_new

            # Store results
            results.append(FundingSummary(
                year=year,
                total_payroll=total_payroll,
                payroll_db_legacy=payroll_db_legacy,
                payroll_db_new=payroll_db_new,
                payroll_dc_legacy=payroll_dc_legacy,
                payroll_dc_new=payroll_dc_new,
                ben_payment_legacy=ben_payment_legacy,
                ben_payment_new=ben_payment_new,
                total_ben_payment=total_ben_payment,
                refund_legacy=refund_legacy,
                refund_new=refund_new,
                total_refund=total_refund,
                nc_legacy=nc_legacy,
                nc_new=nc_new,
                total_nc_rate=total_nc_rate,
                aal_legacy=aal_legacy,
                aal_new=aal_new,
                total_aal=aal_legacy + aal_new,
                liability_gain_loss_legacy=liability_gain_loss_legacy,
                liability_gain_loss_new=liability_gain_loss_new,
                total_liability_gain_loss=liability_gain_loss_legacy + liability_gain_loss_new
            ))

        # Convert to DataFrame
        df = pd.DataFrame([
            {
                'year': r.year,
                'total_payroll': r.total_payroll,
                'payroll_db_legacy': r.payroll_db_legacy,
                'payroll_db_new': r.payroll_db_new,
                'payroll_dc_legacy': r.payroll_dc_legacy,
                'payroll_dc_new': r.payroll_dc_new,
                'ben_payment_legacy': r.ben_payment_legacy,
                'ben_payment_new': r.ben_payment_new,
                'total_ben_payment': r.total_ben_payment,
                'refund_legacy': r.refund_legacy,
                'refund_new': r.refund_new,
                'total_refund': r.total_refund,
                'nc_legacy': r.nc_legacy,
                'nc_new': r.nc_new,
                'total_nc_rate': r.total_nc_rate,
                'aal_legacy': r.aal_legacy,
                'aal_new': r.aal_new,
                'total_aal': r.total_aal,
                'liability_gain_loss_legacy': r.liability_gain_loss_legacy,
                'liability_gain_loss_new': r.liability_gain_loss_new,
                'total_liability_gain_loss': r.total_liability_gain_loss,
                'ava_legacy': r.ava_legacy,
                'ava_new': r.ava_new,
                'total_ava': r.total_ava,
                'mva_legacy': r.mva_legacy,
                'mva_new': r.mva_new,
                'total_mva': r.total_mva,
                'ual_ava_legacy': r.ual_ava_legacy,
                'ual_ava_new': r.ual_ava_new,
                'total_ual_ava': r.total_ual_ava,
                'ual_mva_legacy': r.ual_mva_legacy,
                'ual_mva_new': r.ual_mva_new,
                'total_ual_mva': r.total_ual_mva,
                'fr_ava': r.fr_ava,
                'fr_mva': r.fr_mva
            }
            for r in results
        ])

        return df


def calculate_funding(
    config: PlanConfig,
    liability_summary: pd.DataFrame,
    initial_aal_legacy: float,
    initial_aal_new: float,
    initial_payroll: float,
    initial_payroll_db_legacy_ratio: float,
    initial_payroll_db_new_ratio: float,
    initial_payroll_dc_legacy_ratio: float,
    initial_payroll_dc_new_ratio: float,
    initial_nc_rate_db_legacy: float,
    initial_nc_rate_db_new: float,
    initial_ben_payment: float,
    initial_refund: float
) -> pd.DataFrame:
    """
    Convenience function to calculate funding projections.

    Args:
        config: Plan configuration
        liability_summary: Liability summary by year
        initial_aal_legacy: Initial AAL for legacy members
        initial_aal_new: Initial AAL for new members
        initial_payroll: Initial total payroll
        initial_payroll_db_legacy_ratio: Initial payroll ratio for legacy DB
        initial_payroll_db_new_ratio: Initial payroll ratio for new DB
        initial_payroll_dc_legacy_ratio: Initial payroll ratio for legacy DC
        initial_payroll_dc_new_ratio: Initial payroll ratio for new DC
        initial_nc_rate_db_legacy: Initial NC rate for legacy DB
        initial_nc_rate_db_new: Initial NC rate for new DB
        initial_ben_payment: Initial benefit payments
        initial_refund: Initial refund payments

    Returns:
        DataFrame with funding summary by year
    """
    calculator = FundingCalculator(config)

    return calculator.project_funding(
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
