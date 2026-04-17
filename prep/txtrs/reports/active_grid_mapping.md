# TXTRS Active Grid Mapping Notes

## Purpose

This note records the current understanding of how the TXTRS valuation’s active
member grid relates to the runtime `all_headcount.csv` and `all_salary.csv`
artifacts.

## Source Found In The Valuation

Source:

- [Texas TRS Valuation 2024.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/sources/Texas%20TRS%20Valuation%202024.pdf)
  - Table 17 `Distribution of Active Members by Age and Service`, printed p. 41

The valuation publishes:

- age bands as rows
- credited-service bands as columns
- one row of counts
- one row of average compensation

And states:

- the table includes contributing members
- members in DROP are excluded

## What The Runtime Artifacts Look Like

Current runtime files:

- [plans/txtrs/data/demographics/all_headcount.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs/data/demographics/all_headcount.csv)
- [plans/txtrs/data/demographics/all_salary.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs/data/demographics/all_salary.csv)

These use:

- one row per `(age, yos)` cell
- a single representative age value
- a single representative YOS value

Examples:

- `(22, 2)` maps to the `Under 25` age row and low-service cells
- `(27, 7)` maps to the `25-29` age row and `5-9` service cell
- `(32, 12)` maps to the `30-34` age row and `10-14` service cell

The salary file follows the same grid.

## Current Working Mapping Rule

The current runtime artifacts appear to be derived from Table 17 by:

1. taking each age-band / service-band cell
2. assigning a representative age to the age band
3. assigning a representative YOS value to the service band
4. melting the matrix into long form

Representative values currently visible in the runtime artifacts suggest:

- age bands use interior representative ages such as:
  - `Under 25 -> 22`
  - `25-29 -> 27`
  - `30-34 -> 32`
  - `35-39 -> 37`
  - ...
- service bands use representative YOS values such as:
  - `0-4` style early buckets -> `2`
  - `5-9 -> 7`
  - `10-14 -> 12`
  - `15-19 -> 17`
  - ...

This is consistent with a midpoint-style canonicalization rule.

## What This Means For Source Sufficiency

For TXTRS active grids, the correct classification is now:

- source exists in the PDF
- runtime artifact is `derived`

The remaining task is to pin down the exact canonicalization rule for:

- open-ended age bands such as `65+`
- early service buckets such as `0`, `1`, `2`, `3`, `4`
- whether the current runtime uses exact midpoints, lower bounds plus offsets,
  or another reviewed convention

## Practical Implication For Prep

This is no longer a pure missing-data problem.

The prep task is:

- define and document the band-to-point transformation rule
- verify that applying it to Table 17 reproduces the current runtime files

If exact reproduction fails, then either:

- the runtime files came from a richer underlying source than Table 17, or
- the current canonicalization rule differs from a simple midpoint transform
