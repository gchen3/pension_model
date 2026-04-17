# SOA Reference Inventory

## Purpose

This note records the shared SOA mortality reference materials currently stored
under:

- [prep/common/sources](/home/donboyd5/Documents/python_projects/pension_model/prep/common/sources)

It also summarizes which ones appear relevant to the current FRS and TXTRS
pilot plans.

## Downloaded Shared Sources

- [soa_pub2010_report.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/common/sources/soa_pub2010_report.pdf)
  - official SOA report: Pub-2010 Public Retirement Plans Mortality Tables
- [soa_pub2010_amount_mort_rates.xlsx](/home/donboyd5/Documents/python_projects/pension_model/prep/common/sources/soa_pub2010_amount_mort_rates.xlsx)
  - official SOA amount-weighted Pub-2010 base-rate workbook
- [soa_pub2010_headcount_mort_rates.xlsx](/home/donboyd5/Documents/python_projects/pension_model/prep/common/sources/soa_pub2010_headcount_mort_rates.xlsx)
  - official SOA headcount-weighted Pub-2010 base-rate workbook
- [soa_mp2018_report.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/common/sources/soa_mp2018_report.pdf)
  - official SOA Mortality Improvement Scale MP-2018 report
- [soa_mp2018_rates.xlsx](/home/donboyd5/Documents/python_projects/pension_model/prep/common/sources/soa_mp2018_rates.xlsx)
  - official SOA MP-2018 rate workbook
- [soa_mp2021_report.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/common/sources/soa_mp2021_report.pdf)
  - official SOA Mortality Improvement Scale MP-2021 report
- [soa_mp2021_rates.xlsx](/home/donboyd5/Documents/python_projects/pension_model/prep/common/sources/soa_mp2021_rates.xlsx)
  - official SOA MP-2021 rate workbook

## Workbook Structure Verified

### Pub-2010 amount-weighted workbook

Verified worksheet names:

- `PubT-2010`
- `PubS-2010`
- `PubG-2010`
- `PubT-2010(A)`
- `PubT-2010(B)`
- `PubS-2010(A)`
- `PubS-2010(B)`
- `PubG-2010(A)`
- `PubG-2010(B)`
- `Juvenile`

### Pub-2010 headcount-weighted workbook

Verified worksheet names:

- `PubT.H-2010`
- `PubS.H-2010`
- `PubG.H-2010`
- `PubT.H-2010(A)`
- `PubT.H-2010(B)`
- `PubS.H-2010(A)`
- `PubS.H-2010(B)`
- `PubG.H-2010(A)`
- `PubG.H-2010(B)`
- `Juvenile`

### MP workbooks

Both MP workbooks have:

- `Male`
- `Female`

## Current Pilot Relevance

### FRS

FRS source documents point clearly to SOA shared references:

- Pub-2010 public retirement plan base tables
- MP-2018 mortality improvement scale

The FRS valuation’s Appendix A uses a mix of:

- teacher
- safety
- general
- disabled-retiree

tables, with a mix of:

- headcount-weighted
- amount-weighted
- above/below-median variants

So for FRS, the downloaded SOA materials are not optional background. They are
part of the likely reproducibility package for canonical mortality inputs.

### TXTRS

TXTRS source documents do **not** point to Pub-2010 for the intended pilot
source basis. They instead refer to:

- `2021 TRS of Texas Healthy Pensioner Mortality Tables`
- `Scale UMP 2021`

The downloaded SOA MP-2021 material is still potentially relevant because TXTRS
documents appear to tie `Scale UMP 2021` to an ultimate-rate projection concept
closely related to MP-2021. However, this should be treated as:

- not yet confirmed as a direct one-to-one mapping

So for TXTRS:

- MP-2021 is a useful shared reference now
- Pub-2010 is more relevant to the **current runtime** than to the **source-first target**
- the TRS-specific 2021 mortality tables remain a separate source need

## Important Precision Notes

- A named mortality **basis** and the full mortality **rate table values** are different things.
- A named improvement **scale** and the full scale **rate values** are different things.
- `discount rate` and `investment return assumption` are different concepts, even when a plan uses the same numeric value for both.

## Next Likely Source Need

The remaining major shared-reference gap is not an SOA file already downloaded.
It is likely one or both of:

- a plan-specific TRS of Texas 2021 healthy pensioner mortality table source
- documentation for how `Scale UMP 2021` should be operationalized relative to MP-2021
