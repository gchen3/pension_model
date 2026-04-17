# Narrative Plan Analysis: FRS

## Source Set

- `AV_2022`: [Florida FRS Valuation 2022.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/Florida%20FRS%20Valuation%202022.pdf)
  - executive summary: printed pp. 1-3
  - actuarial methods and assumptions: Appendix A, printed pp. A-3 to A-12
  - plan provisions: Appendix B, printed pp. B-5 to B-17
  - membership data: Appendix C, printed pp. C-4 to C-5
- `ACFR_2023`: [2022-23_ACFR.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/2022-23_ACFR.pdf)
  - plan description: printed pp. 33-35
  - actuarial section overview: printed pp. 140-146
  - active-member and payroll tables: printed pp. 189-191
- `GASB68_2023_TOC`: [2023_GASB68_TOC.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/2023_GASB68_TOC.pdf)
  - supplementary pointer document only; not needed for the main narrative
- Current runtime contract for comparison:
  - [docs/runtime_input_contract.md](/home/donboyd5/Documents/python_projects/pension_model/docs/runtime_input_contract.md)
  - [plans/frs/config/plan_config.json](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/config/plan_config.json)

## Executive Summary

Florida Retirement System is not just a standalone DB plan. The source documents describe an integrated retirement system in which the FRS Pension Plan is the defined-benefit leg and the FRS Investment Plan is a defined-contribution alternative, with blended employer rates and class-specific rules layered on top. Within the Pension Plan, the main structural features are:

- multiple membership classes
- at least two major tiers keyed to initial enrollment before or on/after July 1, 2011
- class-specific benefit multipliers and retirement eligibility
- a substantial DROP overlay
- a mix of DB-only and system-wide reporting depending on the document and table

For prep, FRS looks like a strong source case for understanding plan structure and many actuarial tables directly from the PDFs. It also looks like a case where exact stage-3 reconstruction will require careful scope control, because some reported tables are Pension-Plan-only while others combine Pension Plan and Investment Plan membership, and because the current runtime appears to encode plan-choice and class-detail logic that is not all stated in one place in the PDFs.

## Overall Plan Structure

The 2022 actuarial valuation is explicitly a valuation of the defined-benefit FRS Pension Plan. Its stated purpose is to determine Pension Plan-specific employer contribution rates for the July 1, 2023 through June 30, 2024 plan year, which are then blended with FRS Investment Plan contribution rates to form proposed statutory employer rates.

The ACFR confirms the broader system structure:

- FRS Pension Plan is the main defined-benefit plan
- FRS Investment Plan is an integrated defined-contribution alternative within FRS
- additional non-integrated optional DC arrangements exist for some university and senior-management populations, but those are outside the core FRS Pension Plan runtime target

So the natural source-facing description is:

- FRS as a system is DB plus DC choice
- the valuation target for this repo is the DB Pension Plan, with some runtime inputs reflecting the interaction with the DC alternative
- DROP is a major overlay on the Pension Plan rather than a separate plan

## Membership Structure

The ACFR plan-description section defines five membership classes:

- Regular Class
- Senior Management Service Class
- Special Risk Class
- Special Risk Administrative Support Class
- Elected Officers' Class

The valuation and benefit rules further split Elected Officers' Class service into:

- judicial
- legislative/attorney/cabinet
- local

That subdivision matches the current runtime more closely than the ACFR's broader five-class summary.

The most important tier split is initial enrollment:

- members initially enrolled before July 1, 2011
- members initially enrolled on or after July 1, 2011

This split changes vesting, final-average-compensation period, retirement eligibility, and COLA treatment. The current runtime's `tier_1` and `tier_2` are therefore source-grounded. The runtime's `tier_3` looks more like a forward-looking modeling construct than a directly reported source tier.

The source documents report membership at different scopes.

The ACFR's June 30, 2023 active-member table is system-wide and includes both Pension Plan and Investment Plan members plus renewed membership. It reports:

- 550,931 FRS Regular active members
- 7,714 Senior Management Service
- 75,495 Special Risk
- 93 Special Risk Administrative Support
- 2,105 Elected Officers'
- 646,277 total active members

The 2022 valuation's Appendix C reports DB-plan membership only as of July 1, 2022. It shows active DB members of:

- 372,907 Regular
- 5,123 Senior Management Service
- 63,237 Special Risk
- 77 Special Risk Administrative
- 669 EOC judicial
- 88 EOC legislative/attorney/cabinet
- 656 EOC local
- 442,762 total active DB members

The same valuation reports annuitants and potential annuitants at July 1, 2022 of:

- 393,308 annuitants and 97,836 potential annuitants in Regular
- 41,696 annuitants and 5,588 potential annuitants in Special Risk
- 443,654 annuitants and 105,041 potential annuitants in total

It also reports 32,150 DROP members with annual benefits of $1.060 billion, stated in thousands.

This difference in scope matters immediately for prep: some source tables are ideal for building Pension-Plan runtime inputs, while others are better treated as system-level reasonableness checks.

## Benefit Design Overview

### Core DB formula

The Pension Plan benefit is built from:

- average final compensation
- years of creditable service
- class-specific benefit percentages

Average final compensation is:

- highest five fiscal years for members initially enrolled before July 1, 2011
- highest eight fiscal years for members initially enrolled on or after July 1, 2011

The main class-specific multipliers reported in the valuation and ACFR are:

- Regular: 1.60% to 1.68% depending on retirement age/service combination
- Special Risk: 2.00% for service from December 1, 1970 through September 30, 1974, then 3.00%
- Special Risk Administrative Support: 1.60% to 1.68% with special-risk-service-based eligibility rules
- Elected Officers' Class: 3.00%, except 3.33% for judicial service
- Senior Management Service: 2.00%

### Normal retirement and vesting

For Regular, Senior Management, and Elected Officers' members:

- pre-July 1, 2011 entrants: age 62 with 6 years, or 30 years of service
- on/after July 1, 2011 entrants: age 65 with 8 years, or 33 years of service

For Special Risk:

- pre-July 1, 2011 entrants: age 55 with 6 years of special-risk service, or 25 years of special-risk service
- on/after July 1, 2011 entrants: age 60 with 8 years of special-risk service, or 30 years of special-risk service

Special Risk Administrative Support uses the Special Risk rules only when the member has enough Special Risk service for vesting; otherwise Regular-Class rules apply.

Vesting is:

- 6 years for members initially enrolled before July 1, 2011
- 8 years for members initially enrolled on or after July 1, 2011

### Early retirement, refunds, and survivor/disability features

Early retirement is available after vesting, with a reduction of 5/12 of 1% for each month before the class- and tier-specific normal retirement age:

- age 55 or 60 benchmark for Special Risk, depending on tier
- age 62 or 65 benchmark for other classes, depending on tier

The plan also includes:

- refund of employee contributions, with no interest
- non-duty and line-of-duty disability benefits
- pre-retirement death benefits, including richer line-of-duty benefits for Special Risk
- optional annuity forms at retirement

### COLA and DROP

COLA treatment is materially tier-sensitive:

- members who retired before July 1, 2011 receive 3% annual post-retirement increases
- Tier II members receive no post-retirement increase
- Tier I members retiring after July 1, 2011 receive a prorated 3% COLA based on service earned through June 30, 2011

DROP is a major feature, not an edge case. The valuation's plan-provision appendix describes:

- class- and tier-specific DROP entry windows
- standard maximum participation of 60 months
- special extensions for some instructional personnel
- 2022 law-enforcement extension for certain Special Risk members
- 6.5% annual DROP interest for entrants before July 1, 2011
- 1.3% annual DROP interest for later entrants

That source structure supports the current runtime's explicit DROP handling.

## Funding And Valuation Context

The pilot valuation is dated July 1, 2022. Its stated purpose is funding, not accounting. It determines actuarially calculated Pension Plan employer rates before blending with Investment Plan rates.

The valuation reports:

- individual entry age normal cost method
- actuarial asset smoothing with 20% recognition of gains/losses each year
- AVA corridor of 80% to 120% of market value
- inflation assumption of 2.40%
- aggregate payroll growth assumption of 3.25%
- investment return assumption of 6.70%

The ACFR's 2023 actuarial statement confirms that the system also has separate GASB calculations and that the same 6.70% return assumption was used for those 2023 funding and GASB calculations.

This matters for prep because the source world includes at least three related but distinct numerical frames:

- funding valuation figures
- GASB / accounting figures
- broader ACFR system totals that may include the Investment Plan or other state-administered systems

The AV should therefore remain the authoritative source for Pension-Plan funding inputs, with ACFR tables used carefully for reconciliation, context, and some membership/payroll detail.

## Key Actuarial Assumptions And Tables

The valuation's Appendix A reports a detailed actuarial basis rather than a short narrative summary.

### Economic assumptions

The 2022 funding valuation uses:

- inflation: 2.40%
- payroll growth: 3.25%
- investment return: 6.70%

### Mortality

FRS mortality is source-rich and clearly segmented. The valuation uses PUB-2010 base tables with gender-specific MP-2018 improvement for healthy inactive and healthy active mortality, but the exact base-table mapping depends on member category, including:

- K-12 instructional personnel
- Special Risk members
- other general members

Disabled mortality uses separate PUB-2010 disabled-retiree mappings without mortality improvement projection. This is a good example of where runtime mortality inputs may need category mapping rather than a single plan-wide mortality table.

### Retirement, disability, withdrawal, and salary assumptions

Appendix A provides explicit retirement tables by:

- tier
- class
- sex
- K-12 instructional status
- law-enforcement subset within Special Risk

It also provides:

- line-of-duty and non-duty disability rates by age and broad class group
- withdrawal tables by age and years of service, separately for regular and special-risk groupings
- assumptions about time in DROP
- individual member salary increase assumptions that vary by service and membership class

The practical implication is that FRS source assumptions are already more structured than a simple one-table-per-decrement abstraction.

## Reported Data Structures That Matter For Prep

FRS source documents appear unusually strong for published tabular detail.

The valuation provides:

- active DB member counts, salaries, and accumulated contributions by class
- annuitants and potential annuitants by class
- DROP membership and annual benefits
- class-specific active-member age-by-service tables, starting with Regular in Appendix C
- detailed decrement and mortality assumption tables
- funding seed values such as liabilities, assets, and contribution rates by class

The ACFR provides:

- system-wide active-member counts by class
- annual payroll by class
- DROP participant counts and accrued benefits
- total annuitants and related retiree tables
- broader actuarial and accounting context

The important caution is that the ACFR's membership tables often operate at a broader scope than the valuation:

- they can include both Pension Plan and Investment Plan members
- they may aggregate Elected Officers more heavily than the valuation does
- they follow June 30 fiscal-year timing, whereas the funding valuation is as of July 1

So the PDFs appear strong enough to support a serious PDF-to-stage-3 attempt, but they will require explicit table-by-table scope tagging.

## Implications For Runtime Inputs

The main runtime implications are:

- `benefit_types` likely need to preserve the DB-plus-DC-choice structure for FRS as a system, even though the actuarial valuation itself is DB-focused
- classes should likely remain more granular than the ACFR's broad five-class summary, because the valuation and runtime both distinguish EOC subgroups and Special Risk Administrative Support
- at least two source-grounded tiers are required: pre- and post-July 1, 2011
- benefit multipliers, retirement eligibility, early-retirement reduction, COLA treatment, and DROP logic all need class- and tier-aware inputs
- mortality and retirement assumptions likely require category mappings rather than one uniform table per decrement

The source documents also suggest an important runtime boundary question for later review: some current runtime items appear to encode system-design and plan-choice behavior, not just Pension-Plan valuation inputs. FRS is a plan where that distinction should be made explicit early.

## Modeling Scope, Exclusions, And Simplifications

The FRS source world is broader than the core DB runtime target, so the modeled
boundary should be explicit.

### Included or likely included

- the FRS Pension Plan defined-benefit leg as the core liability and funding
  target
- the main valuation/runtime classes:
  - Regular
  - Special Risk
  - Special Risk Administrative Support
  - Senior Management Service
  - Elected Officers' subclasses where materially needed
- the major tier split around July 1, 2011
- major benefit features that clearly affect liability and cash-flow structure:
  - final average salary periods
  - vesting
  - normal and early retirement eligibility
  - class-specific multipliers
  - DROP
  - major mortality, retirement, withdrawal, disability, and salary
    assumptions

### Excluded or likely excluded from direct modeling

- optional DC arrangements outside the core Pension Plan target
- very small residual systems or groups such as TRS and IFAS rows when they are
  present only as bookkeeping or immaterial tails in the valuation
- fine statutory detail that does not materially affect canonical runtime inputs
- administrative corner cases that are not separately reported and are too rare
  to parameterize defensibly

### Approximated or needing explicit simplification decisions

- system-level Pension Plan versus Investment Plan choice behavior when source
  reporting is broader than the DB valuation target
- Elected Officers' treatment when some source tables are grouped and others are
  subclassed
- any small subclasses or rare benefit elections that are not separately
  published in a reusable way
- retiree-distribution age smoothing if the reviewed runtime artifact preserves
  a legacy constructed distribution rather than a direct source table

### Why this matters

FRS is a plan where some details are real but may still be too small or too
indirectly reported to model separately. The prep record should therefore make
clear whether a detail is:

- included directly
- deliberately excluded
- folded into a broader class
- approximated because the sources do not support separate canonical treatment

## Likely Gaps, Judgment Points, And Risks

The main likely issues are:

- exact stage-3 reproduction will need careful handling of mixed-scope source tables, because some ACFR counts include both Pension Plan and Investment Plan members while the valuation's Appendix C is DB-only
- plan-choice behavior between the Pension Plan and Investment Plan, including default-election effects and renewed membership rules, may not be fully recoverable from the AV and ACFR alone
- some current runtime quantities appear derived from ACFR cash-flow tables rather than directly reported as Pension-Plan-only values
- the current runtime's class and mortality mappings should be checked against the valuation's more specific actuarial categories before building extraction routines
- the FRS source set is strong on reported structure, but exact byte-for-byte stage-3 reconstruction will still depend on explicit rules for scope, units, dates, and derivations
