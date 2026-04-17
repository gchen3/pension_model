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

## Exact Legacy Path Confirmed

The retained TXTRS conversion code shows that the historical stage-3 path was
not a PDF parse. It was a direct workbook export:

- [scripts/build/convert_txtrs_to_stage3.py](/home/donboyd5/Documents/python_projects/pension_model/scripts/build/convert_txtrs_to_stage3.py)
  - reads `R_model/R_model_txtrs/TxTRS_BM_Inputs.xlsx`
  - loads `Salary Matrix` and `Head Count Matrix`
  - melts each wide matrix directly to long form
  - writes `all_salary.csv` and `all_headcount.csv`

The workbook matrices themselves already sit on the canonical point grid used by
runtime:

- ages: `22, 27, 32, 37, ...`
- YOS: `2, 7, 12, 17, ...`

And the runtime artifacts match those workbook matrices exactly for the visible
cells inspected.

Examples:

- workbook `Head Count Matrix!B2 = 29012` maps directly to runtime `(age=22, yos=2, count=29012)`
- workbook `Head Count Matrix!C3 = 16980` maps directly to runtime `(age=27, yos=7, count=16980)`
- workbook `Salary Matrix!B2 = 33220.8465...` maps directly to runtime `(age=22, yos=2, salary=33220.8465...)`
- workbook `Salary Matrix!C3 = 56097` maps directly to runtime `(age=27, yos=7, salary=56097)`

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

But an important distinction is now clear:

- legacy exact reproduction path:
  - workbook matrices -> melt -> runtime files
- future PDF-only target:
  - valuation Table 17 -> reviewed band-to-point canonicalization -> runtime files

Those two paths may turn out to be equivalent, but they should not be assumed
to be equivalent until the PDF table is checked cell by cell against the
workbook matrices.

## Direct PDF Evidence For The Early-Service Rule

Direct PDF extraction from valuation Table 17 shows that the source table is not
already on the runtime point grid.

For the younger ages, the PDF shows separate single-year service columns
`1`, `2`, `3`, and `4` before the broader `5-9`, `10-14`, `15-19`, ... buckets.

Examples from the PDF text extraction:

- `Under 25` row:
  - counts: `17,422`, `8,195`, `2,700`, `695`, then `347` in the next broad
    service bucket
  - salaries: `$31,032`, `$37,619`, `$34,062`, `$32,962`, then `$33,532`
- `25-29` row:
  - counts: `22,207`, `21,575`, `17,977`, `11,521`, then `16,980`, then `90`
  - salaries: `$38,940`, `$49,074`, `$52,503`, `$55,834`, then `$56,097`,
    then `$50,068`

The workbook/runtime canonical point-grid rule is therefore more specific than
“take band midpoints”:

- the single-year service columns `1`, `2`, `3`, and `4` are collapsed into one
  canonical `yos = 2` cell
- later bands are represented by point values like:
  - `5-9 -> 7`
  - `10-14 -> 12`
  - `15-19 -> 17`

For headcount, this collapse is a straight sum.

Examples:

- runtime `(22, 2, 29012)` equals `17,422 + 8,195 + 2,700 + 695`
- runtime `(27, 2, 73280)` equals `22,207 + 21,575 + 17,977 + 11,521`

For salary, the collapsed `yos = 2` value is a count-weighted average of those
same early-service salary cells.

Examples:

- runtime salary `(22, 2) = 33220.8465...`
  - equals the weighted average of:
    - `31,032`, `37,619`, `34,062`, `32,962`
    - weighted by counts `17,422`, `8,195`, `2,700`, `695`
- runtime salary `(27, 2) = 47906.9606...`
  - equals the weighted average of:
    - `38,940`, `49,074`, `52,503`, `55,834`
    - weighted by counts `22,207`, `21,575`, `17,977`, `11,521`

So the early-service canonicalization rule is now known much more precisely.

## What This Means For Source Sufficiency

For TXTRS active grids, the correct classification is now:

- source exists in the PDF
- runtime artifact is `derived`

The remaining task is to pin down the exact canonicalization rule for:

- open-ended age bands such as `65+`
- early service buckets such as `0`, `1`, `2`, `3`, `4`
- whether the current runtime uses exact midpoints, lower bounds plus offsets,
  or another reviewed convention

## Full PDF-To-Runtime Verification

A direct parse of valuation Table 17 now reproduces the current runtime
artifacts exactly.

Verified against:

- [plans/txtrs/data/demographics/all_headcount.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs/data/demographics/all_headcount.csv)
- [plans/txtrs/data/demographics/all_salary.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/txtrs/data/demographics/all_salary.csv)

Result:

- parsed PDF rows: `59`
- runtime rows: `59`
- missing rows: `0`
- extra rows: `0`
- headcount mismatches: `0`
- salary mismatches: `0`

The exact canonicalization rule is therefore now known:

- representative ages:
  - `Under 25 -> 22`
  - `25-29 -> 27`
  - `30-34 -> 32`
  - `35-39 -> 37`
  - `40-44 -> 42`
  - `45-49 -> 47`
  - `50-54 -> 52`
  - `55-59 -> 57`
  - `60-64 -> 62`
  - `65+ -> 67`
- service mapping:
  - single-year service columns `1`, `2`, `3`, and `4` are collapsed into
    canonical `yos = 2`
  - later service bands map directly as:
    - `5-9 -> 7`
    - `10-14 -> 12`
    - `15-19 -> 17`
    - `20-24 -> 22`
    - `25-29 -> 27`
    - `30-34 -> 32`
    - `35+ -> 37`
- headcount rule:
  - canonical `(age, yos=2)` count is the sum of the four single-year service
    counts
  - all later canonical cells take the published band count directly
- salary rule:
  - canonical `(age, yos=2)` salary is the count-weighted average of the four
    single-year service salary cells
  - all later canonical cells take the published band salary directly

This confirms that the current runtime active grid is not dependent on a hidden
Reason-only source. The workbook path is an exact intermediate representation of
the same information already published in the valuation PDF.

## Practical Implication For Prep

For TXTRS active demographics, the prep task is now well-defined:

- extract Table 17 from the valuation PDF
- apply the reviewed band-to-point canonicalization rule above
- validate exact equality to the canonical runtime files

This is a strong example of a source-faithful `derived` artifact rather than a
`referenced_not_published` gap.
