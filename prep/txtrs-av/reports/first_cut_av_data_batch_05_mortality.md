# TXTRS-AV First-Cut AV Data Batch 05: Mortality

## Purpose

This note records the first `txtrs-av` mortality runtime files. It pairs
source-direct active mortality from a published SOA table with a documented
fallback estimator for healthy-retiree mortality, because the AV-named retiree
table is a TX-custom non-public document.

## Artifacts Built

- [base_rates.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs-av/data/mortality/base_rates.csv)
- [improvement_scale.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs-av/data/mortality/improvement_scale.csv)

## Source Pages Used

- AV active mortality narrative
  - printed page `60`
  - PDF page `67`
- AV retiree and disabled mortality narrative
  - printed page `64`
  - PDF page `71`

## What The AV Says

| Member state | Stated basis | Projection | Adjustment |
|---|---|---|---|
| Active | Pub-2010 Amount-Weighted Below-Median-Income Teacher | MP-2021-style generational | male set forward 2 years |
| Healthy retiree | 2021 TRS of Texas Healthy Pensioner Mortality Tables | Scale UMP 2021 | immediate convergence |
| Disabled retiree | healthy table set forward 3 years + minimum floors | Scale UMP 2021 | floors of 0.0200 (F) and 0.0400 (M) |

## Build Rule

Artifact produced by:

- [build_txtrs_av_mortality.py](/home/donboyd5/Documents/python_projects/pension_model/scripts/build/build_txtrs_av_mortality.py)
  - method id: `txtrs_av_mortality_assemble_v1`

### Active employee qx

- Source-direct from SOA `PubT-2010(B)` Employee column, female and male,
  ages 18 through 80
- File `prep/common/sources/soa_pub2010_amount_mort_rates.xlsx`
- Ages 81 through 120 are not published in the Employee column; the runtime
  fills them from the retiree column when reading the CSV
- The AV's "male set forward 2 years" is **not** baked into the qx values.
  It is applied at runtime through
  `plan_config.modeling.male_mp_forward_shift = 2`, the same convention used
  by the legacy txtrs config

### Healthy retiree qx

- The AV-named `2021 TRS of Texas Healthy Pensioner Mortality Tables` is a
  TX-custom non-public document. It cannot be transcribed.
- This first cut uses the txtrs-av prototype TX-custom approximation produced
  by [estimate_txtrs_av_retiree_mortality.py](/home/donboyd5/Documents/python_projects/pension_model/scripts/build/estimate_txtrs_av_retiree_mortality.py)
  (registry method `mortality-checkpoint-spline-estimation-v1`)
- The prototype starts from `PubT-2010(B)` Healthy Retiree, projects to 2021
  using UMP-2021 ultimate rates, and fits a shape-preserving spline through
  published 2021 TRS sample checkpoints from the experience study
- The prototype output is for base year 2021. The runtime mortality builder
  assumes `base_year=2010`, so the build backprojects each 2021 qx to 2010
  via `qx_2010 = qx_2021 / (1 - improvement)^11`, where `improvement` is the
  UMP-2021 ultimate rate at that age. The runtime then reprojects forward
  using the same scale, reproducing the prototype's checkpoint-anchored 2021
  curve at run time

### Improvement scale

- AV cites `Scale UMP 2021` with `immediate convergence` for retirees
- Implemented as the SOA MP-2021 ultimate column (the `2037+` long-term column)
  replicated flat across years 1951-2037 by age and gender
- UMP-2021 ultimate rates are unisex by age in the SOA file
- Both genders share the same per-age ultimate rate
- Active employees use the same improvement scale, which is a small
  approximation to the AV's MP-2021-generational wording for actives. The
  experience study itself favors ultimate rates for all years, which supports
  this choice; the open question is the AV-side wording, which uses
  generational rather than ultimate language

## Scope and Simplifications

This first cut deliberately leaves several items as candidate future
inclusions, not permanent exclusions:

- **disabled-retiree mortality** is not modeled separately. The AV calls for
  a 3-year set-forward of the healthy table plus minimum floors, but the
  current runtime applies one mortality table to all retirees. Excluding
  disabled annuitants from `retiree_distribution.csv` (12,030 retirees,
  about 1.45% of retiree dollars per AV Table 15b) understates retiree AAL
  by an estimated 1.0% to 1.2% of retiree AAL, comfortably within the
  txtrs-av 3% AV-validation tolerance. See issue #71.

- **active improvement scale** uses ultimate rates rather than the AV's
  MP-2021-generational wording. The experience study favors ultimate rates
  for all years; the AV wording is generational. Substantive impact at
  near-term valuation horizons is small. See issue #73.

- **healthy-retiree mortality is the documented fallback estimator**, not the
  AV-named TX-custom table. The estimator passes through the published 2021
  TRS sample checkpoints, but it is not source-faithful closure of the
  retiree-basis question. See issue #72.

- **tail-age (~110) discrepancy** in later-year retiree checkpoints is a
  known limit of the current spline fit per the source assessment.

## Cross-Check

The runtime mortality builder loads the new files cleanly:

- runtime `min_age=18`, `max_age=120`, `min_year=1970`, `max_year=2154`
- retiree (M/F average) at age 65, year 2021: `0.0075`
- retiree (M/F average) at age 65, year 2024: `0.0072`
- retiree (M/F average) at age 65, year 2050: `0.0051` (continued ultimate-rate
  improvement)
- backprojection-then-reprojection round-trip is internally consistent

## Remaining Required Runtime Files

- `funding/return_scenarios.csv`

## Implication

`txtrs-av` now has AV-built mortality files in the runtime contract.

The next pending artifact is `funding/return_scenarios.csv`. After that,
end-to-end validation against AV Tables 1-4 within the 3% tolerance can run.
