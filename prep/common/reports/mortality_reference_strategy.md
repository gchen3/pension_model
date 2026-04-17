# Mortality Reference Strategy

## Purpose

This note records the emerging shared strategy for mortality source handling in
the prep workflow.

Mortality is the clearest current example of a source area where:

- the actuarial valuation often names the basis precisely
- the plan PDFs do not reproduce the full rate tables needed by runtime
- external shared reference materials are therefore part of the reproducibility
  package

## Three Distinct Layers

Mortality prep should keep three layers distinct:

1. source-stated basis
2. shared external reference tables
3. built canonical runtime mortality artifacts

Those are not interchangeable.

### 1. Source-stated basis

Examples:

- FRS Appendix A names specific Pub-2010 variants and MP-2018
- TXTRS Appendix 2 names `2021 TRS of Texas Healthy Pensioner Mortality Tables`
  and `Scale UMP 2021`

This layer answers:

- what mortality basis the plan says it is using
- which member categories use which table families
- what set-forward or set-back adjustments apply
- whether active, healthy retiree, and disabled-retiree mortality use the same
  or different basis

### 2. Shared external reference tables

Examples now stored under
[prep/common/sources](/home/donboyd5/Documents/python_projects/pension_model/prep/common/sources):

- `soa_pub2010_report.pdf`
- `soa_pub2010_amount_mort_rates.xlsx`
- `soa_pub2010_headcount_mort_rates.xlsx`
- `soa_mp2018_report.pdf`
- `soa_mp2018_rates.xlsx`
- `soa_mp2021_report.pdf`
- `soa_mp2021_rates.xlsx`

This layer answers:

- where the actual standard-table rate values come from
- which official workbook/sheet provides the rate values
- which shared references are available across plans

### 3. Built canonical runtime mortality artifacts

Current runtime expects:

- `plans/{plan}/data/mortality/base_rates.csv`
- `plans/{plan}/data/mortality/improvement_scale.csv`

These are build outputs, not raw sources.

They should be treated as:

- normalized, reproducible runtime artifacts
- built from source-stated mortality basis plus approved external references

## Shared References Currently In Hand

The following shared references are now available locally and registered in
[prep/common/source_registry.csv](/home/donboyd5/Documents/python_projects/pension_model/prep/common/source_registry.csv):

- Pub-2010 report PDF
- Pub-2010 amount-weighted rate workbook
- Pub-2010 headcount-weighted rate workbook
- MP-2018 report and rates workbook
- MP-2021 report and rates workbook

These are enough to support a serious FRS mortality reconstruction pass.

They are **not** yet enough to close TXTRS, because TXTRS names a plan-specific
healthy-pensioner table basis in its valuation.

## Plan-Level Implications

### FRS

FRS appears to require shared external references for exact mortality
reconstruction:

- Pub-2010 variants
- MP-2018 improvement rates

The valuation specifies a richer mapping than the current runtime contract uses.
It distinguishes at least:

- K-12 instructional personnel
- special risk
- other members
- disabled special risk
- disabled non-special-risk

And it mixes:

- headcount-weighted tables
- amount-weighted or benefits-weighted below-median tables
- set-forward and set-back adjustments
- improvement for healthy active and healthy inactive mortality
- no improvement for disabled mortality

So for FRS, the external SOA references are part of the actual reproducibility
package, not optional background.

### TXTRS

TXTRS is different.

The current runtime contract uses a Pub-2010 teacher table plus MP-2021, but
the valuation text says:

- active mortality: Pub(2010), amount-weighted, below-median income, teacher
  table, projected by MP-2021
- post-retirement mortality: `2021 TRS of Texas Healthy Pensioner Mortality
  Tables`, projected by `Scale UMP 2021`

That means the shared MP-2021 reference is useful now, but the shared SOA files
do not yet close the full TXTRS source basis.

## Canonical Build Rule

The prep workflow should build canonical mortality artifacts as follows:

1. record the plan-stated basis and category mapping from the valuation
2. identify which rate values are present in plan documents and which require
   approved external references
3. load the external reference values from shared sources
4. apply documented set-forward, set-back, and category-combination rules
5. build canonical `base_rates.csv` and `improvement_scale.csv`
6. validate that the built artifacts match the current reviewed stage-3 files
   for the pilot plans

## Pressure On The Current Runtime Contract

Mortality is the strongest current candidate for early contract review.

Reasons:

- current runtime mortality labels mix source meaning and runtime lookup meaning
- FRS source mortality categories are richer than the current class-to-table map
- TXTRS source text uses different active and retiree basis families
- set-forward and set-back adjustments are source-important and need explicit
  handling rules

This does **not** automatically mean the runtime contract must change now. It
does mean we should use mortality as a concrete test case in the early runtime
contract review.

## Remaining Source Gaps

The main remaining mortality source gaps are:

- the plan-specific `2021 TRS of Texas Healthy Pensioner Mortality Tables`
- confirmation of how `Scale UMP 2021` should be operationalized relative to
  MP-2021

Until those are resolved, TXTRS mortality should remain explicitly classified as
`referenced_not_published` rather than silently mapped to the current runtime
basis.
