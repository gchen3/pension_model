# TXTRS Mortality Mapping Notes

## Purpose

This note records the current understanding of TXTRS mortality sourcing and the
current mismatch between the valuation’s stated basis and the current runtime
mortality artifacts.

## Source-Stated Basis

Source:

- [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/sources/Texas%20TRS%20Valuation%202024.pdf)
  - Appendix 2, printed pp. 59 to 64

The valuation states:

- active mortality:
  `PUB(2010), Amount-Weighted, Below-Median Income, Teacher, Male and Female`
  with a 2-year set forward for male, projected generationally by MP-2021
- post-retirement mortality:
  `2021 TRS of Texas Healthy Pensioner Mortality Tables`, projected on a fully
  generational basis by `Scale UMP 2021`, with immediate convergence
- disabled retiree mortality:
  a 3-year set forward of the healthy-pensioner tables, with minimum mortality
  rates of 0.0200 for females and 0.0400 for males

## What This Means Structurally

The valuation does **not** describe one single mortality basis for all member
states.

Instead, it uses different source families for:

- active mortality
- healthy retiree mortality
- disabled retiree mortality

That matters for prep because the current runtime contract talks in terms of one
base-table label plus one improvement scale.

## Shared External References Currently In Hand

Available shared references under
[prep/common/sources](/home/donboyd5/Documents/python_projects/pension_model/prep/common/sources):

- `soa_pub2010_amount_mort_rates.xlsx`
- `soa_mp2021_rates.xlsx`
- related SOA report PDFs

These help with the active-mortality part of TXTRS, because the valuation’s
active basis is clearly in the Pub-2010 / MP-2021 family.

## Remaining External Gap

The main missing source is still plan-specific:

- `2021 TRS of Texas Healthy Pensioner Mortality Tables`

The valuation names that basis, but the full table values are not yet in hand in
the repo.

A workspace search in the current repo found:

- shared SOA Pub-2010 and MP-2021 workbooks
- no local copy of the `2021 TRS of Texas Healthy Pensioner Mortality Tables`
  under `prep/`, `plans/`, `scripts/`, or `R_model/`

There is also still an interpretation gap:

- whether `Scale UMP 2021` can be treated as the shared SOA MP-2021 workbook,
  or whether it requires some modified or ultimate-rate form of MP-2021

Until those points are resolved, TXTRS retiree mortality should remain
explicitly classified as `referenced_not_published`.

## Current Runtime Representation

Current runtime TXTRS config:

- [plans/txtrs/config/plan_config.json](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs/config/plan_config.json)

Current runtime mortality settings:

- `base_table = pub_2010_teacher_below_median`
- `improvement_scale = mp_2021`
- `male_mp_forward_shift = 2`

Current runtime base-rate file contains only one table label:

- `teacher_below_median`

But the current runtime base-rate file does still distinguish:

- `member_type = employee`
- `member_type = retiree`

So the stage-3 representation is not using one identical `qx` curve for all
statuses. Instead, it stores separate employee and retiree rates under one
shared Pub-2010-derived table family label.

## How Current Stage-3 Mortality Was Built

The legacy conversion script is explicit:

- [scripts/build/convert_txtrs_to_stage3.py](/home/donboyd5/Documents/python_projects/pension_model/scripts/build/convert_txtrs_to_stage3.py)

It builds current stage-3 mortality from:

- `PubT-2010(B)` for both `employee` and `retiree` base rates
- MP-2021 for improvement

The shared loader confirms why this works:

- the SOA `PubT-2010(B)` sheet itself contains both:
  - `Employee`
  - `Healthy Retiree`
    columns for female and male
- the conversion path reads those into:
  - `employee_female`
  - `employee_male`
  - `healthy_retiree_female`
  - `healthy_retiree_male`
- then writes them to runtime `base_rates.csv` as:
  - `member_type = employee`
  - `member_type = retiree`

Representative examples from the current runtime artifact:

- age `40`:
  - employee and retiree rates are the same
- age `60`:
  - female employee `0.00204`, female retiree `0.00344`
  - male employee `0.00357`, male retiree `0.00491`
- age `80`:
  - female employee `0.02318`, female retiree `0.02895`
  - male employee `0.02874`, male retiree `0.04198`

So the current reviewed runtime mortality artifact is clearly a compatibility
construction, not a direct transcription of the valuation’s full stated basis.

There is also evidence of an older competing legacy path:

- the retained workbook `Mortality Rates` sheet contains
  `RP_2014_employee_*` and `RP_2014_ann_employee_*` columns
- the archived script
  [TxTRS_R_BModel revised.R](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_txtrs/TxTRS_R_BModel%20revised.R)
  builds mortality from those workbook RP-2014 columns
- the currently reviewed stage-3 path does **not** use that workbook RP-2014
  path; it uses external Pub-2010 and MP-2021 files instead

That is useful because it shows the retained TXTRS materials contain more than
one historical mortality implementation path.

One further implementation clue is now clear:

- the current active Pub-2010 / MP-2021 path in
  [TxTRS_model_inputs.R](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_txtrs/TxTRS_model_inputs.R)
  shifts male MP rates forward two years and then applies the observed MP
  schedule through the available years, using the ultimate column only after
  the final published year
- the archived
  [TxTRS_R_BModel revised.R](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_txtrs/TxTRS_R_BModel%20revised.R)
  contains a commented note saying:
  - `Since the plan assumes "immediate convergence" of MP rates, the "ultimate rates" are used for all years`

So the retained TXTRS materials preserve at least two different interpretations
of the improvement-scale implementation:

- current active path: MP schedule by year, then ultimate after the horizon
- older archived path: immediate convergence via ultimate rates for all years

## Main Alignment Findings

### What aligns

- active mortality is at least directionally aligned with the valuation
  description:
  Pub-2010 teacher below-median with male set-forward and MP-2021-style
  improvement
- the current runtime `male_mp_forward_shift = 2` is consistent with the active
  mortality text in the valuation

### What does not align cleanly

- the valuation’s retiree mortality basis is plan-specific, not Pub-2010 teacher
- the valuation describes disabled-retiree mortality as a modified version of
  the healthy-pensioner basis with explicit minimum rates
- current runtime uses one base-table family for both active and retiree rates
- current runtime labels the basis as `pub_2010_teacher_below_median`, which is
  too coarse to express that active and retiree rates may come from different
  source families in a source-faithful build
- the valuation explicitly says retiree mortality uses `Scale UMP 2021` with
  `immediate convergence`, while the current active compatibility path does not
  obviously implement that same immediate-convergence rule

## Sample-Rate Comparison Against The Valuation

The valuation publishes specimen mortality rates for `2023` and `2053`.

When the current runtime mortality files are resolved through the project’s
current mortality builder, the resulting rates are broadly similar in shape but
not an exact match to the valuation samples.

Examples:

- active mortality, `2023`
  - valuation average of male/female samples at age `40` ≈ `0.000448`
  - current runtime resolved active rate at age `40` ≈ `0.000640`
  - valuation average at age `80` ≈ `0.028227`
  - current runtime resolved active rate at age `80` ≈ `0.023427`
- retiree mortality, `2023`
  - valuation average at age `60` ≈ `0.005017`
  - current runtime resolved retiree rate at age `60` ≈ `0.004230`
  - valuation average at age `90` ≈ `0.134628`
  - current runtime resolved retiree rate at age `90` ≈ `0.113733`
- retiree mortality, `2053`
  - valuation average at age `60` ≈ `0.003337`
  - current runtime resolved retiree rate at age `60` ≈ `0.002873`
  - valuation average at age `100` ≈ `0.316601`
  - current runtime resolved retiree rate at age `100` ≈ `0.266556`

These comparisons are not perfect apples-to-apples because the runtime model is
sex-neutral after averaging male and female rates, while the valuation samples
are published separately by sex. But they are still useful evidence that the
current runtime mortality is not a verbatim implementation of the valuation’s
stated basis.

## Implication For Prep

For TXTRS, mortality is the clearest current example of a real source gap.

The current runtime files can be reproduced from external Pub-2010 and MP-2021
references, but that does not prove they are source-faithful to the valuation’s
retiree mortality basis.

So the prep workflow should explicitly distinguish:

1. exact reproduction of the current reviewed stage-3 mortality files
2. exact reconstruction of the valuation’s stated mortality basis

Those are not yet the same problem.

## Early Runtime-Contract Question

TXTRS mortality is strong evidence that the current runtime mortality contract
may be too coarse for source-first prep in some plans.

The key issue is not file format. It is semantics:

- one runtime base-table label may cover different source families for active
  and retiree mortality

That does not force a contract change now, but it should be part of the early
runtime contract review.

## Current Working Conclusion

For TXTRS:

- active mortality can probably be tied to shared Pub-2010 and MP-2021
  references
- retiree mortality still needs a plan-specific external source
- current stage-3 mortality appears to be a compatibility approximation rather
  than a complete expression of the valuation’s stated basis

Related Reason-era implementation clues are tracked in:

- [reason_artifact_clues.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/reports/reason_artifact_clues.md)
