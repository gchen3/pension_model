# TXTRS-AV Retiree Mortality Source Assessment

## Purpose

This note narrows the retiree-mortality question for `txtrs-av` to a concrete
source protocol:

1. can we obtain the actual source table?
2. if not, what evidence is strong enough to support a documented estimator?

The goal is to avoid two weak patterns:

- treating the current `txtrs` compatibility path as if it were source-faithful
- estimating a full table from a handful of sample rates with no stronger
  methodological anchor

## Current Source Set

- authoritative valuation:
  - [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/sources/Texas%20TRS%20Valuation%202024.pdf)
- auxiliary estimation-support source:
  - [Texas TRS ACFR 2023.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/sources/Texas%20TRS%20ACFR%202023.pdf)
- supplementary methodology source:
  - [Texas TRS Actuarial Experience Study 2022.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/sources/Texas%20TRS%20Actuarial%20Experience%20Study%202022.pdf)
- reconciliation / later calibration-support source:
  - [Texas TRS GASB 67 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/sources/Texas%20TRS%20GASB%2067%202024.pdf)

## What The Sources Currently Tell Us

### 1. The valuation names the retiree basis, but does not publish the full table

The 2024 valuation states:

- healthy retiree mortality uses the `2021 TRS of Texas Healthy Pensioner
  Mortality Tables`
- rates are projected on a fully generational basis by `Scale UMP 2021`, but
  with immediate convergence
- disabled retiree mortality uses a `3`-year set forward of the healthy
  pensioner tables with minimum mortality floors

The valuation also publishes sample rates for selected ages and years, but not
the full age-by-sex table.

### 2. The experience study gives more than just sample points

The official 2022 actuarial experience study provides important methodology
clues for the post-retirement basis:

- the tables are based on TRS experience
- ages over `60` are built from actual TRS retiree experience
- ages under `60` and over `95` are based on credibility-weighted Pub-2010
  Teacher healthy-retiree rates
- the preliminary rates are then graduated using a cubic spline
- the tables are projected from the center of the study period to `2021` using
  the recommended projection scale
- the study text refers to using the long-term rates of `Scale UMP 2021`
  for all future years

More specifically, the experience study says:

- ages after `60` are based on TRS experience
- ages under `60` and after `95` are equal to a credibility-adjusted version of
  the most recently published Pub-2010 Teacher mortality assumptions
- the results are graduated with a cubic spline
- the final preliminary table is projected from `2017` to `2021`
- for future improvement, the study favors using the long-term or ultimate
  rates for all years rather than the full varying MP pattern

This is a much stronger foundation than sample rates alone.

### 3. The GASB 67 report may matter later, but not as the first mortality source

The 2024 GASB 67 report is not the authoritative source document for `txtrs-av`
prep, but it may later help with:

- liability decomposition
- GASB pension liability comparisons
- understanding roll-forward adjustments or scope differences

It is not the first document we should use to define the retiree mortality
table itself.

### 4. What is still missing

Even with the local experience study and GASB report now in hand, one critical
item is still missing:

- the full age-by-sex `2021 TRS of Texas Healthy Pensioner Mortality Tables`

So the evidence set is much stronger than before, but it is still not the same
as having the actual table.

### 5. The wording is not identical across the documents

The three local sources are directionally aligned, but not textually identical:

- the experience study says post-retirement mortality is projected by the
  long-term rates of `Scale UMP 2021`
- the GASB 67 report says healthy-life mortality uses full generational
  projection with `Scale UMP 2021 (the ultimate rates of MP-2021)` and
  `immediate convergence`
- the valuation says the retiree table is projected on a fully generational
  basis by `Scale UMP 2021`, but with `immediate convergence`

Operational implication:

- for healthy retiree mortality, the most defensible current interpretation is
  that `immediate convergence` means applying the ultimate improvement rates of
  the MP-2021 / UMP-2021 family from the start, not the full year-varying MP
  schedule
- this interpretation is supported by both the experience study and the GASB 67
  report
- it still needs to be treated as an inference until we have the actual table
  or a plan-specific technical note confirming the implementation directly

## Current Conclusion

The full `2021 TRS of Texas Healthy Pensioner Mortality Tables` are still not in
hand.

So the correct protocol is:

1. continue trying to obtain the actual table
2. if that fails, estimate only from the full evidence set, not from sample
   rates alone

## Estimation Should Not Mean Sample-Point Curve Fitting Alone

If we cannot obtain the table, the fallback should not be:

- fit a smooth curve through the valuation sample rates and call that the table

That would ignore the strongest methodological evidence we have.

Instead, a documented estimation method should use:

- the valuation sample rates from multiple calendar years
- the 2022 experience study methodology
- the local 2024 GASB 67 report when useful for liability-context cross-checks
- any AV-referenced external tables needed for younger and oldest ages
- any confirmed implementation rule for `Scale UMP 2021` and immediate
  convergence

## Proposed Fallback Method Structure

If the actual table cannot be obtained, the fallback estimation method should
have these components.

### A. Base-table reconstruction

Estimate a sex-distinct 2021 healthy-retiree base table by age using:

- TRS sample rates from the valuation and experience study
- credibility-weighted Pub-2010 Teacher healthy-retiree rates for ages below
  `60` and above `95`
- a smooth graduation approach consistent with the experience-study description

This is a plan-specific estimator, not a generic off-the-shelf table fit.

### B. Improvement implementation

Separately infer the operational meaning of:

- `Scale UMP 2021`
- `immediate convergence`

This should be validated by checking whether the reconstructed 2021 table,
combined with the inferred improvement rule, reproduces the published sample
rates for:

- `2021` and `2051` in the experience study
- `2023` and `2053` in the 2024 valuation
- potentially later valuation sample years if we use them as additional checks

Current best working interpretation:

- use the ultimate improvement rates of the MP-2021 / UMP-2021 family for all
  future years immediately, rather than running the full year-varying MP
  schedule before convergence

This is now evidence-backed, but should still be documented as an inferred
implementation rule rather than a directly published full-table specification.

### C. Disabled-retiree overlay

Once the healthy-retiree table is reconstructed, disabled-retiree rates should
be built from:

- the stated `3`-year set forward
- the minimum mortality floors

and then checked against the published disabled sample rates.

## Implication For Shared Tooling

Part of this method could become a shared prep tool, but not all of it.

Likely shared pieces:

- a mortality-source assessment workflow
- a template for documenting whether a mortality basis is source-faithful,
  compatibility-only, or estimated
- a generic graduation / validation harness
- tooling to compare reconstructed rates to published sample checkpoints across
  multiple years

Plan-specific pieces:

- the table family being reconstructed
- the credibility rules
- the age ranges that borrow from external tables
- the exact projection-scale implementation

So the right design is probably:

- a shared estimation framework
- with plan-specific method parameters and evidence rules

## Will This Need SOA Tables?

Probably yes.

Based on the experience-study text, the fallback estimator will likely need
external published reference material for the ages where the TRS-specific table
leans on credibility-weighted teacher healthy-retiree rates.

That means the estimator is likely to depend on shared external mortality
reference tables under `prep/common/`, not only on TXTRS-specific documents.

But those shared SOA-style tables would support the estimator; they would not by
themselves replace the need for plan-specific TRS evidence.

## Decision

Current decision:

- do not estimate yet
- use the experience study as the main methodology source now that it is in the
  `txtrs-av` source set
- continue trying to obtain the actual healthy-pensioner table
- if that fails, write a documented estimation method that uses the full
  evidence set described above

## Related Artifacts

- [mortality_basis_review.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/reports/mortality_basis_review.md)
- [source_sufficiency_summary.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs-av/reports/source_sufficiency_summary.md)
- existing repo issue [#52](https://github.com/donboyd5/pension_model/issues/52)
