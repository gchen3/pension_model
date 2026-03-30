"""
FRS (Florida Retirement System) Plan Adapter

This adapter provides FRS-specific business rules, benefit formulas,
and data transformations for the general pension model.
"""

from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
import pandas as pd

from .adapters import BasePlanAdapter, PlanRegistry
from .types import MembershipClass, Tier
from pension_data.decrement_loader import DecrementLoader


class FRSAdapter(BasePlanAdapter):
    """
    Adapter for Florida Retirement System (FRS).

    Implements all FRS-specific business rules including:
    - Benefit multipliers by class and tier
    - Retirement eligibility rules
    - COLA rates
    - DB/DC split ratios
    """

    def __init__(self, config: Union[Dict[str, Any], 'PlanConfig'], baseline_dir: str = "baseline_outputs"):
        """
        Initialize FRS adapter with configuration and decrement table loader.

        Args:
            config: Either a PlanConfig object or a dictionary with config values
            baseline_dir: Directory containing baseline output files (decrement tables)
        """
        # Handle both PlanConfig and dict
        if hasattr(config, '__dataclass_fields__'):
            # It's a PlanConfig dataclass
            self._config_obj = config
            self.config = config.to_dict() if hasattr(config, 'to_dict') else {}
        else:
            # It's a dict
            self._config_obj = None
            self.config = config if config else {}

        # Initialize decrement loader for accessing extracted tables
        self.decrement_loader = DecrementLoader(baseline_dir)

        # Cache for loaded tables by membership class
        self._withdrawal_tables: Dict[str, pd.DataFrame] = {}
        self._retirement_tables: Dict[str, pd.DataFrame] = {}
        self._mortality_tables: Dict[str, pd.DataFrame] = {}

    @property
    def plan_name(self) -> str:
        return "FRS"

    @property
    def membership_classes(self) -> List[MembershipClass]:
        return [
            MembershipClass.REGULAR,
            MembershipClass.SPECIAL,
            MembershipClass.ADMIN,
            MembershipClass.ECO,
            MembershipClass.ESO,
            MembershipClass.JUDGES,
            MembershipClass.SENIOR_MANAGEMENT
        ]

    @property
    def tiers(self) -> List[Tier]:
        return [Tier.TIER_1, Tier.TIER_2, Tier.TIER_3]

    def get_benefit_multiplier(
        self,
        membership_class: MembershipClass,
        tier: Tier,
        years_of_service: float,
        age: Optional[float] = None
    ) -> float:
        """
        Get FRS benefit multiplier for a given class, tier, and YOS.

        FRS Benefit Multipliers:
        - Regular (Tier 1): 1.60% per YOS
        - Regular (Tier 2): 1.60% - 1.68% (graded by YOS)
        - Regular (Tier 3): 1.65% per YOS
        - Special Risk (Tier 1): 1.60% per YOS
        - Special Risk (Tier 2): 1.60% - 1.68% (graded by YOS)
        - Special Risk (Tier 3): 1.65% per YOS
        - Admin (Tier 1): 1.60% per YOS
        - Admin (Tier 2): 1.60% - 1.68% (graded by YOS)
        - Admin (Tier 3): 1.65% per YOS
        - ECO (Tier 1): 1.60% per YOS
        - ESO (Tier 1): 1.60% per YOS
        - Judges (Tier 1): 3.30% per YOS
        - Senior Management (Tier 1): 1.60% per YOS
        """

        # Get benefit rules from config
        benefit_rules = self.config.get('benefit_rules', {})

        # Look up multiplier
        class_key = membership_class.value
        tier_key = tier.value

        if class_key in benefit_rules:
            class_rules = benefit_rules[class_key]
            if tier_key in class_rules:
                tier_rules = class_rules[tier_key]

                # Check if graded by YOS
                if isinstance(tier_rules, dict):
                    # Graded multipliers - find appropriate band
                    yos_bands = sorted(tier_rules.keys())
                    for yos_band in yos_bands:
                        if years_of_service <= yos_band:
                            return tier_rules[yos_band]
                    # Return max if beyond all bands
                    return tier_rules[yos_bands[-1]]
                else:
                    # Single multiplier
                    return tier_rules

        # Default fallback
        return 0.016  # 1.6% per YOS

    def get_normal_retirement_age(
        self,
        membership_class: MembershipClass,
        tier: Tier
    ) -> Tuple[float, float]:
        """
        Get FRS normal retirement age (age and YOS) for a class and tier.

        FRS Normal Retirement:
        - Regular (Tier 1): Age 62, 6 YOS OR Age 65
        - Regular (Tier 2): Age 62, 6 YOS OR Age 65
        - Regular (Tier 3): Age 65, 8 YOS
        - Special Risk (Tier 1): Age 55, 6 YOS
        - Special Risk (Tier 2): Age 55, 6 YOS
        - Special Risk (Tier 3): Age 60, 8 YOS
        - Admin (Tier 1): Age 62, 6 YOS OR Age 65
        - Admin (Tier 2): Age 62, 6 YOS OR Age 65
        - Admin (Tier 3): Age 65, 8 YOS
        - ECO (Tier 1): Age 62, 6 YOS OR Age 65
        - ESO (Tier 1): Age 62, 6 YOS OR Age 65
        - Judges (Tier 1): Age 65, 6 YOS OR Age 70
        - Senior Management (Tier 1): Age 62, 6 YOS OR Age 65
        """

        # Get retirement rules from config
        retirement_rules = self.config.get('retirement_eligibility', {})

        class_key = membership_class.value
        tier_key = tier.value

        if class_key in retirement_rules:
            class_rules = retirement_rules[class_key]
            if tier_key in class_rules:
                tier_rules = class_rules[tier_key]
                if 'normal' in tier_rules:
                    normal = tier_rules['normal']
                    return (normal.get('age', 65.0), normal.get('yos', 6.0))

        # Default fallback
        return (65.0, 6.0)

    def get_early_retirement_age(
        self,
        membership_class: MembershipClass,
        tier: Tier
    ) -> Tuple[float, float]:
        """
        Get FRS early retirement age (age and YOS) for a class and tier.

        FRS Early Retirement:
        - Regular (Tier 1): Age 57, 6 YOS
        - Regular (Tier 2): Age 57, 6 YOS
        - Regular (Tier 3): Age 60, 8 YOS
        - Special Risk (Tier 1): Age 52, 6 YOS
        - Special Risk (Tier 2): Age 52, 6 YOS
        - Special Risk (Tier 3): Age 55, 8 YOS
        - Admin (Tier 1): Age 57, 6 YOS
        - Admin (Tier 2): Age 57, 6 YOS
        - Admin (Tier 3): Age 60, 8 YOS
        - ECO (Tier 1): Age 57, 6 YOS
        - ESO (Tier 1): Age 57, 6 YOS
        - Judges (Tier 1): Age 62, 6 YOS
        - Senior Management (Tier 1): Age 57, 6 YOS
        """

        # Get retirement rules from config
        retirement_rules = self.config.get('retirement_eligibility', {})

        class_key = membership_class.value
        tier_key = tier.value

        if class_key in retirement_rules:
            class_rules = retirement_rules[class_key]
            if tier_key in class_rules:
                tier_rules = class_rules[tier_key]
                if 'early' in tier_rules:
                    early = tier_rules['early']
                    return (early.get('age', 57.0), early.get('yos', 6.0))

        # Default fallback
        return (57.0, 6.0)

    def get_early_retirement_factor(
        self,
        membership_class: MembershipClass,
        tier: Tier,
        current_age: float,
        current_yos: float,
        normal_ret_age: float,
        normal_ret_yos: float
    ) -> float:
        """
        Calculate FRS early retirement reduction factor.

        FRS uses 5% reduction per year early from either age or YOS,
        whichever is greater.
        """
        # Calculate months early from age and YOS
        months_early_age = max(0, (normal_ret_age - current_age) * 12)
        months_early_yos = max(0, (normal_ret_yos - current_yos) * 12)

        # Use greater of the two
        months_early = max(months_early_age, months_early_yos)

        # 5% reduction per year early (0.4167% per month)
        # Maximum reduction is 50%
        reduction = min(0.50, months_early * 0.004167)

        return 1.0 - reduction

    def get_cola_rate(
        self,
        membership_class: MembershipClass,
        tier: Tier,
        is_retired: bool,
        year: int
    ) -> float:
        """
        Get FRS COLA rate for a given class, tier, and year.

        FRS COLA Rates:
        - Tier 1 Active: 3% (constant)
        - Tier 2 Active: 3% (constant)
        - Tier 3 Active: 3% (constant)
        - Current Retirees: 3%
        - Current Retirees (one-time): 1.5% one-time COLA
        """

        cola_config = self.config.get('cola', {})

        if is_retired:
            # Check for one-time COLA
            if year == self.config.get('one_time_cola_year'):
                return cola_config.get('one_time_cola', 0.015)
            return cola_config.get('cola_current_retire', 0.03)
        else:
            # Active members
            class_key = membership_class.value
            tier_key = tier.value

            if class_key in cola_config:
                class_cola = cola_config[class_key]
                if tier_key in class_cola:
                    return class_cola[tier_key]

            # Default fallback
            return 0.03

    def get_salary_growth_rate(
        self,
        membership_class: MembershipClass,
        years_of_service: float
    ) -> float:
        """
        Get FRS salary growth rate for a given class and YOS.

        FRS salary growth varies by YOS band.
        """
        salary_growth = self.config.get('salary_growth', {})

        class_key = membership_class.value

        if class_key in salary_growth:
            class_growth = salary_growth[class_key]

            # Find appropriate YOS band
            yos_bands = sorted(class_growth.keys())
            for yos_band in yos_bands:
                if years_of_service <= yos_band:
                    return class_growth[yos_band]
            # Return max if beyond all bands
            return class_growth[yos_bands[-1]]

        # Default fallback
        return 0.045  # 4.5%

    def load_withdrawal_table(
        self,
        membership_class: MembershipClass,
        gender: Optional[str] = None
    ) -> Optional[pd.DataFrame]:
        """
        Load withdrawal table for a membership class.

        Args:
            membership_class: The membership class
            gender: 'male' or 'female' (required for some classes)

        Returns:
            DataFrame with withdrawal rates
        """
        class_key = membership_class.value
        cache_key = f"{class_key}_{gender}" if gender else class_key

        if cache_key in self._withdrawal_tables:
            return self._withdrawal_tables[cache_key]

        # Load from decrement loader
        table = self.decrement_loader.load_withdrawal_table(class_key, gender)
        if table is not None:
            self._withdrawal_tables[cache_key] = table

        return table

    def get_withdrawal_rate(
        self,
        membership_class: MembershipClass,
        age: float,
        years_of_service: float,
        gender: Optional[str] = None
    ) -> float:
        """
        Get FRS withdrawal/termination rate for a given class, age, and YOS.

        Uses loaded decrement tables from baseline outputs.
        """
        # Load table for this class/gender
        table = self.load_withdrawal_table(membership_class, gender)

        if table is not None:
            # Use decrement loader's lookup method
            return self.decrement_loader.get_withdrawal_rate(
                table,
                int(age),
                int(years_of_service)
            )

        # Fallback to config if table not available
        withdrawal_rates = self.config.get('withdrawal_rates', {})
        class_key = membership_class.value

        if class_key in withdrawal_rates:
            class_rates = withdrawal_rates[class_key]
            for rate_entry in class_rates:
                if (rate_entry.get('age_min', 0) <= age <= rate_entry.get('age_max', 100) and
                    rate_entry.get('yos_min', 0) <= years_of_service <= rate_entry.get('yos_max', 50)):
                    return rate_entry['rate']

        # Default fallback
        return 0.05  # 5%

    def load_mortality_table(
        self,
        membership_class: MembershipClass
    ) -> Optional[pd.DataFrame]:
        """
        Load mortality table for a membership class.

        Args:
            membership_class: The membership class

        Returns:
            DataFrame with mortality rates
        """
        class_key = membership_class.value

        if class_key in self._mortality_tables:
            return self._mortality_tables[class_key]

        # Load from decrement loader
        table = self.decrement_loader.load_mortality_table(class_key)
        if table is not None:
            self._mortality_tables[class_key] = table

        return table

    def load_retirement_table(
        self,
        tier: Tier,
        retirement_type: str = 'normal'
    ) -> Optional[pd.DataFrame]:
        """
        Load retirement table for a tier.

        Args:
            tier: The tier
            retirement_type: 'normal', 'early', or 'drop'

        Returns:
            DataFrame with retirement rates
        """
        cache_key = f"{tier.value}_{retirement_type}"

        if cache_key in self._retirement_tables:
            return self._retirement_tables[cache_key]

        # Load from decrement loader
        table = self.decrement_loader.load_retirement_table(tier.value, retirement_type)
        if table is not None:
            self._retirement_tables[cache_key] = table

        return table

    def get_mortality_rate(
        self,
        membership_class: MembershipClass,
        age: float,
        gender: str,
        is_retired: bool = False
    ) -> float:
        """
        Get FRS mortality rate (qx) for a given class, age, and gender.

        Uses loaded decrement tables from baseline outputs.
        """
        # Load table for this class
        table = self.load_mortality_table(membership_class)

        if table is not None:
            # Use decrement loader's lookup method
            # Note: Mortality tables typically have complex structure with entry_year, entry_age, etc.
            # For now, use a simplified lookup by age
            matches = table[
                (table['dist_age'] == int(age))
            ]
            if len(matches) > 0:
                return matches['mort_final'].iloc[0]

        # Fallback to config if table not available
        mortality_tables = self.config.get('mortality', {})
        class_key = membership_class.value
        table_key = f"{class_key}_{'retired' if is_retired else 'active'}"

        if table_key in mortality_tables:
            table = mortality_tables[table_key]
            gender_key = gender.upper()

            if gender_key in table:
                gender_table = table[gender_key]
                age_int = int(age)
                if age_int in gender_table:
                    return gender_table[age_int]

        # Default fallback - use RP-2000 or similar
        return 0.001  # 0.1%

    def determine_tier(
        self,
        membership_class: MembershipClass,
        entry_year: int,
        distribution_year: Optional[int] = None
    ) -> Tier:
        """
        Determine FRS tier based on entry year.

        FRS Tier Rules:
        - Tier 1: Entry before July 1, 2011
        - Tier 2: Entry July 1, 2011 - June 30, 2018
        - Tier 3: Entry on or after July 1, 2018

        Special Risk has different dates:
        - Tier 1: Entry before July 1, 2011
        - Tier 2: Entry July 1, 2011 - December 31, 2017
        - Tier 3: Entry on or after January 1, 2018
        """

        tier_cutoffs = self.config.get('tier_cutoffs', {})

        if membership_class in [MembershipClass.SPECIAL]:
            # Special Risk cutoffs
            if entry_year < 2011:
                return Tier.TIER_1
            elif entry_year < 2018:
                return Tier.TIER_2
            else:
                return Tier.TIER_3
        else:
            # All other classes
            if entry_year < 2011:
                return Tier.TIER_1
            elif entry_year < 2018:
                return Tier.TIER_2
            else:
                return Tier.TIER_3

    def get_db_dc_ratio(
        self,
        membership_class: MembershipClass,
        tier: Tier,
        entry_year: int
    ) -> Tuple[float, float]:
        """
        Get FRS DB/DC split ratio for a given class, tier, and entry year.

        FRS DB/DC Split:
        - Regular (Tier 1, pre-2018): 100% DB
        - Regular (Tier 2, 2011-2018): 100% DB
        - Regular (Tier 3, post-2018): 78% DB, 22% DC
        - Special Risk (Tier 1, pre-2018): 100% DB
        - Special Risk (Tier 2, 2011-2018): 100% DB
        - Special Risk (Tier 3, post-2018): 78% DB, 22% DC
        - Admin (Tier 3, post-2018): 78% DB, 22% DC
        - All other classes/tiers: 100% DB
        """

        db_dc_ratios = self.config.get('db_dc_ratios', {})

        class_key = membership_class.value
        tier_key = tier.value

        # Check if this class/tier has DC component
        if class_key in db_dc_ratios:
            class_ratios = db_dc_ratios[class_key]
            if tier_key in class_ratios:
                return class_ratios[tier_key]

        # Default: 100% DB, 0% DC
        return (1.0, 0.0)

    def get_retirement_benefit_formula(
        self,
        membership_class: MembershipClass,
        tier: Tier
    ) -> str:
        """
        Get FRS retirement benefit formula description.
        """
        multiplier = self.get_benefit_multiplier(membership_class, tier, 1.0)
        multiplier_pct = multiplier * 100

        if membership_class == MembershipClass.JUDGES:
            return f"{multiplier_pct:.2f}% x YOS x Final Average Salary"
        else:
            return f"{multiplier_pct:.2f}% x YOS x Final 5-Year Average Salary"

    def validate_data_requirements(
        self,
        data: Dict[str, Any]
    ) -> List[str]:
        """
        Validate FRS-specific data requirements.
        """
        errors = super().validate_data_requirements(data)

        # Check for FRS-specific tables
        frs_required = [
            'salary_growth',
            'mortality_regular_active',
            'mortality_regular_retired',
            'mortality_special_active',
            'mortality_special_retired',
            'withdrawal_rates_regular',
            'withdrawal_rates_special',
            'benefit_rules',
            'retirement_eligibility',
            'cola_rates',
            'db_dc_ratios'
        ]

        for table in frs_required:
            if table not in data:
                errors.append(f"Missing FRS-specific table: {table}")

        return errors


# Register FRS adapter with the registry
# This will be done when the adapter is instantiated with config
def register_frs_adapter(config: Dict[str, Any]) -> FRSAdapter:
    """Factory function to create and register FRS adapter"""
    adapter = FRSAdapter(config)
    PlanRegistry.register(adapter)
    return adapter
