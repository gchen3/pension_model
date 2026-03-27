"""
Validation Comparators Module

Compares Python model outputs against R baseline outputs.

Key Design Principles:
- Compare at multiple tolerance levels (strict, moderate, lenient)
- Provide detailed discrepancy reports
- Support comparison by year, class, and metric
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


@dataclass
class ComparisonResult:
    """Result of a single comparison."""
    metric: str
    python_value: float
    r_value: float
    difference: float
    percent_difference: float
    within_tolerance: bool
    tolerance_level: str  # 'strict', 'moderate', 'lenient'


@dataclass
class ComparisonSummary:
    """Summary of all comparisons for a class/year."""
    year: int
    class_name: str
    total_metrics: int
    passed: int
    failed: int
    max_percent_difference: float
    discrepancies: List[ComparisonResult]


class ValidationConfig:
    """Configuration for validation tolerances."""
    # Tolerance levels
    strict_tolerance: float = 0.01  # 1%
    moderate_tolerance: float = 0.05  # 5%
    lenient_tolerance: float = 0.10  # 10%

    # Minimum absolute difference threshold
    min_absolute_threshold: float = 1000.0  # $1,000

    # Metrics to validate
    metrics_to_validate: List[str] = None


class Validator:
    """
    Validates Python model outputs against R baseline.

    This module handles:
    - Loading R baseline outputs
    - Comparing Python outputs to baseline
    - Generating discrepancy reports
    - Calculating pass/fail rates
    """

    def __init__(self, config: ValidationConfig):
        self.config = config

    def load_baseline(
        self,
        baseline_dir: str
    ) -> Dict[str, pd.DataFrame]:
        """
        Load R baseline output files.

        Args:
            baseline_dir: Directory containing baseline outputs

        Returns:
            Dictionary mapping file type to DataFrame
        """
        import os
        from pathlib import Path

        baseline_files = {}
        baseline_path = Path(baseline_dir)

        # Load CSV files
        for csv_file in baseline_path.glob('*.csv'):
            try:
                df = pd.read_csv(csv_file)
                baseline_files[csv_file.stem] = df
            except Exception as e:
                print(f"Warning: Could not load {csv_file}: {e}")

        return baseline_files

    def compare_value(
        self,
        metric: str,
        python_value: float,
        r_value: float,
        tolerance: float
    ) -> ComparisonResult:
        """
        Compare a single value between Python and R.

        Args:
            metric: Name of the metric
            python_value: Python model value
            r_value: R baseline value
            tolerance: Tolerance threshold (as percentage)

        Returns:
            ComparisonResult
        """
        # Calculate difference
        difference = abs(python_value - r_value)

        # Calculate percent difference
        if r_value != 0:
            percent_difference = difference / abs(r_value)
        else:
            percent_difference = 0.0

        # Check if within tolerance
        within_tolerance = percent_difference <= tolerance

        # Determine tolerance level
        if within_tolerance:
            if percent_difference <= self.config.strict_tolerance:
                tolerance_level = 'strict'
            elif percent_difference <= self.config.moderate_tolerance:
                tolerance_level = 'moderate'
            else:
                tolerance_level = 'lenient'
        else:
            tolerance_level = 'failed'

        # Check absolute threshold
        if difference < self.config.min_absolute_threshold:
            # Small absolute differences are OK even if percent is high
            is_within_tolerance = True
        else:
            is_within_tolerance = within_tolerance

        return ComparisonResult(
            metric=metric,
            python_value=python_value,
            r_value=r_value,
            difference=difference,
            percent_difference=percent_difference,
            within_tolerance=is_within_tolerance,
            tolerance_level=tolerance_level
        )

    def compare_dataframes(
        self,
        python_df: pd.DataFrame,
        r_df: pd.DataFrame,
        key_columns: List[str]
    ) -> List[ComparisonResult]:
        """
        Compare two DataFrames row by row.

        Args:
            python_df: Python model output
            r_df: R baseline output
            key_columns: List of column names to compare

        Returns:
            List of ComparisonResults
        """
        results = []

        # Find common years
        common_years = set(python_df['year'].unique()) & set(r_df['year'].unique())

        for year in common_years:
            python_row = python_df[python_df['year'] == year]
            r_row = r_df[r_df['year'] == year]

            if len(python_row) == 0 or len(r_row) == 0:
                continue

            for col in key_columns:
                if col in python_row.columns and col in r_row.columns:
                    python_val = python_row[col].iloc[0]
                    r_val = r_row[col].iloc[0]

                    result = self.compare_value(
                        f"{year}_{col}",
                        python_val,
                        r_val,
                        self.config.moderate_tolerance
                    )
                    results.append(result)

        return results

    def compare_workforce(
        self,
        python_workforce: pd.DataFrame,
        r_workforce: pd.DataFrame
    ) -> ComparisonSummary:
        """
        Compare workforce projections.

        Args:
            python_workforce: Python workforce output
            r_workforce: R baseline workforce output

        Returns:
            ComparisonSummary
        """
        # Key metrics to compare
        key_columns = ['total_active', 'total_payroll']

        # Compare dataframes
        comparisons = self.compare_dataframes(
            python_workforce, r_workforce, key_columns
        )

        # Calculate summary
        passed = sum(1 for c in comparisons if c.within_tolerance)
        failed = sum(1 for c in comparisons if not c.within_tolerance)
        max_diff = max([c.percent_difference for c in comparisons])

        return ComparisonSummary(
            year=self._get_summary_year(python_workforce, r_workforce),
            class_name='workforce',
            total_metrics=len(comparisons),
            passed=passed,
            failed=failed,
            max_percent_difference=max_diff,
            discrepancies=[c for c in comparisons if not c.within_tolerance]
        )

    def compare_benefits(
        self,
        python_benefits: pd.DataFrame,
        r_benefits: pd.DataFrame
    ) -> ComparisonSummary:
        """
        Compare benefit calculations.

        Args:
            python_benefits: Python benefit output
            r_benefits: R baseline benefit output

        Returns:
            ComparisonSummary
        """
        key_columns = ['total_benefit', 'total_normal_cost', 'total_pvfb', 'total_aal']

        comparisons = self.compare_dataframes(
            python_benefits, r_benefits, key_columns
        )

        passed = sum(1 for c in comparisons if c.within_tolerance)
        failed = sum(1 for c in comparisons if not c.within_tolerance)
        max_diff = max([c.percent_difference for c in comparisons])

        return ComparisonSummary(
            year=self._get_summary_year(python_benefits, r_benefits),
            class_name='benefits',
            total_metrics=len(comparisons),
            passed=passed,
            failed=failed,
            max_percent_difference=max_diff,
            discrepancies=[c for c in comparisons if not c.within_tolerance]
        )

    def compare_liabilities(
        self,
        python_liabilities: pd.DataFrame,
        r_liabilities: pd.DataFrame
    ) -> ComparisonSummary:
        """
        Compare liability calculations.

        Args:
            python_liabilities: Python liability output
            r_liabilities: R baseline liability output

        Returns:
            ComparisonSummary
        """
        key_columns = ['total_aal', 'aal_legacy', 'aal_new']

        comparisons = self.compare_dataframes(
            python_liabilities, r_liabilities, key_columns
        )

        passed = sum(1 for c in comparisons if c.within_tolerance)
        failed = sum(1 for c in comparisons if not c.within_tolerance)
        max_diff = max([c.percent_difference for c in comparisons])

        return ComparisonSummary(
            year=self._get_summary_year(python_liabilities, r_liabilities),
            class_name='liabilities',
            total_metrics=len(comparisons),
            passed=passed,
            failed=failed,
            max_percent_difference=max_diff,
            discrepancies=[c for c in comparisons if not c.within_tolerance]
        )

    def compare_funding(
        self,
        python_funding: pd.DataFrame,
        r_funding: pd.DataFrame
    ) -> ComparisonSummary:
        """
        Compare funding calculations.

        Args:
            python_funding: Python funding output
            r_funding: R baseline funding output

        Returns:
            ComparisonSummary
        """
        key_columns = ['total_payroll', 'total_aal', 'total_ben_payment', 'funding_ratio']

        comparisons = self.compare_dataframes(
            python_funding, r_funding, key_columns
        )

        passed = sum(1 for c in comparisons if c.within_tolerance)
        failed = sum(1 for c in comparisons if not c.within_tolerance)
        max_diff = max([c.percent_difference for c in comparisons])

        return ComparisonSummary(
            year=self._get_summary_year(python_funding, r_funding),
            class_name='funding',
            total_metrics=len(comparisons),
            passed=passed,
            failed=failed,
            max_percent_difference=max_diff,
            discrepancies=[c for c in comparisons if not c.within_tolerance]
        )

    def _get_summary_year(
        self,
        python_df: pd.DataFrame,
        r_df: pd.DataFrame
    ) -> int:
        """Get the summary year from DataFrames."""
        if 'year' in python_df.columns and len(python_df) > 0:
            return python_df['year'].iloc[0]
        if 'year' in r_df.columns and len(r_df) > 0:
            return r_df['year'].iloc[0]
        return 0


def validate_model_outputs(
    python_outputs: Dict[str, pd.DataFrame],
    baseline_dir: str,
    config: Optional[ValidationConfig] = None
) -> Dict[str, List[ComparisonSummary]]:
    """
    Validate Python model outputs against R baseline.

    Args:
        python_outputs: Dictionary of Python output DataFrames
        baseline_dir: Directory containing R baseline outputs
        config: Validation configuration

        Returns:
            Dictionary mapping category to comparison summaries
    """
    if config is None:
        config = ValidationConfig()
    else:
        config = config

    validator = Validator(config)

    # Load baseline outputs
    baseline_files = validator.load_baseline(baseline_dir)

    results = {}

    # Compare workforce
    if 'workforce' in python_outputs and 'workforce_summary' in baseline_files:
        results['workforce'] = validator.compare_workforce(
            python_outputs['workforce'],
            baseline_files['workforce_summary']
        )

    # Compare benefits
    if 'benefits' in python_outputs and 'benefit_summary' in baseline_files:
        results['benefits'] = validator.compare_benefits(
            python_outputs['benefits'],
            baseline_files['benefit_summary']
        )

    # Compare liabilities
    if 'liabilities' in python_outputs and 'liability_summary' in baseline_files:
        results['liabilities'] = validator.compare_liabilities(
            python_outputs['liabilities'],
            baseline_files['liability_summary']
        )

    # Compare funding
    if 'funding' in python_outputs and 'funding_summary' in baseline_files:
        results['funding'] = validator.compare_funding(
            python_outputs['funding'],
            baseline_files['funding_summary']
        )

    return results
