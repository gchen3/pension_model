# Narrative Plan Analysis: TXTRS-AV

## 1. Plan Identity And Source Set

- plan name: `txtrs-av`
- intended role: fresh AV-first onboarding of Texas TRS
- valuation year: `2024`
- primary source currently copied into the new plan area:
  - `AV_2024`: [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/sources/Texas%20TRS%20Valuation%202024.pdf)
- supporting shared references expected to matter later:
  - AV-named mortality tables and scales
- auxiliary documents expected to matter later:
  - TXTRS ACFR for reconciliation or estimation support when the AV is not enough

This narrative is intentionally AV-first. It uses the current TXTRS pilot notes
as context, but the source claim for `txtrs-av` should be grounded in the copied
valuation and any AV-referenced external materials brought in later.

## 2. Executive Summary

`txtrs-av` looks like a strong candidate for a controlled first-cut onboarding.
The valuation supports a single broad active-member class with multiple benefit
cohorts driven by grandfathering, hire timing, and vesting status. The core
plan is DB-centric, with strong valuation coverage for benefit provisions,
active-member structure, early-retirement reduction logic, salary assumptions,
and funding targets.

The first-cut prep path should stay close to the valuation and should not
silently inherit every current `txtrs` runtime abstraction. In particular:

- active grid and entrant profile appear source-grounded and buildable from the
  valuation
- funding seed values appear directly mappable from valuation tables
- retiree mortality remains blocked by missing plan-specific external source
  material
- retiree distribution remains unresolved as a clean PDF-only build path

So the right first-cut stance is:

- build what is clearly supported by the valuation
- classify compatibility artifacts explicitly
- leave unresolved mortality and retiree-distribution details visible rather
  than burying them in copied runtime files

## 3. Overall Plan Structure

The 2024 valuation describes Texas TRS as a traditional public defined-benefit
retirement system for public education employees in Texas.

High-level structure visible in the valuation:

- service retirement annuity
- disability retirement benefits
- death and survivor benefits
- deferred vested termination benefits
- refund-of-contributions behavior
- optional annuity forms
- partial lump-sum option for eligible retirees
- closed historical DROP population

For `txtrs-av`, the working first-cut interpretation should be:

- model the plan as DB-centric
- preserve cohort and reduction logic that the valuation actually describes
- do not assume that every broader runtime benefit-leg abstraction in the
  current `txtrs` config is source-direct

## 4. Membership Structure

The valuation indicates one broad active-member population rather than multiple
FRS-style actuarial classes. That supports a first-cut runtime class structure
of:

- classes: `all`

But the plan still has important internal cohort structure. The valuation
supports at least:

- grandfathered members with earlier benefit treatment
- intermediate cohorts
- current cohorts with later retirement and reduction treatment
- active members
- retired members and beneficiaries
- inactive vested and inactive nonvested populations in summary reporting

High-value member counts directly visible in the valuation include:

- active contributing members not in DROP: `970,872`
- active members including DROP: `970,874`
- retired members and beneficiaries: `508,701`

Natural first-cut modeling implication:

- one main class
- multiple tiers/cohorts
- explicit retiree population handling
- no need to invent extra classes unless later source evidence requires them

## 5. Benefit Design Overview

The core benefit formula remains strongly source-supported:

- multiplier of `2.3%`
- benefit based on years of service and final average salary
- standard FAS period of `5` years for most members
- `3`-year FAS treatment for grandfathered members
- vesting after `5` years
- cohort-specific normal and early retirement rules
- cohort-specific early-retirement reductions, including table-based and
  formula-based treatment
- minimum monthly annuity of `$150`

Important first-cut implications:

- tier objects will be needed
- table-based reduction inputs will be needed
- refund behavior matters conceptually, but a first-cut runtime may not need
  every historical nuance immediately
- the closed DROP population should be documented, but may remain out of first-
  cut active scope if the valuation exposure is trivial

## 6. Funding And Valuation Context

The valuation date is `2024-08-31`.

The valuation clearly supports key funding anchors needed for runtime seed data:

- gross normal cost
- actuarial accrued liability
- covered payroll
- actuarial and market value of assets
- benefit payments
- statutory contribution context

This is a good fit for a first-cut `init_funding.csv` build driven directly by
valuation tables rather than ACFR headline summaries.

Current working assumption for `txtrs-av`:

- year-0 funding anchors should default to the valuation basis
- calibration remains computed, not document-sourced
- any runtime-only funding settings should be called out as such

## 7. Key Actuarial Assumptions And Tables

The valuation appears strong on the assumptions that matter for first-cut prep:

- discount rate: `7.00%`
- investment return assumption: `7.00%`
- inflation: `2.30%`
- payroll growth: `2.90%`
- salary growth: inflation plus service-related merit scale
- retirement assumptions: cohort-sensitive and more detailed than a naive flat
  table
- termination assumptions: reported in the assumptions appendix
- mortality:
  - active mortality tied to Pub-2010 teacher below-median treatment with male
    set-forward and MP-2021-style improvement
  - post-retirement mortality tied to `2021 TRS of Texas Healthy Pensioner
    Mortality Tables` and `Scale UMP 2021`

The mortality implication is the main caution point:

- basis names are visible
- full source-faithful retiree mortality inputs are not yet in hand

## 8. Reported Data Structures That Matter For Prep

High-value valuation structures include:

- Table 2 `Summary of Cost Items`
- Table 3b `Calculation of Covered Payroll`
- Table 8a `Change in Plan Net Assets`
- Table 17 `Distribution of Active Members by Age and by Years of Service`
- Appendix 2 `NEW ENTRANT PROFILE`
- Appendix 2 assumption tables and mortality descriptions

The strongest current source-to-runtime candidates are:

- active headcount and salary grid from Table 17 after canonicalization
- entrant profile from the published summary table after the reviewed
  boundary-merge transform
- funding seed values from Tables 2, 3b, and 8a
- tier and reduction logic from plan provisions and assumptions appendices

The weakest current candidates are:

- retiree distribution in exact runtime age-by-age form
- full source-faithful retiree mortality tables

## 9. Implications For Runtime Inputs

Likely first-cut runtime implications:

- likely classes: one class, `all`
- likely tiers: multiple cohort objects
- likely decrement structure: shared tables with tier-sensitive retirement and
  reduction logic
- likely mortality structure: active path can likely be built from AV-stated
  basis plus AV-referenced external tables; retiree path remains blocked
- likely funding input shape: one-row seed file plus statutory-rate structure
- likely entrant profile: explicit artifact, not inferred

Working rule for `txtrs-av`:

- prefer AV-supported plan shape first
- only carry forward current `txtrs` runtime-only settings after explicit
  classification

## 10. Modeling Scope, Exclusions, And Simplifications

First-cut scope should include:

- main DB plan structure
- one broad class
- multiple cohorts/tiers
- valuation-based funding seed values
- source-grounded active grid
- source-grounded entrant profile
- source-grounded reduction logic where directly available

First-cut items that may remain provisional or deferred:

- exact source-faithful retiree mortality implementation
- exact source-faithful retiree age distribution
- any runtime abstraction that goes beyond what the valuation clearly supports

This is intentional. The first cut should be usable and reviewable before it is
exhaustive.
