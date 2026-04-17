# FRS Reason-Artifact Clues

## Purpose

This note records useful clues found in the retained Reason-era FRS workbook.

These are not treated as authoritative source documents. They are legacy
intermediate artifacts that may help explain:

- reviewed baseline values
- undocumented allocation rules
- compatibility-oriented runtime fields

Primary artifact:

- [R_model/R_model_frs/Florida FRS inputs.xlsx](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_frs/Florida%20FRS%20inputs.xlsx)

## What The Workbook Contains

The workbook includes sheets for:

- retiree distribution
- entrant profile
- funding input
- amortization input
- return scenarios
- class-specific salary and headcount distributions
- class-specific withdrawal tables
- retirement rates

This is already important: it confirms that the Reason workflow encoded a large
amount of processed intermediate input data in the workbook itself, not only in
R code.

Additional workbook structure notes:

- `Withdrawal Rates` exists as a hidden consolidated sheet
- the detailed class-specific withdrawal sheets are visible
- `Sheet12` appears to be visible but effectively empty

## Strong Clues From `Funding Input`

The `Funding Input` sheet contains a wide class-by-class funding seed table that
closely resembles the current canonical
[plans/frs/data/funding/init_funding.csv](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/data/funding/init_funding.csv).

### 1. DB/DC payroll splits are explicitly encoded

Examples:

- regular:
  - `total_payroll = 29,126,383,663`
  - `payroll_db_legacy = 18,917,045,000`
  - `payroll_dc_legacy = total_payroll - payroll_db_legacy = 10,209,338,663`
- special:
  - `total_payroll = 5,451,709,307`
  - `payroll_db_legacy = 4,601,265,000`
  - `payroll_dc_legacy = 850,444,307`

This is a major clue for prep because these splits do not come directly from the
AV or ACFR in published form. They are legacy intermediate values embedded in
the workbook.

The same sheet also encodes a second intermediate contribution layer:

- `AW1:BR1` contains cash-flow and contribution build fields
- `AW` columns hold employee normal-cost contribution totals
- `BI` holds total employer DB contribution
- `BJ` holds total employer DC contribution

For example, the Regular row uses:

- `AW2 = AX2 + AY2`
- `AX2 = AK2 * D2`
- `BI2 = 2,980,066,000 - AW2`
- `BJ2 = BF2 + BG2`
- `BH2 = BI2 + BJ2`

So the workbook is not only storing published rates. It is also seeding
hard-coded class-level gross DB contribution anchors and then backing out
employee normal-cost contributions to get the final employer DB contribution
amounts used downstream.

This piece now reconciles exactly to the current canonical funding seed:

- workbook gross DB anchor
  - example: Regular `2,980,066,000`
- equals current
  - `total_er_db_cont + total_ee_nc_cont`
  - example: Regular `2,412,554,650 + 567,511,350 = 2,980,066,000`

So the workbook is not introducing a new unexplained number at that step. It is
encoding the same intermediate contribution logic that survives in the current
funding seed.

A repo-wide text search did not find these gross DB contribution constants
outside the workbook, which makes the workbook look like the unique retained
source for this intermediate contribution layer.

### 2. EOC payroll split is encoded by explicit formulas

The workbook allocates the published Elected Officers' total payroll
`211,724,251` across runtime `eso`, `eco`, and `judges` using the relative
sizes of workbook `payroll_db_legacy` values:

- `eso total_payroll = 211,724,251 * D5 / SUM(D5:D7)`
- `eco total_payroll = 211,724,251 * D6 / SUM(D5:D7)`
- `judges total_payroll = 211,724,251 * D7 / SUM(D5:D7)`

This is strong evidence that at least some runtime subclass splits were created
inside the workbook rather than copied directly from a published source table.

### 3. Class outflow constants are present directly in formulas

Workbook `ben_payment_legacy` formulas expose these constants:

- regular = `8,967,096,000`
- special = `2,423,470,000`
- admin = `8,090,000`
- eso = `53,526,000`
- eco = `9,442,000`
- judges = `105,844,000`
- senior management = `338,864,000`
- drop = `857,600,000`

This is a crucial clue because those constants are close to the reviewed
baseline outflow values already captured in
[plans/frs/baselines/input_params.json](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/baselines/input_params.json).

The workbook location is now explicit:

- headers in row 1:
  - `BL1 = ben_payment_legacy`
  - `BM1 = ben_payment_new`
  - `BN1 = total_refund`
  - `BO1 = refund_legacy`
  - `BP1 = refund_new`
  - `BQ1 = disbursement_to_IP`
  - `BR1 = admin_exp_legacy`
- plan-wide seed values in row 10:
  - `BL10 = 11,944,986,866`
  - `BM10 = 0`
  - `BO10 = 28,343,757`
  - `BP10 = 0`
  - `BQ10 = 768,106,850`
  - `BR10 = 22,494,571`

Those row-10 values match the ACFR deductions-table anchors exactly.

One small discrepancy is visible:

- workbook senior management outflow constant = `338,864,000`
- reviewed baseline senior management outflow = `338,664,000`

So the workbook is evidence, but not necessarily the final reviewed value.

Additional narrowing result from a workbook-wide scan:

- each class outflow constant appears only in the `Funding Input` formulas
  `BL2:BR9`
- the retained workbook does not contain those values anywhere else as
  standalone inputs, helper cells, or derived references
- the companion workbook
  [Florida FRS COLA analysis.xlsx](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_frs/Florida%20FRS%20COLA%20analysis.xlsx)
  does not contain those constants either

This matters because it sharply narrows the retained-evidence boundary:

- the workbook explains how the constants were used downstream
- but the workbook does not explain how they were originally constructed
- so the upstream provenance gap is now more clearly a pre-workbook or
  off-workbook legacy step

### 4. Workbook `ben_payment_legacy` does not exactly match the current reviewed runtime

The workbook formula pattern is:

- `class_outflow * BL10 / SUM(BL10:BR10)`

For example:

- regular:
  - `8967096000 * BL10 / SUM(BL10:BR10)`
- special:
  - `2423470000 * BL10 / SUM(BL10:BR10)`

The important subtlety is that `SUM(BL10:BR10)` appears to include both:

- `total_refund`
- `refund_legacy`

which double-counts refunds in the denominator.

This produces a workbook ratio of about:

- `0.9337655826`

instead of the current reviewed runtime ratio:

- `11,944,986,866 / 12,763,932,044 = 0.9358391148`

Implication:

- the workbook helps expose the outflow constants
- but the workbook's own `ben_payment_legacy` outputs are not the same as the
  current reviewed runtime values
- so the workbook is a clue source, not the final truth

One additional result from the workbook inspection:

- no useful workbook defined names were found for the outflow logic
- the important evidence is in the cell formulas themselves, not in named
  ranges or comments

## Strong Clues From `Retiree Distribution`

The workbook `Retiree Distribution` sheet is not a plain copied table. It is a
formula-built age distribution with columns:

- `age`
- `n_retire`
- `total_ben`
- `avg_ben`
- `n_retire_ratio`
- `total_ben_ratio`

Examples of formula structure:

- age 45:
  - `n_retire = (1964 + 424) / 5`
  - `total_ben = (28,474,000 + 8,740,000) / 5`
- age 53:
  - `n_retire = (3903 + 805) / 5`
  - `total_ben = (133,928,000 + 15,834,000) / 5`
- age 83:
  - `n_retire = (87,072 + 1,033) / 10`
  - `total_ben = (2,125,387,000 + 17,878,000) / 10`
- older ages are sometimes flat-carried from the previous row:
  - age 103 uses `=B59` and `=C59`
  - age 118 uses `=B74` and `=C74`

Implication:

- the workbook retiree distribution is a legacy constructed intermediate
  artifact
- it appears to smooth or spread grouped counts and grouped benefit totals over
  multiple ages
- this is not the same as a direct age-by-age source extraction from the AV or
  ACFR

That makes retiree distribution another place where the Reason workflow likely
inserted a substantive transformation step between official documents and the
reviewed runtime artifacts.

## What This Changes

The FRS mystery is now more structured:

- the workbook explains where many compatibility-style class values may have
  been stored
- it exposes explicit EOC split logic for payroll
- it exposes class outflow constants used in benefit-payment allocation
- but it also shows that some workbook formulas differ from the final reviewed
  baseline

So the likely path is:

1. official AV/ACFR tables
2. Reason workbook intermediate allocations
3. reviewed baseline values

not:

1. official AV/ACFR tables
2. direct one-step runtime mapping

## Follow-Up

- inspect whether a similar workbook rule exists for class benefit outflows
  beyond the constants already exposed in formulas
- determine whether the hard-coded gross DB contribution anchors such as
  `2,980,066,000` (Regular) and `1,354,235,000` (Special) can be reconciled to
  published source totals or are also workbook-only legacy intermediates
- determine how the workbook `Retiree Distribution` age smoothing was chosen and
  whether the reviewed runtime artifact still reflects that construction
- determine whether the senior-management outflow discrepancy is a typo,
  revision, or later manual adjustment
- check whether the workbook `Funding Input` sheet or another sheet documents
  the source of the outflow constants explicitly

See also:

- [benefit_payment_mapping.md](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/reports/benefit_payment_mapping.md)
- [legacy_reconstruction_log.md](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/reports/legacy_reconstruction_log.md)
