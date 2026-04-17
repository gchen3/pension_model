# Input Prep Method Registry

## Purpose

This registry captures reusable prep methods, techniques, and transformation
patterns that should survive beyond any one plan.

It exists to prevent reverse-engineering knowledge from remaining trapped in:

- plan-specific notes
- one-off scripts
- working memory

The goal is to make methods reusable when moving from:

- reverse-engineering legacy FRS and TXTRS inputs

to:

- forward-engineering canonical inputs for new plans

## How To Use This Registry

Each method entry should record:

- `method_id`
- short name
- purpose
- input shape
- output shape
- method status
- whether the method is:
  - `source-faithful transform`
  - `legacy reconstruction`
  - `documented estimation`
- assumptions
- validation approach
- known plan examples
- known failure modes or limits

Recommended method statuses:

- `confirmed`
- `partially_confirmed`
- `candidate`
- `legacy_only`

## Method Entries

### `active-grid-band-to-point-v1`

- Status: `confirmed`
- Type: `source-faithful transform`
- Purpose: Convert grouped active-member age/service tables into canonical
  point-grid runtime tables.
- Inputs:
  - grouped count matrix by age band and service band
  - grouped compensation matrix on the same grid
- Outputs:
  - canonical `all_headcount.csv`
  - canonical `all_salary.csv`
- Core rule:
  - assign representative ages to age bands
  - map service bands to canonical representative YOS values
  - where early service is published as separate single-year columns, collapse
    those columns into canonical `yos = 2`
  - for salary, use count-weighted averaging when collapsing multiple cells
- Validation:
  - exact equality to canonical runtime files
  - row-count equality
  - no missing or extra canonical cells
- Confirmed examples:
  - TXTRS Table 17 -> runtime active grid
- Notes:
  - this method should stay source-faithful; it is not a generic smoothing
    method

### `entrant-profile-boundary-merge-v1`

- Status: `confirmed`
- Type: `source-faithful transform`
- Purpose: Convert grouped entrant-profile age bands into canonical single-age
  entrant rows.
- Inputs:
  - entrant counts by age band
  - entrant average salaries by age band
- Outputs:
  - canonical `entrant_profile.csv`
- Core rule:
  - use canonical five-year boundary ages such as `20, 25, ..., 65`
  - merge the lowest published entrant band into the first canonical age
  - merge the highest published entrant band into the last canonical age
  - for salaries, take the simple average of adjacent band-average salaries at
    each canonical boundary age
  - normalize counts to `entrant_dist`
- Validation:
  - exact equality to canonical runtime file
  - distribution sums to `1`
- Confirmed examples:
  - TXTRS valuation `NEW ENTRANT PROFILE` -> runtime entrant profile

### `retiree-distribution-age-smoothing-v1`

- Status: `partially_confirmed`
- Type: `legacy reconstruction`
- Purpose: Spread grouped retiree counts and grouped benefit totals across
  age-by-age canonical retiree rows.
- Inputs:
  - grouped retiree counts
  - grouped retiree benefit totals
- Outputs:
  - canonical or legacy-compatible `retiree_distribution.csv`
- Core rule observed so far:
  - divide grouped counts and grouped benefit totals across age ranges
  - repeat the same average values within each spread range
  - flat-carry very old-age tails in some legacy cases
- Validation:
  - exact equality to the current runtime file if the legacy path is being
    reproduced
  - preservation of group totals after spreading
- Confirmed examples:
  - FRS workbook retiree distribution
  - TXTRS workbook retiree distribution
- Limits:
  - exact PDF-only source path is not yet known for either pilot
  - should not be treated as a default forward-looking method until source
    support and justification are clearer

### `acfr-deductions-ratio-allocation-v1`

- Status: `partially_confirmed`
- Type: `legacy reconstruction`
- Purpose: Allocate plan-wide cash-flow categories such as benefit payments,
  refunds, or admin expense across classes using retained class outflow
  constants.
- Inputs:
  - plan-wide deductions anchors from ACFR
  - class outflow constants from legacy artifacts
- Outputs:
  - class-level `valuation_inputs.{class}.ben_payment`
  - possibly related class-level cash-flow items
- Core rule observed so far:
  - `class_value = class_outflow * plan_anchor / plan_total`
- Validation:
  - exact equality to current reviewed runtime values
- Confirmed examples:
  - FRS current `ben_payment` runtime values
- Limits:
  - downstream allocation rule is known
  - upstream provenance of the class outflow constants is still unresolved

### `first-year-disbursement-proxy-v1`

- Status: `partially_confirmed`
- Type: `legacy reconstruction`
- Purpose: Estimate first-year class benefit payments when the best retained
  class-level source is a broader disbursement concept rather than a direct
  benefit-payment table.
- Inputs:
  - class-level disbursement allocations from a valuation or funding table
  - plan-wide observed cash-flow totals from ACFR or financial statements
  - a documented ratio that converts broader disbursements to the narrower
    benefit-payment concept
- Outputs:
  - first-year class benefit-payment inputs
- Core rule observed so far:
  - `class_benefit_payment = class_disbursement_proxy * planwide_benefit_share`
- Validation:
  - exact equality to canonical first-year runtime values
  - explicit reconciliation of what is included in the broader disbursement
    base
  - explicit documentation of any first-year-only cash-flow items
- Confirmed examples:
  - FRS first-year `ben_payment` path using valuation Table 2-4 line `3`
    together with the ACFR plan-wide benefit share
- Limits:
  - this method can reproduce a reviewed runtime path without proving that the
    path is the best conceptual choice for new plans
  - should not be promoted to a default forward-looking method without plan-
    specific review

### `eoc-payroll-subclass-allocation-v1`

- Status: `partially_confirmed`
- Type: `legacy reconstruction`
- Purpose: Split a grouped payroll total across EOC-style subclasses when the
  grouped total is published but subclass payroll is not.
- Inputs:
  - grouped total payroll
  - subclass legacy payroll basis values
- Outputs:
  - subclass payroll allocations
- Core rule observed so far:
  - proportional allocation using the relative size of retained subclass
    payroll-basis values
- Confirmed examples:
  - FRS `eso`, `eco`, and `judges` payroll split in the retained workbook
- Limits:
  - this is not yet a generic approved method for new plans
  - currently it is evidence about legacy construction, not a recommended
    default technique

### `monetary-unit-normalization-v1`

- Status: `confirmed`
- Type: `source-faithful transform`
- Purpose: Convert monetary values from source units into canonical dollars.
- Inputs:
  - source monetary value
  - explicit source unit label such as dollars, thousands, or millions
- Outputs:
  - canonical dollar value
- Core rule:
  - never infer units silently
  - record source unit explicitly
  - scale before writing reviewed prep artifacts or runtime outputs
- Validation:
  - totals reconcile after scaling
  - comparisons and equivalence tests use normalized dollar values
- Confirmed examples:
  - valuation liability tables published in thousands
  - ACFR and valuation cash-flow tables with mixed presentation conventions

### `printed-pdf-page-crosswalk-v1`

- Status: `confirmed`
- Type: `source-faithful transform`
- Purpose: Standardize page citations so provenance references are unambiguous.
- Inputs:
  - printed report page, appendix page, or table label when available
  - PDF/electronic page number
- Outputs:
  - provenance entry with both page systems when known
- Core rule:
  - use printed page as the primary human-facing citation
  - also record PDF page when practical
- Validation:
  - source references remain reproducible across tools and viewers
- Confirmed examples:
  - FRS and TXTRS page crosswalk notes

### `mortality-basis-dual-track-review-v1`

- Status: `partially_confirmed`
- Type: `source-faithful transform`
- Purpose: Separate `can we reproduce the current runtime mortality files` from
  `can we reconstruct the valuation's stated mortality basis`.
- Inputs:
  - current runtime mortality artifacts
  - valuation mortality narrative and sample rates
  - any retained legacy implementation code
  - external mortality and improvement-scale reference files
- Outputs:
  - source-gap statement
  - implementation-gap statement
  - explicit classification of the runtime mortality path as source-faithful or
    compatibility-oriented
- Core rule:
  - do not treat a named mortality basis as solved until both the source table
    and the intended implementation rule are known
  - compare runtime results against valuation specimen rates when available
  - distinguish missing base tables from ambiguous projection-scale rules
- Validation:
  - explicit rate comparisons at specimen ages/years
  - documented alignment or mismatch against valuation text
- Confirmed examples:
  - TXTRS mortality review
- Limits:
  - this is a review method, not a build method
  - additional plan-specific source acquisition may still be required before a
    source-faithful build is possible

## Method Design Guidance

When adding a new method:

- prefer a source-faithful transform over an estimation method
- treat legacy reconstruction separately from new-plan estimation
- do not elevate a legacy workaround into a shared method without evidence
- document exact validation rules before relying on the method operationally
- add plan examples and counterexamples as they are discovered

## Related Documents

- [current_stage3_build_rules.md](/home/donboyd5/Documents/python_projects/pension_model/prep/common/build/current_stage3_build_rules.md)
- [consistency_check_catalog.md](/home/donboyd5/Documents/python_projects/pension_model/prep/common/checks/consistency_check_catalog.md)
- [cross_plan_lessons.md](/home/donboyd5/Documents/python_projects/pension_model/prep/common/reports/cross_plan_lessons.md)
