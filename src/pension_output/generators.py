"""
Output Generators Module

Creates output tables and exports results in various formats.

Key Design Principles:
- Stream year-by-year to avoid keeping all years in memory
- Use long format for core data (one row = one entity)
- Support multiple output formats (CSV, Excel, JSON)
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd

from pension_config.plan import MembershipClass, PlanConfig


@dataclass
class OutputConfig:
    """Configuration for output generation."""
    output_dir: str
    export_format: str  # 'csv', 'excel', 'json'
    include_summary: bool = True
    include_detailed: bool = True


class OutputGenerator:
    """
    Generates output tables from model results.

    This module handles:
    - Summary tables
    - Detailed workforce tables
    - Benefit tables
    - Liability tables
    - Funding tables
    - FRS system summary
    """

    def __init__(self, config: PlanConfig):
        self.config = config
        self.start_year = config.start_year
        self.model_period = config.model_period

    def generate_workforce_summary(
        self,
        workforce_results: Dict[MembershipClass, Dict[str, pd.DataFrame]]
    ) -> pd.DataFrame:
        """
        Generate workforce summary table.

        Args:
            workforce_results: Workforce results by class

        Returns:
            DataFrame with workforce summary by year and class
        """
        rows = []

        for class_name, results in workforce_results.items():
            if 'workforce_active' in results:
                active = results['workforce_active']

                # Summarize by year
                for year in range(self.start_year, self.start_year + self.model_period + 1):
                    year_data = active[active['year'] == year]

                    if len(year_data) > 0:
                        total_active = year_data['n_active'].sum()
                        rows.append({
                            'year': year,
                            'class': class_name.value,
                            'total_active': total_active
                        })

        df = pd.DataFrame(rows)

        # Pivot to wide format
        if len(df) > 0:
            df = df.pivot(index='year', columns='class', values='total_active').fillna(0)
            df['total'] = df.sum(axis=1)

        return df

    def generate_benefit_summary(
        self,
        benefit_results: Dict[MembershipClass, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        Generate benefit summary table.

        Args:
            benefit_results: Benefit calculation results by class

        Returns:
            DataFrame with benefit summary by year and class
        """
        rows = []

        for class_name, benefit_table in benefit_results.items():
            if len(benefit_table) > 0:
                # Summarize by year
                for year in range(self.start_year, self.start_year + self.model_period + 1):
                    year_data = benefit_table[benefit_table['year'] == year]

                    if len(year_data) > 0:
                        total_benefit = year_data['benefit'].sum()
                        total_nc = year_data['normal_cost'].sum()
                        total_pvfb = year_data['pvfb'].sum()
                        total_aal = year_data['accrued_liability'].sum()

                        rows.append({
                            'year': year,
                            'class': class_name.value,
                            'total_benefit': total_benefit,
                            'total_normal_cost': total_nc,
                            'total_pvfb': total_pvfb,
                            'total_aal': total_aal
                        })

        df = pd.DataFrame(rows)

        # Pivot to wide format
        if len(df) > 0:
            for col in ['total_benefit', 'total_normal_cost', 'total_pvfb', 'total_aal']:
                df[col] = df.pivot(index='year', columns='class', values=col).fillna(0)
                df[f'{col}_total'] = df[[col]].sum(axis=1)

        return df

    def generate_liability_summary(
        self,
        liability_results: Dict[MembershipClass, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        Generate liability summary table.

        Args:
            liability_results: Liability calculation results by class

        Returns:
            DataFrame with liability summary by year and class
        """
        rows = []

        for class_name, liability_table in liability_results.items():
            if len(liability_table) > 0:
                # Summarize by year
                for year in range(self.start_year, self.start_year + self.model_period + 1):
                    year_data = liability_table[liability_table['year'] == year]

                    if len(year_data) > 0:
                        total_aal = year_data['total_aal'].iloc[0] if len(year_data) > 0 else 0.0
                        total_aal_legacy = year_data['aal_active_db_legacy'].iloc[0] + year_data['aal_term_db_legacy'].iloc[0] + year_data['aal_retire_db_legacy'].iloc[0] if len(year_data) > 0 else 0.0
                        total_aal_new = year_data['aal_active_db_new'].iloc[0] + year_data['aal_term_db_new'].iloc[0] + year_data['aal_retire_db_new'].iloc[0] if len(year_data) > 0 else 0.0

                        rows.append({
                            'year': year,
                            'class': class_name.value,
                            'total_aal': total_aal,
                            'aal_legacy': total_aal_legacy,
                            'aal_new': total_aal_new
                        })

        df = pd.DataFrame(rows)

        # Pivot to wide format
        if len(df) > 0:
            for col in ['total_aal', 'aal_legacy', 'aal_new']:
                df[col] = df.pivot(index='year', columns='class', values=col).fillna(0)
                df[f'{col}_total'] = df[[col]].sum(axis=1)

        return df

    def generate_funding_summary(
        self,
        funding_results: Dict[MembershipClass, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        Generate funding summary table.

        Args:
            funding_results: Funding calculation results by class

        Returns:
            DataFrame with funding summary by year and class
        """
        rows = []

        for class_name, funding_table in funding_results.items():
            if len(funding_table) > 0:
                # Summarize by year
                for year in range(self.start_year, self.start_year + self.model_period + 1):
                    year_data = funding_table[funding_table['year'] == year]

                    if len(year_data) > 0:
                        total_payroll = year_data['total_payroll'].iloc[0] if len(year_data) > 0 else 0.0
                        total_aal = year_data['total_aal'].iloc[0] if len(year_data) > 0 else 0.0
                        total_ben_payment = year_data['total_ben_payment'].iloc[0] if len(year_data) > 0 else 0.0
                        total_nc = (year_data['nc_legacy'].iloc[0] + year_data['nc_new'].iloc[0]) if len(year_data) > 0 else 0.0

                        rows.append({
                            'year': year,
                            'class': class_name.value,
                            'total_payroll': total_payroll,
                            'total_aal': total_aal,
                            'total_ben_payment': total_ben_payment,
                            'total_normal_cost': total_nc,
                            'funding_ratio': year_data['fr_mva'].iloc[0] if len(year_data) > 0 else 0.0
                        })

        df = pd.DataFrame(rows)

        # Pivot to wide format
        if len(df) > 0:
            for col in ['total_payroll', 'total_aal', 'total_ben_payment', 'total_normal_cost', 'funding_ratio']:
                df[col] = df.pivot(index='year', columns='class', values=col).fillna(0)
                df[f'{col}_total'] = df[[col]].sum(axis=1)

        return df

    def generate_frs_summary(
        self,
        funding_results: Dict[MembershipClass, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        Generate FRS system summary table.

        Args:
            funding_results: Funding calculation results by class

        Returns:
            DataFrame with FRS system summary by year
        """
        rows = []

        # Aggregate across all classes (excluding FRS itself)
        for year in range(self.start_year, self.start_year + self.model_period + 1):
            total_payroll = 0.0
            total_aal = 0.0
            total_ben_payment = 0.0
            total_nc = 0.0
            total_mva = 0.0

            for class_name, funding_table in funding_results.items():
                if class_name != MembershipClass.FRS and len(funding_table) > 0:
                    year_data = funding_table[funding_table['year'] == year]

                    if len(year_data) > 0:
                        total_payroll += year_data['total_payroll'].iloc[0]
                        total_aal += year_data['total_aal'].iloc[0]
                        total_ben_payment += year_data['total_ben_payment'].iloc[0]
                        total_nc += (year_data['nc_legacy'].iloc[0] + year_data['nc_new'].iloc[0])
                        total_mva += year_data['total_mva'].iloc[0]

            funding_ratio = total_mva / total_aal if total_aal > 0 else 0.0

            rows.append({
                'year': year,
                'total_payroll': total_payroll,
                'total_aal': total_aal,
                'total_ben_payment': total_ben_payment,
                'total_normal_cost': total_nc,
                'total_mva': total_mva,
                'funding_ratio': funding_ratio
            })

        return pd.DataFrame(rows)

    def export_to_csv(
        self,
        df: pd.DataFrame,
        output_path: str
    ) -> None:
        """
        Export DataFrame to CSV.

        Args:
            df: DataFrame to export
            output_path: Output file path
        """
        df.to_csv(output_path, index=False)

    def export_to_excel(
        self,
        dfs: Dict[str, pd.DataFrame],
        output_path: str
    ) -> None:
        """
        Export DataFrames to Excel.

        Args:
            dfs: Dictionary of sheet names to DataFrames
            output_path: Output file path
        """
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            for sheet_name, df in dfs.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)

    def export_to_json(
        self,
        data: Dict,
        output_path: str
    ) -> None:
        """
        Export data to JSON.

        Args:
            data: Data to export
            output_path: Output file path
        """
        import json

        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)


def generate_outputs(
    config: PlanConfig,
    workforce_results: Dict[MembershipClass, Dict[str, pd.DataFrame]],
    benefit_results: Dict[MembershipClass, pd.DataFrame],
    liability_results: Dict[MembershipClass, pd.DataFrame],
    funding_results: Dict[MembershipClass, pd.DataFrame],
    output_config: OutputConfig
) -> None:
    """
    Convenience function to generate all outputs.

    Args:
        config: Plan configuration
        workforce_results: Workforce results by class
        benefit_results: Benefit results by class
        liability_results: Liability results by class
        funding_results: Funding results by class
        output_config: Output configuration
    """
    generator = OutputGenerator(config)

    # Generate summaries
    workforce_summary = generator.generate_workforce_summary(workforce_results)
    benefit_summary = generator.generate_benefit_summary(benefit_results)
    liability_summary = generator.generate_liability_summary(liability_results)
    funding_summary = generator.generate_funding_summary(funding_results)
    frs_summary = generator.generate_frs_summary(funding_results)

    # Export based on format
    if output_config.export_format == 'csv':
        generator.export_to_csv(workforce_summary, f"{output_config.output_dir}/workforce_summary.csv")
        generator.export_to_csv(benefit_summary, f"{output_config.output_dir}/benefit_summary.csv")
        generator.export_to_csv(liability_summary, f"{output_config.output_dir}/liability_summary.csv")
        generator.export_to_csv(funding_summary, f"{output_config.output_dir}/funding_summary.csv")
        generator.export_to_csv(frs_summary, f"{output_config.output_dir}/frs_summary.csv")

    elif output_config.export_format == 'excel':
        generator.export_to_excel({
            'Workforce Summary': workforce_summary,
            'Benefit Summary': benefit_summary,
            'Liability Summary': liability_summary,
            'Funding Summary': funding_summary,
            'FRS Summary': frs_summary
        }, f"{output_config.output_dir}/pension_model_outputs.xlsx")

    elif output_config.export_format == 'json':
        import json

        output_data = {
            'workforce_summary': workforce_summary.to_dict(orient='records'),
            'benefit_summary': benefit_summary.to_dict(orient='records'),
            'liability_summary': liability_summary.to_dict(orient='records'),
            'funding_summary': funding_summary.to_dict(orient='records'),
            'frs_summary': frs_summary.to_dict(orient='records')
        }

        generator.export_to_json(output_data, f"{output_config.output_dir}/pension_model_outputs.json")
