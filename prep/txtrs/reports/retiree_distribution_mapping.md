# TXTRS Retiree Distribution Mapping Notes

## Purpose

This note records the current understanding of how the TXTRS runtime
`retiree_distribution.csv` relates to published plan documents and to the
retained Reason workbook.

## Current Runtime Artifact

Current canonical file:

- [plans/txtrs/data/demographics/retiree_distribution.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs/data/demographics/retiree_distribution.csv)

The runtime artifact is an age-by-age table with:

- `age`
- `count`
- `avg_benefit`
- `total_benefit`

It spans ages `55` through `120` and has a visibly smoothed structure:

- ages `55-59` repeat the same count and benefit values
- ages `60-64` repeat the same values
- ...
- the oldest ages repeat a flat tail

So the runtime artifact is already a clue that the source path is not a direct
age-by-age extraction from a published table.

## Published Source Information Found So Far

### Valuation Table 15b

Source:

- [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/sources/Texas%20TRS%20Valuation%202024.pdf)
  - Table 15b, printed p. `39`, PDF p. `46`

This table publishes broad retiree categories and totals, including:

- total persons receiving benefits = `508,701`
- total annual annuities = `$13,385,787,289`

But it does **not** publish an age distribution.

### Valuation Table 20

Source:

- [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/sources/Texas%20TRS%20Valuation%202024.pdf)
  - Table 20, printed p. `44`, PDF p. `51`

This table publishes historical retirement cohorts by retirement year, with:

- counts
- annual allowances
- average annual allowances

It is useful context, but it is not an age-by-age retiree distribution.

## What The Reason Workbook Does

Retained workbook:

- [R_model/R_model_txtrs/TxTRS_BM_Inputs.xlsx](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_txtrs/TxTRS_BM_Inputs.xlsx)
  - `Retiree Distribution` sheet

The workbook sheet is explicitly formula-built. It spreads grouped counts and
grouped benefit totals across age ranges.

Examples:

- ages `55-59` each use:
  - `n.retire = (532 + 457 + 672 + 918 + 6140 + 24738) / 5`
  - `total_ben = (7,590,110 + 7,193,460 + 10,096,388 + 14,738,549 + 251,656,344 + 983,011,271) / 5`
- ages `60-64` each use:
  - `n.retire = 56,932 / 5`
  - `total_ben = 1,936,166,924 / 5`
- ages `65-69` each use:
  - `n.retire = 94,850 / 5`
  - `total_ben = 2,741,905,661 / 5`

So the workbook is constructing a smoothed age profile from grouped source
values rather than copying a published age-by-age table.

Additional narrowing result:

- a repo-wide search for representative grouped literals such as `532`,
  `24,738`, `56,932`, `94,850`, `107,028`, `1,936,166,924`, and
  `2,741,905,661` did not find a retained upstream table or note that explains
  those grouped inputs outside the workbook formulas themselves

So, as currently retained in the repo, the workbook explains the smoothing step
but not the source provenance of the grouped values being smoothed.

## Current Working Interpretation

The correct classification is currently:

- source totals exist in the PDFs
- the runtime age distribution is `derived`
- the retained workbook provides a legacy smoothing rule
- exact PDF-only reconstruction is **not yet** established

This is different from TXTRS active members and entrant profile, where the
PDF-only path is now fully known.

## What Is Resolved

- the runtime file is not a direct transcription of a published age table
- the workbook uses explicit five-year spreading logic for most ages
- the workbook `Retiree Distribution` sheet is a substantive intermediate
  artifact, not a passive copy
- the grouped values feeding that intermediate artifact currently appear to be
  off-workbook or otherwise not retained in the repo

## What Is Not Yet Resolved

- which exact published values feed each workbook grouped total
- whether the workbook grouping can be reconstructed cleanly from valuation
  tables alone
- whether the final age-by-age runtime artifact can be reproduced from plan PDFs
  alone without leaning on the workbook formulas

## Practical Implication For Prep

For TXTRS retiree distribution, the prep path is still unresolved.

The likely next steps are:

- identify the source tables behind the grouped workbook totals
- determine whether those grouped totals are fully published in the valuation or
  ACFR
- decide whether the workbook smoothing rule should be treated as:
  - a legacy unresolved reconstruction rule, or
  - a documented new canonical estimation/smoothing method if we adopt it going
    forward
