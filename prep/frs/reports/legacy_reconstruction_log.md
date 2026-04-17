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

### Attempt 2: Baseline class outflows equal ACFR `Total Annual Benefits by System/Class`

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

### Attempt 3: Baseline class outflows equal valuation Table C-5 annuitant annual benefits

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

## Current Working Conclusion

The evidence now supports the following interpretation:

- the runtime `ben_payment` formula is known exactly
- the plan-wide deductions ratio is source-grounded
- the class outflow inputs appear to be a legacy intermediate allocation from
  the Reason/R workflow
- no single published source table tested so far reproduces those outflows
  exactly

## Open Follow-Up

- search for any Reason-era workbook or handwritten prep note that explains the
  class outflow allocation
- determine whether the outflow concept includes only annual benefits or a
  broader payout concept
- determine whether the EOC split was estimated from valuation subclass data,
  ACFR totals, or some hybrid rule

See also:

- [benefit_payment_mapping.md](/home/donboyd5/Documents/python_projects/pension_model/prep/frs/reports/benefit_payment_mapping.md)
