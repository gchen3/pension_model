# FRS Legacy Reconstruction Log

## Purpose

This note records concrete reconstruction attempts against the current reviewed
FRS baseline when the exact upstream Reason-era logic is not yet fully known.

The goal is to preserve:

- what was tested
- what matched exactly
- what only partially matched
- what failed

This is distinct from new-plan estimation. These are legacy reconstruction
attempts against an existing reviewed baseline.

## Current Focus: Class Benefit-Payment Inputs

The main active legacy-reconstruction issue is the source path for the class
outflows that drive current runtime `valuation_inputs.{class}.ben_payment`.

Relevant current baseline values are stored in:

- [plans/frs/baselines/input_params.json](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/baselines/input_params.json)

Relevant current runtime targets are stored in:

- [plans/frs/config/plan_config.json](/home/donboyd5/Documents/python_projects/pension_model/plans/frs/config/plan_config.json)

## Tested Reconstructions

### Attempt 1: Runtime `ben_payment = class_outflow * ben_payment_ratio`

Status:

- `success`

Evidence:

- `ben_payment_ratio = 11,944,986,866 / 12,763,932,044 = 0.9358391148451025`
- the ratio components come from the ACFR plan-wide deductions table
- the retained Reason workbook seeds the same cash-flow anchors in
  `Funding Input!BL10:BR10`, with:
  - `BL10 = 11,944,986,866`
  - `BO10 = 28,343,757`
  - `BQ10 = 768,106,850`
  - `BR10 = 22,494,571`
- the workbook also applies each class outflow constant directly across that
  block in `Funding Input!BL2:BR9`
- every current class-level runtime `ben_payment` value matches this formula
  exactly when the baseline class outflows are used

Examples:

- regular:
  - `8,967,096,000 * 0.9358391148451025 = 8,391,759,183.371059`
- judges:
  - `105,844,000 * 0.9358391148451025 = 99,052,955.271665`
- eco:
  - `9,442,000 * 0.9358391148451025 = 8,836,192.922367`

Conclusion:

- the current runtime formula is fully explained
- this is no longer the mystery

### Attempt 2: Baseline class outflows equal valuation Table 2-4 line `3` class disbursements

Status:

- `near-exact provenance match`

Source:

- [Florida FRS Valuation 2022.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/Florida%20FRS%20Valuation%202022.pdf)
  - Table 2-4 `Development of Actuarial Value of Assets by Membership Class`,
    printed p. `18`, PDF p. `23`

Tested comparison:

- valuation Table 2-4 line `3` `Benefit Payments and other Disbursements`
  by class, scaled from thousands to dollars

Examples:

- regular:
  - Table 2-4 line `3` = `8,967,096,000`
  - baseline outflow = `8,967,096,000`
  - difference = `0`
- special:
  - Table 2-4 line `3` = `2,423,470,000`
  - baseline outflow = `2,423,470,000`
  - difference = `0`
- admin:
  - Table 2-4 line `3` = `8,090,000`
  - baseline outflow = `8,090,000`
  - difference = `0`
- judges:
  - Table 2-4 line `3` = `105,844,000`
  - baseline outflow = `105,844,000`
  - difference = `0`
- senior management:
  - Table 2-4 line `3` = `338,864,000`
  - baseline outflow = `338,664,000`
  - difference = `-200,000`

Conclusion:

- this is now the best current provenance match for the legacy class outflow
  inputs
- the remaining question is conceptual, not provenance
- Table 2-4 line `3` is `Benefit Payments and other Disbursements` for plan
  year `2021/2022`, not a narrow class benefit-payment table
- so this evidence supports:
  - where the class outflow inputs came from
  - but not necessarily that they were the right target for first-year benefit
    payments

### Attempt 3: Baseline class outflows equal ACFR `Total Annual Benefits by System/Class`

Status:

- `failed exact match`

Source:

- [2022-23_ACFR.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/2022-23_ACFR.pdf)
  - statistical section `Total Annual Benefits by System/Class`, printed p. 205

Examples:

- regular:
  - ACFR annual benefits = `8,431,219,359`
  - baseline outflow = `8,967,096,000`
  - difference = `+535,876,641` (`+6.36%`)
- special:
  - ACFR annual benefits = `2,139,187,633`
  - baseline outflow = `2,423,470,000`
  - difference = `+284,282,367` (`+13.29%`)
- grouped EOC:
  - ACFR Elected Officers' total = `164,431,365`
  - baseline `judges + eso + eco = 168,812,000`
  - difference = `+4,380,635` (`+2.66%`)

Conclusion:

- ACFR statistical annual benefits are informative, but they are not a direct
  exact source for the baseline class outflows

### Attempt 4: Baseline class outflows equal valuation Table C-5 annuitant annual benefits

Status:

- `failed exact match`

Source:

- [Florida FRS Valuation 2022.pdf](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/sources/Florida%20FRS%20Valuation%202022.pdf)
  - Table C-5 `Annuitants and Potential Annuitants at July 1, 2022`, printed
    p. C-4

Tested comparison:

- current annuitant annual benefits plus future DROP annuities by class and
  EOC subclass

Examples:

- regular:
  - valuation total = `9,188,016,000`
  - baseline outflow = `8,967,096,000`
  - difference = `-220,920,000` (`-2.40%`)
- special:
  - valuation total = `2,187,975,000`
  - baseline outflow = `2,423,470,000`
  - difference = `+235,495,000` (`+10.76%`)
- eco:
  - valuation total = `11,367,000`
  - baseline outflow = `9,442,000`
  - difference = `-1,925,000` (`-16.93%`)
- eso:
  - valuation total = `57,922,000`
  - baseline outflow = `53,526,000`
  - difference = `-4,396,000` (`-7.59%`)

Conclusion:

- valuation annuitant-benefit totals are also not a direct exact source for the
  baseline class outflows

### Attempt 5: Baseline class outflows equal a composite of published payout slices

Status:

- `partial`

Source families used:

- valuation Table C-5 current annuitant annual benefits
- ACFR disability benefits by class
- ACFR terminated DROP participants by class using `count * average annual current benefit`

Tested composite:

- `current annuitant annual benefits`
- plus `disability annual benefits`
- plus `terminated DROP current benefits`

Examples:

- regular:
  - valuation current annuitants = `8,552,985,000`
  - ACFR disability benefits = `191,018,512`
  - terminated DROP current benefits = `192,649,882`
  - composite = `8,936,653,394`
  - baseline outflow = `8,967,096,000`
  - difference = `+30,442,606` (`+0.34%`)
- senior management:
  - composite = `335,421,494`
  - baseline outflow = `338,664,000`
  - difference = `+3,242,506` (`+0.97%`)
- special:
  - composite = `2,219,664,488`
  - baseline outflow = `2,423,470,000`
  - difference = `+203,805,512` (`+9.18%`)
- admin:
  - composite = `7,302,599`
  - baseline outflow = `8,090,000`
  - difference = `+787,401` (`+10.78%`)
- grouped EOC:
  - valuation current annuitants only = `169,201,000`
  - baseline grouped outflow = `168,812,000`
  - difference = `-389,000` (`-0.23%`)

Conclusion:

- the outflow constants appear to be closer to a mix of published payout slices
  than to any single published table
- this is strongest for `regular`, `senior management`, and grouped EOC
- `special` and `admin` remain materially underexplained even after adding the
  extra published payout components
- this supports a `partially_reconstructed` interpretation rather than a solved
  direct-source mapping

### Attempt 6: Search retained Reason workbooks for a pre-formula origin of the class outflow constants

Status:

- `failed`

Source families used:

- [Florida FRS inputs.xlsx](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_frs/Florida%20FRS%20inputs.xlsx)
- [Florida FRS COLA analysis.xlsx](/home/donboyd5/Documents/python_projects/pension_model/R_model/R_model_frs/Florida%20FRS%20COLA%20analysis.xlsx)

Tested search:

- workbook-wide scan for literals:
  - `8,967,096,000`
  - `2,423,470,000`
  - `8,090,000`
  - `53,526,000`
  - `9,442,000`
  - `105,844,000`
  - `338,864,000`
  - `857,600,000`

Result:

- every hit is in `Funding Input!BL2:BR9`
- no retained workbook cell was found that derives or documents those values
  upstream
- the companion `Florida FRS COLA analysis.xlsx` workbook contains none of
  those constants

Conclusion:

- the retained workbooks explain how the class outflow constants were used
- they do not explain how those constants were first constructed
- this pushes the unresolved step earlier in the legacy workflow, possibly to
  manual spreadsheet prep or missing R-side code that is not currently in the
  repo

### Attempt 7: Compare the remaining `special` and `admin` gaps as class-scaled extra amounts

Status:

- `partial`

Source families used:

- ACFR `Total Annual Benefits by System/Class`
- valuation and ACFR annuitant counts
- ACFR plan-provisions narrative on disability and survivor benefits

Tested comparison:

- start from the mixed payout composite in Attempt 4
- look only at the remaining unexplained gaps for:
  - `special`
  - `admin`
- scale those gaps by class size and by class annual benefits

Results:

- special:
  - remaining unexplained gap = `203,805,512`
  - 2022 annuitant count = `43,523`
  - gap per annuitant ≈ `$4,683`
  - gap as share of 2022 ACFR class annual benefits ≈ `9.53%`
- admin:
  - remaining unexplained gap = `787,401`
  - 2022 annuitant count = `165`
  - gap per annuitant ≈ `$4,772`
  - gap as share of 2022 ACFR class annual benefits ≈ `10.81%`

Interpretation:

- the two remaining unexplained gaps are surprisingly similar on a
  per-annuitant basis
- that supports a common Special Risk-family uplift rather than two unrelated
  residuals

Supporting policy clue:

- the ACFR plan-provisions narrative states that Special Risk in-line-of-duty
  disability retirement has a minimum Option 1 benefit of `65%` of average
  final compensation, versus `42%` for other classes
- the same narrative also describes richer line-of-duty death benefits for
  Special Risk members

Conclusion:

- this is not a solved reconstruction rule
- but it is a meaningful clue that the remaining `special` and `admin`
  differences may reflect a common special-risk-specific benefit enhancement
  that is not separately published in the class annual-benefit tables used so
  far

## Current Working Conclusion

The evidence now supports the following interpretation:

- the runtime `ben_payment` formula is known exactly
- the plan-wide deductions ratio is source-grounded
- the class outflow inputs appear to be a legacy intermediate allocation from
  the Reason/R workflow
- no single published source table tested so far reproduces those outflows
  exactly
- some class outflows are partially explainable as composites of multiple
  published payout slices, but the composite rule is not yet stable across
  classes
- the retained workbook evidence is now close to exhausted for this question:
  the constants are present only at the point where they are consumed
- the remaining `special` and `admin` gaps now look more like a shared
  Special-Risk-family uplift than random residual noise

## Open Follow-Up

- search for any Reason-era workbook or handwritten prep note that explains the
  class outflow allocation
- determine whether the outflow concept includes only annual benefits or a
  broader payout concept
- determine whether the EOC split was estimated from valuation subclass data,
  ACFR totals, or some hybrid rule

See also:

- [benefit_payment_mapping.md](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/reports/benefit_payment_mapping.md)
