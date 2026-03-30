"""
Calibration parameter loader for pension modeling.

This module provides access to calibration factors extracted from the R model
that are needed to match the actuarial valuation results.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional


class CalibrationLoader:
    """
    Load and provide access to calibration parameters.

    These parameters are used to adjust model outputs to match
    the actuarial valuation results from the Florida FRS valuation report.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the calibration loader.

        Args:
            config_path: Path to calibration JSON file.
                        Defaults to configs/calibration_params.json
        """
        if config_path is None:
            config_path = "configs/calibration_params.json"

        self.config_path = Path(config_path)
        self._params: Dict[str, Any] = {}
        self._load_params()

    def _load_params(self) -> None:
        """Load calibration parameters from JSON file."""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Calibration config not found: {self.config_path}"
            )

        with open(self.config_path, "r") as f:
            self._params = json.load(f)

    @property
    def global_cal_factor(self) -> float:
        """Global calibration factor for benefit model."""
        return self._params.get("global_calibration", {}).get("cal_factor", 1.0)

    @property
    def retire_refund_ratio(self) -> float:
        """Ratio of vested members choosing retirement vs refund."""
        return self._params.get("retire_refund_ratio", {}).get("value", 1.0)

    @property
    def population_growth(self) -> float:
        """Population growth assumption (0 = stable population)."""
        return self._params.get("population_growth", {}).get("value", 0.0)

    def get_normal_cost_cal_factor(self, class_name: str) -> float:
        """
        Get normal cost calibration factor for a membership class.

        Args:
            class_name: Membership class name

        Returns:
            Calibration factor (val_report_nc / model_nc)
        """
        nc_cal = self._params.get("normal_cost_calibration", {})
        class_data = nc_cal.get(class_name, {})
        return class_data.get("cal_factor", 1.0)

    def get_pvfb_term_adjustment(self, class_name: str) -> float:
        """
        Get PVFB term current adjustment for a membership class.

        This is the remaining accrued liability not captured by
        the standard PVFB calculations.

        Args:
            class_name: Membership class name

        Returns:
            Adjustment amount in dollars
        """
        pvfb_adj = self._params.get("pvfb_term_current_adjustment", {})
        return pvfb_adj.get(class_name, 0.0)

    @property
    def pvfb_amortization_period(self) -> int:
        """Amortization period for remaining accrued liability."""
        return self._params.get("pvfb_term_current_adjustment", {}).get(
            "amortization_period_years", 50
        )

    @property
    def pvfb_amortization_growth_rate(self) -> float:
        """Growth rate for PVFB amortization payments."""
        return self._params.get("pvfb_term_current_adjustment", {}).get(
            "amortization_growth_rate", 0.03
        )

    def get_db_plan_ratio(self, class_type: str, hire_period: str) -> float:
        """
        Get DB plan ratio for member classification.

        Args:
            class_type: "special" or "non_special"
            hire_period: "legacy_before_2018", "legacy_after_2018", or "new"

        Returns:
            Proportion of members choosing DB plan
        """
        db_ratios = self._params.get("db_plan_ratios", {})
        key = f"{class_type}_{hire_period}"
        return db_ratios.get(key, 0.5)

    def get_total_active_membership(self, class_name: str) -> int:
        """
        Get total active membership for a class from ACFR.

        Args:
            class_name: Membership class name

        Returns:
            Total active members (DB + DC)
        """
        membership = self._params.get("total_active_membership", {})
        return membership.get(class_name, 0)

    def get_retiree_population(self, class_name: str) -> int:
        """
        Get retiree population for a class.

        Args:
            class_name: Membership class name

        Returns:
            Number of annuitants
        """
        retirees = self._params.get("retiree_population", {})
        return retirees.get(class_name, 0)

    def get_benefit_payment_current(self, class_name: str) -> float:
        """
        Get current benefit payment estimate for a class.

        Args:
            class_name: Membership class name

        Returns:
            Estimated annual benefit payments
        """
        payments = self._params.get("benefit_payments_current", {})
        return payments.get(class_name, 0.0)

    def get_all_normal_cost_factors(self) -> Dict[str, float]:
        """Get normal cost calibration factors for all classes."""
        nc_cal = self._params.get("normal_cost_calibration", {})
        return {
            class_name: data.get("cal_factor", 1.0)
            for class_name, data in nc_cal.items()
        }

    def get_all_pvfb_adjustments(self) -> Dict[str, float]:
        """Get PVFB adjustments for all classes."""
        pvfb_adj = self._params.get("pvfb_term_current_adjustment", {})
        classes = ["regular", "special", "admin", "eco", "eso", "judges", "senior_management"]
        return {
            cls: pvfb_adj.get(cls, 0.0)
            for cls in classes
        }

    def to_dict(self) -> Dict[str, Any]:
        """Return all calibration parameters as dictionary."""
        return self._params.copy()


def create_calibration_loader(config_path: Optional[str] = None) -> CalibrationLoader:
    """
    Factory function to create a CalibrationLoader.

    Args:
        config_path: Optional path to calibration config file

    Returns:
        CalibrationLoader instance
    """
    return CalibrationLoader(config_path)
