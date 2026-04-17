# Narrative Plan Analysis: TXTRS

## Source Set

- `AV_2024`: [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/sources/Texas%20TRS%20Valuation%202024.pdf)
  - cover letter and executive discussion: PDF pp. 1-8
  - plan provisions: Appendix 1, printed pp. 46-57
  - actuarial assumptions and methods: Appendix 2, printed pp. 59-68
- `ACFR_2023`: [Texas TRS ACFR 2023.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/sources/Texas%20TRS%20ACFR%202023.pdf)
  - membership information: printed pp. 14-15
  - actuarial section contents and tables: printed pp. 133-146
  - benefit payments and funded-status discussion in transmittal letter: printed pp. 8-10
- Current runtime contract for comparison:
  - [docs/runtime_input_contract.md](/home/donboyd5/Documents/python_projects/pension_model/docs/runtime_input_contract.md)
  - [plans/txtrs/config/plan_config.json](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs/config/plan_config.json)

## Executive Summary

Texas TRS is an overwhelmingly defined-benefit public pension plan for Texas public education employees, with a single broad member class in the current runtime but multiple benefit cohorts driven by grandfathering and hire/vesting dates. The core benefit is a service retirement annuity equal to 2.3% times years of service times final average salary, with important variation in final-average-salary periods, unreduced retirement eligibility, and early-retirement reductions across cohorts.

For prep purposes, TXTRS looks like a good example of a plan whose reported actuarial structure is richer than a naive age-by-service table model. The reported assumptions and plan provisions strongly support a runtime structure with:

- one main class of active members
- multiple tiers/cohorts
- retirement and early-retirement logic that depends on grandfathering and Rule-of-80 status
- a termination structure that likely depends on years from normal retirement rather than age-and-service alone

The source documents provide strong narrative and actuarial-summary coverage, but they do not obviously provide everything needed for exact stage-3 reconstruction from PDFs alone. The biggest likely gaps are the exact low-level decrement tables needed to reproduce the current runtime inputs byte-for-byte and the plan-specific retiree mortality source. The valuation does publish both a banded active-member age/service grid and a summary new-entrant profile, but the current runtime artifacts are more granular than those published summaries.

## Overall Plan Structure

Based on the 2024 valuation and 2023 ACFR, TXTRS is a statewide public pension trust fund serving employees and retirees of state-supported educational institutions in Texas.

The pension design described in the valuation is a traditional defined-benefit plan:

- service retirement benefit
- disability retirement benefit
- death and survivor benefits
- refund and deferred-vested termination benefits
- optional forms of annuity payment
- historical DROP provisions for a closed legacy population
- partial lump-sum option for eligible retirees

The source documents do not describe the current active plan as a cash-balance or defined-contribution plan. The actual plan described in the valuation is DB-centric.

This is important because the current runtime config includes `benefit_types` of `["db", "cb", "dc"]`, even though the source documents reviewed here present the actual pension trust fund as a DB plan. That looks like a runtime-modeling or scenario/generalization choice rather than a direct description of the current plan as reported.

## Membership Structure

The ACFR membership section reports that, as of August 31, 2023, the pension trust fund had:

- 953,295 active contributing members
- 424,658 inactive non-vested members
- 134,100 inactive vested members
- 489,921 retirement recipients
- 2,001,974 total members

The same ACFR reports 1,350 participating employers in 2023 across school districts, charter schools, colleges, universities, service centers, and related entities.

The runtime currently treats TXTRS as one broad class, `all`. That looks directionally consistent with the source documents, which describe a unified statewide plan rather than distinct actuarial classes like the FRS classes.

However, the valuation clearly indicates multiple benefit cohorts that matter for modeling:

- grandfathered members, defined by status as of August 31, 2005
- members hired on or before August 31, 2007
- members hired after August 31, 2007 who were vested as of August 31, 2014
- members not vested as of August 31, 2014, including later hires

These cohort distinctions materially affect:

- final average salary period
- unreduced retirement eligibility
- early-retirement reduction logic
- retirement behavior after Rule of 80

So the natural modeling structure appears to be:

- one main class
- multiple tiers/cohorts

## Benefit Design Overview

### Core service retirement benefit

The valuation describes the standard annuity as:

- `2.3% * average compensation * years of creditable service`

Average compensation is:

- highest five annual salaries for most members
- highest three annual salaries for grandfathered members

Normal retirement eligibility includes:

- age 65 with at least 5 years of service
- Rule of 80 for older cohorts
- Rule of 80 with minimum age 60 for certain post-2007 hires vested by August 31, 2014
- Rule of 80 with minimum age 62 for members not vested by August 31, 2014

The valuation also notes a minimum annuity floor of:

- greater of the standard annuity or $150 per month

### Early retirement

Early retirement is allowed under combinations of:

- age 55 with at least 5 years of service
- 30 years of service regardless of age
- Rule of 80 for certain post-2007 groups

The reduction structure is cohort-specific:

- a linear 2% per point reduction from age 50 for some pre-2007/30-year cases
- a grandfathered age-by-service reduction table
- 5% per year reductions from age 60 or 62 for later cohorts meeting Rule of 80 or 30 years
- a more severe general age-based reduction table when none of the special conditions apply

This is exactly the kind of plan where prep should preserve actuarial reduction-table structure rather than flattening it away too early.

### Other benefit features

The valuation also describes:

- optional annuity forms
- deferred vested benefits
- refund behavior for terminating vested members
- death and survivor benefits
- disability benefits
- a historical DROP program that is effectively legacy-only because entry had to occur before January 1, 2006
- a partial lump-sum option for eligible unreduced retirees

### COLA

The valuation does not describe a standing automatic COLA for active accruals. It instead discusses ad hoc legislative enhancements, including a 2023 stipend and COLA that were separately funded.

For runtime interpretation, that supports the current config's zero ongoing active COLA with separate treatment for one-time retiree enhancements.

## Funding And Valuation Context

The 2024 actuarial valuation is as of August 31, 2024 and states that its primary purpose is:

- to determine adequacy of statutory contribution rates
- to describe the fund's financial condition
- to analyze changes in that condition

The valuation reports:

- UAAL of $60.6 billion as of August 31, 2024
- funded ratio of 77.8%
- amortization period of 28 years on the smoothed actuarial value of assets

The 2023 ACFR transmittal letter reports for the prior year:

- funded ratio of 77.5%
- UAAL of $57.9 billion
- pension benefit payments totaling $12.7 billion to 489,921 retirees and beneficiaries

Contribution context in the valuation is statutory and phased in:

- member contribution rate at 8.25%
- state base rate rising to 8.25%
- supplemental public education employer contribution rising to 2.00% of capped payroll
- additional retiree-return-to-work contributions

The valuation treats the resulting total contribution stream as sufficient to amortize the UAAL under current assumptions.

This source context maps naturally to runtime funding inputs:

- initial asset/liability and payroll seed data
- statutory contribution-rate components
- asset-smoothing method
- valuation targets used for calibration

## Key Actuarial Assumptions And Tables

The valuation states that the actuarial methods and assumptions are primarily based on an experience study through August 31, 2021 and were adopted July 15, 2022.

### Discount rate and economic assumptions

The valuation reports:

- investment return assumption of 7.00%
- inflation of 2.30%
- real return of 4.70%
- payroll growth of 2.90%

The valuation also appears to use the same 7.00% figure as its liability
discount rate. That equality is common in public-plan valuations, but the two
concepts should still be treated separately in prep and provenance.

### Salary increase assumptions

Appendix 2 reports salary growth as:

- inflation 2.30%
- productivity/general component 0.65%
- merit/promotion/longevity component varying by years of service

The combined salary scale ranges from:

- 8.95% in year 1
- down to 2.95% at 25 years and up

### Mortality

The valuation reports post-retirement mortality based on:

- `2021 TRS of Texas Healthy Pensioner Mortality Tables`
- projected generationally by `Scale UMP 2021`

Disabled-retiree mortality is described as:

- a three-year set-forward of those tables
- with minimum mortality rates of 0.0200 for females and 0.0400 for males

This is notable because the current runtime contract uses `pub_2010_teacher_below_median` plus `mp_2021` in `plan_config.json`, which is not the same description as the valuation's TRS-specific mortality basis. That is a likely source gap or modeling/compatibility issue to investigate in the next pass.

### Retirement assumptions

The valuation provides sample normal and early retirement rates by age and notes important cohort-specific adjustments:

- baseline normal retirement rates by age and sex
- early retirement rates by age
- 10% rate increases for certain post-2007 cohorts once they are beyond Rule of 80 but not yet at the relevant minimum unreduced retirement age

### Disability and other decrement assumptions

The valuation provides:

- disability probabilities by age and service grouping
- narrative treatment of termination, retirement, death, and benefit-election assumptions

The ACFR actuarial section also lists reported tables for:

- post-retirement mortality
- assumed retirement age
- probability of decrement due to disability
- probability of decrement due to death
- probability of decrement due to termination
- salary increase due to merit and promotion
- active member payroll valuation data
- retirees/beneficiaries/disabled participants added to and removed from membership

This is a strong indication that the reported actuarial structure is rich enough to support a principled prep workflow, even if not all low-level canonical inputs are directly published.

## Reported Data Structures That Matter For Prep

From the valuation and ACFR, the most relevant reported structures appear to be:

- member counts by active, inactive vested, inactive non-vested, and retiree status
- retiree and disability distribution summaries
- actuarial present value and cost summaries
- actuarial tables for retirement, disability, death, termination, and salary increase
- active member payroll valuation data
- historical retiree roll activity
- funding context and contribution schedule

These sources are strong for:

- narrative plan analysis
- actuarial assumption capture
- valuation targets
- retiree totals and some distributional information

They appear weak or incomplete for direct stage-3 reconstruction of:

- active salary-by-age-and-service cells
- active headcount-by-age-and-service cells
- entrant profile
- exact canonical termination tables in current runtime format
- exact early-retirement reduction tables in current runtime format
- exact current runtime mortality basis, if that basis differs from the valuation's textual description

## Implications For Runtime Inputs

Based on the source documents, the likely runtime implications are:

- benefit structure should be treated as fundamentally DB for baseline plan representation
- one main member class appears reasonable
- multiple tiers/cohorts are essential
- early-retirement reduction tables are required
- retirement behavior must account for Rule-of-80 cohort differences
- termination assumptions likely need a structure richer than simple age/YOS-only tables
- funding inputs should reflect statutory contribution components and gain/loss asset smoothing
- retiree-population totals and benefit-payment totals are available, but detailed retiree distribution may still need reconstruction or confirmation

There is also a notable interpretive issue:

- the current runtime config includes `db`, `cb`, and `dc` benefit types even though the source documents reviewed here describe the live plan as a DB pension trust fund

That does not mean the runtime config is wrong. It does mean the distinction between:

- actual source-described plan structure
- runtime model capability
- scenario or policy-analysis structure

should be made explicit in the prep workflow.

## Modeling Scope, Exclusions, And Simplifications

TXTRS is a good example of a plan where the main structure is unified, but
there are still some small or special populations that need explicit scope
decisions.

### Included or likely included

- the core DB pension trust fund benefit structure
- one main member class for active members, unless later source work shows a
  material need for a finer class split
- cohort/tier distinctions that materially affect:
  - final average salary period
  - unreduced retirement eligibility
  - early-retirement reductions
  - retirement behavior after Rule of 80
- the major liability-relevant participant groups:
  - active
  - inactive vested
  - inactive nonvested
  - retirees and beneficiaries
  - disability participants

### Excluded or likely excluded from direct modeling

- tiny legacy populations that are not separately material in the published
  sources
- very rare optional-form or election behavior if it is only discussed
  narratively and not published in a way that supports stable canonical inputs
- DC- or CB-style benefit structures as descriptions of the actual current plan,
  unless a later policy-analysis layer requires them

### Approximated or needing explicit simplification decisions

- closed DROP-related legacy effects if the published sources are too sparse to
  support separate canonical treatment
- partial lump-sum option behavior if it affects aggregate reported benefits but
  is not represented as a reusable input table
- detailed retiree age distributions when only summary retiree totals or
  constructed workbook intermediates are available
- entrant profile granularity when the valuation publishes only a banded summary

### Why this matters

For TXTRS, the main risk is not dozens of tiny actuarial classes. It is letting
legacy model intermediates or runtime generalizations quietly expand the scope
beyond what the source-described plan actually is. The prep narrative should
therefore keep a clear record of:

- what is being represented directly from source-described plan structure
- what is being simplified
- what is outside the intended modeled boundary

## Likely Gaps, Judgment Points, And Risks

### Likely gaps

- active salary/headcount cells by age and years of service are not obviously published in the AV or ACFR
- entrant profile is not obviously published in the AV or ACFR
- the exact stage-3 reduction tables used by the current runtime are not obviously published in their canonical machine-readable shape
- exact low-level termination tables may not be published in the same structure as the current runtime inputs

### Judgment points

- how to map the source-described benefit structure, which is DB-centric, to a runtime config that currently advertises `db`, `cb`, and `dc`
- how to represent cohort distinctions cleanly in canonical prep outputs
- whether current runtime mortality inputs reflect the valuation basis directly or a compatibility approximation

### Risks for PDF-to-stage-3 reconstruction

- the PDFs may be sufficient for plan narrative, funding targets, and high-level actuarial assumptions, but not sufficient for exact recovery of all current stage-3 demographic and decrement inputs
- exact stage-3 reproduction may depend on source materials beyond the AV and ACFR, such as internal valuation census extracts, experience-study appendices, or prior actuarial workbooks

## Preliminary Conclusion

TXTRS is a strong candidate for the prep pilot because:

- it is structurally simpler than FRS at the class level
- the AV and ACFR are rich in actuarial explanation
- the plan's benefit tiers/cohorts are legible from the source documents

But the source documents alone may still be insufficient for exact stage-3 reconstruction.

The next source sufficiency pass should therefore focus on a precise mapping between:

- current runtime requirements
- what the TXTRS AV and ACFR actually publish
- what appears to require derivation, judgment, or additional sources
