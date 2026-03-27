"""
Pension Output Module

Output generation and export functionality for pension model results.

This module provides:
- Output generators for summaries and detailed tables
- Export to CSV, Excel, and JSON formats
"""

from .generators import (
    OutputGenerator,
    OutputConfig,
    generate_outputs
)

__all__ = [
    'OutputGenerator',
    'OutputConfig',
    'generate_outputs'
]
