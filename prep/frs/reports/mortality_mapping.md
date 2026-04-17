# FRS Mortality Mapping Notes

## Purpose

This note records the current understanding of how FRS mortality is described in
the source valuation, how the current runtime represents mortality, and where
the two do or do not align.

## Source-Stated Basis

Source:

- [Florida FRS Valuation 2022.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/Florida%20FRS%20Valuation%202022.pdf)
  - Appendix A mortality section, printed pp. A-4 to A-5

The valuation describes:

- healthy inactive mortality using Pub-2010 base tables with gender-specific
  MP-2018 improvement
- healthy active mortality using Pub-2010 base tables with gender-specific
  MP-2018 improvement
- disabled mortality using Pub-2010 disabled-retiree tables without mortality
  improvement

## Category Mapping Stated In The Valuation

### Healthy inactive mortality

- female K-12 instructional personnel:
  headcount-weighted teachers healthy retiree female, set forward 1 year
- male K-12 instructional personnel:
  benefits-weighted teachers below-median healthy retiree male, set forward 2 years
- female special risk:
  headcount-weighted safety healthy retiree female, set forward 1 year
- male special risk:
  headcount-weighted safety below-median healthy retiree male, set forward 1 year
- female other members:
  headcount-weighted general below-median healthy retiree female
- male other members:
  headcount-weighted general below-median healthy retiree male, set back 1 year

### Healthy active mortality

- female K-12 instructional personnel:
  headcount-weighted teachers employee female, set forward 1 year
- male K-12 instructional personnel:
  benefits-weighted teachers below-median employee male, set forward 2 years
- female special risk:
  headcount-weighted safety employee female, set forward 1 year
- male special risk:
  headcount-weighted safety below-median employee male, set forward 1 year
- female other members:
  headcount-weighted general below-median employee female
- male other members:
  headcount-weighted general below-median employee male, set back 1 year

### Disabled mortality

- female disabled special risk:
  80% general disabled retiree female plus 20% safety disabled retiree female
- male disabled special risk:
  80% general disabled retiree male plus 20% safety disabled retiree male
- female disabled non-special-risk:
  general disabled retiree female, set forward 3 years
- male disabled non-special-risk:
  general disabled retiree male, set forward 3 years

## Shared External References Needed

The valuation names the basis, but does not publish the full standard-table
rates. Exact mortality reconstruction therefore requires the shared SOA sources
now stored under
[prep/common/sources](/home/donboyd5/Documents/python_projects/pension_model/prep/common/sources):

- `soa_pub2010_headcount_mort_rates.xlsx`
- `soa_pub2010_amount_mort_rates.xlsx`
- `soa_mp2018_rates.xlsx`

The headcount workbook alone is not enough, because the valuation explicitly
uses below-median or benefits-weighted male teacher and special-risk tables.

## Current Runtime Representation

Current runtime FRS config:

- [plans/frs/config/plan_config.json](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/config/plan_config.json)

Current base-table map:

- `regular -> regular`
- `special -> safety`
- `admin -> safety`
- `eco -> general`
- `eso -> general`
- `judges -> general`
- `senior_management -> general`

Current runtime base-rate file contains only these table labels:

- `general`
- `teacher`
- `safety`

Current runtime improvement handling:

- one shared `improvement_scale.csv`
- `male_mp_forward_shift = 0`

## How Current Stage-3 Mortality Was Built

The legacy conversion script makes the current behavior explicit:

- [scripts/build/convert_frs_to_stage3.py](/home/donboyd5/Documents/python_projects/pension_model/scripts/build/convert_frs_to_stage3.py)

It loads:

- `PubG.H-2010 -> general`
- `PubT.H-2010 -> teacher`
- `PubS.H-2010 -> safety`
- MP-2018 from the shared male and female sheets

And for the `regular` class, runtime averages:

- `general`
- `teacher`

That is materially simpler than the valuation’s stated mortality basis.

## Main Alignment Findings

### What aligns

- the valuation clearly points to the Pub-2010 family and MP-2018
- the current runtime’s broad table families `general`, `teacher`, and `safety`
  are directionally related to the valuation basis
- shared SOA references now in `prep/common/sources` are the correct family of
  external inputs

### What does not align cleanly

- the valuation uses a richer category map than the current class map
- the valuation uses below-median and benefits-weighted variants, but current
  stage-3 base rates only carry plain `general`, `teacher`, and `safety`
- the valuation uses explicit set-forward and set-back adjustments, but current
  runtime config has no FRS male MP shift and no table-specific shift metadata
- the valuation distinguishes disabled mortality without improvement, but the
  current runtime mortality artifacts do not document a separate disabled basis

## Implication For Prep

For the FRS pilot, mortality should be treated as:

- source-rich
- reproducible only with shared external SOA reference tables
- likely to require documented approximation or compatibility logic if the goal
  is to match current stage-3 artifacts exactly

That means there are really two targets to compare:

1. source-faithful mortality basis as stated in the valuation
2. current reviewed runtime mortality artifacts

Those may not be identical.

## Early Runtime-Contract Question

FRS mortality is a concrete example of a possible runtime-structure pressure
point.

The current runtime can probably still carry a built compatibility version of
FRS mortality, but it does not naturally express:

- member-category-specific table selection
- disabled-retiree basis separately from healthy-retiree basis
- explicit set-forward and set-back metadata

This should be used as evidence in the early runtime contract review, not as a
reason to change behavior immediately.

## Current Working Conclusion

For FRS:

- the authoritative source basis is clear
- the shared SOA references needed for reconstruction are mostly in hand
- the current stage-3 mortality files appear to be a compatibility-oriented
  simplification of the richer valuation basis
- exact PDF-to-stage-3 reproduction will therefore need an explicit documented
  build rule, not just table extraction
