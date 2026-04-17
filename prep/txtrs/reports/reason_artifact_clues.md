# TXTRS Reason-Artifact Clues

## Purpose

This note records useful clues found in the retained Reason-era TXTRS R model
and workbook inputs.

These artifacts are not authoritative source documents. They are legacy
intermediate materials that help explain:

- calibration constants
- compatibility-oriented input choices
- which workbook tables the R model actually used

Primary artifacts:

- [R_model/R_model_txtrs/TxTRS_model_inputs.R](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_txtrs/TxTRS_model_inputs.R)
- [R_model/R_model_txtrs/TxTRS_liability_model.R](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_txtrs/TxTRS_liability_model.R)
- [R_model/R_model_txtrs/TxTRS_funding_model.R](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_txtrs/TxTRS_funding_model.R)
- [R_model/R_model_txtrs/TxTRS_BM_Inputs.xlsx](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_txtrs/TxTRS_BM_Inputs.xlsx)

## Workbook Structure Clues

`TxTRS_BM_Inputs.xlsx` contains visible sheets for:

- `Funding Data`
- `Return Scenarios`
- `Salary Matrix`
- `Head Count Matrix`
- `Entrant Profile`
- `Retiree Distribution`
- `Salary Growth YOS`
- `Reduced GFT`
- `Reduced Others`
- `Mortality Rates`
- `Termination Rates after 10`
- `Termination Rates before 10`
- `Retirement Rates`
- `MP-2018_Male`
- `MP-2018_Female`

Two immediate implications:

- the workbook still contains mortality tabs tied to an older RP-2014 /
  MP-2018-style setup
- the active R code no longer treats those workbook tabs as the primary
  mortality input path

## Strong Clues From `TxTRS_model_inputs.R`

### 1. The R model hard-codes key valuation targets and calibration constants

Examples:

- `retiree_pop_current <- 508701`
- `ben_payment_current <- 15258219146`
- `retire_refund_ratio_ <- 0.3`
- `cal_factor_ <- 12.1 / 12.189475`
- `nc_cal_ <- 12.1 / 12.1117`
- `ben_cal_ <- 1`
- `PVFB_term_current <- 273095060051 - 262639131631`

This is important because it confirms that some current/runtime-aligned TXTRS
values are not direct document extracts. They are explicit legacy model inputs
or calibrations.

### 2. The model reads external Pub-2010 and MP-2021 workbooks directly

The file loads:

- `Inputs/pub-2010-amount-mort-rates.xlsx`, sheet `PubT-2010(B)`
- `Inputs/mp-2021-rates.xlsx`, sheets `Male` and `Female`

This is a strong clue that the current reviewed TXTRS mortality path is
deliberately compatibility-oriented around:

- Pub-2010 teacher below-median
- MP-2021

rather than source-faithful reproduction of the valuation's stated retiree
mortality basis.

An important refinement is now clear:

- the Pub-2010 teacher sheet used by the current path is not one flat mortality
  curve
- it contains separate `Employee` and `Healthy Retiree` columns for female and
  male
- the current stage-3 build writes those out as distinct runtime
  `member_type = employee` and `member_type = retiree` rows

So the current reviewed runtime does preserve an employee-versus-retiree base
rate distinction, but it still does so inside a Pub-2010 compatibility family
rather than using the valuation's stated TRS-specific retiree tables.

The active code path also reveals a more specific implementation detail:

- male MP rates are shifted forward by two years by renaming the MP columns and
  extending the tail with the last available column
- the current path then uses the observed MP schedule through the workbook
  horizon and only uses the ultimate column after the final published year

That matters because it is not obviously the same as a blanket “immediate
convergence” implementation of `Scale UMP 2021`.

### 3. Workbook-internal mortality tables appear secondary or stale

`TxTRS_BM_Inputs.xlsx` contains sheets named:

- `Mortality Rates`
- `MP-2018_Male`
- `MP-2018_Female`

But the current R model uses the external Pub-2010 and MP-2021 workbooks in the
active code path.

Implication:

- not every workbook tab should be treated as current intended logic
- some tabs may be remnants of older versions
- the workbook still contains historically meaningful intermediate structure,
  but active-path logic must be confirmed from the R code rather than inferred
  from sheet names alone

The retained workbook does contain a distinct older mortality basis:

- `Mortality Rates` has columns:
  - `RP_2014_employee_male`
  - `RP_2014_employee_female`
  - `RP_2014_ann_employee_male`
  - `RP_2014_ann_employee_female`
- the archived
  [TxTRS_R_BModel revised.R](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_txtrs/TxTRS_R_BModel%20revised.R)
  uses those workbook RP-2014 columns to build separate active and retiree
  mortality tables

So the retained TXTRS artifacts preserve at least two historical mortality
paths:

- an older workbook-based RP-2014 path
- the current reviewed external Pub-2010 / MP-2021 compatibility path

There is also a very specific clue in the archived RP-2014 path:

- the commented legacy code says:
  - `Since the plan assumes "immediate convergence" of MP rates, the "ultimate rates" are used for all years`
- that note appears in the archived
  [TxTRS_R_BModel revised.R](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_txtrs/TxTRS_R_BModel%20revised.R)
  immediately above the older RP-2014 / MP implementation

This is important because it shows that at least one historical TXTRS code path
explicitly recognized the valuation's immediate-convergence language and tried
to implement it via ultimate rates for all years.

The current active Pub-2010 / MP-2021 path does not appear to do that. It uses
the evolving MP schedule through the available years and only then holds at the
ultimate rate.

So the retained TXTRS artifacts preserve not just different source families,
but also different interpretations of how the mortality-improvement scale should
be operationalized.

### 3a. Workbook `Funding Data` is minimal and valuation-anchored

The workbook `Funding Data` sheet currently contains a sparse starting row with:

- `fy = 2024`
- `payroll = 61,388,248,000`
- `payroll_DB_legacy = payroll`
- `nc_rate = 0.121`
- zero liability gain/loss seed values

The exact cells are:

- `A1:G1` headers:
  - `fy`, `payroll`, `payroll_DB_legacy`, `payroll_DB_new`,
    `payroll_CB_new`, `nc_rate`, `nc_rate_DB_legacy`
- `A2:G2` seed row:
  - `A2 = 2024`
  - `B2 = 61,388,248,000`
  - `C2 = =B2`
  - `D2 = 0`
  - `E2 = 0`
  - `F2 = 0.121`
  - `G2 = =F2`

This supports the idea that TXTRS uses a much thinner workbook funding seed than
FRS, with more of the substantive shaping happening in R code.

### 3b. Workbook `Retiree Distribution` is also formula-built

The workbook `Retiree Distribution` sheet is not just a raw source copy.
Examples:

- age 55:
  - `n.retire = (532 + 457 + 672 + 918 + 6140 + 24738) / 5`
  - `total_ben = (7,590,110 + 7,193,460 + 10,096,388 + 14,738,549 + 251,656,344 + 983,011,271) / 5`
- age 60:
  - `n.retire = 56,932 / 5`
  - `total_ben = 1,936,166,924 / 5`

So even in TXTRS, the workbook carries a constructed age distribution rather
than a plain age-by-age source extract.

The construction is explicit in the worksheet cells:

- `A1:F1` headers:
  - `age`, `n.retire`, `total_ben`, `avg_ben`, `n.retire_ratio`,
    `total_ben_ratio`
- ages `55` to `59` (`A2:A6`) each use the same five-year spread:
  - `B2:B6 = (532 + 457 + 672 + 918 + 6140 + 24738) / 5`
  - `C2:C6 = (7,590,110 + 7,193,460 + 10,096,388 + 14,738,549 + 251,656,344 + 983,011,271) / 5`
- ages `60` to `64` (`A7:A11`) each use:
  - `B7:B11 = 56,932 / 5`
  - `C7:C11 = 1,936,166,924 / 5`
- ages `65` to `69` (`A12:A16`) each use:
  - `B12:B16 = 94,850 / 5`
  - `C12:C16 = 2,741,905,661 / 5`

One more narrowing result is useful:

- a repo-wide search for representative grouped literals from these formulas did
  not find a retained upstream source table elsewhere in the repo
- so the retained workbook shows the smoothing rule, but not the provenance of
  the grouped values being smoothed

### 3c. Workbook `Entrant Profile` is partly synthetic

Examples:

- age 20:
  - `Count = 859 + 49,665`
  - `start_sal = AVERAGE(D1:D2)` using adjacent hard-coded values
- later rows step age upward by formula:
  - age 25 = `A2 + 5`
  - age 30 = `A3 + 5`

This is another sign that the workbook contains processed intermediate inputs,
not only direct copied source tables.

Again, the cell structure is explicit:

- `A1:D1` headers:
  - `entry_age`, `Count`, `start_sal`, raw salary anchor column
- `A2:B11` hold five-year age bands from `20` to `65`
- `B2 = 859 + 49,665`
- `B11 = 11,678 + 2,372`
- `C2:C11` are midpoints formed from adjacent raw salary anchors:
  - `C2 = AVERAGE(D1:D2)`
  - `C3 = AVERAGE(D2:D3)`
  - ...
  - `C11 = AVERAGE(D10:D11)`

One more negative finding is useful here:

- no relevant workbook defined names were found for the TXTRS funding,
  retiree-distribution, or entrant-profile logic
- the evidence is again in the sheet formulas themselves, not in named ranges

## Strong Clues From `TxTRS_liability_model.R`

### 4. Current-retiree benefit payments are built from retiree-distribution ratios

The model constructs:

- `n.retire_current = n.retire_ratio * retiree_pop_current`
- `total_ben_current = total_ben_ratio * ben_payment_current * ben_cal_`

So current-retiree cash flows are not just copied from a source table. They are
allocated across the retiree distribution using:

- distribution ratios from the workbook
- a total benefit-payment anchor
- a benefit calibration factor

### 5. Current term-vested benefits are explicitly synthetic

The model creates current term-vested retiree benefit payments from:

- `PVFB_term_current`
- an amortization-like timing pattern
- a bell-curve style sequence

This is not a direct document extract. It is a constructed legacy model input
path.

## Strong Clues From `TxTRS_funding_model.R`

### 6. Normal-cost rates are explicitly calibrated in the funding model

The model applies:

- `nc_rate_DB_legacy_est * nc_cal_`
- `nc_rate_DB_new_est * nc_cal_`

This is a direct example of a computed legacy model calibration sitting between
source data and final funding outputs.

## What This Changes

For TXTRS, the Reason artifacts clarify that several important current-model
inputs are intentionally model-mediated rather than direct document extracts.

That includes:

- calibration factors
- allocation of current-retiree benefit payments across age distribution
- construction of current term-vested benefit payments
- compatibility-oriented mortality loading

So the prep problem for TXTRS is not only:

- `find the right PDF table`

It is also:

- `separate document-sourced quantities from legacy model constants and computed intermediates`

## Follow-Up

- inspect whether `TxTRS_BM_Inputs.xlsx` preserves older intermediate tables
  that explain current canonical artifacts more directly than the PDFs do
- document which workbook tabs are actually active inputs to the final R path
  versus historical leftovers
- document which workbook tabs are formula-built intermediate artifacts rather
  than direct source-table copies
- treat TXTRS mortality as a compatibility path until the plan-specific healthy
  pensioner tables are acquired

See also:

- [mortality_mapping.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/reports/mortality_mapping.md)
- [external_source_requirements.md](/home/donboyd5/Documents/python_projects/pension_model/prep/txtrs/reports/external_source_requirements.md)
