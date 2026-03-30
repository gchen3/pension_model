"""
Pydantic schemas for data validation.

This module contains Pydantic models for validating
data structures used throughout the pension modeling framework.
"""

from pydantic import BaseModel, Field, field_validator, validator
from typing import Optional, Union, List, Dict
from enum import Enum
from datetime import datetime


class MembershipClass(str, Enum):
    """Membership class types for pension plans."""
    REGULAR = "regular"
    SPECIAL_RISK = "special"
    SPECIAL_RISK_ADMIN = "admin"
    JUDICIAL = "judges"
    ECO = "eco"
    ESO = "eso"
    SENIOR_MANAGEMENT = "senior_management"


class Gender(str, Enum):
    """Gender for actuarial calculations."""
    MALE = "male"
    FEMALE = "female"


class Tier(str, Enum):
    """Benefit tier types."""
    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


class SalaryData(BaseModel):
    """
    Salary data for a membership class.

    Represents salary by years of service and age.
    """
    yos: int = Field(ge=0, description="Years of service")
    age: int = Field(ge=18, description="Age")
    salary: float = Field(gt=0, description="Salary amount")

    class Config:
        validate_assignment = True


class HeadcountData(BaseModel):
    """
    Headcount data for a membership class.

    Represents number of members by years of service and age.
    """
    yos: int = Field(ge=0, description="Years of service")
    age: int = Field(ge=18, description="Age")
    count: int = Field(ge=0, description="Number of members")

    class Config:
        validate_assignment = True


class SalaryHeadcountData(BaseModel):
    """
    Combined salary and headcount data.

    Used for workforce modeling and benefit calculations.
    """
    yos: int = Field(ge=0, description="Years of service")
    age: int = Field(ge=18, description="Age")
    salary: Optional[float] = Field(None, description="Salary amount")
    count: int = Field(ge=0, description="Number of members")
    entry_age: Optional[int] = Field(None, ge=18, description="Entry age")
    entry_salary: Optional[float] = Field(None, gt=0, description="Entry salary")

    class Config:
        validate_assignment = True


class MortalityRate(BaseModel):
    """
    Mortality rate data point.

    Represents probability of death at a given age.
    """
    age: int = Field(ge=0, description="Age")
    qx: float = Field(ge=0, le=1, description="Probability of death")

    class Config:
        validate_assignment = True


class WithdrawalRate(BaseModel):
    """
    Withdrawal (termination) rate data point.

    Represents probability of leaving the plan.
    """
    yos: int = Field(ge=0, description="Years of service")
    age: int = Field(ge=18, description="Age")
    rate: float = Field(ge=0, le=1, description="Withdrawal rate")

    class Config:
        validate_assignment = True


class RetirementEligibility(BaseModel):
    """
    Retirement eligibility data point.

    Defines when members are eligible for retirement.
    """
    yos: int = Field(ge=0, description="Years of service")
    age: int = Field(ge=18, description="Age")
    normal_retirement: bool = Field(description="Eligible for normal retirement")
    early_retirement: bool = Field(description="Eligible for early retirement")
    early_retirement_factor: Optional[float] = Field(None, ge=0, description="Early retirement factor")

    class Config:
        validate_assignment = True


class SalaryGrowthRate(BaseModel):
    """
    Salary growth rate data point.

    Represents salary increase by years of service.
    """
    yos: int = Field(ge=0, description="Years of service")
    growth_rate: float = Field(ge=0, description="Salary growth rate")

    class Config:
        validate_assignment = True


class EntrantProfile(BaseModel):
    """
    New entrant profile data.

    Distribution of new hires by entry age and salary.
    """
    entry_age: int = Field(ge=18, description="Entry age")
    entry_salary: float = Field(gt=0, description="Entry salary")
    entrant_dist: float = Field(ge=0, le=1, description="Distribution proportion")

    class Config:
        validate_assignment = True


class WorkforceData(BaseModel):
    """
    Complete workforce projection data.

    Contains all workforce-related data for a membership class.
    """
    membership_class: MembershipClass = Field(description="Membership class")
    active_population: Optional[Dict] = Field(None, description="Active population by year, age, yos")
    terminations: Optional[Dict] = Field(None, description="Terminations by year, age, yos")
    retirements: Optional[Dict] = Field(None, description="Retirements by year, age, yos")

    class Config:
        validate_assignment = True


class BenefitValuation(BaseModel):
    """
    Benefit valuation data point.

    Used in normal cost and liability calculations.
    """
    entry_age: int = Field(ge=18, description="Entry age")
    age: int = Field(ge=18, description="Current age")
    yos: int = Field(ge=0, description="Years of service")
    year: int = Field(ge=1900, description="Projection year")
    term_year: Optional[int] = Field(None, ge=1900, description="Termination year")
    pvfb: Optional[float] = Field(None, ge=0, description="Present value of future benefits")
    pvfs: Optional[float] = Field(None, ge=0, description="Present value of future service")
    al: Optional[float] = Field(None, ge=0, description="Accrued liability")
    nc: Optional[float] = Field(None, ge=0, description="Normal cost")

    class Config:
        validate_assignment = True


class LiabilityData(BaseModel):
    """
    Liability calculation results.

    Aggregate liability metrics by year.
    """
    year: int = Field(ge=1900, description="Valuation year")
    total_actuarial_liability: float = Field(ge=0, description="Total actuarial liability")
    normal_cost: float = Field(ge=0, description="Normal cost")
    present_value_future_benefits: float = Field(ge=0, description="Present value of future benefits")
    present_value_future_service: float = Field(ge=0, description="Present value of future service")
    accrued_liability: float = Field(ge=0, description="Accrued liability")

    class Config:
        validate_assignment = True


class FundingData(BaseModel):
    """
    Funding calculation results.

    Aggregate funding metrics by year.
    """
    year: int = Field(ge=1900, description="Valuation year")
    required_contribution: float = Field(ge=0, description="Required contribution")
    amortization_payment: float = Field(ge=0, description="Amortization payment")
    funded_ratio: float = Field(ge=0, description="Funded ratio")
    total_unfunded_liability: float = Field(ge=0, description="Total unfunded liability")
    market_value_assets: float = Field(ge=0, description="Market value of assets")
    actuarial_value_assets: float = Field(ge=0, description="Actuarial value of assets")

    class Config:
        validate_assignment = True


class WorkforceProjection(BaseModel):
    """
    Workforce projection result for a single year/age/entry_age combination.

    Used for tracking workforce population through projection period.
    """
    year: int = Field(ge=1900, description="Projection year")
    entry_age: int = Field(ge=18, description="Entry age")
    age: int = Field(ge=18, description="Current age")
    yos: Optional[int] = Field(None, ge=0, description="Years of service")
    n_active: float = Field(ge=0, description="Number of active members")
    n_term: Optional[float] = Field(None, ge=0, description="Number of terminated members")
    n_refund: Optional[float] = Field(None, ge=0, description="Number of refunded members")
    n_retire: Optional[float] = Field(None, ge=0, description="Number of retired members")
    term_year: Optional[int] = Field(None, ge=1900, description="Termination year")
    retire_year: Optional[int] = Field(None, ge=1900, description="Retirement year")

    class Config:
        validate_assignment = True


class LiabilityResult(BaseModel):
    """
    Liability calculation result for a single year.

    Aggregate liability metrics for reporting and validation.
    """
    year: int = Field(ge=1900, description="Valuation year")
    aal: float = Field(ge=0, description="Accrued actuarial liability")
    nc: float = Field(ge=0, description="Normal cost")
    pvfb: float = Field(ge=0, description="Present value of future benefits")
    pvfs: Optional[float] = Field(None, ge=0, description="Present value of future service")
    payroll: Optional[float] = Field(None, ge=0, description="Total payroll")
    nc_rate: Optional[float] = Field(None, ge=0, description="Normal cost rate (NC/payroll)")

    class Config:
        validate_assignment = True


class FundingResult(BaseModel):
    """
    Funding calculation result for a single year.

    Aggregate funding metrics for reporting and validation.
    """
    year: int = Field(ge=1900, description="Valuation year")
    aal: float = Field(ge=0, description="Accrued actuarial liability")
    ava: float = Field(ge=0, description="Actuarial value of assets")
    mva: float = Field(ge=0, description="Market value of assets")
    funded_ratio: Optional[float] = Field(None, ge=0, description="Funded ratio (AVA/AAL)")
    unfunded_liability: Optional[float] = Field(None, description="Unfunded liability (AAL - AVA)")
    required_contribution: Optional[float] = Field(None, ge=0, description="Required contribution")
    amortization_payment: Optional[float] = Field(None, ge=0, description="Amortization payment")

    class Config:
        validate_assignment = True
