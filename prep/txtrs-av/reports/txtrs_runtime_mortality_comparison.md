# TXTRS Runtime Mortality Comparison

## Purpose

This note records what the existing `txtrs` runtime mortality path did and why
`txtrs-av` should not copy it as the default retiree-mortality solution.

## Short Answer

The existing `txtrs` runtime did **not** use the actual `2021 TRS of Texas
Healthy Pensioner Mortality Tables`.

It also did **not** estimate those tables from the AV sample rates.

Instead, it used a compatibility construction based on:

- shared Pub-2010 Teacher healthy-retiree rates
- shared MP-2021 improvement rates

That was sufficient to build a reviewed runtime path, but it is not a
source-faithful implementation of the valuation's stated retiree mortality
basis.

## What The Existing `txtrs` Path Did

Evidence:

- [scripts/build/convert_txtrs_to_stage3.py](/home/donboyd5/Documents/python_projects/pension_model/scripts/build/convert_txtrs_to_stage3.py)
- [R_model/R_model_txtrs/TxTRS_model_inputs.R](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_txtrs/TxTRS_model_inputs.R)
- [plans/txtrs/data/mortality/base_rates.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs/data/mortality/base_rates.csv)
- [plans/txtrs/config/plan_config.json](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs/config/plan_config.json)

The current reviewed path:

- reads `Inputs/pub-2010-amount-mort-rates.xlsx`, sheet `PubT-2010(B)`
- reads `Inputs/mp-2021-rates.xlsx`
- writes `base_rates.csv` with:
  - `member_type = employee`
  - `member_type = retiree`
  - `table = teacher_below_median`
- configures runtime mortality as:
  - `base_table = pub_2010_teacher_below_median`
  - `improvement_scale = mp_2021`
  - `male_mp_forward_shift = 2`

Operationally, that means retiree mortality in the current `txtrs` path is
based on the shared Pub-2010 teacher healthy-retiree columns, not on a
TRS-specific healthy pensioner table.

## What It Did Not Do

The current reviewed `txtrs` path did **not**:

- load the actual `2021 TRS of Texas Healthy Pensioner Mortality Tables`
- reconstruct those tables from the experience study methodology
- estimate the tables from AV sample rates plus plan-specific evidence

So the existing path is a compatibility approximation, not a source-faithful
reconstruction and not a documented estimator of the TRS-specific retiree
tables.

## Why `txtrs-av` Should Not Copy It

For `txtrs-av`, copying the existing runtime path would blur three distinct
things:

- a reviewed runtime compatibility construction
- a source-faithful implementation of the valuation basis
- a documented fallback estimator when the actual table is unavailable

Those are not the same.

`txtrs-av` should therefore treat the old `txtrs` retiree-mortality path as:

- useful evidence about prior compatibility behavior
- not the default source path
- not the fallback estimation method

## What `txtrs-av` Should Do Instead

Preferred order:

1. obtain the actual `2021 TRS of Texas Healthy Pensioner Mortality Tables`
2. if unavailable, use a documented estimator built from:
   - the experience study methodology
   - the published sample-rate checkpoints
   - the immediate-convergence interpretation supported by the AV and GASB 67
   - shared external mortality references where the experience study leans on
     credibility-weighted published teacher rates

## Current Classification

- existing `txtrs` retiree mortality path: `compatibility approximation`
- desired `txtrs-av` path: `source-faithful if table obtained, otherwise
  documented estimation`
